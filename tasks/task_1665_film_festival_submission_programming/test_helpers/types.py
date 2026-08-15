"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PUBLIC = "PUBLIC"
    FESTIVAL_ADMIN = "FESTIVAL_ADMIN"
    FILMMAKER = "FILMMAKER"
    PROGRAMMER = "PROGRAMMER"
    PROGRAM_CHAIR = "PROGRAM_CHAIR"
    FESTIVAL_DIRECTOR = "FESTIVAL_DIRECTOR"
    SCHEDULING_OPS = "SCHEDULING_OPS"
    TRAVEL_COORDINATOR = "TRAVEL_COORDINATOR"
    JUROR = "JUROR"
    AWARDS_ADMIN = "AWARDS_ADMIN"


class EditionStatus(str, Enum):
    SETUP = "SETUP"
    INTAKE_OPEN = "INTAKE_OPEN"
    INTAKE_CLOSED = "INTAKE_CLOSED"
    SCREENING = "SCREENING"
    DELIBERATION = "DELIBERATION"
    SLATE_LOCKED = "SLATE_LOCKED"
    NOTIFICATION = "NOTIFICATION"
    SCHEDULING = "SCHEDULING"
    FESTIVAL_LIVE = "FESTIVAL_LIVE"
    AWARDS_NIGHT = "AWARDS_NIGHT"
    CLOSED = "CLOSED"


class Category(str, Enum):
    NARRATIVE_FEATURE = "NARRATIVE_FEATURE"
    DOCUMENTARY_FEATURE = "DOCUMENTARY_FEATURE"
    SHORT_FILM = "SHORT_FILM"
    EPISODIC = "EPISODIC"


class PremiereRequirement(str, Enum):
    WORLD_REQUIRED = "WORLD_REQUIRED"
    NORTH_AMERICA_REQUIRED = "NORTH_AMERICA_REQUIRED"
    US_REQUIRED = "US_REQUIRED"
    NONE = "NONE"


class PremiereStatus(str, Enum):
    WORLD = "WORLD"
    INTERNATIONAL = "INTERNATIONAL"
    NORTH_AMERICA = "NORTH_AMERICA"
    US = "US"
    REGIONAL = "REGIONAL"
    NONE = "NONE"


class FilmFormat(str, Enum):
    DCP_2K = "DCP_2K"
    DCP_4K = "DCP_4K"
    FILM_35MM = "FILM_35MM"
    PRORES_4444 = "PRORES_4444"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    NEEDS_INFO = "NEEDS_INFO"
    ELIGIBLE = "ELIGIBLE"
    IN_SCREENING = "IN_SCREENING"
    ADVANCED = "ADVANCED"
    INVITED = "INVITED"
    WAITLISTED = "WAITLISTED"
    CONFIRMED = "CONFIRMED"
    PROGRAMMED = "PROGRAMMED"
    INELIGIBLE = "INELIGIBLE"
    DECLINED = "DECLINED"
    DECLINED_BY_FILMMAKER = "DECLINED_BY_FILMMAKER"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class FeePaymentStatus(str, Enum):
    INITIATED = "INITIATED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class FeeTier(str, Enum):
    EARLY = "EARLY"
    REGULAR = "REGULAR"
    LATE = "LATE"


class Seniority(str, Enum):
    STAFF = "STAFF"
    SENIOR = "SENIOR"
    LEAD = "LEAD"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SCORED = "SCORED"
    RECUSED = "RECUSED"
    EXPIRED = "EXPIRED"


class Recommendation(str, Enum):
    STRONG_ADVOCATE = "STRONG_ADVOCATE"
    ADVOCATE = "ADVOCATE"
    NEUTRAL = "NEUTRAL"
    PASS = "PASS"
    STRONG_PASS = "STRONG_PASS"


class Section(str, Enum):
    US_DRAMATIC = "US_DRAMATIC"
    US_DOCUMENTARY = "US_DOCUMENTARY"
    WORLD_CINEMA_DRAMATIC = "WORLD_CINEMA_DRAMATIC"
    NEXT = "NEXT"
    PREMIERES = "PREMIERES"
    MIDNIGHT = "MIDNIGHT"
    SHORTS = "SHORTS"


class SlateStatus(str, Enum):
    OPEN = "OPEN"
    DELIBERATING = "DELIBERATING"
    LOCKED = "LOCKED"


