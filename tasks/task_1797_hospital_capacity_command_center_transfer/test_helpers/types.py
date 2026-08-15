"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class DiversionStatus(str, Enum):
    ACCEPTING = "ACCEPTING"
    DIVERT_FULL = "DIVERT_FULL"
    DIVERT_SERVICE = "DIVERT_SERVICE"


class BedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class BedService(str, Enum):
    CARDIAC = "CARDIAC"
    NEURO = "NEURO"
    TRAUMA = "TRAUMA"
    MEDICAL = "MEDICAL"
    SURGICAL = "SURGICAL"
    ONCOLOGY = "ONCOLOGY"


class Acuity(str, Enum):
    ACUITY_1_CRITICAL = "ACUITY_1_CRITICAL"
    ACUITY_2_STEPDOWN = "ACUITY_2_STEPDOWN"
    ACUITY_3_MEDICAL_SURGICAL = "ACUITY_3_MEDICAL_SURGICAL"
    ACUITY_4_OBSERVATION = "ACUITY_4_OBSERVATION"


class Isolation(str, Enum):
    NONE = "NONE"
    CONTACT = "CONTACT"
    DROPLET = "DROPLET"
    AIRBORNE = "AIRBORNE"


class PhysicianStatus(str, Enum):
    ON_CALL = "ON_CALL"
    OFF_CALL = "OFF_CALL"


class AdmissionStatus(str, Enum):
    ADMITTED = "ADMITTED"
    PENDING_DISCHARGE = "PENDING_DISCHARGE"
    DISCHARGED = "DISCHARGED"


class TransferPriority(str, Enum):
    EMERGENT = "EMERGENT"
    URGENT = "URGENT"
    ELECTIVE = "ELECTIVE"


class TransferStatus(str, Enum):
    INTAKE = "INTAKE"
    CONSULT_PENDING = "CONSULT_PENDING"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    ACCEPTED = "ACCEPTED"
    HOLD_PLACED = "HOLD_PLACED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeclineReason(str, Enum):
    DIVERSION = "DIVERSION"
    NO_CAPACITY = "NO_CAPACITY"
    CLINICAL = "CLINICAL"
    PHYSICIAN_DECLINED = "PHYSICIAN_DECLINED"
    TIMEOUT = "TIMEOUT"


class BedHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class BedAssignmentStatus(str, Enum):
    PLACED = "PLACED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DiversionLevel(str, Enum):
    FULL = "FULL"
    SERVICE = "SERVICE"


class DiversionEventStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    EXPIRED = "EXPIRED"


class PlacementStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    PLACED = "PLACED"
    LEFT_AMA = "LEFT_AMA"


class EscalationStatus(str, Enum):
    NONE = "NONE"
    HUDDLE_CALLED = "HUDDLE_CALLED"
    HUDDLE_RESOLVED = "HUDDLE_RESOLVED"


class HuddleTrigger(str, Enum):
    AUTO_THRESHOLD = "AUTO_THRESHOLD"
    MANUAL = "MANUAL"


class HuddleStatus(str, Enum):
    CALLED = "CALLED"
    RESOLVED = "RESOLVED"


class ForecastStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    SYSTEM_ADMINISTRATOR = "SystemAdministrator"
    BED_MANAGER = "BedManager"
    TRANSFER_CENTER_COORDINATOR = "TransferCenterCoordinator"
    ACCEPTING_PHYSICIAN = "AcceptingPhysician"
    HOUSE_SUPERVISOR = "HouseSupervisor"
    CAPACITY_PLANNER = "CapacityPlanner"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Entity TypedDicts (every entity in this PRD carries the common system fields)
# ---------------------------------------------------------------------------

class Facility(TypedDict, total=False):
    id: str
    name: str
    region: str
    diversion_status: str
    diversion_recommended: bool
    staffed_beds: int
    occupied_beds: int
    held_beds: int
    available_beds: int
    out_of_service_beds: int
    boarding_waiters: int
    active_inbound_transfers: int
    load_score_raw: float
    load_score_weighted: float
    service_weighted_occupancy_pct: float
    next_elective_window_start: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bed(TypedDict, total=False):
    id: str
    facility_id: str
    unit: str
    label: str
    service: str
    max_acuity: str
    isolation_capability: str
    staffed: bool
    turnover_minutes: int
    status: str
    projected_free_at: Optional[str]
    cooling_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    facility_id: str
    full_name: str
    services: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Admission(TypedDict, total=False):
    id: str
    facility_id: str
    bed_id: str
    patient_ref: str
    acuity: str
    isolation_need: str
    service: str
    status: str
    expected_discharge_at: Optional[str]
    discharge_order_signed: bool
    pending_discharge_at: Optional[str]
    confirmed_discharge_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict, total=False):
    id: str
    facility_id: str
    source_facility_name: str
    patient_ref: str
    acuity: str
    isolation_need: str
    service: str
    priority: str
    preferred_unit: Optional[str]
    status: str
    accepting_physician_id: Optional[str]
    consult_deadline: Optional[str]
    consult_count: int
    decline_reason: Optional[str]
    intake_coordinator_id: str
    assigned_bed_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BedHold(TypedDict, total=False):
    id: str
    bed_id: str
    transfer_request_id: str
    starts_at: str
    ttl_minutes: int
    expires_at: str
    status: str
    extend_count: int
    created_at: str
    updated_at: str
    version: int


class BedAssignment(TypedDict, total=False):
    id: str
    transfer_request_id: str
    bed_hold_id: str
    bed_id: str
    created_by_user_id: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiversionEvent(TypedDict, total=False):
    id: str
    facility_id: str
    level: str
    service: Optional[str]
    starts_at: str
    ends_at: str
    declared_by_user_id: str
    status: str
    lifted_at: Optional[str]
    lifted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoardingRecord(TypedDict, total=False):
    id: str
    facility_id: str
    admission_id: str
    started_at: str
    boarding_minutes: int
    placement_status: str
    escalation_status: str
    huddle_count_24h: int
    executive_escalation: bool
    last_heartbeat_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EscalationHuddle(TypedDict, total=False):
    id: str
    boarding_record_id: str
    trigger_reason: str
    status: str
    called_at: str
    resolved_at: Optional[str]
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityForecast(TypedDict, total=False):
    id: str
    facility_id: str
    horizon_hours: int
    generated_at: str
    variant_snapshots: Dict[str, List[int]]
    occupancy_pct_committed: float
    occupancy_pct_provisional: float
    status: str
    stale: bool
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
