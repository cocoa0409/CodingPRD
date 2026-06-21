"""Domain types: entity TypedDicts, status enums, role enum (ASC Scheduling PRD)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SCHEDULER = "Scheduler"
    PREOP_NURSE = "PreOpNurse"
    OR_MANAGER = "ORManager"
    BILLING_ANALYST = "BillingAnalyst"


# ---------------------------------------------------------------------------
# Status / enum dimensions
# ---------------------------------------------------------------------------
class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"


class BayStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"


class AnesthesiaCredential(str, Enum):
    MD = "MD"
    DO = "DO"
    CRNA = "CRNA"


class AnesthesiaClass(str, Enum):
    LOCAL = "LOCAL"
    MAC = "MAC"
    REGIONAL = "REGIONAL"
    GENERAL = "GENERAL"


class CmsPaymentIndicator(str, Enum):
    COVERED_ASC = "COVERED_ASC"
    DEVICE_INTENSIVE = "DEVICE_INTENSIVE"
    OFFICE_BASED = "OFFICE_BASED"
    EXCLUDED = "EXCLUDED"


class DayPosture(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class BlockStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class CaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_OR = "IN_OR"
    IN_RECOVERY = "IN_RECOVERY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClearanceStatus(str, Enum):
    PENDING_CLEARANCE = "PENDING_CLEARANCE"
    ON_HOLD = "ON_HOLD"
    CLEARED = "CLEARED"


class ImplantStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class CheckType(str, Enum):
    HP_REVIEW = "HP_REVIEW"
    LABS = "LABS"
    ANESTHESIA_ASSESSMENT = "ANESTHESIA_ASSESSMENT"
    CARDIAC_CONSULT = "CARDIAC_CONSULT"


class CheckOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    DEFER = "DEFER"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# common_fields: true entities carry id, created_at, updated_at, version.
# ClearanceCheck (common_fields: false) carries ONLY id + created_at.
# ---------------------------------------------------------------------------
class Facility(TypedDict):
    id: str
    name: str
    turnover_minutes: int
    hp_validity_days: int
    utilization_target_pct: float
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class OperatingRoom(TypedDict):
    id: str
    facility_id: str
    room_label: str
    prime_time_start_min: int
    prime_time_end_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryBay(TypedDict):
    id: str
    facility_id: str
    bay_label: str
    phase2_capable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Anesthesiologist(TypedDict):
    id: str
    facility_id: str
    full_name: str
    credential: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Surgeon(TypedDict):
    id: str
    facility_id: str
    full_name: str
    npi: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Procedure(TypedDict):
    id: str
    facility_id: str
    cpt_code: str
    description: str
    scheduled_minutes: int
    requires_phase2: bool
    anesthesia_class: str
    cms_payment_indicator: str
    cms_base_rate_cents: int
    device_offset_pct: float
    created_at: str
    updated_at: str
    version: int


class SupplyItem(TypedDict):
    id: str
    facility_id: str
    sku: str
    description: str
    is_device: bool
    unit_cost_cents: int
    on_hand_qty: int
    reserved_qty: int
    created_at: str
    updated_at: str
    version: int


class SurgicalDay(TypedDict):
    id: str
    facility_id: str
    service_date: str
    posture: str
    booked_minutes: int
    utilization_pct: float
    created_at: str
    updated_at: str
    version: int


class SurgeonBlock(TypedDict):
    id: str
    facility_id: str
    surgical_day_id: str
    surgeon_id: str
    operating_room_id: str
    start_min: int
    end_min: int
    allocated_minutes: int
    committed_minutes: int
    release_threshold_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SurgicalCase(TypedDict):
    id: str
    facility_id: str
    surgical_day_id: str
    surgeon_block_id: str
    patient_id: str
    procedure_id: str
    operating_room_id: str
    anesthesiologist_id: Optional[str]
    recovery_bay_id: Optional[str]
    start_min: int
    scheduled_minutes: int
    end_min: int
    is_add_on: bool
    actual_minutes: Optional[int]
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    cms_payment_cents: Optional[int]
    clearance_status: str
    hp_signed_at: Optional[str]
    case_status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    facility_id: str
    mrn: str
    full_name: str
    date_of_birth: str
    created_at: str
    updated_at: str
    version: int


class CaseImplant(TypedDict):
    id: str
    surgical_case_id: str
    supply_item_id: str
    planned_qty: int
    consumed_qty: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event: ONLY id + created_at (no updated_at / version)
class ClearanceCheck(TypedDict):
    id: str
    surgical_case_id: str
    check_type: str
    outcome: str
    recorded_by: str
    created_at: str
