"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as the Licensing Exam Prep PRD declares them.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    LEARNER = "Learner"
    CONTENT_ADMIN = "ContentAdmin"
    EXAM_PROCTOR = "ExamProctor"
    PLATFORM_OPS = "PlatformOps"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class LicenseProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class SubscriptionPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CohortStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class EnrollmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    WITHDRAWN = "WITHDRAWN"


class ExamOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class InstallmentStatus(str, Enum):
    DUE = "DUE"
    PAID = "PAID"
    VOID = "VOID"


class PracticeSessionStatus(str, Enum):
    COMPLETED = "COMPLETED"


class MockExamStatus(str, Enum):
    COMPLETED = "COMPLETED"


class PassGuaranteeClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClaimRemedy(str, Enum):
    RETAKE_EXTENSION = "RETAKE_EXTENSION"
    MONEY_BACK = "MONEY_BACK"


class CohortMembershipStatus(str, Enum):
    JOINED = "JOINED"
    DROPPED = "DROPPED"


class Difficulty(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class SubscriptionTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PRO = "PRO"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at ONLY (QuestionItem)
# --------------------------------------------------------------------------
class LicenseProgram(TypedDict):
    id: str
    license_code: str
    title: str
    passing_scaled_score: int
    domain_weights: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict):
    id: str
    tier: str
    total_price_cents: int
    down_payment_pct: float
    financing_months: int
    included_mock_credits: int
    pass_guarantee: bool
    guarantee_refund_pct: float
    includes_ce: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CEBundle(TypedDict):
    id: str
    license_program_id: str
    ce_credits_total: int
    modules_total: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only immutable content, NO updated_at / version
class QuestionItem(TypedDict):
    id: str
    license_program_id: str
    domain_code: str
    difficulty: str
    correct_choice: str
    created_at: str


class Cohort(TypedDict):
    id: str
    license_program_id: str
    title: str
    capacity: int
    seats_taken: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CohortSession(TypedDict):
    id: str
    cohort_id: str
    topic: str
    session_start_utc: str
    session_end_utc: str
    created_at: str
    updated_at: str
    version: int


class Learner(TypedDict):
    id: str
    email: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    learner_id: str
    license_program_id: str
    subscription_plan_id: str
    ce_bundle_id: Optional[str]
    financed: bool
    financing_total_due_cents: int
    financing_paid_cents: int
    financing_balance_cents: int
    questions_answered_total: int
    completed_mock_count: int
    readiness_score: int
    projected_readiness_score: int
    exam_outcome: str
    guarantee_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    enrollment_id: str
    sequence_no: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StudyPlanDomain(TypedDict):
    id: str
    enrollment_id: str
    domain_code: str
    weight: float
    mastery: int
    created_at: str
    updated_at: str
    version: int


class PracticeSession(TypedDict):
    id: str
    enrollment_id: str
    domain_code: str
    answered_count: int
    correct_count: int
    batch_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MockExam(TypedDict):
    id: str
    enrollment_id: str
    raw_score: int
    item_count: int
    scaled_score: int
    is_overage: bool
    completed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PassGuaranteeClaim(TypedDict):
    id: str
    enrollment_id: str
    remedy: str
    refund_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CECreditAward(TypedDict):
    id: str
    enrollment_id: str
    ce_bundle_id: str
    modules_completed: int
    credits_awarded: int
    cumulative_credits: int
    created_at: str
    updated_at: str
    version: int


class CohortMembership(TypedDict):
    id: str
    cohort_id: str
    enrollment_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
