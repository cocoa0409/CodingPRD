"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# --- Role enum (PRD §2.1: exactly six roles) ---
class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    CASTING_DIRECTOR = "CastingDirector"
    CASTING_ASSOCIATE = "CastingAssociate"
    BACKGROUND_ACTOR = "BackgroundActor"
    PAYROLL_COORDINATOR = "PayrollCoordinator"
    UNION_REPRESENTATIVE = "UnionRepresentative"


# --- Status enums (PRD §3) ---
class ProductionStatus(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    WRAPPED = "WRAPPED"


class ActorStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"


class UnionStatus(str, Enum):
    SAG_AFTRA = "SAG_AFTRA"
    NONUNION = "NONUNION"


class CastingCallStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    SHOOTING = "SHOOTING"
    WRAPPED = "WRAPPED"
    CANCELLED = "CANCELLED"


class SlotType(str, Enum):
    UNION = "UNION"
    NONUNION = "NONUNION"


class LookCategory(str, Enum):
    WARDROBE_OWN = "WARDROBE_OWN"
    FORMAL_WEAR = "FORMAL_WEAR"
    PERIOD_COSTUME = "PERIOD_COSTUME"
    HAIR_MAKEUP = "HAIR_MAKEUP"
    PROPS_OWN = "PROPS_OWN"
    SPECIAL_ABILITY = "SPECIAL_ABILITY"


class BookingStatus(str, Enum):
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    WRAPPED = "WRAPPED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class TimeEventType(str, Enum):
    CHECK_IN = "CHECK_IN"
    MEAL_OUT = "MEAL_OUT"
    MEAL_IN = "MEAL_IN"
    WRAP_OUT = "WRAP_OUT"


class VoucherStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class BumpStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_REJECTED = "PARTIALLY_REJECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    CANDIDATE_OFFERED = "CANDIDATE_OFFERED"
    FILLED = "FILLED"
    EXPIRED = "EXPIRED"


class CaseReason(str, Enum):
    NO_SHOW = "NO_SHOW"
    CANCELLATION = "CANCELLATION"


class StandbyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    PROMOTED = "PROMOTED"
    EXPIRED = "EXPIRED"


class WaiverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).


class Production(TypedDict, total=False):
    id: str
    title: str
    studio_code: str
    payroll_company_name: str
    status: str
    compliance_index: int
    payroll_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class BackgroundActor(TypedDict, total=False):
    id: str
    legal_name: str
    union_status: str
    special_abilities: List[str]
    sizes: Optional[dict]
    status: str
    no_show_count: int
    reliability_score: int
    created_at: str
    updated_at: str
    version: int


class CastingCall(TypedDict, total=False):
    id: str
    production_id: str
    shoot_date: str
    general_call_time: str
    scheduled_duration_minutes: int
    location: str
    union_slots: int
    nonunion_slots: int
    union_rate_cents: int
    nonunion_rate_cents: int
    wardrobe_notes: Optional[str]
    status: str
    approved_waiver_reduction: int
    required_union_slots: int
    slots_available: int
    union_bookings_active: int
    nonunion_bookings_active: int
    projected_union_count: int
    projected_compliant: bool
    actual_union_checkins: int
    actual_compliant: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class HoldingArea(TypedDict, total=False):
    id: str
    casting_call_id: str
    name: str
    capacity: int
    current_occupancy: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    casting_call_id: str
    actor_id: str
    replacement_case_id: Optional[str]
    replaces_booking_id: Optional[str]
    is_replacement: bool
    slot_type: str
    daily_rate_cents: int
    call_time: str
    expected_wrap_time: str
    offer_expires_at: str
    holding_area_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict, total=False):
    id: str
    booking_id: str
    payroll_batch_id: Optional[str]
    status: str
    check_in_at: Optional[str]
    wrap_out_at: Optional[str]
    gross_elapsed_minutes: int
    net_work_minutes: int
    ot_tier1_minutes: int
    ot_tier2_minutes: int
    meal_penalty_count: int
    base_wages_cents: int
    ot_wages_cents: int
    meal_penalty_cents: int
    bumps_total_cents: int
    gross_total_cents: int
    issued_by_user_id: str
    adjusted_by_user_id: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BumpAdjustment(TypedDict, total=False):
    id: str
    voucher_id: str
    category: str
    amount_cents: int
    justification: Optional[str]
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PayrollBatch(TypedDict, total=False):
    id: str
    production_id: str
    period_label: str
    status: str
    gross_total_cents: int
    voucher_count: int
    submitted_by_user_id: Optional[str]
    acknowledged_by_user_id: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplacementCase(TypedDict, total=False):
    id: str
    casting_call_id: str
    original_booking_id: str
    required_slot_type: str
    reason: str
    deadline_at: str
    excluded_actor_ids: List[str]
    offered_booking_id: Optional[str]
    offered_actor_id: Optional[str]
    attempts_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StandbyEntry(TypedDict, total=False):
    id: str
    casting_call_id: str
    actor_id: str
    slot_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RatioWaiver(TypedDict, total=False):
    id: str
    casting_call_id: str
    union_slot_reduction: int
    justification: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only / immutable records: ONLY id + created_at, no updated_at/version
# (PRD §2.4: both fields "are absent from these two resources").


class LookRequirement(TypedDict, total=False):
    id: str
    casting_call_id: str
    category: str
    description: str
    bump_amount_cents: int
    mandatory: bool
    created_at: str


class TimeEvent(TypedDict, total=False):
    id: str
    booking_id: str
    event_type: str
    occurred_at: str
    corrects_event_id: Optional[str]
    recorded_by: str
    created_at: str
