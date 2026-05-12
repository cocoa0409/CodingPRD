"""Payload factories - one per endpoint with input fields.

Each factory emits only source: input fields and accepts **overrides so
that tests can pin specific values (e.g., a known battery_pct for
boundary tests).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Identifier helpers
# ---------------------------------------------------------------------------
def unique_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def unique_code(prefix: str = "C") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Fleet
# ---------------------------------------------------------------------------
def create_fleet_payload(
    *,
    name: Optional[str] = None,
    charging_low_threshold_pct: Optional[int] = None,
    charging_opportunity_pct: Optional[int] = None,
    charging_full_pct: Optional[int] = None,
    slot_seconds: Optional[int] = None,
    task_expiry_seconds: Optional[int] = None,
    deadlock_wait_seconds: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name if name is not None else f"fleet-{unique_id()}",
    }
    if charging_low_threshold_pct is not None:
        payload["charging_low_threshold_pct"] = charging_low_threshold_pct
    if charging_opportunity_pct is not None:
        payload["charging_opportunity_pct"] = charging_opportunity_pct
    if charging_full_pct is not None:
        payload["charging_full_pct"] = charging_full_pct
    if slot_seconds is not None:
        payload["slot_seconds"] = slot_seconds
    if task_expiry_seconds is not None:
        payload["task_expiry_seconds"] = task_expiry_seconds
    if deadlock_wait_seconds is not None:
        payload["deadlock_wait_seconds"] = deadlock_wait_seconds
    payload.update(overrides)
    return payload


def advance_clock_payload(
    *, delta_seconds: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"delta_seconds": delta_seconds}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Map nodes / edges
# ---------------------------------------------------------------------------
def create_map_node_payload(
    *,
    code: Optional[str] = None,
    kind: str = "LANE",
    x: int = 0,
    y: int = 0,
    capacity: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code if code is not None else unique_code("N"),
        "kind": kind,
        "x": x,
        "y": y,
    }
    if capacity is not None:
        payload["capacity"] = capacity
    payload.update(overrides)
    return payload


def create_map_edge_payload(
    *,
    from_node_id: str,
    to_node_id: str,
    cost: Optional[int] = None,
    directional: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
    }
    if cost is not None:
        payload["cost"] = cost
    if directional is not None:
        payload["directional"] = directional
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Charging station
# ---------------------------------------------------------------------------
def create_charging_station_payload(
    *,
    node_id: str,
    charge_rate_pct_per_second: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"node_id": node_id}
    if charge_rate_pct_per_second is not None:
        payload["charge_rate_pct_per_second"] = charge_rate_pct_per_second
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Robot
# ---------------------------------------------------------------------------
def create_robot_payload(
    *,
    position_node_id: str,
    code: Optional[str] = None,
    battery_pct: Optional[int] = None,
    standby_priority: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code if code is not None else unique_code("R"),
        "position_node_id": position_node_id,
    }
    if battery_pct is not None:
        payload["battery_pct"] = battery_pct
    if standby_priority is not None:
        payload["standby_priority"] = standby_priority
    payload.update(overrides)
    return payload


def queue_charger_payload(
    *, charging_station_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"charging_station_id": charging_station_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------
def create_task_payload(
    *,
    source: str = "INBOUND",
    pickup_node_id: str,
    dropoff_node_id: str,
    priority_class: Optional[str] = None,
    payload_units: Optional[int] = None,
    max_units_per_robot: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source": source,
        "pickup_node_id": pickup_node_id,
        "dropoff_node_id": dropoff_node_id,
    }
    if priority_class is not None:
        payload["priority_class"] = priority_class
    if payload_units is not None:
        payload["payload_units"] = payload_units
    if max_units_per_robot is not None:
        payload["max_units_per_robot"] = max_units_per_robot
    payload.update(overrides)
    return payload


def assign_task_payload(*, robot_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"robot_id": robot_id}
    payload.update(overrides)
    return payload


def merge_tasks_payload(
    *, task_id_a: str, task_id_b: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "task_id_a": task_id_a,
        "task_id_b": task_id_b,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Slot reservation
# ---------------------------------------------------------------------------
def create_slot_reservation_payload(
    *,
    node_id: str,
    robot_id: str,
    scheduled_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "node_id": node_id,
        "robot_id": robot_id,
        "scheduled_at": scheduled_at,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Fault incident
# ---------------------------------------------------------------------------
def open_fault_payload(*, kind: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"kind": kind}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def emit_event_payload(
    *,
    event_kind: str,
    node_ids: Optional[List[str]] = None,
    wms_task_payload: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_kind": event_kind}
    if node_ids is not None:
        payload["node_ids"] = node_ids
    if wms_task_payload is not None:
        payload["wms_task_payload"] = wms_task_payload
    payload.update(overrides)
    return payload


__all__ = [
    "unique_id",
    "unique_code",
    "create_fleet_payload",
    "advance_clock_payload",
    "create_map_node_payload",
    "create_map_edge_payload",
    "create_charging_station_payload",
    "create_robot_payload",
    "queue_charger_payload",
    "create_task_payload",
    "assign_task_payload",
    "merge_tasks_payload",
    "create_slot_reservation_payload",
    "open_fault_payload",
    "emit_event_payload",
]
