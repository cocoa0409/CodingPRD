"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# --- Role enum (PRD §2.1) ---------------------------------------------------

class UserRole(str, Enum):
    BAND_DIRECTOR = "BandDirector"
    ASSISTANT_DIRECTOR = "AssistantDirector"
    BOOSTER_TREASURER = "BoosterTreasurer"
    EQUIPMENT_MANAGER = "EquipmentManager"
    SECTION_LEADER = "SectionLeader"
    STUDENT = "Student"
    ANY = "Any"


# --- Status / enum vocabularies (PRD §3) ------------------------------------

class ProgramStatus(str, Enum):
    SETUP = "SETUP"
    ENROLLMENT_OPEN = "ENROLLMENT_OPEN"
    SEASON_ACTIVE = "SEASON_ACTIVE"
    CLOSED = "CLOSED"


class RentalFeeMode(str, Enum):
    FLAT = "FLAT"
    PRORATED = "PRORATED"


class ScoringMode(str, Enum):
    RAW_WEIGHTED = "RAW_WEIGHTED"
    RANK_NORMALIZED = "RANK_NORMALIZED"


class Section(str, Enum):
    WOODWIND = "WOODWIND"
    BRASS = "BRASS"
    PERCUSSION = "PERCUSSION"
    GUARD = "GUARD"


class EnrollmentStatus(str, Enum):
    APPLIED = "APPLIED"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    UNPLAYABLE = "UNPLAYABLE"


class InstrumentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKED_OUT = "CHECKED_OUT"
    RETURN_PENDING_INSPECTION = "RETURN_PENDING_INSPECTION"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    RETIRED = "RETIRED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"


class GarmentType(str, Enum):
    JACKET = "JACKET"
    BIBBERS = "BIBBERS"
    SHAKO = "SHAKO"
    PLUME = "PLUME"
    GLOVES = "GLOVES"


class UniformStatus(str, Enum):
    IN_STORAGE = "IN_STORAGE"
    ISSUED = "ISSUED"
    RETURNED_DIRTY = "RETURNED_DIRTY"
    AT_CLEANER = "AT_CLEANER"
    RETIRED = "RETIRED"


class UniformAssignmentStatus(str, Enum):
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"


class SoilingLevel(str, Enum):
    NORMAL = "NORMAL"
    HEAVY = "HEAVY"


class CleaningBatchStatus(str, Enum):
    OPEN = "OPEN"
    SENT = "SENT"
    RECONCILED = "RECONCILED"


class LicenseType(str, Enum):
    STANDARD = "STANDARD"
    CUSTOM_ARRANGEMENT = "CUSTOM_ARRANGEMENT"
    COMPETITION_EXCERPT = "COMPETITION_EXCERPT"


class ArrangementStatus(str, Enum):
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    LICENSED_ACTIVE = "LICENSED_ACTIVE"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class EventType(str, Enum):
    REHEARSAL = "REHEARSAL"
    SECTIONAL = "SECTIONAL"
    COMPETITION = "COMPETITION"
    PERFORMANCE = "PERFORMANCE"
    FUNDRAISER = "FUNDRAISER"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WEATHER_WATCH = "WEATHER_WATCH"
    INDOOR_RELOCATED = "INDOOR_RELOCATED"
    POSTPONED = "POSTPONED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TripStatus(str, Enum):
    PLANNING = "PLANNING"
    ROSTER_OPEN = "ROSTER_OPEN"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    FINALIZED = "FINALIZED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class AttendanceStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    CONFIRMED = "CONFIRMED"
    EXCUSED = "EXCUSED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PaymentKind(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"
    WAIVER = "WAIVER"
    MANUAL_DEBIT = "MANUAL_DEBIT"
    RENTAL_FEE_DEBIT = "RENTAL_FEE_DEBIT"
    LATE_FEE_DEBIT = "LATE_FEE_DEBIT"
    CLEANING_FEE_DEBIT = "CLEANING_FEE_DEBIT"
    TRIP_SHARE_DEBIT = "TRIP_SHARE_DEBIT"
    FUNDRAISING_CREDIT = "FUNDRAISING_CREDIT"


class FundraiserStatus(str, Enum):
    OPEN = "OPEN"
    CREDITED = "CREDITED"


class AuditionStatus(str, Enum):
    SCORING_OPEN = "SCORING_OPEN"
    SCORES_FINALIZED = "SCORES_FINALIZED"
    PLACEMENTS_PUBLISHED = "PLACEMENTS_PUBLISHED"
    UNDER_CHALLENGE = "UNDER_CHALLENGE"


class ChairPlacementStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class TruckCharterStatus(str, Enum):
    RESERVED = "RESERVED"
    LOADED = "LOADED"
    DEPARTED = "DEPARTED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts ------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# Payment and TruckLoad are append-only: only id + created_at (PRD §2.4).

class BandProgram(TypedDict, total=False):
    id: str
    season_name: str
    status: str
    rental_fee_mode: str
    scoring_mode: str
    music_budget_cents: int
    repair_budget_cents: int
    subsidy_pool_cents: int
    delinquency_grace_cents: int
    music_spent_cents: int
    repair_spent_cents: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    program_id: str
    full_name: str
    grade: int
    section: str
    is_section_leader: bool
    enrollment_status: str
    account_balance_cents: int
    is_delinquent: bool
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict, total=False):
    id: str
    program_id: str
    serial_number: str
    instrument_type: str
    condition_grade: str
    replacement_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstrumentAssignment(TypedDict, total=False):
    id: str
    student_id: str
    instrument_id: str
    status: str
    checkout_at: str
    due_date: str
    returned_at: Optional[str]
    fee_variant: str
    accrued_fee_cents: int
    late_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Uniform(TypedDict, total=False):
    id: str
    program_id: str
    garment_type: str
    size_label: str
    status: str
    cleaning_batch_id: Optional[str]
    cleaning_count: int
    created_at: str
    updated_at: str
    version: int


class UniformAssignment(TypedDict, total=False):
    id: str
    student_id: str
    uniform_id: str
    status: str
    issued_at: str
    returned_at: Optional[str]
    soiling_level: Optional[str]
    cleaning_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class CleaningBatch(TypedDict, total=False):
    id: str
    program_id: str
    status: str
    garment_count: int
    discount_pct: float
    total_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class MusicArrangement(TypedDict, total=False):
    id: str
    program_id: str
    title: str
    arranger: str
    license_type: str
    cost_cents: int
    rights_end: str
    status: str
    creator_user_id: str
    approver_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict, total=False):
    id: str
    program_id: str
    event_type: str
    facility: str
    starts_at: str
    ends_at: str
    is_outdoor: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict, total=False):
    id: str
    event_id: str
    program_id: str
    status: str
    capacity: int
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    subsidy_applied_cents: int
    departure_at: str
    registered_count: int
    confirmed_count: int
    created_at: str
    updated_at: str
    version: int


class TripEnrollment(TypedDict, total=False):
    id: str
    trip_id: str
    student_id: str
    attendance_status: str
    payment_status: str
    provisional_share_cents: int
    amount_due_cents: int
    final_share_cents: Optional[int]
    net_paid_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class PaymentAllocation(TypedDict, total=False):
    debit_payment_id: str
    applied_cents: int


class Payment(TypedDict, total=False):
    # Append-only ledger row: id + created_at only (PRD §2.4) — no updated_at,
    # no version.
    id: str
    student_id: str
    kind: str
    amount_cents: int
    trip_enrollment_id: Optional[str]
    fundraiser_id: Optional[str]
    reference_payment_id: Optional[str]
    allocations: List[PaymentAllocation]
    note: Optional[str]
    created_at: str


class Fundraiser(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    goal_cents: int
    status: str
    raised_cents: Optional[int]
    allocated_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Audition(TypedDict, total=False):
    id: str
    program_id: str
    section: str
    chair_capacity: int
    scoring_mode: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JudgeScore(TypedDict):
    judge_id: str
    musicianship: int
    marching: int
    leadership: int


class AuditionEntry(TypedDict, total=False):
    id: str
    audition_id: str
    student_id: str
    judge_scores: List[JudgeScore]
    composite_score: Optional[float]
    rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ChairPlacement(TypedDict, total=False):
    id: str
    audition_id: str
    entry_id: str
    chair_number: Optional[int]
    is_alternate: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TruckCharter(TypedDict, total=False):
    id: str
    program_id: str
    event_id: Optional[str]
    vehicle_label: str
    status: str
    capacity_weight_lb: int
    capacity_volume_cuft: int
    window_start: str
    window_end: str
    loaded_weight_lb: int
    loaded_volume_cuft: int
    created_at: str
    updated_at: str
    version: int


class TruckLoad(TypedDict, total=False):
    # Append-only manifest row: id + created_at only (PRD §2.4) — no updated_at,
    # no version.
    id: str
    charter_id: str
    instrument_id: Optional[str]
    description: str
    weight_lb: int
    volume_cuft: int
    created_at: str
