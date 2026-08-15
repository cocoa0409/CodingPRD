"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SCORING = "SCORING"
    REVIEW = "REVIEW"
    FINALIZED = "FINALIZED"


class ProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class CaseStatus(str, Enum):
    SCREENING = "SCREENING"
    AWAITING_COMMITTEE = "AWAITING_COMMITTEE"
    APPEAL_PENDING = "APPEAL_PENDING"
    IDENTIFIED = "IDENTIFIED"
    NOT_IDENTIFIED = "NOT_IDENTIFIED"


class ReviewStatus(str, Enum):
    VOTING = "VOTING"
    DECIDED = "DECIDED"


class ReviewOutcome(str, Enum):
    QUALIFY = "QUALIFY"
    DENY = "DENY"


class PlacementStatus(str, Enum):
    OFFERED = "OFFERED"
    ACTIVE = "ACTIVE"
    WAITLISTED = "WAITLISTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    EXITED = "EXITED"


class ReEvaluationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_REVIEW = "IN_REVIEW"
    CONCLUDED = "CONCLUDED"


class ReEvaluationOutcome(str, Enum):
    RETAINED = "RETAINED"
    PROBATION = "PROBATION"
    EXITED = "EXITED"


class GiftedStatus(str, Enum):
    NOT_IDENTIFIED = "NOT_IDENTIFIED"
    IDENTIFIED = "IDENTIFIED"
    EXITED = "EXITED"


class ScoredVariant(str, Enum):
    STANDARD = "STANDARD"
    TWICE_EXCEPTIONAL = "TWICE_EXCEPTIONAL"


class UserRole(str, Enum):
    GIFTED_COORDINATOR = "GiftedCoordinator"
    REFERRING_EDUCATOR = "ReferringEducator"
    PARENT_GUARDIAN = "ParentGuardian"
    COMMITTEE_MEMBER = "CommitteeMember"
    SPECIAL_ED_COORDINATOR = "SpecialEdCoordinator"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Full-lifecycle entities carry id + created_at + updated_at + version.
# Ledger-style entities (SpedPlan, MeasureScore, CommitteeVote) carry ONLY
# id + created_at; updated_at and version are absent on them.

class SchoolSite(TypedDict):
    id: str
    name: str
    code: str
    pull_out_capacity: int
    cluster_capacity: int
    acceleration_capacity: int
    pull_out_occupied: int
    cluster_occupied: int
    acceleration_occupied: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    student_number: str
    legal_name: str
    grade_level: int
    school_site_id: str
    demographic_group: str
    is_ell: bool
    primary_guardian_user_id: Optional[str]
    gifted_status: str
    has_active_sped_plan: bool
    created_at: str
    updated_at: str
    version: int


class SpedPlan(TypedDict):
    id: str
    student_id: str
    plan_type: str
    started_on: str
    created_at: str


class ScreeningCycle(TypedDict):
    id: str
    name: str
    school_year: str
    grade_band: str
    screening_open_on: str
    screening_close_on: str
    referral_close_on: str
    status: str
    published_profile_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CutScoreProfile(TypedDict):
    id: str
    cycle_id: str
    label: str
    ability_weight: float
    achievement_weight: float
    rating_weight: float
    portfolio_weight: float
    cut_score: int
    review_band_floor: int
    cut_score_2e: int
    review_band_floor_2e: int
    measure_validity_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftedCase(TypedDict):
    id: str
    student_id: str
    cycle_id: str
    pathway: str
    referral_source: Optional[str]
    referrer_user_id: Optional[str]
    external_district_name: Optional[str]
    external_identified_on: Optional[str]
    status: str
    composite_score: Optional[float]
    scored_variant: Optional[str]
    appeal_used: bool
    decided_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeasureScore(TypedDict):
    id: str
    case_id: str
    measure_type: str
    percentile: float
    administered_on: str
    weighted_contribution: Optional[float]
    created_at: str


class CommitteeReview(TypedDict):
    id: str
    case_id: str
    review_kind: str
    grounds: Optional[str]
    status: str
    outcome: Optional[str]
    decided_on: Optional[str]
    qualify_votes: int
    deny_votes: int
    abstain_votes: int
    created_at: str
    updated_at: str
    version: int


class CommitteeVote(TypedDict):
    id: str
    review_id: str
    member_user_id: str
    verdict: str
    created_at: str


class ServicePlacement(TypedDict):
    id: str
    case_id: str
    student_id: str
    site_id: str
    service_model: str
    start_on: str
    end_on: Optional[str]
    status: str
    offered_on: Optional[str]
    accept_by: Optional[str]
    waitlisted_at: Optional[str]
    is_on_probation: bool
    created_at: str
    updated_at: str
    version: int


class ReEvaluation(TypedDict):
    id: str
    placement_id: str
    due_on: str
    status: str
    growth_percentile: Optional[float]
    service_rating: Optional[int]
    teacher_rating: Optional[int]
    exit_score: Optional[float]
    outcome: Optional[str]
    concluded_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GroupMetric(TypedDict):
    demographic_group: str
    enrolled: int
    identified: int
    rate: float
    risk_ratio: Optional[float]
    flagged: bool


class DisproportionalityReport(TypedDict):
    cycle_id: str
    variant: str
    reference_group: Optional[str]
    total_identified: int
    group_metrics: List[dict]
    flagged_groups: List[str]
