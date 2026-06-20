"""Domain types: entity TypedDicts, status enums, role enum.

All names use Hospital Bed Flow API terminology from the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class UnitType(str, Enum):
    MEDSURG = "MEDSURG"
    TELEMETRY = "TELEMETRY"
    ICU = "ICU"
    ED = "ED"


class Posture(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    CLOSED = "CLOSED"


class BedStatus(str, Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    OCCUPIED = "OCCUPIED"
    BLOCKED = "BLOCKED"
    RETIRED = "RETIRED"


class RoomType(str, Enum):
    PRIVATE = "PRIVATE"
    SEMIPRIVATE = "SEMIPRIVATE"


class SexCohort(str, Enum):
    NONE = "NONE"
    MALE = "MALE"
    FEMALE = "FEMALE"


class BlockedReason(str, Enum):
    MAINTENANCE = "MAINTENANCE"
    STAFFING = "STAFFING"
    INFECTION_CONTROL = "INFECTION_CONTROL"


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class Origin(str, Enum):
    ED = "ED"
    DIRECT = "DIRECT"
    TRANSFER_IN = "TRANSFER_IN"


class EncounterStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ADMIT_PENDING = "ADMIT_PENDING"
    BOARDING = "BOARDING"
    PLACED = "PLACED"
    DISCHARGE_ORDERED = "DISCHARGE_ORDERED"
    DISCHARGED = "DISCHARGED"
    CANCELLED = "CANCELLED"


class BedRequestStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class Priority(str, Enum):
    STAT = "STAT"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class EvsTaskType(str, Enum):
    STAT = "STAT"
    ISOLATION = "ISOLATION"
    ROUTINE = "ROUTINE"


class EvsTaskStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BarrierType(str, Enum):
    PLACEMENT_SNF = "PLACEMENT_SNF"
    TRANSPORT = "TRANSPORT"
    PHARMACY = "PHARMACY"
    FAMILY = "FAMILY"
    EQUIPMENT = "EQUIPMENT"


class BarrierStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class SurgeLevel(str, Enum):
    YELLOW = "YELLOW"
    RED = "RED"


class SurgeStatus(str, Enum):
    OPEN = "OPEN"
    STOOD_DOWN = "STOOD_DOWN"


class AdtEventType(str, Enum):
    ADMIT = "ADMIT"
    PLACE = "PLACE"
    TRANSFER = "TRANSFER"
    DISCHARGE_ORDER = "DISCHARGE_ORDER"
    DISCHARGE = "DISCHARGE"
    CANCEL = "CANCEL"


class UserRole(str, Enum):
    FlowAdmin = "FlowAdmin"
    BedControlCoordinator = "BedControlCoordinator"
    ChargeNurse = "ChargeNurse"
    TransferCenterAgent = "TransferCenterAgent"
    CaseManager = "CaseManager"
    EvsTech = "EvsTech"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# Entities with common_fields: true carry id + created_at + updated_at + version.

class Unit(TypedDict):
    id: str
    name: str
    unit_type: str
    gmlos_days: int
    total_bed_count: int
    staffed_bed_count: int
    occupied_bed_count: int
    clean_available_count: int
    occupancy_pct: float
    derived_posture: str
    declared_surge_level: str
    effective_posture: str
    created_at: str
    updated_at: str
    version: int


class Bed(TypedDict):
    id: str
    unit_id: str
    label: str
    room_type: str
    isolation_capable: bool
    telemetry_capable: bool
    status: str
    sex_cohort: str
    current_encounter_id: Optional[str]
    blocked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    mrn: str
    sex: str
    requires_isolation: bool
    requires_telemetry: bool
    origin: str
    status: str
    current_bed_id: Optional[str]
    transferred_from_bed_id: Optional[str]
    admit_decision_at: Optional[str]
    admitted_at: Optional[str]
    discharge_order_at: Optional[str]
    discharged_at: Optional[str]
    boarding_hours: float
    boarding_breached: bool
    length_of_stay_hours: float
    long_stay_flag: bool
    open_barrier_count: int
    created_at: str
    updated_at: str
    version: int


class BedRequest(TypedDict):
    id: str
    encounter_id: str
    preferred_unit_id: Optional[str]
    acceptable_unit_types: List[str]
    priority: str
    status: str
    assigned_bed_id: Optional[str]
    match_score: Optional[int]
    queued_ops_index: int
    created_at: str
    updated_at: str
    version: int


class EvsTask(TypedDict):
    id: str
    bed_id: str
    task_type: str
    status: str
    assigned_tech_id: Optional[str]
    requested_at: Optional[str]
    priority_score: int
    created_at: str
    updated_at: str
    version: int


class DischargeBarrier(TypedDict):
    id: str
    encounter_id: str
    barrier_type: str
    note: str
    status: str
    opened_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurgeEvent(TypedDict):
    id: str
    unit_id: str
    level: str
    reason: str
    status: str
    opened_at: Optional[str]
    stood_down_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# CapacityHuddle is an immutable snapshot; PRD §2.4 states it exposes
# version and updated_at per the common pattern but is never mutated.
class CapacityHuddle(TypedDict):
    id: str
    huddle_at: str
    total_staffed_beds: int
    total_occupied_beds: int
    house_occupancy_pct: float
    boarding_encounter_count: int
    queued_request_count: int
    red_unit_count: int
    created_at: str
    updated_at: str
    version: int


# AdtEvent is append-only (common_fields: false): only id + created_at.
# No updated_at, no version.
class AdtEvent(TypedDict):
    id: str
    encounter_id: str
    event_type: str
    from_bed_id: Optional[str]
    to_bed_id: Optional[str]
    event_at: str
    created_at: str
