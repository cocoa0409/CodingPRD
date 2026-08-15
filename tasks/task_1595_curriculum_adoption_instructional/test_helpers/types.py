"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD: every primary resource carries id, created_at,
updated_at, and version — except the committee vote, which is immutable once
cast and carries only id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    DISTRICT_ADMIN = "DistrictAdmin"
    CURRICULUM_DIRECTOR = "CurriculumDirector"
    INSTRUCTIONAL_SPECIALIST = "InstructionalSpecialist"
    BOARD_SECRETARY = "BoardSecretary"
    PROCUREMENT_OFFICER = "ProcurementOfficer"
    WAREHOUSE_MANAGER = "WarehouseManager"
    TEACHER = "Teacher"
    COMMITTEE_MEMBER = "CommitteeMember"
    COMMUNITY_MEMBER = "CommunityMember"


class SubjectArea(str, Enum):
    MATHEMATICS = "MATHEMATICS"
    ENGLISH_LANGUAGE_ARTS = "ENGLISH_LANGUAGE_ARTS"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"
    WORLD_LANGUAGES = "WORLD_LANGUAGES"


class GradeBand(str, Enum):
    K_5 = "K_5"
    GRADES_6_8 = "GRADES_6_8"
    GRADES_9_12 = "GRADES_9_12"


class FrameworkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ALIGNMENT_REVIEW = "ALIGNMENT_REVIEW"
    PILOT_OPEN = "PILOT_OPEN"
    SCORING = "SCORING"
    PUBLIC_REVIEW = "PUBLIC_REVIEW"
    BOARD_PENDING = "BOARD_PENDING"
    ADOPTED = "ADOPTED"
    PROCURING = "PROCURING"
    DISTRIBUTING = "DISTRIBUTING"
    ACTIVE = "ACTIVE"
    SUNSET = "SUNSET"
    NOT_ADOPTED = "NOT_ADOPTED"


class AwardMethod(str, Enum):
    LOWEST_RESPONSIVE = "LOWEST_RESPONSIVE"
    BEST_VALUE = "BEST_VALUE"


class MaterialAdoptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VETTED = "VETTED"
    PILOT_CANDIDATE = "PILOT_CANDIDATE"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"


class MaterialAvailabilityStatus(str, Enum):
    USABLE = "USABLE"
    UNDER_CHALLENGE = "UNDER_CHALLENGE"
    RESTRICTED = "RESTRICTED"
    REMOVED = "REMOVED"


class MaterialType(str, Enum):
    CORE = "CORE"
    SUPPLEMENTAL = "SUPPLEMENTAL"


