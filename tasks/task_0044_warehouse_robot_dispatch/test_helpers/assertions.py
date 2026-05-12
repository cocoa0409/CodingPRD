"""Entity assertions: shape and domain-invariant checkers.

Each assert_X(data) verifies the field names/types declared in PRD prose
for entity X. Append-only entities (MapEdge, SlotReservation,
TrajectoryRecord, AuditEvent) carry only id + created_at (PRD section
2.4) so their assertions deliberately do not require updated_at /
version.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------
def _assert_common_fields_full(data: Dict[str, Any], entity_name: str):
    """For entities that carry id + created_at + updated_at + version."""
    assert "id" in data, f"{entity_name}.id missing"
    assert is_valid_uuid(data["id"]), (
        f"{entity_name}.id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(data["created_at"]), (
        f"{entity_name}.created_at must be ISO 8601 timestamp"
    )
    assert "updated_at" in data and is_iso8601_timestamp(data["updated_at"]), (
        f"{entity_name}.updated_at must be ISO 8601 timestamp"
    )
    assert "version" in data and isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity_name}.version must be int >= 1"
    )


def _assert_common_fields_append_only(data: Dict[str, Any], entity_name: str):
    """For append-only entities: id + created_at only (no updated_at, no version)."""
    assert "id" in data, f"{entity_name}.id missing"
    assert is_valid_uuid(data["id"]), (
        f"{entity_name}.id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(data["created_at"]), (
        f"{entity_name}.created_at must be ISO 8601 timestamp"
    )


# ---------------------------------------------------------------------------
# Fleet
# ---------------------------------------------------------------------------
def assert_fleet(data: Dict[str, Any]):
    _assert_common_fields_full(data, "Fleet")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data["clock_now"]), (
        "Fleet.clock_now must be ISO 8601"
    )
    for k in (
        "charging_low_threshold_pct",
        "charging_opportunity_pct",
        "charging_full_pct",
        "slot_seconds",
        "task_expiry_seconds",
        "deadlock_wait_seconds",
    ):
        assert isinstance(data[k], int), f"Fleet.{k} must be int"
    # PRD section 3.8: opportunity > low, full > opportunity.
    assert (
        data["charging_opportunity_pct"]
        > data["charging_low_threshold_pct"]
    ), "Fleet.charging_opportunity_pct must be > charging_low_threshold_pct"
    assert (
        data["charging_full_pct"] > data["charging_opportunity_pct"]
    ), "Fleet.charging_full_pct must be > charging_opportunity_pct"


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
def assert_map_node(data: Dict[str, Any]):
    _assert_common_fields_full(data, "MapNode")
    assert isinstance(data["fleet_id"], str)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["kind"] in (
        "LANE",
        "INTERSECTION",
        "LIFT_POINT",
        "CHARGER",
        "PARK",
        "SHELF",
    )
    assert isinstance(data["x"], int)
    assert isinstance(data["y"], int)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["status"] in ("OPEN", "BLOCKED")
    if data["status"] == "OPEN":
        # PRD section 3.1: "When the node returns to OPEN, the reason is cleared back to null."
        assert data.get("blocked_reason") in (None,), (
            "blocked_reason must be null on OPEN node"
        )
    else:
        assert data.get("blocked_reason") in (
            "OBSTACLE",
            "EQUIPMENT_LOCKED",
            "MANUAL",
        ), f"blocked_reason must be one of OBSTACLE/EQUIPMENT_LOCKED/MANUAL, got {data.get('blocked_reason')!r}"


def assert_map_edge(data: Dict[str, Any]):
    _assert_common_fields_append_only(data, "MapEdge")
    assert "updated_at" not in data, (
        "MapEdge is append-only and must NOT include updated_at"
    )
    assert "version" not in data, (
        "MapEdge is append-only and must NOT include version"
    )
    assert isinstance(data["fleet_id"], str)
    assert isinstance(data["from_node_id"], str)
    assert isinstance(data["to_node_id"], str)
    assert isinstance(data["cost"], int) and data["cost"] >= 1
    assert isinstance(data["directional"], bool)


# ---------------------------------------------------------------------------
# Charging station
# ---------------------------------------------------------------------------
def assert_charging_station(data: Dict[str, Any]):
    _assert_common_fields_full(data, "ChargingStation")
    assert isinstance(data["fleet_id"], str)
    assert isinstance(data["node_id"], str)
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "DISABLED")
    if data["status"] == "AVAILABLE":
        assert data.get("occupying_robot_id") in (None,), (
            "occupying_robot_id must be null when AVAILABLE"
        )
    assert isinstance(data["queue_length"], int) and data["queue_length"] >= 0
    assert (
        isinstance(data["charge_rate_pct_per_second"], int)
        and data["charge_rate_pct_per_second"] >= 1
    )


# ---------------------------------------------------------------------------
# Robot
# ---------------------------------------------------------------------------
def assert_robot(data: Dict[str, Any]):
    _assert_common_fields_full(data, "Robot")
    assert isinstance(data["fleet_id"], str)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["connectivity"] in ("ONLINE", "OFFLINE")
    assert data["operational_state"] in (
        "IDLE",
        "EXECUTING",
        "WAITING_RIGHT_OF_WAY",
        "CHARGING",
        "WAITING_CHARGER",
        "UNDER_MANUAL_CONTROL",
        "OUT_OF_SERVICE",
    )
    assert data["fault_state"] in ("OK", "FAULTED")
    assert (
        isinstance(data["battery_pct"], int) and 0 <= data["battery_pct"] <= 100
    ), f"battery_pct out of range: {data['battery_pct']!r}"
    assert isinstance(data["position_node_id"], str)
    assert is_iso8601_timestamp(data["last_heartbeat_at"])
    assert isinstance(data["standby_priority"], int)
    assert (
        isinstance(data["trajectory_archived_count"], int)
        and data["trajectory_archived_count"] >= 0
    )


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------
TASK_STATUSES = (
    "QUEUED",
    "ASSIGNED",
    "EXECUTING",
    "COMPLETED",
    "CANCELLED",
    "EXPIRED",
    "ROLLED_BACK",
    "MERGED",
)
TASK_SOURCES = ("INBOUND", "OUTBOUND", "REPLENISHMENT", "RELOCATION")
TASK_PRIORITY_CLASSES = ("CRITICAL", "HIGH", "NORMAL", "LOW")


def assert_task(data: Dict[str, Any]):
    _assert_common_fields_full(data, "Task")
    assert isinstance(data["fleet_id"], str)
    assert data["source"] in TASK_SOURCES
    assert data["priority_class"] in TASK_PRIORITY_CLASSES
    assert isinstance(data["priority_score"], int)
    assert isinstance(data["payload_units"], int) and data["payload_units"] >= 1
    assert (
        isinstance(data["max_units_per_robot"], int)
        and data["max_units_per_robot"] >= 1
    )
    assert isinstance(data["pickup_node_id"], str)
    assert isinstance(data["dropoff_node_id"], str)
    assert data["status"] in TASK_STATUSES
    assert is_iso8601_timestamp(data["queued_at"])
    assert isinstance(data["planned_path_node_ids"], list)
    assert (
        isinstance(data["rollback_count"], int)
        and data["rollback_count"] >= 0
    )


# ---------------------------------------------------------------------------
# Slot reservation (append-only)
# ---------------------------------------------------------------------------
def assert_slot_reservation(data: Dict[str, Any]):
    _assert_common_fields_append_only(data, "SlotReservation")
    assert "updated_at" not in data, (
        "SlotReservation is append-only and must NOT include updated_at"
    )
    assert "version" not in data, (
        "SlotReservation is append-only and must NOT include version"
    )
    assert isinstance(data["fleet_id"], str)
    assert isinstance(data["node_id"], str)
    assert isinstance(data["robot_id"], str)
    assert isinstance(data["slot_index"], int)
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert data["status"] in ("HELD", "CONSUMED", "RELEASED")


# ---------------------------------------------------------------------------
# Charging session
# ---------------------------------------------------------------------------
def assert_charging_session(data: Dict[str, Any]):
    _assert_common_fields_full(data, "ChargingSession")
    assert isinstance(data["fleet_id"], str)
    assert isinstance(data["robot_id"], str)
    assert isinstance(data["charging_station_id"], str)
    assert data["trigger"] in ("FORCED_LOW", "OPPORTUNITY", "MANUAL")
    assert data["status"] in ("QUEUED", "CHARGING", "COMPLETED", "CANCELLED")


# ---------------------------------------------------------------------------
# Fault incident
# ---------------------------------------------------------------------------
def assert_fault_incident(data: Dict[str, Any]):
    _assert_common_fields_full(data, "FaultIncident")
    assert isinstance(data["fleet_id"], str)
    assert isinstance(data["robot_id"], str)
    assert data["kind"] in ("COMM_LOSS", "SENSOR_ANOMALY", "MECHANICAL_FAULT")
    assert data["status"] in ("OPEN", "TAKEOVER", "RESOLVED")
    assert isinstance(data["isolation_node_ids"], list)
    assert is_iso8601_timestamp(data["detected_at"])


# ---------------------------------------------------------------------------
# Trajectory record (append-only)
# ---------------------------------------------------------------------------
def assert_trajectory_record(data: Dict[str, Any]):
    _assert_common_fields_append_only(data, "TrajectoryRecord")
    assert "updated_at" not in data, (
        "TrajectoryRecord is append-only and must NOT include updated_at"
    )
    assert "version" not in data, (
        "TrajectoryRecord is append-only and must NOT include version"
    )
    assert isinstance(data["robot_id"], str)
    assert isinstance(data["from_node_id"], str)
    assert isinstance(data["to_node_id"], str)
    assert is_iso8601_timestamp(data["occurred_at"])


# ---------------------------------------------------------------------------
# Audit event (append-only)
# ---------------------------------------------------------------------------
def assert_audit_event(data: Dict[str, Any]):
    _assert_common_fields_append_only(data, "AuditEvent")
    assert "updated_at" not in data, (
        "AuditEvent is append-only and must NOT include updated_at"
    )
    assert "version" not in data, (
        "AuditEvent is append-only and must NOT include version"
    )
    assert isinstance(data["fleet_id"], str)
    assert data["event_kind"] in (
        "TASK_STATUS",
        "FAULT",
        "WMS_SYNC",
        "EQUIPMENT_LOCK",
        "EQUIPMENT_UNLOCK",
    )
    assert data["subject_kind"] in ("Task", "Robot", "FaultIncident", "MapNode")
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["to_state"], str)
    assert isinstance(data["actor_role"], str)
    assert is_iso8601_timestamp(data["occurred_at"])


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------
def find_audit_events(
    events: Iterable[Dict[str, Any]],
    *,
    event_kind: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in events:
        if event_kind is not None and e.get("event_kind") != event_kind:
            continue
        if subject_kind is not None and e.get("subject_kind") != subject_kind:
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        if from_state is not None and e.get("from_state") != from_state:
            continue
        if to_state is not None and e.get("to_state") != to_state:
            continue
        out.append(e)
    return out


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def assert_ratio_4dp(value: Any, *, label: str = "value"):
    """PRD section 2.9: ratio-style metrics are rounded half up to four
    decimal places. We verify the value has at most 4 decimal digits."""
    assert isinstance(value, (int, float)), (
        f"{label} must be numeric, got {type(value).__name__}"
    )
    # Use round-trip to detect more than 4 decimals.
    rounded = round(float(value), 4)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{label}={value} exceeds 4 decimal places of precision"
    )


def assert_duration_2dp(value: Any, *, label: str = "value"):
    """PRD section 2.9: average task duration in seconds is rounded half
    up to two decimal places."""
    assert isinstance(value, (int, float)), (
        f"{label} must be numeric, got {type(value).__name__}"
    )
    rounded = round(float(value), 2)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{label}={value} exceeds 2 decimal places of precision"
    )


__all__ = [
    "assert_fleet",
    "assert_map_node",
    "assert_map_edge",
    "assert_charging_station",
    "assert_robot",
    "assert_task",
    "assert_slot_reservation",
    "assert_charging_session",
    "assert_fault_incident",
    "assert_trajectory_record",
    "assert_audit_event",
    "find_audit_events",
    "assert_ratio_4dp",
    "assert_duration_2dp",
    "TASK_STATUSES",
    "TASK_SOURCES",
    "TASK_PRIORITY_CLASSES",
]
