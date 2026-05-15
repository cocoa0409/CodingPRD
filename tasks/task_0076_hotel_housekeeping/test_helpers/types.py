"""Domain types for the Hotel Housekeeping API.

Entity TypedDicts, status enums, and role enum. Mutable entities carry
id + created_at + updated_at + version; append-only entities
(InspectionRecord, RoomStatusEvent, LinenMovement, AuditLog) carry only
id + created_at, per PRD §2.4.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1) — five role names; see RBAC matrix in PRD §4.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    HOUSEKEEPER = "Housekeeper"
    SUPERVISOR = "Supervisor"
    FRONT_DESK = "FrontDesk"
    ENGINEER = "Engineer"
    SYSTEM_INTEGRATION = "SystemIntegration"


# ---------------------------------------------------------------------------
# Room (PRD §3.1, §3.9)
# ---------------------------------------------------------------------------
class RoomType(str, Enum):
    STANDARD = "STANDARD"
    SUITE = "SUITE"
    PRESIDENTIAL = "PRESIDENTIAL"


class PmsOccupancy(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"
    DUE_OUT = "DUE_OUT"
    NO_SHOW = "NO_SHOW"


class RoomStatus(str, Enum):
    VACANT_CLEAN = "VACANT_CLEAN"
    VACANT_DIRTY = "VACANT_DIRTY"
    OCCUPIED_CLEAN = "OCCUPIED_CLEAN"
    OCCUPIED_DIRTY = "OCCUPIED_DIRTY"
    INSPECTED = "INSPECTED"
    OUT_OF_ORDER = "OUT_OF_ORDER"


class RoomStatusChangeReason(str, Enum):
    INITIAL = "INITIAL"
    PMS_SYNC = "PMS_SYNC"
    TASK_COMPLETED = "TASK_COMPLETED"
    INSPECTION_PASS = "INSPECTION_PASS"
    MAINTENANCE_ISOLATE = "MAINTENANCE_ISOLATE"
    MAINTENANCE_VERIFY = "MAINTENANCE_VERIFY"
    MANUAL_CORRECTION = "MANUAL_CORRECTION"


# ---------------------------------------------------------------------------
# Housekeeper (PRD §3.6)
# ---------------------------------------------------------------------------
class ShiftStatus(str, Enum):
    OFF_SHIFT = "OFF_SHIFT"
    ON_SHIFT = "ON_SHIFT"


# ---------------------------------------------------------------------------
# CleaningTask (PRD §3.3, §3.5)
# ---------------------------------------------------------------------------
class CleaningTaskSource(str, Enum):
    CHECK_OUT = "CHECK_OUT"
    STAYOVER = "STAYOVER"
    SCHEDULED = "SCHEDULED"


class CleaningTaskStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PriorityTier(str, Enum):
    URGENT = "URGENT"
    HIGH = "HIGH"
    NORMAL = "NORMAL"


# ---------------------------------------------------------------------------
# MaintenanceTicket (PRD §3.7)
# ---------------------------------------------------------------------------
class MaintenanceCategory(str, Enum):
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    FURNITURE = "FURNITURE"
    APPLIANCE = "APPLIANCE"
    OTHER = "OTHER"


class MaintenanceSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MaintenanceTicketStatus(str, Enum):
    REPORTED = "REPORTED"
    DISPATCHED = "DISPATCHED"
    IN_REPAIR = "IN_REPAIR"
    REPAIR_COMPLETED = "REPAIR_COMPLETED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Minibar (PRD §3.11)
# ---------------------------------------------------------------------------
class MinibarItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MinibarConsumptionSource(str, Enum):
    HOUSEKEEPER = "HOUSEKEEPER"
    GUEST_SELF_REPORT = "GUEST_SELF_REPORT"


class MinibarConsumptionStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    DISPUTED = "DISPUTED"
    INVESTIGATED = "INVESTIGATED"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


# ---------------------------------------------------------------------------
# Linen (PRD §3.12)
# ---------------------------------------------------------------------------
class LinenReplacementPolicy(str, Enum):
    PER_STAY = "PER_STAY"
    SCHEDULED = "SCHEDULED"
    ON_REQUEST = "ON_REQUEST"


class LinenMovementStatus(str, Enum):
    COLLECTED = "COLLECTED"
    SENT_TO_LAUNDRY = "SENT_TO_LAUNDRY"
    RETURNED = "RETURNED"
    LOSS_REPORTED = "LOSS_REPORTED"
    RESOLVED = "RESOLVED"


# ---------------------------------------------------------------------------
# Audit (PRD §2.7)
# ---------------------------------------------------------------------------
class AuditActionType(str, Enum):
    ROOM_STATUS_CHANGE = "ROOM_STATUS_CHANGE"
    MINIBAR_CONSUMPTION_POST = "MINIBAR_CONSUMPTION_POST"
    MINIBAR_CONSUMPTION_DISPUTE = "MINIBAR_CONSUMPTION_DISPUTE"
    MINIBAR_CONSUMPTION_WAIVE = "MINIBAR_CONSUMPTION_WAIVE"
    MANUAL_CORRECTION = "MANUAL_CORRECTION"
    EVENT_INGESTED = "EVENT_INGESTED"


# ---------------------------------------------------------------------------
# Mutable entities — carry id, created_at, updated_at, version (PRD §2.4)
# ---------------------------------------------------------------------------
class Room(TypedDict, total=False):
    id: str
    room_number: str
    zone_code: str
    room_type: str
    vip_flag: bool
    pms_occupancy: str
    pms_synced_at: Optional[str]
    status: str
    discrepancy_flag: bool
    out_of_order_ticket_id: Optional[str]
    last_cleaned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Housekeeper(TypedDict, total=False):
    id: str
    employee_code: str
    display_name: str
    assigned_zone: str
    shift_status: str
    provisional_workload_minutes: int
    realized_workload_minutes: int
    created_at: str
    updated_at: str
    version: int


class CleaningTask(TypedDict, total=False):
    id: str
    room_id: str
    task_source: str
    expedite_flag: bool
    early_check_in_at: Optional[str]
    parent_task_id: Optional[str]
    priority_score: int
    priority_tier: str
    estimated_minutes: int
    assigned_housekeeper_id: Optional[str]
    accepted_at: Optional[str]
    started_at: Optional[str]
    submitted_at: Optional[str]
    actual_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MinibarItem(TypedDict, total=False):
    id: str
    sku_code: str
    display_name: str
    unit_price_cents: int
    par_level: int
    replenishment_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MinibarConsumption(TypedDict, total=False):
    id: str
    room_id: str
    cleaning_task_id: Optional[str]
    source_type: str
    line_items: List[dict]
    gross_amount_cents: Optional[int]
    tax_cents: Optional[int]
    posted_amount_cents: Optional[int]
    folio_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceTicket(TypedDict, total=False):
    id: str
    room_id: str
    reporter_housekeeper_id: str
    category: str
    severity: str
    description: str
    isolates_room: bool
    engineering_assignee: Optional[str]
    completed_at: Optional[str]
    verified_at: Optional[str]
    re_clean_task_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LinenType(TypedDict, total=False):
    id: str
    code: str
    display_name: str
    replacement_policy: str
    scheduled_interval_days: Optional[int]
    par_per_room: int
    replacement_cost_cents: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at ONLY (no updated_at, no version)
# ---------------------------------------------------------------------------
class InspectionRecord(TypedDict, total=False):
    id: str
    created_at: str
    cleaning_task_id: str
    room_id: str
    supervisor_id: str
    sampled_flag: bool
    checklist_items: List[dict]
    outcome: str
    notes: Optional[str]


class RoomStatusEvent(TypedDict, total=False):
    id: str
    created_at: str
    room_id: str
    previous_status: Optional[str]
    new_status: str
    change_reason: str
    actor_id: str
    correction_note: Optional[str]


class LinenMovement(TypedDict, total=False):
    id: str
    created_at: str
    room_id: str
    linen_type_id: str
    cleaning_task_id: Optional[str]
    collected_quantity: int
    sent_to_laundry_quantity: int
    returned_quantity: int
    loss_quantity: int
    damage_quantity: int
    folio_charge_cents: Optional[int]
    status: str


class AuditLog(TypedDict, total=False):
    id: str
    created_at: str
    actor_id: str
    actor_role: Optional[str]
    action_type: str
    subject_entity: str
    subject_id: str
    detail: dict


__all__ = [
    "UserRole",
    "RoomType",
    "PmsOccupancy",
    "RoomStatus",
    "RoomStatusChangeReason",
    "ShiftStatus",
    "CleaningTaskSource",
    "CleaningTaskStatus",
    "PriorityTier",
    "MaintenanceCategory",
    "MaintenanceSeverity",
    "MaintenanceTicketStatus",
    "MinibarItemStatus",
    "MinibarConsumptionSource",
    "MinibarConsumptionStatus",
    "LinenReplacementPolicy",
    "LinenMovementStatus",
    "AuditActionType",
    "Room",
    "Housekeeper",
    "CleaningTask",
    "MinibarItem",
    "MinibarConsumption",
    "MaintenanceTicket",
    "LinenType",
    "InspectionRecord",
    "RoomStatusEvent",
    "LinenMovement",
    "AuditLog",
]