class CoverageRating(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class PilotStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"


class QuoteStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class PaymentStatus(str, Enum):
    UNENCUMBERED = "UNENCUMBERED"
    ENCUMBERED = "ENCUMBERED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    RELEASED = "RELEASED"


class DistributionOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    BACKORDERED = "BACKORDERED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class SupplementalRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VETTING = "VETTING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    UNDER_CHALLENGE = "UNDER_CHALLENGE"
    REAFFIRMED = "REAFFIRMED"
    REVOKED = "REVOKED"


class ChallengeStatus(str, Enum):
    FILED = "FILED"
    SCREENING = "SCREENING"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    HEARING = "HEARING"
    DECIDED = "DECIDED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


class ChallengeTargetType(str, Enum):
    MATERIAL = "MATERIAL"
    SUPPLEMENTAL_REQUEST = "SUPPLEMENTAL_REQUEST"


class ChallengeGrounds(str, Enum):
    CONTENT_OBJECTION = "CONTENT_OBJECTION"
    AGE_APPROPRIATENESS = "AGE_APPROPRIATENESS"
    ALIGNMENT_DISPUTE = "ALIGNMENT_DISPUTE"
    PROCEDURAL_IRREGULARITY = "PROCEDURAL_IRREGULARITY"


class ChallengeDecision(str, Enum):
    UPHELD = "UPHELD"
    RESTRICTED = "RESTRICTED"
    REMOVED = "REMOVED"


class CommitteeVoteValue(str, Enum):
    UPHOLD = "UPHOLD"
    RESTRICT = "RESTRICT"
    REMOVE = "REMOVE"


class ForecastVariant(str, Enum):
    ROLLING = "ROLLING"
    STRAIGHT_LINE = "STRAIGHT_LINE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common fields: id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class CurriculumFramework(TypedDict, total=False):
    id: str
    code: str
    subject_area: str
    grade_band: str
    standards_required_count: int
    effective_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdoptionCycle(TypedDict, total=False):
    id: str
    subject_area: str
    grade_band: str
    school_year_start: int
    framework_id: str
    award_method: str
    district_enrollment: int
    status: str
    public_review_opens_at: Optional[str]
    public_review_closes_at: Optional[str]
    adopted_material_id: Optional[str]
    pinned_quote_id: Optional[str]
    quote_version_pin: Optional[int]
    open_backorder_count: int
    replacement_due: bool
    created_at: str
    updated_at: str
    version: int


class InstructionalMaterial(TypedDict, total=False):
    id: str
    cycle_id: str
    title: str
    publisher_name: str
    isbn: Optional[str]
    material_type: str
    adoption_status: str
    availability_status: str
    coverage_pct: float
    provisional_composite: Optional[float]
    official_composite: Optional[float]
    participation_rate: Optional[float]
    adopted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlignmentMapping(TypedDict, total=False):
    id: str
    material_id: str
    standard_code: str
    coverage_rating: str
    created_at: str
    updated_at: str
    version: int


class PilotProgram(TypedDict, total=False):
    id: str
    cycle_id: str
    material_id: str
    school_code: str
    starts_on: str
    ends_on: str
    teacher_count: int
    status: str
    submitted_review_count: int
    created_at: str
    updated_at: str
    version: int


class TeacherReview(TypedDict, total=False):
    id: str
    pilot_id: str
    teacher_user_id: str
    pedagogy_score: int
    alignment_score: int
    usability_score: int
    equity_score: int
    review_composite: float
    status: str
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class PublisherQuote(TypedDict, total=False):
    id: str
    cycle_id: str
    material_id: str
    publisher_name: str
    print_unit_price: float
    print_quantity: int
    digital_seat_rate: float
    digital_seat_count: int
    bundle_discount_pct: float
    training_sessions: int
    license_years: int
    evaluated_total: Optional[float]
    best_value_score: Optional[float]
    status: str
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    cycle_id: str
    quote_id: str
    print_quantity: int
    digital_seat_count: int
    total_amount: float
    amount_paid: float
    received_print_qty: int
    quote_version_pin: int
    order_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    material_id: str
    on_hand_units: int
    in_transit_units: int
    delivered_units: int
    total_received_units: int
    allocated_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class DistributionOrder(TypedDict, total=False):
    id: str
    material_id: str
    school_code: str
    classroom_label: str
    quantity: int
    need_priority: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplementalRequest(TypedDict, total=False):
    id: str
    cycle_id: str
    requester_user_id: str
    title: str
    publisher_name: str
    estimated_cost: float
    subject_area: str
    grade_band: str
    school_code: str
    justification: Optional[str]
    approver_user_id: Optional[str]
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChallengeCase(TypedDict, total=False):
    id: str
    target_type: str
    target_id: str
    grounds: str
    filer_user_id: str
    status: str
    decision: Optional[str]
    vote_round: int
    appeal_used: bool
    filed_at: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeVote(TypedDict, total=False):
    """Immutable once cast: carries ONLY id and created_at as system fields.

    No updated_at, no version.
    """
    id: str
    challenge_id: str
    voter_user_id: str
    vote: str
    vote_round: int
    created_at: str


class BudgetLedger(TypedDict, total=False):
    id: str
    cycle_id: str
    appropriation_total: float
    encumbered_total: float
    expended_total: float
    available_balance: float
    created_at: str
    updated_at: str
    version: int
