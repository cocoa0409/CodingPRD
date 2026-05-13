"""WorkOrder helpers: priority computation, downstream graph traversal."""
import math

from db import (
    alerts,
    investigations,
    pipeline_nodes,
    pipeline_segments,
    dmas,
)
from services.common import (
    active_topology_id,
    find_segment_in_version,
    segments_in_version,
)


P1_THRESHOLD = 15
P2_THRESHOLD = 8
DOWNSTREAM_BUCKET_SIZE = 50


def _segments_by_from_node(version_id: str):
    """Return dict: from_node_code -> list of segments leaving this node."""
    out = {}
    for s in segments_in_version(version_id):
        out.setdefault(s["from_node_code"], []).append(s)
    return out


def _downstream_customer_count(active_v: str, target_segment_code: str) -> int:
    """BFS from the target segment's downstream node and count CUSTOMER_TAP nodes."""
    if not active_v or not target_segment_code:
        return 0
    target_seg = find_segment_in_version(active_v, target_segment_code)
    if not target_seg:
        return 0
    nodes_by_code = {
        n["node_code"]: n
        for n in pipeline_nodes.values()
        if n.get("topology_version_id") == active_v
    }
    out_edges = _segments_by_from_node(active_v)
    start = target_seg["to_node_code"]
    visited = set()
    queue = [start]
    count = 0
    while queue:
        node_code = queue.pop(0)
        if node_code in visited:
            continue
        visited.add(node_code)
        node = nodes_by_code.get(node_code)
        if node and node.get("kind") == "CUSTOMER_TAP":
            count += 1
        for nxt_seg in out_edges.get(node_code, []):
            queue.append(nxt_seg["to_node_code"])
    return count


def compute_priority(network: dict, work_order: dict) -> str:
    """Compute P1/P2/P3 per PRD §3.8."""
    origin = work_order.get("origin")
    parent_alert_severity = None
    if origin in ("ALERT_AUTO", "INVESTIGATION"):
        alert_id = None
        if origin == "ALERT_AUTO":
            alert_id = work_order.get("alert_id")
        else:
            inv = investigations.get(work_order.get("investigation_id") or "")
            if inv:
                alert_id = inv.get("alert_id")
        a = alerts.get(alert_id or "")
        if a:
            parent_alert_severity = a.get("severity")

    sev_map = {"CRITICAL": 10, "WARNING": 5, "INFO": 0}
    severity_score = sev_map.get(parent_alert_severity, 0) if parent_alert_severity else 0

    dma = dmas.get(work_order.get("dma_id") or "")
    ocac = int(dma.get("open_critical_alert_count", 0)) if dma else 0
    if ocac >= 3:
        dma_score = 5
    elif ocac >= 1:
        dma_score = 2
    else:
        dma_score = 0

    leak_score = 0
    if origin == "INVESTIGATION":
        inv = investigations.get(work_order.get("investigation_id") or "")
        if inv and float(inv.get("water_balance_loss_lps") or 0.0) >= 1.0:
            leak_score = 8

    av = active_topology_id(network)
    dc_count = _downstream_customer_count(av, work_order.get("target_segment_code"))
    downstream_score = math.ceil(dc_count / DOWNSTREAM_BUCKET_SIZE) if dc_count > 0 else 0

    total = severity_score + dma_score + leak_score + downstream_score
    if total >= P1_THRESHOLD:
        return "P1"
    if total >= P2_THRESHOLD:
        return "P2"
    return "P3"
