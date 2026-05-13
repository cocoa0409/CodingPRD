"""Payload factories — one per entity, input fields only.

Every factory emits the exact schema PRD declares for the corresponding
create / mutate endpoint. Overrides are merged on top of defaults so tests
can vary the minimum needed to exercise their claim.
"""
from __future__ import annotations
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-suffix helpers — every payload must be unique to avoid collisions
# across the per-session API client.
# ---------------------------------------------------------------------------
_counter = 0


def unique_suffix() -> str:
    global _counter
    _counter += 1
    return f"{int(time.time() * 1000)}-{_counter}-{uuid.uuid4().hex[:6]}"


def unique_code(prefix: str = "C") -> str:
    return f"{prefix}-{unique_suffix()}"


def iso_z(dt: datetime) -> str:
    """Return ISO 8601 UTC string with three fractional digits (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    # Truncate microseconds to milliseconds.
    return s[:-3] + "Z"


def iso_from_epoch_ms(epoch_ms: int) -> str:
    return iso_z(datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc))


# ---------------------------------------------------------------------------
# Network (PRD §3.1)
# ---------------------------------------------------------------------------
def create_network_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'display name, a globally unique utility_code that
    identifies the operating entity, and optionally a nrw_target_pct'."""
    defaults: Dict[str, Any] = {
        "name": f"Test Network {unique_suffix()}",
        "utility_code": f"UTIL-{unique_suffix()}",
        "nrw_target_pct": 12.0,
    }
    defaults.update(overrides)
    return defaults


def advance_clock_payload(advance_ms: int) -> Dict[str, Any]:
    """PRD §3.1: 'advance_ms body parameter, which must be strictly
    greater than zero.'"""
    return {"advance_ms": advance_ms}


