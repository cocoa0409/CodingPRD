"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    GARDEN_ADMIN = "GardenAdmin"
    COORDINATOR = "Coordinator"
    VOLUNTEER = "Volunteer"
    GROUP_LEADER = "GroupLeader"
    FOOD_SAFETY_OFFICER = "FoodSafetyOfficer"


class OrientationStatus(str, Enum):
    PENDING = "PENDING"
    ORIENTED = "ORIENTED"


class WaiverStatus(str, Enum):
    UNSIGNED = "UNSIGNED"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"


class Standing(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class CertType(str, Enum):
    PRODUCE_SAFETY = "PRODUCE_SAFETY"
    SUPERVISION = "SUPERVISION"
    TOOL_SAFETY = "TOOL_SAFETY"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_ENROLLMENT = "OPEN_ENROLLMENT"
    PLANTING = "PLANTING"
    GROWING = "GROWING"
    HARVESTING = "HARVESTING"
    RECONCILIATION = "RECONCILIATION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BedStatus(str, Enum):
    FALLOW = "FALLOW"
    RESERVED = "RESERVED"
    PLANTED = "PLANTED"
    GROWING = "GROWING"
    HARVEST_OPEN = "HARVEST_OPEN"
    POST_HARVEST = "POST_HARVEST"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class SunExposure(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    SHADE = "SHADE"


class CropPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PLANTED = "PLANTED"
    HARVESTING = "HARVESTING"
    COMPLETE = "COMPLETE"
    WITHDRAWN = "WITHDRAWN"


class TaskType(str, Enum):
    PLANTING = "PLANTING"
    WEEDING = "WEEDING"
    HARVEST = "HARVEST"
    IRRIGATION = "IRRIGATION"
    COMPOST = "COMPOST"
    REPAIR = "REPAIR"
    OUTREACH = "OUTREACH"


class SlotStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    FULL = "FULL"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SignupStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class GroupBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ShedKeyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKED_OUT = "CHECKED_OUT"
    OVERDUE = "OVERDUE"
    LOST = "LOST"
    RETIRED = "RETIRED"


class ToolCategory(str, Enum):
    HAND = "HAND"
    POWER = "POWER"
    IRRIGATION = "IRRIGATION"
    SAFETY = "SAFETY"
    OTHER = "OTHER"


class ToolStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    RETIRED = "RETIRED"


class CheckoutStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL_RETURN = "PARTIAL_RETURN"
    RETURNED = "RETURNED"
    CLOSED_LOSS = "CLOSED_LOSS"
    AUTO_CLOSED = "AUTO_CLOSED"


class ReturnCondition(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"


class HarvestLogStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    SPLIT_FINALIZED = "SPLIT_FINALIZED"
    REJECTED = "REJECTED"
    DISCARDED = "DISCARDED"


class QualityGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISTRIBUTED = "DISTRIBUTED"


class IrrigationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    MISSED = "MISSED"
    LOGGED = "LOGGED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts. Every resource carries id/created_at/updated_at/version
# per PRD §2.4. ---


class Volunteer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    phone: Optional[str]
    date_of_birth: str
    is_minor: bool
    orientation_status: str
    waiver_status: str
    waiver_signed_at: Optional[str]
    standing: str
    can_supervise: bool
    produce_safety_certified: bool
    tool_safety_certified: bool
    total_service_minutes: int
    no_show_count: int
    held_key_count: int


class TrainingCertification(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    volunteer_id: str
    cert_type: str
    issued_at: str
    expires_at: str
    status: str
    revoked_reason: Optional[str]


class Season(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    signup_opens_at: str
    signup_closes_at: str
    season_starts_at: str
    season_ends_at: str
    water_budget_gallons: int
    water_committed_gallons: int
    water_actual_gallons: int
    water_remaining_gallons: int
    status: str


class GardenBed(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    bed_code: str
    size_sq_ft: int
    sun_exposure: str
    irrigation_zone: str
    soil_ph: Optional[float]
    allocated_sq_ft: int
    last_plant_family: Optional[str]
    last_harvest_closed_at: Optional[str]
    status: str


class CropPlan(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    season_id: str
    bed_id: str
    proposer_volunteer_id: str
    crop_type: str
    plant_family: str
    requested_sq_ft: int
    planned_start_date: str
    planned_end_date: str
    expected_yield_grams: int
    rejection_reason: Optional[str]
    status: str


class ShiftSlot(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    season_id: str
    task_type: str
    starts_at: str
    ends_at: str
    capacity_total: int
    capacity_youth: int
    requires_produce_safety: bool
    required_tool_id: Optional[str]
    required_tool_qty: int
    confirmed_count: int
    confirmed_youth_count: int
    waitlist_count: int
    next_waitlist_position: int
    status: str


class ShiftSignup(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    slot_id: str
    volunteer_id: str
    supervision_adult_signup_id: Optional[str]
    is_youth: bool
    waitlist_position: Optional[int]
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    credited_minutes: int
    status: str


class GroupBooking(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    slot_id: str
    leader_volunteer_id: str
    organization_name: str
    member_count: int
    minor_count: int
    chaperone_count: int
    chaperone_volunteer_ids: List[str]
    required_chaperones: int
    rejection_reason: Optional[str]
    status: str


class ShedKey(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    key_code: str
    current_holder_volunteer_id: Optional[str]
    due_back_at: Optional[str]
    status: str


class ToolItem(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tool_name: str
    category: str
    total_count: int
    available_count: int
    checked_out_count: int
    in_maintenance_count: int
    written_off_count: int
    status: str


class ToolCheckout(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tool_id: str
    volunteer_id: str
    signup_id: Optional[str]
    qty: int
    qty_returned: int
    condition_on_return: Optional[str]
    status: str


class HarvestLog(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    season_id: str
    bed_id: str
    crop_plan_id: Optional[str]
    logged_by_volunteer_id: str
    crop_type: str
    weight_grams: int
    quality_grade: str
    harvested_at: str
    safety_attestation: bool
    rejection_reason: Optional[str]
    status: str


class DonationRecipient(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    org_name: str
    contact_email: str
    weekly_capacity_grams: int
    priority_tier: int
    accepts_grade_c: bool
    active: bool
    committed_this_week_grams: int


class DonationAllocation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    harvest_log_id: str
    volunteer_share_grams: int
    donatable_grams: int
    lines: List[Dict[str, Any]]
    rejection_reason: Optional[str]
    status: str


class IrrigationSchedule(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    season_id: str
    zone: str
    planned_start_at: str
    planned_end_at: str
    planned_gallons: int
    gallons_actual: Optional[int]
    variance_flag: bool
    status: str
