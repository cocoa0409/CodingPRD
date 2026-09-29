"""Domain types: status enums, entity TypedDicts, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DISTRICT_PLANNER = "DistrictPlanner"
    ENGAGEMENT_COORDINATOR = "EngagementCoordinator"
    BOARD_MEMBER = "BoardMember"
    TRANSFER_OFFICER = "TransferOfficer"
    GUARDIAN = "Guardian"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------
class StudyStatus(str, Enum):
    SETUP = "SETUP"
    DATA_LOCKED = "DATA_LOCKED"
    SCENARIO_DEVELOPMENT = "SCENARIO_DEVELOPMENT"
    ENGAGEMENT = "ENGAGEMENT"
    BOARD_DECISION = "BOARD_DECISION"
    IMPLEMENTATION = "IMPLEMENTATION"
    CLOSED = "CLOSED"


class SchoolLevel(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"


class SchoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MOTHBALLED = "MOTHBALLED"


class GradeBand(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"


class UnitType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    TOWNHOME = "TOWNHOME"
    MULTI_FAMILY = "MULTI_FAMILY"


class EntitlementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ENTITLED = "ENTITLED"
    PERMITTED = "PERMITTED"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    COMPLETE = "COMPLETE"
    WITHDRAWN = "WITHDRAWN"


ENTITLEMENT_LADDER = [
    EntitlementStatus.PROPOSED.value,
    EntitlementStatus.ENTITLED.value,
    EntitlementStatus.PERMITTED.value,
    EntitlementStatus.UNDER_CONSTRUCTION.value,
    EntitlementStatus.COMPLETE.value,
]
"""The forward-only entitlement ladder, in order."""


class ProjectionVariant(str, Enum):
    COHORT_SURVIVAL = "COHORT_SURVIVAL"
    DEVELOPMENT_WEIGHTED = "DEVELOPMENT_WEIGHTED"


class ProjectionRunStatus(str, Enum):
    COMPLETE = "COMPLETE"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class ScenarioStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION = "REVISION"
    BOARD_READY = "BOARD_READY"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"


class ImpactVariant(str, Enum):
    RESIDENT_BASED = "RESIDENT_BASED"
    PROJECTED_BASED = "PROJECTED_BASED"


class CommentTheme(str, Enum):
    TRANSPORTATION = "TRANSPORTATION"
    SIBLING_SPLIT = "SIBLING_SPLIT"
    EQUITY = "EQUITY"
    CAPACITY = "CAPACITY"
    PROGRAM_ACCESS = "PROGRAM_ACCESS"
    OTHER = "OTHER"


class CommentPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CommentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    ADDRESSED = "ADDRESSED"
    DISMISSED = "DISMISSED"


class ImplementationStatus(str, Enum):
    PENDING_EFFECTIVE = "PENDING_EFFECTIVE"
    IN_EFFECT = "IN_EFFECT"
    MONITORING_CLOSED = "MONITORING_CLOSED"
    RESCINDED = "RESCINDED"


class TransferWindowStatus(str, Enum):
    TRANSFER_WINDOW_OPEN = "TRANSFER_WINDOW_OPEN"
    TRANSFER_WINDOW_CLOSED = "TRANSFER_WINDOW_CLOSED"


class PhaseInRuleType(str, Enum):
    TERMINAL_GRADE_GRANDFATHER = "TERMINAL_GRADE_GRANDFATHER"
    SIBLING_LINK = "SIBLING_LINK"
    PHASE_IN_GRADE_BAND = "PHASE_IN_GRADE_BAND"


class TransferReason(str, Enum):
    GRANDFATHER = "GRANDFATHER"
    SIBLING = "SIBLING"
    PHASE_IN = "PHASE_IN"
    HARDSHIP = "HARDSHIP"
    PROGRAM = "PROGRAM"


class TransferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WAITLISTED = "WAITLISTED"


class ResolvedReason(str, Enum):
    TERMINAL_GRADE_GRANDFATHER = "TERMINAL_GRADE_GRANDFATHER"
    SIBLING_LINK = "SIBLING_LINK"
    PHASE_IN_GRADE_BAND = "PHASE_IN_GRADE_BAND"
    HARDSHIP_REVIEW = "HARDSHIP_REVIEW"
    NONE = "NONE"


class PromotionSource(str, Enum):
    OFFICER_DECISION = "OFFICER_DECISION"
    WAITLIST_AUTO = "WAITLIST_AUTO"


class TransferDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    WAITLIST = "WAITLIST"


class VarianceFlag(str, Enum):
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    WATCH = "WATCH"
    CORRECTIVE_ACTION_REQUIRED = "CORRECTIVE_ACTION_REQUIRED"


# ---------------------------------------------------------------------------
# Nested value objects
# ---------------------------------------------------------------------------
class TravelOption(TypedDict):
    school_id: str
    walk_distance_miles: float
    bus_minutes: int
    has_safe_route: bool


class ProgramPlacement(TypedDict):
    program_type: str
    school_id: str
    seats: int


class AreaProjection(TypedDict):
    area_id: str
    base_students: int
    development_students: float
    projected_students: int


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class BoundaryStudy(TypedDict):
    id: str
    name: str
    district_name: str
    target_school_year: int
    horizon_years: int
    capacity_target_low_pct: float
    capacity_target_high_pct: float
    portables_count_toward_capacity: bool
    required_program_types: List[str]
    status: str
    comment_intake_open: bool
    data_locked_at: Optional[str]
    resident_student_total: int
    enrolled_of_record_total: int
    projection_stale: bool
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    study_id: str
    name: str
    level: str
    core_capacity_seats: int
    portable_capacity_seats: int
    program_types: List[str]
    status: str
    effective_capacity_seats: int
    enrolled_students_of_record: int
    created_at: str
    updated_at: str
    version: int


class PlanningArea(TypedDict):
    id: str
    study_id: str
    area_code: str
    grade_band: str
    current_school_id: str
    previous_school_id: Optional[str]
    resident_student_count: int
    frl_student_count: int
    ell_student_count: int
    median_household_income_usd: int
    annual_absorption_cap_units: int
    travel_options: List[TravelOption]
    created_at: str
    updated_at: str
    version: int


class HousingDevelopment(TypedDict):
    id: str
    area_id: str
    name: str
    unit_type: str
    total_units: int
    first_occupancy_date: str
    buildout_months: int
    student_yield_override: Optional[float]
    entitlement_status: str
    created_at: str
    updated_at: str
    version: int


class ProjectionRun(TypedDict):
    id: str
    study_id: str
    variant: str
    horizon_years: int
    status: str
    stale_reason: Optional[str]
    area_projections: List[AreaProjection]
    projected_total_students: int
    created_at: str
    updated_at: str
    version: int


class BoundaryScenario(TypedDict):
    id: str
    study_id: str
    projection_run_id: str
    name: str
    author_user_id: str
    status: str
    revision_round: int
    revision_reason: Optional[str]
    rejection_reason: Optional[str]
    projection_stale: bool
    program_placements: List[ProgramPlacement]
    impact_variant: str
    contiguity_ok: bool
    noncontiguous_school_ids: List[str]
    total_assigned_students: int
    max_utilization_pct: float
    walk_eligible_pct: float
    transport_cost_annual_usd: float
    students_reassigned_count: int
    students_reassigned_pct: float
    frl_dissimilarity_index: float
    created_at: str
    updated_at: str
    version: int


class AreaAssignment(TypedDict):
    id: str
    scenario_id: str
    area_id: str
    assigned_school_id: str
    is_superseded: bool
    superseded_at: Optional[str]
    projected_students: int
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    id: str
    scenario_id: str
    area_id: Optional[str]
    guardian_user_id: str
    body: str
    theme: Optional[str]
    priority: Optional[str]
    status: str
    dismissal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdoptionRecord(TypedDict):
    id: str
    study_id: str
    scenario_id: str
    effective_date: str
    effective_school_year: int
    regime_years: int
    transfer_deadline_date: str
    transfer_cap_pct: float
    variance_tolerance_pct: float
    votes_for: int
    votes_against: int
    votes_abstain: int
    board_member_count: int
    adopted_by_user_id: str
    supermajority_required: bool
    implementation_status: str
    transfer_window_status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    adoption_id: str
    area_id: str
    origin_school_id: str
    requested_school_id: str
    sibling_transfer_id: Optional[str]
    guardian_user_id: str
    student_reference: str
    student_grade: int
    reason: str
    status: str
    resolved_reason: str
    consumes_seat_pool: bool
    promotion_source: Optional[str]
    decided_by_user_id: Optional[str]
    decision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable records — these carry ONLY id and created_at
# ---------------------------------------------------------------------------
class AreaAdjacency(TypedDict):
    id: str
    area_id: str
    neighbor_area_id: str
    shared_boundary_length_ft: int
    is_reciprocal: bool
    created_at: str


class PhaseInRule(TypedDict):
    id: str
    adoption_id: str
    rule_type: str
    grade_low: int
    grade_high: int
    sunset_school_year: int
    consumes_seat_pool: bool
    created_at: str


class VarianceObservation(TypedDict):
    id: str
    adoption_id: str
    school_id: str
    observed_on: str
    observed_enrollment: int
    projected_enrollment: int
    variance_pct: float
    flag: str
    created_at: str


IMMUTABLE_ENTITY_NAMES = ("AreaAdjacency", "PhaseInRule", "VarianceObservation")
"""Records that carry only id and created_at — no updated_at, no version."""
