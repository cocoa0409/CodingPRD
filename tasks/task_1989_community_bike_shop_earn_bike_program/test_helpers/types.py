"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BikeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    IN_REFURBISHMENT = "IN_REFURBISHMENT"
    SAFETY_REVIEW = "SAFETY_REVIEW"
    READY_FOR_DISPOSITION = "READY_FOR_DISPOSITION"
    RESERVED_FOR_GRADUATE = "RESERVED_FOR_GRADUATE"
    SOLD = "SOLD"
    GIFTED = "GIFTED"
    HARVEST_QUEUE = "HARVEST_QUEUE"
    HARVESTED = "HARVESTED"
    SCRAP_PENDING = "SCRAP_PENDING"
    SCRAPPED = "SCRAPPED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class BikeType(str, Enum):
    ROAD = "ROAD"
    MTB = "MTB"
    HYBRID = "HYBRID"
    KIDS = "KIDS"
    BMX = "BMX"
    CARGO = "CARGO"


class DonorType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    ORGANIZATION = "ORGANIZATION"


class ReceiptMethod(str, Enum):
    FLAT_SCHEDULE = "FLAT_SCHEDULE"
    FMV_COMPARABLE = "FMV_COMPARABLE"


class PartCategory(str, Enum):
    DRIVETRAIN = "DRIVETRAIN"
    BRAKES = "BRAKES"
    WHEELS = "WHEELS"
    FRAME = "FRAME"
    COCKPIT = "COCKPIT"
    SADDLE = "SADDLE"
    TIRES = "TIRES"
    HELMET = "HELMET"
    MISC = "MISC"


class HelmetSize(str, Enum):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class SkillLevel(str, Enum):
    TRAINEE = "TRAINEE"
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    LEAD_MECHANIC = "LEAD_MECHANIC"


class EngagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TrainingLevel(str, Enum):
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"
    LEAD_CERT = "LEAD_CERT"


class TrainingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AttendanceStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    DROPPED = "DROPPED"


class ShiftRole(str, Enum):
    MECHANIC = "MECHANIC"
    INTAKE = "INTAKE"
    FLOOR = "FLOOR"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class AgeGroup(str, Enum):
    YOUTH = "YOUTH"
    ADULT = "ADULT"


class ParticipantStatus(str, Enum):
    ENROLLED = "ENROLLED"
    HOURS_MET = "HOURS_MET"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class HourLogStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ActivityType(str, Enum):
    REFURB_WORK = "REFURB_WORK"
    SHOP_HELP = "SHOP_HELP"
    OUTREACH = "OUTREACH"
    TRAINING_ASSIST = "TRAINING_ASSIST"


class SaleStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    VOUCHER = "VOUCHER"


class AwardStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PRO = "PRO"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class SessionStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_USE = "IN_USE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ScrapMaterial(str, Enum):
    STEEL = "STEEL"
    ALUMINUM = "ALUMINUM"
    MIXED = "MIXED"


class ScrapTicketStatus(str, Enum):
    OPEN = "OPEN"
    PICKED_UP = "PICKED_UP"


class RecipientKind(str, Enum):
    EARN_A_BIKE_GRADUATE = "EARN_A_BIKE_GRADUATE"
    SALE_BUYER = "SALE_BUYER"
    GIVEAWAY_RECIPIENT = "GIVEAWAY_RECIPIENT"
    COMMUNITY = "COMMUNITY"


class RouteDestination(str, Enum):
    REFURBISH = "REFURBISH"
    HARVEST = "HARVEST"
    SCRAP = "SCRAP"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class UserRole(str, Enum):
    SHOP_COORDINATOR = "ShopCoordinator"
    PROGRAM_DIRECTOR = "ProgramDirector"
    VOLUNTEER = "Volunteer"
    PARTICIPANT = "Participant"
    MEMBER = "Member"


