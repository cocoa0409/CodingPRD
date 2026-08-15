"""Domain types: entity TypedDicts, status enums, role enum.

All twelve resources share the same bookkeeping shape (id, created_at,
updated_at, version) per the PRD's resource-identity rules.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PARENT = "Parent"
    CONSULTANT = "Consultant"
    PRACTICE_ADMIN = "PracticeAdmin"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSMENT = "ASSESSMENT"
    PLANNING = "PLANNING"
    ACTIVE_SUPPORT = "ACTIVE_SUPPORT"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    COMPLETED = "COMPLETED"
    CLOSED_REFUNDED = "CLOSED_REFUNDED"


class QuestionnaireStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVIEWED = "REVIEWED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NEEDS_ADJUSTMENT = "NEEDS_ADJUSTMENT"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    CLOSED_EARLY = "CLOSED_EARLY"


class LogReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    REVIEWED_ON_TRACK = "REVIEWED_ON_TRACK"
    REVIEWED_REGRESSION = "REVIEWED_REGRESSION"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MessageStatus(str, Enum):
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    RESPONDED = "RESPONDED"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    WITHDRAWN = "WITHDRAWN"


class DeliveryMode(str, Enum):
    ONE_ON_ONE = "ONE_ON_ONE"
    GROUP_COURSE = "GROUP_COURSE"


class AgeBand(str, Enum):
    NEWBORN = "NEWBORN"
    INFANT = "INFANT"
    TODDLER = "TODDLER"
    PRESCHOOL = "PRESCHOOL"


class PlanMethod(str, Enum):
    GENTLE_NO_CRY = "GENTLE_NO_CRY"
    FERBER_GRADUATED = "FERBER_GRADUATED"
    CHAIR_METHOD = "CHAIR_METHOD"
    EXTINCTION = "EXTINCTION"


class PackageTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class PackageKind(str, Enum):
    INITIAL = "INITIAL"
    FOLLOW_UP = "FOLLOW_UP"


class SessionType(str, Enum):
    REGRESSION = "REGRESSION"
    TRAVEL = "TRAVEL"


class RefundType(str, Enum):
    COOLING_OFF = "COOLING_OFF"
    GUARANTEE = "GUARANTEE"
    PRO_RATA = "PRO_RATA"


class LogReviewOutcome(str, Enum):
    ON_TRACK = "ON_TRACK"
    REGRESSION = "REGRESSION"


class Consultant(TypedDict):
    id: str
    full_name: str
    certification_no: str
    max_active_cases: int
    active_case_count: int
    created_at: str
    updated_at: str
    version: int


class ClientFamily(TypedDict):
    id: str
    full_name: str
    email: str
    credit_balance_cents: int
    is_repeat_client: bool
    created_at: str
    updated_at: str
    version: int


class ClientCase(TypedDict):
    id: str
    family_id: str
    consultant_id: str
    child_birth_date: str
    delivery_mode: str
    guarantee_goal_night_wakings: int
    child_age_months: int
    age_band: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntakeQuestionnaire(TypedDict):
    id: str
    case_id: str
    answers: dict
    provisional_severity_score: int
    adjustment_points: Optional[int]
    reviewed_severity_score: Optional[int]
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SleepPlan(TypedDict):
    id: str
    case_id: str
    plan_sequence: int
    age_band: str
    method: str
    target_night_wake_count: int
    target_longest_stretch_minutes: int
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SupportPackage(TypedDict):
    id: str
    case_id: str
    tier: str
    kind: str
    purchased_at: str
    starts_on: str
    duration_weeks: int
    expires_on: str
    included_calls: int
    included_messages: int
    response_sla_hours: int
    remaining_calls: int
    remaining_messages: int
    gross_price_cents: int
    repeat_discount_cents: int
    credit_applied_cents: int
    net_price_cents: int
    sla_credit_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NightlySleepLog(TypedDict):
    id: str
    case_id: str
    log_date: str
    night_wake_count: int
    longest_stretch_minutes: int
    nap_count: int
    nap_total_minutes: int
    notes: Optional[str]
    review_status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TroubleshootingSession(TypedDict):
    id: str
    case_id: str
    package_id: str
    session_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Message(TypedDict):
    id: str
    case_id: str
    package_id: str
    body: str
    response_body: Optional[str]
    first_responded_at: Optional[str]
    sla_breached: Optional[bool]
    credit_granted_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    case_id: str
    package_id: str
    refund_type: str
    reason: Optional[str]
    amount_cents: Optional[int]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GroupCourse(TypedDict):
    id: str
    consultant_id: str
    title: str
    starts_on: str
    capacity: int
    price_cents: int
    enrolled_count: int
    created_at: str
    updated_at: str
    version: int


class CourseEnrollment(TypedDict):
    id: str
    course_id: str
    case_id: str
    status: str
    promoted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