# ---------------------------------------------------------------------------
# Topology / nodes / segments (PRD §3.2)
# ---------------------------------------------------------------------------
def create_topology_version_payload(change_summary: Optional[str] = None,
                                    parent_version_id: Optional[str] = None,
                                    **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: input is 'change_summary describing what they intend to
    change and optionally a parent_version_id'."""
    payload: Dict[str, Any] = {
        "change_summary": change_summary or f"Draft {unique_suffix()}",
    }
    if parent_version_id is not None:
        payload["parent_version_id"] = parent_version_id
    payload.update(overrides)
    return payload


def create_node_payload(node_code: Optional[str] = None,
                        kind: str = "JUNCTION",
                        dma_id: Optional[str] = None,
                        latitude: float = 40.0,
                        longitude: float = -73.0,
                        elevation_m: float = 10.0,
                        valve_default_open: Optional[bool] = None,
                        **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: node carries node_code, kind, latitude, longitude,
    elevation_m; dma_id required unless kind=RESERVOIR; valve_default_open
    required only when kind=VALVE."""
    payload: Dict[str, Any] = {
        "node_code": node_code or unique_code("N"),
        "kind": kind,
        "latitude": latitude,
        "longitude": longitude,
        "elevation_m": elevation_m,
    }
    if kind != "RESERVOIR":
        # PRD §3.2: 'the only kind for which dma_id may be null is RESERVOIR'.
        payload["dma_id"] = dma_id
    if kind == "VALVE":
        payload["valve_default_open"] = (
            True if valve_default_open is None else valve_default_open
        )
    payload.update(overrides)
    return payload


def create_segment_payload(segment_code: Optional[str] = None,
                           from_node_code: str = "N-from",
                           to_node_code: str = "N-to",
                           length_m: float = 100.0,
                           diameter_mm: int = 200,
                           material: str = "PVC",
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: segment_code unique, from/to node_codes (not equal),
    strictly positive length_m and diameter_mm, material in closed enum."""
    payload: Dict[str, Any] = {
        "segment_code": segment_code or unique_code("S"),
        "from_node_code": from_node_code,
        "to_node_code": to_node_code,
        "length_m": length_m,
        "diameter_mm": diameter_mm,
        "material": material,
    }
    payload.update(overrides)
    return payload


def reject_topology_payload(reason: str = "needs revision") -> Dict[str, Any]:
    return {"rejection_reason": reason}


# ---------------------------------------------------------------------------
# DMA (PRD §3.3)
# ---------------------------------------------------------------------------
def create_dma_payload(dma_code: Optional[str] = None,
                       name: Optional[str] = None,
                       inlet_node_codes: Optional[List[str]] = None,
                       outlet_node_codes: Optional[List[str]] = None,
                       **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'dma_code unique within the network, a display name, and
    optionally the inlet_node_codes and outlet_node_codes arrays'."""
    payload: Dict[str, Any] = {
        "dma_code": dma_code or unique_code("D"),
        "name": name or f"DMA {unique_suffix()}",
    }
    if inlet_node_codes is not None:
        payload["inlet_node_codes"] = inlet_node_codes
    if outlet_node_codes is not None:
        payload["outlet_node_codes"] = outlet_node_codes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Device (PRD §3.4)
# ---------------------------------------------------------------------------
def create_device_payload(device_code: Optional[str] = None,
                          mounted_on_node_code: Optional[str] = None,
                          protocol: str = "WIRED",
                          sensor_kind: str = "PRESSURE",
                          polling_interval_s: int = 60,
                          valid_range_min: float = 200.0,
                          valid_range_max: float = 600.0,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: device_code unique, optional mount, protocol/sensor_kind
    enums, polling_interval_s in [30, 3600], valid_range_min <
    valid_range_max."""
    payload: Dict[str, Any] = {
        "device_code": device_code or unique_code("DV"),
        "protocol": protocol,
        "sensor_kind": sensor_kind,
        "polling_interval_s": polling_interval_s,
        "valid_range_min": valid_range_min,
        "valid_range_max": valid_range_max,
    }
    if mounted_on_node_code is not None:
        payload["mounted_on_node_code"] = mounted_on_node_code
    payload.update(overrides)
    return payload


def patch_device_payload(version: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §2.4: 'A client supplies the version field they last
    observed.'"""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


def post_reading_payload(observed_at: str, raw_value: float,
                         idempotency_key: Optional[str] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'observed_at (the device-side timestamp, in ISO 8601
    UTC), raw_value ... and optionally an idempotency_key.'"""
    payload: Dict[str, Any] = {
        "observed_at": observed_at,
        "raw_value": raw_value,
    }
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Alerts (PRD §3.6)
# ---------------------------------------------------------------------------
def resolve_alert_payload(resolution_note: str = "resolved by test"
                          ) -> Dict[str, Any]:
    """PRD §3.6: 'the request body must also supply a resolution_note'."""
    return {"resolution_note": resolution_note}


def suppress_alert_payload(resolution_note: str = "false positive"
                           ) -> Dict[str, Any]:
    """PRD §3.6: 'From OPEN, the request body must supply a
    resolution_note.'"""
    return {"resolution_note": resolution_note}


# ---------------------------------------------------------------------------
# Investigations (PRD §3.7)
# ---------------------------------------------------------------------------
def dispatch_investigation_payload(assigned_technician_id: str,
                                   target_segment_code: str
                                   ) -> Dict[str, Any]:
    """PRD §3.7: dispatch requires assigned_technician_id and accepts
    target_segment_code."""
    return {
        "assigned_technician_id": assigned_technician_id,
        "target_segment_code": target_segment_code,
    }


# ---------------------------------------------------------------------------
# WorkOrder (PRD §3.8)
# ---------------------------------------------------------------------------
def create_work_order_payload(origin: str,
                              target_segment_code: str,
                              alert_id: Optional[str] = None,
                              investigation_id: Optional[str] = None,
                              parts_required: Optional[List[Dict[str, Any]]] = None,
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'When origin=ALERT_AUTO, the supervisor must supply
    alert_id; when origin=INVESTIGATION, investigation_id is required.
    Every work order carries a target_segment_code referencing the segment
    scheduled for repair.'"""
    payload: Dict[str, Any] = {
        "origin": origin,
        "target_segment_code": target_segment_code,
    }
    if origin == "ALERT_AUTO" and alert_id is not None:
        payload["alert_id"] = alert_id
    if origin == "INVESTIGATION" and investigation_id is not None:
        payload["investigation_id"] = investigation_id
    if parts_required is not None:
        payload["parts_required"] = parts_required
    payload.update(overrides)
    return payload


def assign_work_order_payload(assigned_technician_id: str) -> Dict[str, Any]:
    return {"assigned_technician_id": assigned_technician_id}


def request_parts_payload(parts: Optional[List[Dict[str, Any]]] = None
                          ) -> Dict[str, Any]:
    """PRD §3.8: 'the supplied parts_required array to be non-empty (each
    element is a {part_code, quantity} object).'"""
    if parts is None:
        parts = [{"part_code": "VALVE-1", "quantity": 1}]
    return {"parts_required": parts}


def complete_work_order_payload(leak_class: str = "LEAK_CONFIRMED",
                                summary: str = "Repair complete",
                                valve_isolations_used: Optional[List[str]] = None
                                ) -> Dict[str, Any]:
    """PRD §3.8: 'a repair_record object — carrying free-form notes such
    as a summary, a valve_isolations_used list, and a categorical
    leak_class.'"""
    if valve_isolations_used is None:
        valve_isolations_used = []
    return {
        "repair_record": {
            "summary": summary,
            "valve_isolations_used": valve_isolations_used,
            "leak_class": leak_class,
        }
    }


def verify_work_order_payload(outcome: str,
                              verification_note: Optional[str] = None
                              ) -> Dict[str, Any]:
    """PRD §3.8: 'an outcome of PASS or FAIL, and optionally a
    verification_note.'"""
    payload: Dict[str, Any] = {"outcome": outcome}
    if verification_note is not None:
        payload["verification_note"] = verification_note
    return payload


# ---------------------------------------------------------------------------
# Water balance report (PRD §3.9)
# ---------------------------------------------------------------------------
def water_balance_report_payload(window_start: str,
                                 window_end: str) -> Dict[str, Any]:
    """PRD §3.9: 'window_start and window_end, both expressed as ISO 8601
    UTC timestamps.'"""
    return {"window_start": window_start, "window_end": window_end}


__all__ = [
    "unique_suffix",
    "unique_code",
    "iso_z",
    "iso_from_epoch_ms",
    "create_network_payload",
    "advance_clock_payload",
    "create_topology_version_payload",
    "create_node_payload",
    "create_segment_payload",
    "reject_topology_payload",
    "create_dma_payload",
    "create_device_payload",
    "patch_device_payload",
    "post_reading_payload",
    "resolve_alert_payload",
    "suppress_alert_payload",
    "dispatch_investigation_payload",
    "create_work_order_payload",
    "assign_work_order_payload",
    "request_parts_payload",
    "complete_work_order_payload",
    "verify_work_order_payload",
    "water_balance_report_payload",
]
