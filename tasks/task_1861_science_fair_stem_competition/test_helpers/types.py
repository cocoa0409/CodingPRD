"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3).

Standard resources carry id/created_at/updated_at/version (PRD §2.4).
Judge-conflict records and score sheets are immutable once written and carry
only id/created_at among the standard fields, so their TypedDicts omit
updated_at and version (PRD §2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FAIR_DIRECTOR = "FairDirector"
    MENTOR = "Mentor"
    ETHICS_REVIEWER = "EthicsReviewer"
    JUDGE = "Judge"
    OPERATIONS_LEAD = "OperationsLead"
    SAFETY_INSPECTOR = "SafetyInspector"


class NormalizationAlgorithm(str, Enum):
    Z_SCORE = "Z_SCORE"
    MIN_MAX = "MIN_MAX"


class FairEditionStatus(str, Enum):
    SETUP = "SETUP"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    JUDGING = "JUDGING"
    ADVANCEMENT_PUBLISHED = "ADVANCEMENT_PUBLISHED"
    AWARDS_FINALIZED = "AWARDS_FINALIZED"
    ARCHIVED = "ARCHIVED"


class GradeBand(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"


class CategoryStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class EthicsStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InspectionStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class JudgingStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    JUDGED = "JUDGED"


class AdvancementResult(str, Enum):
    PENDING = "PENDING"
    ADVANCED = "ADVANCED"
    WAITLISTED = "WAITLISTED"
    NOT_ADVANCED = "NOT_ADVANCED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ResearchPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISION_REQUIRED = "REVISION_REQUIRED"


class EthicsDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"


class JudgeStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SUBMITTED = "SUBMITTED"
    RECUSED = "RECUSED"
    RELEASED = "RELEASED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AwardType(str, Enum):
    CATEGORY_FIRST = "CATEGORY_FIRST"
    CATEGORY_SECOND = "CATEGORY_SECOND"
    GRAND_PRIZE = "GRAND_PRIZE"
    SPECIAL_TOPIC = "SPECIAL_TOPIC"


class AwardStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFERRED = "CONFERRED"
    REVOKED = "REVOKED"


# --- Entity TypedDicts --------------------------------------------------------


class FairEdition(TypedDict, total=False):
    id: str
    name: str
    status: str
    normalization_algorithm: str
    max_judges_per_project: int
    min_quorum_ratio_pct: int
    advancement_freeze: bool
    created_at: str
    updated_at: str
    version: int


class Category(TypedDict, total=False):
    id: str
    fair_edition_id: str
    code: str
    name: str
    grade_band: str
    advancement_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Mentor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    recognition_points: int
    leaderboard_points: int
    recognition_tier: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    fair_edition_id: str
    category_id: str
    mentor_id: str
    title: str
    team_size: int
    involves_human_subjects: bool
    involves_animal_subjects: bool
    registration_status: str
    ethics_status: Optional[str]
    inspection_status: str
    judging_status: str
    provisional_aggregate: Optional[float]
    final_aggregate: Optional[float]
    advancement_result: str
    advancement_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ResearchPlan(TypedDict, total=False):
    id: str
    project_id: str
    plan_text: str
    risk_level: str
    status: str
    review_cycle_count: int
    approved_plan_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EthicsReview(TypedDict, total=False):
    id: str
    research_plan_id: str
    reviewer_mentor_id: str
    decision: str
    rationale: Optional[str]
    decided_at: str
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict, total=False):
    id: str
    fair_edition_id: str
    full_name: str
    expertise_category_ids: List[str]
    max_assignments: int
    active_assignment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class JudgeConflict(TypedDict, total=False):
    # Immutable record: only id + created_at among the standard fields.
    id: str
    judge_id: str
    project_id: str
    reason: str
    created_at: str


class JudgingAssignment(TypedDict, total=False):
    id: str
    project_id: str
    judge_id: str
    status: str
    assigned_at: str
    created_at: str
    updated_at: str
    version: int


class ScoreSheet(TypedDict, total=False):
    # Immutable record: only id + created_at among the standard fields.
    id: str
    judging_assignment_id: str
    project_id: str
    judge_id: str
    raw_score: int
    normalized_score: float
    submitted_at: str
    created_at: str


class BoothAssignment(TypedDict, total=False):
    id: str
    project_id: str
    hall: str
    booth_number: int
    inspection_window_start: str
    inspection_window_end: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    fair_edition_id: str
    project_id: str
    award_type: str
    scholarship_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScholarshipPool(TypedDict, total=False):
    id: str
    fair_edition_id: str
    total_cents: int
    remaining_cents: int
    created_at: str
    updated_at: str
    version: int
