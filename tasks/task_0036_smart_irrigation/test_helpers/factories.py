"""Payload factories — one factory per entity, input fields only.

Field names match PRD §3 verbatim. Each factory accepts **overrides so
individual tests can pin specific values for boundary or precondition
behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers for unique inputs
# ---------------------------------------------------------------------------
def unique_name(prefix: str = "name") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_email(prefix: str = "tenant") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.test"


def unique_pump_id(prefix: str = "pump") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_valve_id(prefix: str = "valve") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tenant (PRD §3.1)
# ---------------------------------------------------------------------------
def create_tenant_payload(
    *,
    name: Optional[str] = None,
    contact_email: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or unique_name("Tenant"),
        "contact_email": contact_email or unique_email("tenant"),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plot (PRD §3.1)
# ---------------------------------------------------------------------------
def create_plot_payload(
    *,
    tenant_id: str,
    name: Optional[str] = None,
    area_hectares: float = 10.0,
    crop_type: str = "CORN",
    crop_stage: str = "VEGETATIVE",
    pump_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "name": name or unique_name("Plot"),
        "area_hectares": area_hectares,
        "crop_type": crop_type,
        "crop_stage": crop_stage,
        "pump_id": pump_id or unique_pump_id("pump"),
    }
    payload.update(overrides)
    return payload


def patch_plot_payload(
    *,
    crop_stage: Optional[str] = None,
    pump_id: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if crop_stage is not None:
        payload["crop_stage"] = crop_stage
    if pump_id is not None:
        payload["pump_id"] = pump_id
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Sensor (PRD §3.1)
# ---------------------------------------------------------------------------
def create_sensor_payload(
    *,
    plot_id: str,
    sensor_type: str = "SOIL_MOISTURE",
    poll_interval_seconds: int = 300,
    min_valid_value: float = 10.0,
    max_valid_value: float = 90.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plot_id": plot_id,
        "sensor_type": sensor_type,
        "poll_interval_seconds": poll_interval_seconds,
        "min_valid_value": min_valid_value,
        "max_valid_value": max_valid_value,
    }
    payload.update(overrides)
    return payload


def patch_sensor_payload(
    *,
    poll_interval_seconds: Optional[int] = None,
    min_valid_value: Optional[float] = None,
    max_valid_value: Optional[float] = None,
    status: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if poll_interval_seconds is not None:
        payload["poll_interval_seconds"] = poll_interval_seconds
    if min_valid_value is not None:
        payload["min_valid_value"] = min_valid_value
    if max_valid_value is not None:
        payload["max_valid_value"] = max_valid_value
    if status is not None:
        payload["status"] = status
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SensorReading (PRD §3.1)
# ---------------------------------------------------------------------------
def create_reading_payload(
    *,
    value: float,
    reading_timestamp: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "value": value,
        "reading_timestamp": reading_timestamp,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# IrrigationPlan (PRD §3.2)
# ---------------------------------------------------------------------------
def create_plan_payload(
    *,
    window_start: str,
    window_end: str,
    source: Optional[str] = None,
    planned_volume_liters: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "window_start": window_start,
        "window_end": window_end,
    }
    if source is not None:
        payload["source"] = source
    if planned_volume_liters is not None:
        payload["planned_volume_liters"] = planned_volume_liters
    payload.update(overrides)
    return payload


def override_plan_payload(
    *,
    planned_volume_liters: Optional[float] = None,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if planned_volume_liters is not None:
        payload["planned_volume_liters"] = planned_volume_liters
    if window_start is not None:
        payload["window_start"] = window_start
    if window_end is not None:
        payload["window_end"] = window_end
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ValveGroup (PRD §3.3)
# ---------------------------------------------------------------------------
def create_valve_group_payload(
    *,
    tenant_id: str,
    name: Optional[str] = None,
    pump_id: Optional[str] = None,
    valve_ids: Optional[List[str]] = None,
    control_mode: str = "SEQUENTIAL",
    max_parallel_valves: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    # Distinguish "caller did not pass valve_ids" (None) from "caller
    # passed empty list" (test_empty_valve_ids_rejected) — the latter
    # must reach the implementation as `[]` so PRD §3.3's non-empty
    # check can fire.
    if valve_ids is None:
        valve_ids = [unique_valve_id("v")]
    payload: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "name": name or unique_name("ValveGroup"),
        "pump_id": pump_id or unique_pump_id("pump"),
        "valve_ids": valve_ids,
        "control_mode": control_mode,
        "max_parallel_valves": max_parallel_valves,
    }
    payload.update(overrides)
    return payload


def patch_valve_group_payload(
    *,
    name: Optional[str] = None,
    valve_ids: Optional[List[str]] = None,
    control_mode: Optional[str] = None,
    max_parallel_valves: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if valve_ids is not None:
        payload["valve_ids"] = valve_ids
    if control_mode is not None:
        payload["control_mode"] = control_mode
    if max_parallel_valves is not None:
        payload["max_parallel_valves"] = max_parallel_valves
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ControlCommand (PRD §3.4)
# ---------------------------------------------------------------------------
def create_control_command_payload(
    *,
    plan_id: str,
    valve_group_id: str,
    requested_volume_liters: float,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plan_id": plan_id,
        "valve_group_id": valve_group_id,
        "requested_volume_liters": requested_volume_liters,
    }
    payload.update(overrides)
    return payload


def feedback_payload(
    *,
    phase: str,
    actual_volume_liters: Optional[float] = None,
    failure_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"phase": phase}
    if actual_volume_liters is not None:
        payload["actual_volume_liters"] = actual_volume_liters
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# WaterQuota (PRD §3.5)
# ---------------------------------------------------------------------------
def create_water_quota_payload(
    *,
    plot_id: str,
    period_start: str,
    period_end: str,
    allocated_liters: float = 10000.0,
    warning_threshold_pct: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plot_id": plot_id,
        "period_start": period_start,
        "period_end": period_end,
        "allocated_liters": allocated_liters,
    }
    if warning_threshold_pct is not None:
        payload["warning_threshold_pct"] = warning_threshold_pct
    payload.update(overrides)
    return payload


def patch_water_quota_payload(
    *,
    allocated_liters: Optional[float] = None,
    warning_threshold_pct: Optional[float] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if allocated_liters is not None:
        payload["allocated_liters"] = allocated_liters
    if warning_threshold_pct is not None:
        payload["warning_threshold_pct"] = warning_threshold_pct
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def request_override_payload(
    *,
    reason: str = "Drought response",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def approve_override_payload(
    *,
    extra_liters: float,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"extra_liters": extra_liters}
    payload.update(overrides)
    return payload


def reject_override_payload(
    *,
    reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# WaterBill (PRD §3.6)
# ---------------------------------------------------------------------------
def create_water_bill_payload(
    *,
    tenant_id: str,
    plot_id: str,
    period_start: str,
    period_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "plot_id": plot_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def payment_payload(
    *,
    amount_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def dispute_payload(
    *,
    dispute_reason: str = "Meter reading appears inflated",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"dispute_reason": dispute_reason}
    payload.update(overrides)
    return payload


def dispute_resolve_payload(
    *,
    outcome: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driving / events (PRD §3.8 / §4)
# ---------------------------------------------------------------------------
def emit_event_payload(
    *,
    event_type: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return {"event_type": event_type, "payload": payload}


__all__ = [
    "unique_name",
    "unique_email",
    "unique_pump_id",
    "unique_valve_id",
    "create_tenant_payload",
    "create_plot_payload",
    "patch_plot_payload",
    "create_sensor_payload",
    "patch_sensor_payload",
    "create_reading_payload",
    "create_plan_payload",
    "override_plan_payload",
    "create_valve_group_payload",
    "patch_valve_group_payload",
    "create_control_command_payload",
    "feedback_payload",
    "create_water_quota_payload",
    "patch_water_quota_payload",
    "request_override_payload",
    "approve_override_payload",
    "reject_override_payload",
    "create_water_bill_payload",
    "payment_payload",
    "dispute_payload",
    "dispute_resolve_payload",
    "emit_event_payload",
]
