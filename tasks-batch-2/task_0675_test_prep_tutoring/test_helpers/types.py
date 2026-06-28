"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---

class CourseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class CohortStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    CONCLUDED = "CONCLUDED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    WAITLISTED = "WAITLISTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GuaranteeStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    REFUND_ISSUED = "REFUND_ISSUED"
    RETAKE_GRANTED = "RETAKE_GRANTED"


class PracticeAttemptStatus(str, Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class AttemptType(str, Enum):
    DIAGNOSTIC = "DIAGNOSTIC"
    PRACTICE = "PRACTICE"


class InstallmentPlanStatus(str, Enum):
    OPEN = "OPEN"
    PAID_IN_FULL = "PAID_IN_FULL"
    DEFAULTED = "DEFAULTED"
    REFUNDED = "REFUNDED"


class GuaranteeClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExamType(str, Enum):
    SAT = "SAT"
    ACT = "ACT"
    MCAT = "MCAT"
    LSAT = "LSAT"


class CourseFormat(str, Enum):
    LIVE = "LIVE"
    ONLINE = "ONLINE"
    SELF = "SELF"


class Resolution(str, Enum):
    REFUND = "REFUND"
    RETAKE = "RETAKE"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    STUDENT = "Student"
    INSTRUCTOR = "Instructor"
    REGISTRAR = "Registrar"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Course(TypedDict):
    id: str
    exam_type: str
    format: str
    title: str
    list_price_cents: int
    baseline_scale_max: int
    guarantee_min_delta: int
    required_practice_tests: int
    required_attendance_pct: float
    materials_access_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    certified_exam_types: List[str]
    max_concurrent_cohorts: int
    active_cohort_count: int
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict):
    id: str
    course_id: str
    instructor_id: Optional[str]
    seat_capacity: int
    seats_committed: int
    starts_at: str
    ends_at: str
    total_sessions: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    email: str
    full_name: str
    diagnostic_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    cohort_id: str
    status: str
    price_paid_cents: int
    completed_practice_count: int
    sessions_attended: int
    best_practice_score: Optional[int]
    guarantee_status: str
    materials_expire_at: Optional[str]
    waitlist_seq: Optional[int]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only analytics record: id + created_at only,
# NO updated_at, NO version.
class PracticeAttempt(TypedDict):
    id: str
    enrollment_id: str
    attempt_type: str
    raw_correct: int
    total_items: int
    scaled_score: Optional[int]
    percentile: Optional[float]
    status: str
    created_at: str


class InstallmentPlan(TypedDict):
    id: str
    enrollment_id: str
    num_installments: int
    total_financed_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GuaranteeClaim(TypedDict):
    id: str
    enrollment_id: str
    resolution: str
    improvement_delta: Optional[int]
    refund_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
