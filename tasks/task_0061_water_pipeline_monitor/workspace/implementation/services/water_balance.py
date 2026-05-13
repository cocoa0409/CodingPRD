"""DMA water-balance report computation (PRD §3.9)."""
from clock import iso, iso_to_epoch_ms, parse_iso, server_now
from db import devices, gen_id, next_seq, public, readings, water_balance_reports
from errors import err
from services.common import (
    active_topology_id,
    find_node_in_version,
    round_half_up,
)
from services.sync import emit_sync_for_water_balance_published


APPARENT_LOSS_RATE = 0.04
ALLOWED_WINDOWS_S = (3600, 86400, 604800)


def _devices_in_dma(network_id: str, dma_id: str, active_v: str):
    """Return list of Device dicts whose mounted_on_node_code lies in this DMA."""
    out = []
    for d in devices.values():
        if d.get("network_id") != network_id:
            continue
        nc = d.get("mounted_on_node_code")
        if not nc:
            continue
        node = find_node_in_version(active_v, nc) if active_v else None
        if node and node.get("dma_id") == dma_id:
            out.append(d)
    return out


def _inlet_devices(network_id: str, dma: dict, active_v: str):
    inlets = set(dma.get("inlet_node_codes") or [])
    out = []
    for d in devices.values():
        if d.get("network_id") != network_id:
            continue
        if d.get("mounted_on_node_code") in inlets and d.get("sensor_kind") == "FLOW":
            out.append(d)
    return out


def _accepted_readings_in_window(device_id: str, start_ms: int, end_ms: int):
    """Return ACCEPTED readings for the device, sorted by (observed_at, ingested_at).

    Window is [start, end). Deterministic tie-break on (observed_at, ingested_at).
    """
    rows = []
    for r in readings.values():
        if r.get("device_id") != device_id:
            continue
        if r.get("validity") != "ACCEPTED":
            continue
        obs_ms = iso_to_epoch_ms(r["observed_at"])
        if start_ms <= obs_ms < end_ms:
            rows.append(r)
    # Tie-break: if two readings share observed_at, the one with lower ingested_at wins.
    rows.sort(key=lambda r: (r["observed_at"], r["ingested_at"]))
    return rows


def _integrate_flow_lps_to_m3(rows, window_start_ms: int, window_end_ms: int) -> float:
    """Piecewise-constant integration of L/s to m³ over [start, end)."""
    if not rows:
        return 0.0
    # Treat the segment from each reading's observed_at to the next reading's
    # observed_at (or window_end) as constant flow at this reading's raw_value.
    total_liters = 0.0
    for i, r in enumerate(rows):
        obs_ms = iso_to_epoch_ms(r["observed_at"])
        if i + 1 < len(rows):
            next_ms = iso_to_epoch_ms(rows[i + 1]["observed_at"])
        else:
            next_ms = window_end_ms
        # Clip to window
        seg_start = max(obs_ms, window_start_ms)
        seg_end = min(next_ms, window_end_ms)
        if seg_end <= seg_start:
            continue
        duration_s = (seg_end - seg_start) / 1000.0
        total_liters += float(r["raw_value"]) * duration_s
    return total_liters / 1000.0  # m^3


def create_water_balance_report(network: dict, dma: dict, body: dict) -> dict:
    network_id = network["id"]
    dma_id = dma["id"]

    ws = body.get("window_start")
    we = body.get("window_end")
    if not ws or not we:
        raise err("ERR_BAD_REQUEST", "window_start and window_end are required")
    try:
        ws_dt = parse_iso(ws)
        we_dt = parse_iso(we)
    except Exception:
        raise err("ERR_BAD_REQUEST", "window_start/window_end must be ISO 8601")

    ws_ms = int(ws_dt.timestamp() * 1000)
    we_ms = int(we_dt.timestamp() * 1000)
    if we_ms <= ws_ms:
        raise err("ERR_INVALID_WINDOW", "window_end must be strictly after window_start")
    window_s = (we_ms - ws_ms) // 1000
    if window_s not in ALLOWED_WINDOWS_S:
        raise err("ERR_INVALID_WINDOW", "window length must be 3600s, 86400s, or 604800s")

    active_v = active_topology_id(network)

    # Inlet flow integration
    inlets = _inlet_devices(network_id, dma, active_v)
    input_volume_m3 = 0.0
    any_inlet_reading = False
    for dev in inlets:
        rows = _accepted_readings_in_window(dev["id"], ws_ms, we_ms)
        if rows:
            any_inlet_reading = True
        input_volume_m3 += _integrate_flow_lps_to_m3(rows, ws_ms, we_ms)

    if not any_inlet_reading or input_volume_m3 <= 0:
        raise err("ERR_INSUFFICIENT_DATA", "no inlet flow data in window")

    # Billed and unbilled-authorized: METER devices in the DMA.
    billed_m3 = 0.0
    unbilled_auth_m3 = 0.0
    for d in _devices_in_dma(network_id, dma_id, active_v):
        if d.get("sensor_kind") != "METER":
            continue
        rows = _accepted_readings_in_window(d["id"], ws_ms, we_ms)
        if not rows:
            continue
        delta = float(rows[-1]["raw_value"]) - float(rows[0]["raw_value"])
        if delta < 0:
            delta = 0
        billed_flag = bool(d.get("billed_flag", False))
        authorized = bool(d.get("authorized", False))
        if billed_flag:
            billed_m3 += delta
        elif authorized:
            unbilled_auth_m3 += delta

    apparent_loss_m3 = input_volume_m3 * APPARENT_LOSS_RATE
    real_loss_m3 = input_volume_m3 - billed_m3 - unbilled_auth_m3 - apparent_loss_m3
    if real_loss_m3 < 0:
        real_loss_m3 = 0.0

    nrw_pct = (input_volume_m3 - billed_m3) / input_volume_m3 * 100.0

    # Build report row
    server_ts = server_now()
    ts = iso(server_ts)
    report = {
        "id": gen_id(),
        "dma_id": dma_id,
        "window_start": iso(ws_dt),
        "window_end": iso(we_dt),
        "input_volume_m3": round_half_up(input_volume_m3, 3),
        "billed_consumption_m3": round_half_up(billed_m3, 3),
        "unbilled_authorized_m3": round_half_up(unbilled_auth_m3, 3),
        "apparent_loss_m3": round_half_up(apparent_loss_m3, 3),
        "real_loss_m3": round_half_up(real_loss_m3, 3),
        "nrw_pct": round_half_up(nrw_pct, 2),
        "published_at": ts,
        "created_at": ts,
        "_seq": next_seq(),
    }
    water_balance_reports[report["id"]] = report
    emit_sync_for_water_balance_published(network_id, report)
    return report
