import logging as log
import pytest
from helpers.otg import otg


@pytest.mark.all
@pytest.mark.dp
def test_vxlan_inner_ipv4():
    test_const = {
        "pktRate": 50,
        "pktCount": 100,
        "pktSize": 256,
        "txMac": "00:00:01:01:01:01",
        "rxMac": "00:00:01:01:01:02",
        "innerTxMac": "00:00:01:01:01:03",
        "innerRxMac": "00:00:01:01:01:04",
        "txIpv6": "::1",
        "rxIpv6": "::2",
        "txIp": "1.1.1.3",
        "rxIp": "1.1.1.4",
        "txUdpPortValue": 4789,
        "rxUdpPortValue": 4789,
        "vxLanVniValues": [1000, 1001, 1002, 1003, 1004],
        "txTcpPortValue": 80,
        "rxTcpPortValue": 80,
    }
    api = otg.OtgApi()
    c = vxlan_inner_ipv4_config(api, test_const)
    api.api.request_timeout = 300
    api.set_config(c)

    api.start_capture()
    api.start_transmit()

    api.wait_for(
        fn=lambda: metrics_ok(api, test_const), fn_name="wait_for_flow_metrics"
    )

    api.stop_capture()

    capture_ok(api, c, test_const)


def vxlan_inner_ipv4_config(api, tc):
    c = api.api.config()
    p1 = c.ports.add(name="p1", location=api.test_config.otg_ports[0])
    p2 = c.ports.add(name="p2", location=api.test_config.otg_ports[1])

    ly = c.layer1.add(name="ly", port_names=[p1.name, p2.name])
    ly.speed = api.test_config.otg_speed

    if api.test_config.otg_capture_check:
        ca = c.captures.add(name="ca", port_names=[p1.name, p2.name])
        ca.format = ca.PCAP

    f1 = c.flows.add(name="f1")
    f1.tx_rx.port.tx_name = p1.name
    f1.tx_rx.port.rx_names = [p2.name]
    f1.duration.fixed_packets.packets = tc["pktCount"]
    f1.rate.pps = tc["pktRate"]
    f1.size.fixed = tc["pktSize"]
    f1.metrics.enable = True

    eth1, ip6, udp, vxlan, eth2, ip, tcp = (
        f1.packet.ethernet().ipv6().udp().vxlan().ethernet().ipv4().tcp()
    )

    eth1.src.value = tc["txMac"]
    eth1.dst.value = tc["rxMac"]

    eth2.src.value = tc["innerTxMac"]
    eth2.dst.value = tc["innerRxMac"]

    ip6.src.value = tc["txIpv6"]
    ip6.dst.value = tc["rxIpv6"]

    udp.src_port.value = tc["txUdpPortValue"]
    udp.dst_port.value = tc["rxUdpPortValue"]

    vxlan.vni.values = tc["vxLanVniValues"]

    ip.src.value = tc["txIp"]
    ip.dst.value = tc["rxIp"]

    tcp.src_port.value = tc["txTcpPortValue"]
    tcp.dst_port.value = tc["rxTcpPortValue"]

    log.info("Config:\n%s", c)
    return c


def metrics_ok(api, tc):
    m = api.get_flow_metrics()[0]
    ok = (
        m.transmit == m.STOPPED
        and m.frames_tx == tc["pktCount"]
        and m.frames_rx == tc["pktCount"]
    )
    return ok


def capture_ok(api, c, tc):
    if not api.test_config.otg_capture_check:
        return

    ignored_count = 0
    captured_packets = api.get_capture(c.ports[1].name)

    for i, p in enumerate(captured_packets.packets):
        # ignore unexpected packets based on ethernet src MAC
        if not captured_packets.has_field(
            "ethernet src", i, 6, api.mac_addr_to_bytes(tc["txMac"])
        ):
            ignored_count += 1
            continue

        # packet size
        captured_packets.validate_size(i, tc["pktSize"])

        # ethernet header
        captured_packets.validate_field(
            "ethernet dst", i, 0, api.mac_addr_to_bytes(tc["rxMac"])
        )
        captured_packets.validate_field(
            "ethernet type", i, 12, api.num_to_bytes(34525, 2)
        )

        # ipv6 header
        captured_packets.validate_field(
            "ipv6 payload length",
            i,
            18,
            api.num_to_bytes(tc["pktSize"] - 14 - 40 - 4, 2),
        )
        captured_packets.validate_field(
            "ipv6 next header", i, 20, api.num_to_bytes(17, 1)
        )
        captured_packets.validate_field(
            "ipv6 src", i, 22, api.ipv6_addr_to_bytes(tc["txIpv6"])
        )
        captured_packets.validate_field(
            "ipv6 dst", i, 38, api.ipv6_addr_to_bytes(tc["rxIpv6"])
        )

        # udp header
        captured_packets.validate_field(
            "udp src", i, 54, api.num_to_bytes(tc["txUdpPortValue"], 2)
        )
        captured_packets.validate_field(
            "udp dst", i, 56, api.num_to_bytes(tc["rxUdpPortValue"], 2)
        )
        captured_packets.validate_field(
            "udp length", i, 58, api.num_to_bytes(tc["pktSize"] - 14 - 40 - 4, 2)
        )

        # vxlan header
        j = i - ignored_count
        captured_packets.validate_field(
            "vxlan Network Identifier",
            i,
            66,
            api.num_to_bytes(tc["vxLanVniValues"][j % len(tc["vxLanVniValues"])], 3),
        )

        # inner ethernet header
        captured_packets.validate_field(
            "ethernet dst", i, 70, api.mac_addr_to_bytes(tc["innerRxMac"])
        )
        captured_packets.validate_field(
            "ethernet type", i, 82, api.num_to_bytes(2048, 2)
        )

        # inner ipv4 header
        captured_packets.validate_field(
            "ipv4 total length",
            i,
            86,
            api.num_to_bytes(tc["pktSize"] - 14 - 4 - 40 - 8 - 8 - 14 - 4, 2),
        )
        captured_packets.validate_field("ipv4 protocol", i, 93, api.num_to_bytes(6, 1))
        captured_packets.validate_field(
            "ipv4 src", i, 96, api.ipv4_addr_to_bytes(tc["txIp"])
        )
        captured_packets.validate_field(
            "ipv4 dst", i, 100, api.ipv4_addr_to_bytes(tc["rxIp"])
        )

        # inner tcp header
        captured_packets.validate_field(
            "tcp src port", i, 104, api.num_to_bytes(tc["txTcpPortValue"], 2)
        )
        captured_packets.validate_field(
            "tcp dst port", i, 106, api.num_to_bytes(tc["rxTcpPortValue"], 2)
        )

    exp_count = tc["pktCount"]
    act_count = len(captured_packets.packets) - ignored_count
    if exp_count != act_count:
        raise Exception("exp_count %d != act_count %d" % (exp_count, act_count))