# ---------------------------------------------------------------------------
# TypedDicts — entities carrying common_fields (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class Donor(TypedDict):
    id: str
    display_name: str
    donor_type: str
    email: str
    receipt_method: str
    donated_bike_count: int
    lifetime_receipt_value_cents: int
    created_at: str
    updated_at: str
    version: int


class DonatedBike(TypedDict):
    id: str
    donor_id: str
    serial_number: str
    bike_type: str
    wheel_size_inches: float
    condition_grade: Optional[str]
    frame_damage: Optional[bool]
    status: str
    refurb_lead_volunteer_id: Optional[str]
    parts_cost_cents: int
    rework_count: int
    latest_inspection_result: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    name: str
    category: str
    helmet_size: Optional[str]
    unit_cost_cents: int
    quantity_on_hand: int
    reorder_threshold: int
    low_stock: bool
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    full_name: str
    email: str
    skill_level: str
    engagement_status: str
    training_hours: int
    sessions_attended: int
    inspections_conducted: int
    no_show_count: int
    shift_minutes: int
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict):
    id: str
    topic: str
    level: str
    scheduled_start: str
    scheduled_end: str
    credit_hours: int
    capacity: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingAttendance(TypedDict):
    id: str
    session_id: str
    volunteer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerShift(TypedDict):
    id: str
    volunteer_id: str
    shift_role: str
    scheduled_start: str
    scheduled_end: str
    status: str
    checked_in_at: Optional[str]
    credited_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EarnABikeParticipant(TypedDict):
    id: str
    full_name: str
    contact_email: str
    age_group: str
    enrolled_at: str
    enrollment_deadline: str
    required_hours: int
    hours_earned: int
    safety_quiz_passed: bool
    reserved_bike_id: Optional[str]
    status: str
    graduated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HourLog(TypedDict):
    id: str
    participant_id: str
    shift_id: Optional[str]
    work_date: str
    hours: int
    activity_type: str
    description: Optional[str]
    status: str
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    bike_id: str
    buyer_name: str
    buyer_email: str
    buyer_membership_id: Optional[str]
    quoted_price_cents: int
    final_price_cents: Optional[int]
    round_up: bool
    grand_total_cents: Optional[int]
    donation_cents: Optional[int]
    payment_method: Optional[str]
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GiveawayAward(TypedDict):
    id: str
    bike_id: str
    partner_org: str
    referral_code: str
    recipient_age_group: str
    status: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    fulfilled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ToolMembership(TypedDict):
    id: str
    member_name: str
    member_email: str
    tier: str
    status: str
    start_date: str
    end_date: str
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ToolSession(TypedDict):
    id: str
    membership_id: str
    stand_number: int
    start_time: str
    end_time: str
    status: str
    started_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScrapTicket(TypedDict):
    id: str
    bike_id: str
    material: str
    weight_kg: float
    recycler_name: str
    payout_cents: int
    status: str
    picked_up_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# TypedDicts — append-only event entities (NO updated_at, NO version)
# ---------------------------------------------------------------------------

class PartHarvest(TypedDict):
    id: str
    bike_id: str
    part_id: str
    quantity: int
    harvested_by_user_id: str
    note: Optional[str]
    created_at: str


class PartUsage(TypedDict):
    id: str
    bike_id: str
    part_id: str
    quantity: int
    unit_cost_cents: int
    logged_by_user_id: str
    status: str
    void_reason: Optional[str]
    created_at: str


class SafetyInspection(TypedDict):
    id: str
    bike_id: str
    inspector_volunteer_id: str
    result: str
    checklist: dict
    note: Optional[str]
    created_at: str


class HelmetDistribution(TypedDict):
    id: str
    helmet_part_id: str
    recipient_kind: str
    participant_id: Optional[str]
    sale_id: Optional[str]
    giveaway_id: Optional[str]
    recipient_name: Optional[str]
    distributed_by_user_id: str
    created_at: str
