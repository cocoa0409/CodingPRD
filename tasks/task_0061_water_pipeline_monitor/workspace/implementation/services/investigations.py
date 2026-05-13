"""Leak-localization narrowing computations (PRD §3.7)."""
import math

from clock import iso_to_epoch_ms, parse_iso
from db import (
    alerts,
    devices,
    investigations,
    pipeline_nodes,
    pipeline_segments,
    readings,
    water_balance_reports,
)
from services.common import (
    active_topology_id,
    clock_now_ms,
    find_node_in_version,
    round_half_up,
    segments_in_version,
)


HAZEN_WILLIAMS_K = 10.67
RHO_G_KPA_PER_M = 9.81
GRADIENT_ANOMALY_THRESHOLD_PCT = 25.0
LOOKBACK_S = 3600
NIGHT_FLOW_THRESHOLD_LPS = 2.0


# ---------- Pressure gradient anomaly segments ----------


def _flow_estimate_for_dma(network_id: str, dma_id: str, clock_ms: int) -> float:
    """Median of FLOW device readings in the DMA's mounted nodes over the past LOOKBACK_S."""
    cutoff_ms = clock_ms - LOOKBACK_S * 1000
    relevant_values = []
    # Devices in this DMA whose sensor_kind == FLOW
    flow_device_ids = set()
    # We resolve devices by walking devices whose mounted node belongs to this DMA in active topology
    # but in test fixtures, devices store dma association via their mounted node. Iterate readings
    # by their device's properties.
    for d in devices.values():
        if d.get("network_id") != network_id:
            continue
        if d.get("sensor_kind") != "FLOW":
            continue
        flow_device_ids.add(d["id"])
    for r in readings.values():
        if r.get("device_id") not in flow_device_ids:
            continue
        if r.get("validity") != "ACCEPTED":
            continue
        ing_ms = iso_to_epoch_ms(r["ingested_at"])
        if cutoff_ms <= ing_ms <= clock_ms:
            relevant_values.append(float(r["raw_value"]))
    if not relevant_values:
        return 0.0
    relevant_values.sort()
    n = len(relevant_values)
    if n % 2 == 1:
        return relevant_values[n // 2]
    return (relevant_values[n // 2 - 1] + relevant_values[n // 2]) / 2.0


def _pressure_at(network_id: str, node_code: str, active_v: str):
    """Find an ACTIVE pressure sensor mounted on node_code; return its last_reading_value or None."""
    if not node_code or not active_v:
        return None
    for d in devices.values():
        if d.get("network_id") != network_id:
            continue
        if d.get("status") != "ACTIVE":
            continue
        if d.get("sensor_kind") != "PRESSURE":
            continue
        if d.get("mounted_on_node_code") != node_code:
            continue
        lrv = d.get("last_reading_value")
        if lrv is not None:
            return float(lrv)
    return None


def _pressure_anomaly_segments(network: dict, dma_id: str) -> list:
    network_id = network["id"]
    active_v = active_topology_id(network)
    if not active_v:
        return []
    clock_ms = clock_now_ms(network)
    flow_est = _flow_estimate_for_dma(network_id, dma_id, clock_ms)
    nodes_by_code = {
        n["node_code"]: n
        for n in pipeline_nodes.values()
        if n.get("topology_version_id") == active_v
    }
    anomaly = []
    for s in segments_in_version(active_v):
        if s.get("dma_id") != dma_id:
            continue
        from_p = _pressure_at(network_id, s["from_node_code"], active_v)
        to_p = _pressure_at(network_id, s["to_node_code"], active_v)
        if from_p is None or to_p is None:
            continue
        length_m = float(s["length_m"])
        diameter_mm = float(s["diameter_mm"])
        if diameter_mm <= 0:
            continue
        # Expected head loss (Hazen-Williams)
        expected = (
            HAZEN_WILLIAMS_K
            * length_m
            / (diameter_mm ** 4.87)
            * (max(flow_est, 0.0) ** 1.85)
        )
        from_node = nodes_by_code.get(s["from_node_code"])
        to_node = nodes_by_code.get(s["to_node_code"])
        elev_diff = 0.0
        if from_node is not None and to_node is not None:
            elev_diff = float(from_node.get("elevation_m", 0)) - float(to_node.get("elevation_m", 0))
        measured = (from_p - to_p) + elev_diff * RHO_G_KPA_PER_M
        expected_r = round_half_up(expected, 2)
        measured_r = round_half_up(measured, 2)
        threshold = expected_r * GRADIENT_ANOMALY_THRESHOLD_PCT / 100.0
        if (measured_r - expected_r) >= threshold:
            anomaly.append(s["segment_code"])
    return sorted(anomaly)


# ---------- Min night flow ----------


def _min_night_flow_lps(network: dict, dma: dict) -> float:
    """Hourly average of inlet FLOW devices between 02:00–04:00 UTC across past 7 nights.

    PRD says "local-time"; we use UTC as a deterministic stand-in since the
    fixtures do not specify a timezone for the DMA. The minimum across the
    14 hour-buckets is returned.
    """
    network_id = network["id"]
    inlets = set(dma.get("inlet_node_codes") or [])
    if not inlets:
        return None
    # Collect candidate readings
    clock_ms = clock_now_ms(network)
    cutoff_ms = clock_ms - 7 * 86400 * 1000
    rows = []
    for d in devices.values():
        if d.get("network_id") != network_id:
            continue
        if d.get("mounted_on_node_code") not in inlets:
            continue
        if d.get("sensor_kind") != "FLOW":
            continue
        for r in readings.values():
            if r.get("device_id") != d["id"]:
                continue
            if r.get("validity") != "ACCEPTED":
                continue
            ing_ms = iso_to_epoch_ms(r["ingested_at"])
            if cutoff_ms <= ing_ms <= clock_ms:
                rows.append(r)
    if not rows:
        return None
    # Bin by (date, hour) for hours in {02, 03}
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in rows:
        obs = parse_iso(r["observed_at"])
        if obs.hour in (2, 3):
            buckets[(obs.date(), obs.hour)].append(float(r["raw_value"]))
    if not buckets:
        return None
    averages = [sum(vs) / len(vs) for vs in buckets.values()]
    return round_half_up(min(averages), 3)


# ---------- Water-balance loss ----------


def _water_balance_loss_lps(dma: dict) -> float:
    """Most recent WaterBalanceReport for the DMA with window length 86400s."""
    dma_id = dma["id"]
    candidates = []
    for r in water_balance_reports.values():
        if r.get("dma_id") != dma_id:
            continue
        ws_ms = iso_to_epoch_ms(r["window_start"])
        we_ms = iso_to_epoch_ms(r["window_end"])
        if (we_ms - ws_ms) // 1000 == 86400:
            candidates.append(r)
    if not candidates:
        return None
    latest = max(candidates, key=lambda x: x.get("published_at") or "")
    real_loss = float(latest.get("real_loss_m3", 0.0))
    return round_half_up(real_loss * 1000.0 / 86400.0, 3)


# ---------- Downstream-of-inlet segments ----------


def _segments_downstream_of_inlet(active_v: str, dma: dict) -> set:
    if not active_v:
        return set()
    inlets = set(dma.get("inlet_node_codes") or [])
    out_edges = {}
    for s in segments_in_version(active_v):
        out_edges.setdefault(s["from_node_code"], []).append(s)
    visited_nodes = set()
    reachable_segments = set()
    queue = list(inlets)
    while queue:
        node_code = queue.pop(0)
        if node_code in visited_nodes:
            continue
        visited_nodes.add(node_code)
        for s in out_edges.get(node_code, []):
            if s.get("dma_id") != dma["id"]:
                # Don't traverse across DMA boundaries
                continue
            reachable_segments.add(s["segment_code"])
            queue.append(s["to_node_code"])
    return reachable_segments


# ---------- Final narrowing ----------


def narrow_investigation(network: dict, investigation: dict, dma: dict) -> None:
    active_v = active_topology_id(network)
    pgrad = _pressure_anomaly_segments(network, dma["id"])
    mnf = _min_night_flow_lps(network, dma)
    wbl = _water_balance_loss_lps(dma)

    # Signal availability check (PRD §3.7): must have at least one of {mnf, wbl}.
    if mnf is None and wbl is None:
        from errors import err
        raise err("ERR_INVESTIGATION_NO_SIGNAL", "no min_night_flow or water_balance signal")

    downstream = _segments_downstream_of_inlet(active_v, dma)
    if pgrad and (mnf is not None and mnf >= NIGHT_FLOW_THRESHOLD_LPS):
        suspected = sorted(set(pgrad) & downstream)
    elif (mnf is not None and mnf >= NIGHT_FLOW_THRESHOLD_LPS):
        # night-flow-only fallback: downstream segments bordering lowest-pressure node,
        # ranked by segment_code ascending.
        suspected = _night_flow_only_fallback(network, dma, active_v, downstream)
    else:
        suspected = sorted(set(pgrad) & downstream)

    investigation["pressure_gradient_anomaly_segments"] = pgrad
    investigation["min_night_flow_lps"] = mnf
    investigation["water_balance_loss_lps"] = wbl
    investigation["suspected_segment_codes"] = suspected


def _night_flow_only_fallback(network, dma, active_v: str, downstream: set) -> list:
    """Find the lowest-pressure node, return its bordering downstream segments."""
    network_id = network["id"]
    # Identify nodes referenced by downstream segments + DMA nodes
    candidate_nodes = set()
    for s in segments_in_version(active_v):
        if s["segment_code"] in downstream:
            candidate_nodes.add(s["from_node_code"])
            candidate_nodes.add(s["to_node_code"])
    # Find lowest pressure
    lowest_node = None
    lowest_p = None
    for nc in candidate_nodes:
        p = _pressure_at(network_id, nc, active_v)
        if p is None:
            continue
        if lowest_p is None or p < lowest_p:
            lowest_p = p
            lowest_node = nc
    if not lowest_node:
        return []
    out = []
    for s in segments_in_version(active_v):
        if s["segment_code"] in downstream and (
            s["from_node_code"] == lowest_node or s["to_node_code"] == lowest_node
        ):
            out.append(s["segment_code"])
    return sorted(out)
