"""Common cross-cutting helpers: network resolution, OCC, rounding."""
from decimal import ROUND_HALF_UP, Decimal

from clock import epoch_ms_to_iso, iso, server_now
from db import (
    alerts,
    devices,
    dmas,
    investigations,
    networks,
    pipeline_nodes,
    pipeline_segments,
    public,
    topology_versions,
    work_orders,
    water_balance_reports,
)
from errors import err


# ---------- Network / resource resolution ----------


def get_network(network_id: str) -> dict:
    n = networks.get(network_id)
    if not n:
        raise err("ERR_NOT_FOUND", f"Network {network_id} not found")
    return n


def get_topology_version(network_id: str, version_id: str) -> dict:
    # Network must exist first (left-to-right path-id resolution)
    get_network(network_id)
    tv = topology_versions.get(version_id)
    if not tv or tv.get("network_id") != network_id:
        raise err("ERR_NOT_FOUND", f"TopologyVersion {version_id} not found")
    return tv


def get_dma(network_id: str, dma_id: str) -> dict:
    get_network(network_id)
    d = dmas.get(dma_id)
    if not d or d.get("network_id") != network_id:
        raise err("ERR_NOT_FOUND", f"DMA {dma_id} not found")
    return d


def get_device(network_id: str, device_id: str) -> dict:
    get_network(network_id)
    d = devices.get(device_id)
    if not d or d.get("network_id") != network_id:
        raise err("ERR_NOT_FOUND", f"Device {device_id} not found")
    return d


def get_alert(network_id: str, alert_id: str) -> dict:
    get_network(network_id)
    a = alerts.get(alert_id)
    if not a or a.get("network_id") != network_id:
        raise err("ERR_NOT_FOUND", f"Alert {alert_id} not found")
    return a


def get_investigation(network_id: str, investigation_id: str) -> dict:
    get_network(network_id)
    inv = investigations.get(investigation_id)
    if not inv:
        raise err("ERR_NOT_FOUND", f"Investigation {investigation_id} not found")
    # Validate the alert belongs to the network
    parent = alerts.get(inv.get("alert_id"))
    if not parent or parent.get("network_id") != network_id:
        raise err("ERR_NOT_FOUND", f"Investigation {investigation_id} not found")
    return inv


def get_work_order(network_id: str, work_order_id: str) -> dict:
    get_network(network_id)
    wo = work_orders.get(work_order_id)
    if not wo or wo.get("network_id") != network_id:
        raise err("ERR_NOT_FOUND", f"WorkOrder {work_order_id} not found")
    return wo


# ---------- OCC helper ----------


def check_occ(entity: dict, body: dict) -> None:
    """If body supplies `version`, compare to entity['version']; mismatch -> ERR_VERSION_CONFLICT.

    Per PRD §2.4, omitting `version` skips the check entirely.
    """
    if "version" in body and body["version"] is not None:
        try:
            client_version = int(body["version"])
        except (TypeError, ValueError):
            raise err("ERR_BAD_REQUEST", "version must be an integer")
        if client_version != int(entity.get("version", 0)):
            raise err("ERR_VERSION_CONFLICT", "version mismatch")


# ---------- Rounding ----------


def round_half_up(value, places: int) -> float:
    """Round value to `places` decimal places using ROUND_HALF_UP. Returns float."""
    q = Decimal(10) ** -places
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


# ---------- Active topology helpers ----------


def active_topology_id(network: dict) -> str:
    return network.get("active_topology_version_id")


def nodes_in_version(version_id: str):
    return [n for n in pipeline_nodes.values() if n.get("topology_version_id") == version_id]


def segments_in_version(version_id: str):
    return [s for s in pipeline_segments.values() if s.get("topology_version_id") == version_id]


def find_node_in_version(version_id: str, node_code: str):
    if not version_id or not node_code:
        return None
    for n in pipeline_nodes.values():
        if n.get("topology_version_id") == version_id and n.get("node_code") == node_code:
            return n
    return None


def find_segment_in_version(version_id: str, segment_code: str):
    if not version_id or not segment_code:
        return None
    for s in pipeline_segments.values():
        if s.get("topology_version_id") == version_id and s.get("segment_code") == segment_code:
            return s
    return None


# ---------- Clock helpers ----------


def clock_now_iso(network: dict) -> str:
    return epoch_ms_to_iso(int(network.get("clock_epoch_ms", 0)))


def clock_now_ms(network: dict) -> int:
    return int(network.get("clock_epoch_ms", 0))
