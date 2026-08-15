"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PARENT = "Parent"
    REVIEWER = "Reviewer"
    REGISTRAR = "Registrar"
    ACADEMIC_DIRECTOR = "AcademicDirector"
    STATE_AUDITOR = "StateAuditor"


class AcademicYearStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REPORTED = "REPORTED"


class EnrollmentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class ComplianceStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    NONCOMPLIANT = "NONCOMPLIANT"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RETURNED = "RETURNED"
    WITHDRAWN = "WITHDRAWN"


class CurriculumPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    AMENDMENT_REVIEW = "AMENDMENT_REVIEW"
    ARCHIVED = "ARCHIVED"


class AttendanceEntryStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class PortfolioStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class EvaluationOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    REJECTED = "REJECTED"


class ExamSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    ADMINISTERED = "ADMINISTERED"


class TestRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    EXCUSED = "EXCUSED"
    SCORED = "SCORED"
    CANCELLED = "CANCELLED"


class CourseCreditStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    POSTED = "POSTED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class CoopClassStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CoopEnrollmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class DropReason(str, Enum):
    PARENT_INITIATED = "PARENT_INITIATED"
    SCHOOL_STANDING = "SCHOOL_STANDING"
    SCHOOL_CANCEL = "SCHOOL_CANCEL"


class GraduationApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DIPLOMA_ISSUED = "DIPLOMA_ISSUED"


class ComplianceReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts (common fields: id, created_at, updated_at, version) ---

class AcademicYear(TypedDict):
    id: str
    label: str
    start_date: str
    end_date: str
    notice_filing_deadline: str
    portfolio_due_date: str
    state_report_due_date: str
    mid_year_date: str
    testing_grades: list
    required_instructional_days: int
    required_minutes_elementary: int
    required_minutes_secondary: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict):
    id: str
    display_name: str
    district_code: str
    fee_balance_cents: int
    oldest_unpaid_charge_at: Optional[str]
    fee_status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    family_id: str
    full_name: str
    date_of_birth: str
    transcript_sealed: bool
    sealed_at: Optional[str]
    diploma_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    academic_year_id: str
    grade_level: int
    enrollment_status: str
    compliance_standing: str
    standing_locked: bool
    provisional_days_counted: int
    provisional_minutes_credited: int
    certified_days_counted: int
    certified_minutes_credited: int
    testing_required: bool
    testing_satisfied: bool
    activated_at: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NoticeOfIntent(TypedDict):
    id: str
    enrollment_id: str
    district_code: str
    status: str
    filed_at: Optional[str]
    acknowledged_at: Optional[str]
    returned_reason: Optional[str]
    refile_count: int
    created_at: str
    updated_at: str
    version: int


class CurriculumPlan(TypedDict):
    id: str
    enrollment_id: str
    subjects: list
    status: str
    revision_count: int
    reviewer_id: Optional[str]
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceEntry(TypedDict):
    id: str
    enrollment_id: str
    entry_date: str
    minutes: int
    status: str
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Portfolio(TypedDict):
    id: str
    enrollment_id: str
    status: str
    attempt_count: int
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Evaluation is immutable once written: it carries only id and created_at —
# no updated_at, no version (PRD §2.5).
class Evaluation(TypedDict):
    id: str
    portfolio_id: str
    reviewer_id: str
    attempt_number: int
    overall_outcome: str
    subject_scores: list
    notes: Optional[str]
    created_at: str


class ExamSession(TypedDict):
    id: str
    academic_year_id: str
    test_name: str
    session_date: str
    start_minutes: int
    end_minutes: int
    capacity: int
    registration_deadline: str
    target_grades: list
    location: Optional[str]
    seats_taken: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TestRegistration(TypedDict):
    id: str
    enrollment_id: str
    exam_session_id: str
    status: str
    composite_percentile: Optional[int]
    passed: Optional[bool]
    exemption_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourseCredit(TypedDict):
    id: str
    enrollment_id: str
    subject: str
    course_title: str
    is_lab: bool
    planned_hours: int
    completed_hours: Optional[int]
    letter_grade: Optional[str]
    credit_value: Optional[float]
    status: str
    posted_at: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoopClass(TypedDict):
    id: str
    academic_year_id: str
    title: str
    subject: str
    grade_min: int
    grade_max: int
    meeting_day: str
    meeting_start_minutes: int
    meeting_end_minutes: int
    start_date: str
    end_date: str
    capacity: int
    fee_base_cents: int
    materials_fee_cents: int
    seats_taken: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoopEnrollment(TypedDict):
    id: str
    enrollment_id: str
    coop_class_id: str
    status: str
    fee_cents: int
    discount_pct_applied: int
    refund_cents: Optional[int]
    drop_reason: Optional[str]
    promoted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GraduationApplication(TypedDict):
    id: str
    student_id: str
    academic_year_id: str
    status: str
    evaluated_by: Optional[str]
    decision_notes: Optional[str]
    diploma_issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict):
    id: str
    academic_year_id: str
    status: str
    generated_at: str
    submitted_at: Optional[str]
    late: Optional[bool]
    total_enrollments: int
    compliant_count: int
    noncompliant_enrollment_ids: list
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
