"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks pinned to PRD prose. Each assertion
checks exactly the surface contract the PRD declares.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_versioned(data: Dict[str, Any], label: str) -> None:
    """Standard resources expose id, created_at, updated_at, version
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be a positive integer, got {version!r}"
    )


def _assert_append_only(data: Dict[str, Any], label: str) -> None:
    """Append-only entries (SensorReading, AuditLog) expose only id and
    created_at per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------
def assert_tenant(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Tenant")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert data["status"] in {"ACTIVE", "SUSPENDED"}


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
def assert_plot(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Plot")
    assert isinstance(data["tenant_id"], str) and data["tenant_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["area_hectares"], (int, float))
    assert data["area_hectares"] > 0
    assert data["crop_type"] in {"WHEAT", "CORN", "RICE", "COTTON", "VEGETABLE"}
    assert data["crop_stage"] in {
        "SEEDLING", "VEGETATIVE", "FLOWERING", "FRUITING", "MATURE",
    }
    assert isinstance(data["pump_id"], str) and data["pump_id"]
    assert data["status"] in {"ACTIVE", "FALLOW"}
    last_irrigated = data.get("last_irrigated_at")
    assert last_irrigated is None or is_iso8601_timestamp(last_irrigated)


# ---------------------------------------------------------------------------
# Sensor
# ---------------------------------------------------------------------------
def assert_sensor(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Sensor")
    assert isinstance(data["plot_id"], str) and data["plot_id"]
    assert data["sensor_type"] in {
        "SOIL_MOISTURE", "SOIL_TEMPERATURE", "SOIL_EC", "WEATHER_STATION",
    }
    assert isinstance(data["poll_interval_seconds"], int)
    assert 30 <= data["poll_interval_seconds"] <= 3600
    assert isinstance(data["min_valid_value"], (int, float))
    assert isinstance(data["max_valid_value"], (int, float))
    assert data["status"] in {"ONLINE", "OFFLINE", "FAULTY"}
    last_reading = data.get("last_reading_at")
    assert last_reading is None or is_iso8601_timestamp(last_reading)


# ---------------------------------------------------------------------------
# SensorReading (append-only)
# ---------------------------------------------------------------------------
def assert_sensor_reading(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "SensorReading")
    assert isinstance(data["sensor_id"], str) and data["sensor_id"]
    assert isinstance(data["value"], (int, float))
    assert is_iso8601_timestamp(data["reading_timestamp"])
    assert data["validity"] in {
        "VALID", "OUT_OF_RANGE", "ABNORMAL_FILTERED", "ARCHIVED",
    }
    assert isinstance(data["archived"], bool)


# ---------------------------------------------------------------------------
# IrrigationPlan
# ---------------------------------------------------------------------------
def assert_irrigation_plan(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "IrrigationPlan")
    assert isinstance(data["plot_id"], str) and data["plot_id"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["planned_volume_liters"], (int, float))
    assert data["planned_volume_liters"] >= 0
    assert data["source"] in {"AUTO", "MANUAL_OVERRIDE"}
    assert data["status"] in {
        "DRAFT", "ACTIVE", "SUSPENDED", "COMPLETED", "CANCELLED",
    }
    assert isinstance(data["plan_version"], int)
    assert data["plan_version"] >= 1
    parent = data.get("parent_plan_id")
    assert parent is None or (isinstance(parent, str) and parent)


# ---------------------------------------------------------------------------
# ValveGroup
# ---------------------------------------------------------------------------
def assert_valve_group(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "ValveGroup")
    assert isinstance(data["tenant_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["pump_id"], str) and data["pump_id"]
    assert isinstance(data["valve_ids"], list)
    assert 1 <= len(data["valve_ids"]) <= 16
    assert data["control_mode"] in {"SEQUENTIAL", "PARALLEL"}
    assert isinstance(data["max_parallel_valves"], int)
    assert data["max_parallel_valves"] >= 1
    if data["control_mode"] == "SEQUENTIAL":
        assert data["max_parallel_valves"] == 1, (
            "PRD §3.3: 'control_mode of SEQUENTIAL forces "
            "max_parallel_valves to equal 1'"
        )


# ---------------------------------------------------------------------------
# ControlCommand
# ---------------------------------------------------------------------------
def assert_control_command(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "ControlCommand")
    assert isinstance(data["plan_id"], str) and data["plan_id"]
    assert isinstance(data["valve_group_id"], str) and data["valve_group_id"]
    assert isinstance(data["requested_volume_liters"], (int, float))
    assert data["requested_volume_liters"] > 0
    if "dispatch_mode" in data and data["dispatch_mode"] is not None:
        assert data["dispatch_mode"] in {"REMOTE", "LOCAL_DEGRADED"}
    assert data["status"] in {
        "PENDING", "DISPATCHING", "EXECUTING", "EXECUTED", "FAILED",
        "OFFLINE_LOCAL",
    }
    assert isinstance(data.get("actual_volume_liters", 0), (int, float))
    fb_at = data.get("feedback_received_at")
    assert fb_at is None or is_iso8601_timestamp(fb_at)


# ---------------------------------------------------------------------------
# WaterQuota
# ---------------------------------------------------------------------------
def assert_water_quota(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "WaterQuota")
    assert isinstance(data["plot_id"], str) and data["plot_id"]
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["allocated_liters"], (int, float))
    assert data["allocated_liters"] >= 0
    assert isinstance(data["carry_forward_liters"], (int, float))
    assert data["carry_forward_liters"] >= 0
    assert isinstance(data["provisional_used_liters"], (int, float))
    assert data["provisional_used_liters"] >= 0
    assert isinstance(data["final_used_liters"], (int, float))
    assert data["final_used_liters"] >= 0
    assert isinstance(data["warning_threshold_pct"], (int, float))
    assert 1 <= data["warning_threshold_pct"] <= 100
    assert data["usage_state"] in {"UNDER", "WARNING", "OVER"}
    assert data["approval_state"] in {
        "NOT_REQUIRED", "PENDING_APPROVAL", "APPROVED", "REJECTED",
    }
    assert isinstance(data["approval_extra_liters"], (int, float))
    assert data["approval_extra_liters"] >= 0


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------
def assert_alert(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Alert")
    assert isinstance(data["tenant_id"], str)
    assert data["subject_type"] in {"SENSOR", "PLOT", "VALVE_GROUP"}
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert data["rule_code"] in {
        "SENSOR_OFFLINE", "ABNORMAL_FLOW", "PIPE_BURST_SUSPICION",
        "VALVE_FAULT",
    }
    assert data["severity"] in {"INFO", "WARN", "CRITICAL"}
    assert data["status"] in {
        "TRIGGERED", "ACKNOWLEDGED", "RESOLVED", "REOPENED",
    }
    ack_by = data.get("acknowledged_by")
    assert ack_by is None or isinstance(ack_by, str)
    res_by = data.get("resolved_by")
    assert res_by is None or isinstance(res_by, str)


# ---------------------------------------------------------------------------
# WaterBill
# ---------------------------------------------------------------------------
def assert_water_bill(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "WaterBill")
    assert isinstance(data["tenant_id"], str) and data["tenant_id"]
    assert isinstance(data["plot_id"], str) and data["plot_id"]
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["peak_liters"], (int, float))
    assert data["peak_liters"] >= 0
    assert isinstance(data["offpeak_liters"], (int, float))
    assert data["offpeak_liters"] >= 0
    assert isinstance(data["line_items"], list)
    assert isinstance(data["total_amount_cents"], int)
    assert data["total_amount_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int)
    assert data["amount_paid_cents"] >= 0
    assert data["status"] in {
        "DRAFT", "ISSUED", "PAID", "DISPUTED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# AuditLog (append-only)
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "AuditLog")
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert data["action_type"] in {
        "CONTROL_COMMAND_ISSUED",
        "CONTROL_COMMAND_FAILED",
        "QUOTA_ALLOCATED",
        "QUOTA_OVERRIDE_APPROVED",
        "QUOTA_OVERRIDE_REJECTED",
        "PLAN_OVERRIDDEN",
    }
    assert data["subject_type"] in {
        "CONTROL_COMMAND", "WATER_QUOTA", "IRRIGATION_PLAN",
    }
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert isinstance(data.get("payload", {}), dict)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_quota_invariants(quota: Dict[str, Any]) -> None:
    """PRD §3.5 invariants:
    - effective_allocation == allocated_liters + carry_forward_liters + approval_extra_liters
    - usage_state derives from final_used_liters / effective_allocation.
    """
    effective = (
        quota["allocated_liters"]
        + quota["carry_forward_liters"]
        + quota["approval_extra_liters"]
    )
    assert effective >= 0


# ---------------------------------------------------------------------------
# Iteration helpers — find audit / line-item entries matching a predicate.
# ---------------------------------------------------------------------------
def find_audit_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    action_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in entries:
        if subject_type is not None and e.get("subject_type") != subject_type:
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        if action_type is not None and e.get("action_type") != action_type:
            continue
        out.append(e)
    return out


def _window_matches(item_window: Optional[str], expected: str) -> bool:
    """PRD §3.6 prose names the two windows 'peak or off-peak'. Two
    PRD-faithful encodings are visible: with or without the hyphen
    ('off-peak' vs 'offpeak'); upper or lower case. Accept both."""
    if item_window is None:
        return False
    iv = str(item_window).lower().replace("_", "-")
    ev = expected.lower().replace("_", "-")
    if ev == "offpeak":
        return iv in {"offpeak", "off-peak"}
    if ev == "off-peak":
        return iv in {"offpeak", "off-peak"}
    return iv == ev


def find_line_items(
    line_items: Iterable[Dict[str, Any]],
    *,
    window: Optional[str] = None,
    tier_index: Optional[int] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in line_items:
        if window is not None and not _window_matches(
            item.get("window"), window
        ):
            continue
        if tier_index is not None and item.get("tier_index") != tier_index:
            continue
        out.append(item)
    return out


def find_alerts(
    alerts: Iterable[Dict[str, Any]],
    *,
    rule_code: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for a in alerts:
        if rule_code is not None and a.get("rule_code") != rule_code:
            continue
        if subject_type is not None and a.get("subject_type") != subject_type:
            continue
        if subject_id is not None and a.get("subject_id") != subject_id:
            continue
        out.append(a)
    return out


__all__ = [
    "assert_tenant",
    "assert_plot",
    "assert_sensor",
    "assert_sensor_reading",
    "assert_irrigation_plan",
    "assert_valve_group",
    "assert_control_command",
    "assert_water_quota",
    "assert_alert",
    "assert_water_bill",
    "assert_audit_log",
    "assert_quota_invariants",
    "find_audit_entries",
    "find_line_items",
    "find_alerts",
]
