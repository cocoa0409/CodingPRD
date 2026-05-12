"""Domain types: entity TypedDicts, status enums, role enum.

All fields and enum values match PRD names verbatim. Append-only ledger
entities (MapEdge, SlotReservation, TrajectoryRecord, AuditEvent) carry
only id and created_at per PRD section 2.4.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD section 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    Operator = "Operator"
    FleetAdmin = "FleetAdmin"
    WMS = "WMS"


# ---------------------------------------------------------------------------
# Status / enum types (PRD sections 3.1-3.10)
# ---------------------------------------------------------------------------
class MapNodeKind(str, Enum):
    LANE = "LANE"
    INTERSECTION = "INTERSECTION"
    LIFT_POINT = "LIFT_POINT"
    CHARGER = "CHARGER"
    PARK = "PARK"
    SHELF = "SHELF"


class MapNodeStatus(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"


class MapNodeBlockedReason(str, Enum):
    OBSTACLE = "OBSTACLE"
    EQUIPMENT_LOCKED = "EQUIPMENT_LOCKED"
    MANUAL = "MANUAL"


class ChargingStationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    DISABLED = "DISABLED"


class RobotConnectivity(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class RobotOperationalState(str, Enum):
    IDLE = "IDLE"
    EXECUTING = "EXECUTING"
    WAITING_RIGHT_OF_WAY = "WAITING_RIGHT_OF_WAY"
    CHARGING = "CHARGING"
    WAITING_CHARGER = "WAITING_CHARGER"
    UNDER_MANUAL_CONTROL = "UNDER_MANUAL_CONTROL"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RobotFaultState(str, Enum):
    OK = "OK"
    FAULTED = "FAULTED"


class TaskSource(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    REPLENISHMENT = "REPLENISHMENT"
    RELOCATION = "RELOCATION"


class TaskPriorityClass(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    ROLLED_BACK = "ROLLED_BACK"
    MERGED = "MERGED"


class SlotReservationStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class ChargingTrigger(str, Enum):
    FORCED_LOW = "FORCED_LOW"
    OPPORTUNITY = "OPPORTUNITY"
    MANUAL = "MANUAL"


class ChargingSessionStatus(str, Enum):
    QUEUED = "QUEUED"
    CHARGING = "CHARGING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FaultKind(str, Enum):
    COMM_LOSS = "COMM_LOSS"
    SENSOR_ANOMALY = "SENSOR_ANOMALY"
    MECHANICAL_FAULT = "MECHANICAL_FAULT"


class FaultIncidentStatus(str, Enum):
    OPEN = "OPEN"
    TAKEOVER = "TAKEOVER"
    RESOLVED = "RESOLVED"


class AuditEventKind(str, Enum):
    TASK_STATUS = "TASK_STATUS"
    FAULT = "FAULT"
    WMS_SYNC = "WMS_SYNC"
    EQUIPMENT_LOCK = "EQUIPMENT_LOCK"
    EQUIPMENT_UNLOCK = "EQUIPMENT_UNLOCK"


class AuditSubjectKind(str, Enum):
    Task = "Task"
    Robot = "Robot"
    FaultIncident = "FaultIncident"
    MapNode = "MapNode"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD section 2.4: common_fields=true entities carry the
# full quartet; append-only entities carry only id+created_at).
# ---------------------------------------------------------------------------
class Fleet(TypedDict):
    id: str
    name: str
    clock_now: str
    charging_low_threshold_pct: int
    charging_opportunity_pct: int
    charging_full_pct: int
    slot_seconds: int
    task_expiry_seconds: int
    deadlock_wait_seconds: int
    created_at: str
    updated_at: str
    version: int


class MapNode(TypedDict):
    id: str
    fleet_id: str
    code: str
    kind: str
    x: int
    y: int
    capacity: int
    status: str
    blocked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only.
class MapEdge(TypedDict):
    id: str
    fleet_id: str
    from_node_id: str
    to_node_id: str
    cost: int
    directional: bool
    created_at: str


class ChargingStation(TypedDict):
    id: str
    fleet_id: str
    node_id: str
    status: str
    occupying_robot_id: Optional[str]
    queue_length: int
    charge_rate_pct_per_second: int
    created_at: str
    updated_at: str
    version: int


class Robot(TypedDict):
    id: str
    fleet_id: str
    code: str
    connectivity: str
    operational_state: str
    fault_state: str
    battery_pct: int
    position_node_id: str
    current_task_id: Optional[str]
    charging_station_id: Optional[str]
    last_heartbeat_at: str
    standby_priority: int
    trajectory_archived_count: int
    created_at: str
    updated_at: str
    version: int


class Task(TypedDict):
    id: str
    fleet_id: str
    source: str
    priority_class: str
    priority_score: int
    payload_units: int
    max_units_per_robot: int
    pickup_node_id: str
    dropoff_node_id: str
    status: str
    assigned_robot_id: Optional[str]
    parent_task_id: Optional[str]
    merged_into_task_id: Optional[str]
    queued_at: str
    assigned_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    planned_path_node_ids: List[str]
    rollback_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only.
class SlotReservation(TypedDict):
    id: str
    fleet_id: str
    node_id: str
    robot_id: str
    task_id: Optional[str]
    slot_index: int
    scheduled_at: str
    status: str
    created_at: str


class ChargingSession(TypedDict):
    id: str
    fleet_id: str
    robot_id: str
    charging_station_id: str
    trigger: str
    status: str
    start_battery_pct: Optional[int]
    end_battery_pct: Optional[int]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FaultIncident(TypedDict):
    id: str
    fleet_id: str
    robot_id: str
    kind: str
    status: str
    isolation_node_ids: List[str]
    rolled_back_task_id: Optional[str]
    reassigned_task_id: Optional[str]
    detected_at: str
    takeover_started_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only.
class TrajectoryRecord(TypedDict):
    id: str
    robot_id: str
    from_node_id: str
    to_node_id: str
    occurred_at: str
    created_at: str


# Append-only: id + created_at only.
class AuditEvent(TypedDict):
    id: str
    fleet_id: str
    event_kind: str
    subject_kind: str
    subject_id: str
    from_state: Optional[str]
    to_state: str
    actor_role: str
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "MapNodeKind",
    "MapNodeStatus",
    "MapNodeBlockedReason",
    "ChargingStationStatus",
    "RobotConnectivity",
    "RobotOperationalState",
    "RobotFaultState",
    "TaskSource",
    "TaskPriorityClass",
    "TaskStatus",
    "SlotReservationStatus",
    "ChargingTrigger",
    "ChargingSessionStatus",
    "FaultKind",
    "FaultIncidentStatus",
    "AuditEventKind",
    "AuditSubjectKind",
    "Fleet",
    "MapNode",
    "MapEdge",
    "ChargingStation",
    "Robot",
    "Task",
    "SlotReservation",
    "ChargingSession",
    "FaultIncident",
    "TrajectoryRecord",
    "AuditEvent",
]