class Lane(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    MAIN = "MAIN"
    WAITLIST = "WAITLIST"


class SlateEntryStatus(str, Enum):
    NOMINATED = "NOMINATED"
    INVITED = "INVITED"
    CONFIRMED = "CONFIRMED"
    PROGRAMMED = "PROGRAMMED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    DROPPED = "DROPPED"
    RELEASED = "RELEASED"


class SlotType(str, Enum):
    PREMIERE = "PREMIERE"
    PUBLIC = "PUBLIC"
    PRESS_INDUSTRY = "PRESS_INDUSTRY"
    AWARDS_ENCORE = "AWARDS_ENCORE"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    PLAYED = "PLAYED"
    CANCELLED = "CANCELLED"


class TravelPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    BOOKED = "BOOKED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class AwardStatus(str, Enum):
    SETUP = "SETUP"
    VOTING_OPEN = "VOTING_OPEN"
    TALLIED = "TALLIED"
    ANNOUNCED = "ANNOUNCED"
    DISBURSED = "DISBURSED"


class RightsScope(str, Enum):
    FESTIVAL_WORLD = "FESTIVAL_WORLD"
    FESTIVAL_NORTH_AMERICA = "FESTIVAL_NORTH_AMERICA"
    FESTIVAL_US = "FESTIVAL_US"


# --- Entity TypedDicts (common_fields: id + created_at + updated_at + version) ---


class FestivalEdition(TypedDict, total=False):
    id: str
    year: int
    host_country_code: str
    intake_open_at: str
    early_deadline_at: str
    regular_deadline_at: str
    late_deadline_at: str
    rsvp_window_days: int
    festival_start_at: str
    festival_end_at: str
    hotel_nights_pool: int
    travel_budget_cents: int
    prize_pool_cents: int
    status: str
    total_fees_collected_cents: int
    total_refunded_cents: int
    hotel_nights_allocated: int
    hotel_nights_remaining: int
    travel_committed_cents: int
    travel_penalty_sink_cents: int
    travel_budget_remaining: int
    prize_committed_cents: int
    prize_disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class CategoryConfig(TypedDict, total=False):
    id: str
    edition_id: str
    category: str
    min_runtime_minutes: int
    max_runtime_minutes: int
    premiere_requirement: str
    completion_cutoff: str
    early_fee_cents: int
    regular_fee_cents: int
    late_fee_cents: int
    screener_count_required: int
    created_at: str
    updated_at: str
    version: int


class Submitter(TypedDict, total=False):
    id: str
    legal_name: str
    email: str
    country_of_residence: str
    is_student: bool
    is_member: bool
    created_at: str
    updated_at: str
    version: int


class Programmer(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    seniority: str
    categories_covered: List[str]
    coi_production_companies: List[str]
    max_active_assignments: int
    active: bool
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict, total=False):
    id: str
    edition_id: str
    submitter_id: str
    category: str
    title: str
    runtime_minutes: int
    completion_date: str
    premiere_status: str
    production_company: str
    format: str
    status: str
    payment_status: str
    needs_info_resolved: bool
    provisional_score: Optional[float]
    composite_score: Optional[float]
    award_names: List[str]
    created_at: str
    updated_at: str
    version: int


class FeePayment(TypedDict, total=False):
    id: str
    submission_id: str
    tier_applied: str
    base_fee_cents: int
    student_discount_applied: bool
    member_discount_applied: bool
    student_discount_cents: int
    member_discount_cents: int
    amount_cents: int
    status: str
    paid_at: Optional[str]
    refunded_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class ScreenerAssignment(TypedDict, total=False):
    id: str
    submission_id: str
    programmer_id: str
    due_at: str
    status: str
    replaced_by_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Score(TypedDict, total=False):
    id: str
    assignment_id: str
    originality: int
    craft: int
    story: int
    overall: int
    recommendation: str
    locked: bool
    created_at: str
    updated_at: str
    version: int


class Slate(TypedDict, total=False):
    id: str
    edition_id: str
    section: str
    capacity_slots: int
    status: str
    last_entry_added_by: Optional[str]
    entry_count: int
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SlateEntry(TypedDict, total=False):
    id: str
    slate_id: str
    submission_id: str
    rank_position: int
    lane: str
    status: str
    rsvp_deadline_at: Optional[str]
    locked_composite_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    edition_id: str
    name: str
    seat_capacity: int
    formats_supported: List[str]
    turnover_minutes: int
    created_at: str
    updated_at: str
    version: int


class ScreeningSlot(TypedDict, total=False):
    id: str
    venue_id: str
    slate_entry_id: Optional[str]
    slot_type: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TravelPackage(TypedDict, total=False):
    id: str
    submission_id: str
    edition_id: str
    delegate_count: int
    origin_country_code: str
    is_international: bool
    hotel_nights_requested: int
    hotel_nights_allocated: int
    raw_stipend_cents: int
    stipend_cents: int
    penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExhibitionAgreement(TypedDict, total=False):
    id: str
    submission_id: str
    slate_entry_id: str
    rights_scope: str
    licensed_screening_count: int
    used_screening_count: int
    exclusivity_until: str
    revenue_share_pct: float
    submission_version_at_signing: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Juror(TypedDict, total=False):
    id: str
    edition_id: str
    display_name: str
    coi_production_companies: List[str]
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    edition_id: str
    name: str
    section: str
    prize_cents: int
    assigned_juror_ids: List[str]
    status: str
    winner_submission_id: Optional[str]
    rounds_log: List[dict]
    disbursed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


# JuryVote carries only id + created_at (immutable ballot; no updated_at/version).
class JuryVote(TypedDict, total=False):
    id: str
    created_at: str
    award_id: str
    juror_id: str
    ranked_submission_ids: List[str]
    submitted_at: str
