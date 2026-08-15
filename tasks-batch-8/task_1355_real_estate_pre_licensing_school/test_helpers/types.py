"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's resource descriptions: every persisted entity except
the audit trail carries id, created_at, updated_at, and version (PRD §2.5); the
audit trail carries only id and created_at.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    STATE_COMMISSION = "StateCommission"
    SCHOOL_DIRECTOR = "SchoolDirector"
    REGISTRAR = "Registrar"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    INSTRUCTOR = "Instructor"
    PROCTOR = "Proctor"
    STUDENT = "Student"


class SchoolStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    LICENSED = "LICENSED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class SchoolPosture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"


class CourseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CourseType(str, Enum):
    PRE_LICENSING = "PRE_LICENSING"
    CONTINUING_ED = "CONTINUING_ED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRING = "EXPIRING"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    DISTANCE = "DISTANCE"


class AcademicStatus(str, Enum):
    ENROLLED = "ENROLLED"
    IN_PROGRESS = "IN_PROGRESS"
    SEAT_TIME_MET = "SEAT_TIME_MET"
    EXAM_PASSED = "EXAM_PASSED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class WithdrawalReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    SCHOOL_CANCELLED = "SCHOOL_CANCELLED"


class AttendanceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    VOID = "VOID"


class ExamAttemptStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PROCTORED = "PROCTORED"
    SCORED = "SCORED"
    NO_SHOW = "NO_SHOW"
    INVALIDATED = "INVALIDATED"


class ExamOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class CreditReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


# --- Entity payloads (common_fields: id, created_at, updated_at, version) ---

class School(TypedDict, total=False):
    id: str
    school_name: str
    school_code: str
    home_state_code: str
    pass_rate_threshold_bps: int
    director_user_id: str
    status: str
    posture: str
    last_evaluation_attempt_count: int
    last_evaluation_first_attempt_pass_rate_bps: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict, total=False):
    id: str
    school_id: str
    course_code: str
    title: str
    course_type: str
    required_seat_minutes: int
    tuition_cents: int
    pass_score_pct: int
    max_exam_attempts: int
    completion_deadline_days: int
    ce_credit_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CourseApproval(TypedDict, total=False):
    id: str
    course_id: str
    state_code: str
    application_round: int
    status: str
    valid_from: Optional[str]
    valid_until: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict, total=False):
    id: str
    school_id: str
    full_name: str
    license_number: str
    created_at: str
    updated_at: str
    version: int


class InstructorApproval(TypedDict, total=False):
    id: str
    instructor_id: str
    state_code: str
    application_round: int
    status: str
    valid_from: Optional[str]
    valid_until: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourseOffering(TypedDict, total=False):
    id: str
    course_id: str
    instructor_id: str
    state_code: str
    start_date: str
    end_date: str
    capacity: int
    delivery_mode: str
    status: str
    enrolled_count: int
    seats_available: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    school_id: str
    full_name: str
    email: str
    license_goal_state: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    student_id: str
    offering_id: str
    academic_status: str
    payment_status: str
    scholarship_cents: int
    charge_total_cents: int
    paid_cents: int
    retained_cents: int
    verified_seat_minutes: int
    creditable_seat_minutes: int
    completion_fraction_bps: int
    exam_attempts_used: int
    deadline_date: str
    enrolled_at: str
    withdrawn_at: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict, total=False):
    id: str
    enrollment_id: str
    session_date: str
    minutes: int
    recorded_by_instructor_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExamAttempt(TypedDict, total=False):
    id: str
    enrollment_id: str
    attempt_number: int
    scheduled_at: str
    proctor_instructor_id: str
    status: str
    score_pct: Optional[int]
    outcome: Optional[str]
    invalidation_reason: Optional[str]
    verified_at: Optional[str]
    scored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    enrollment_id: str
    certificate_number: str
    credit_hours_pinned: float
    issue_date: str
    status: str
    revoked_reason: Optional[str]
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict, total=False):
    id: str
    enrollment_id: str
    reason: str
    status: str
    completion_fraction_bps_at_withdrawal: int
    scheduled_refund_cents: int
    statutory_refund_cents: int
    granted_refund_cents: int
    denial_reason: Optional[str]
    decided_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditReportLine(TypedDict, total=False):
    certificate_id: str
    enrollment_id: str
    student_id: str
    credit_hours: float


class CreditReport(TypedDict, total=False):
    id: str
    school_id: str
    period_start: str
    period_end: str
    amendment_of_id: Optional[str]
    reason: Optional[str]
    status: str
    line_items: List[CreditReportLine]
    total_credit_hours: float
    reporting_deadline_date: str
    submitted_at: Optional[str]
    late_days: int
    late_fee_cents: int
    submission_count: int
    created_at: str
    updated_at: str
    version: int


class EquivalencyGrant(TypedDict, total=False):
    id: str
    course_id: str
    home_state_code: str
    recognized_state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit trail: carries ONLY id + created_at (no updated_at/version).
class AuditEvent(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    event_type: str
    actor_role: str
    actor_id: str
    detail: Dict[str, Any]
    created_at: str
