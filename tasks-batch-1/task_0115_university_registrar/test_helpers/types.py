"""Domain types: entity TypedDicts, status enums, role enum.

All field names match the University Registrar PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    STUDENT = "Student"
    ADVISOR = "Advisor"
    REGISTRAR = "Registrar"
    BURSAR = "Bursar"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class TermStatus(str, Enum):
    PLANNING = "PLANNING"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    IN_SESSION = "IN_SESSION"
    CLOSED = "CLOSED"


class SectionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"
    WITHDRAWN = "WITHDRAWN"


class GradeStatus(str, Enum):
    UNGRADED = "UNGRADED"
    GRADED = "GRADED"


class HoldType(str, Enum):
    FINANCIAL = "FINANCIAL"
    ADVISING = "ADVISING"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"


class SwapStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


class RequirementType(str, Enum):
    PREREQUISITE = "PREREQUISITE"
    COREQUISITE = "COREQUISITE"


class RefundTier(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    NONE = "NONE"


class RefundTrigger(str, Enum):
    DROP = "DROP"
    WITHDRAW = "WITHDRAW"
    SECTION_CANCEL = "SECTION_CANCEL"


class AcademicStanding(str, Enum):
    GOOD = "GOOD"
    WARNING = "WARNING"
    PROBATION = "PROBATION"


# --------------------------------------------------------------------------
# Entity TypedDicts
#
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at ONLY (no updated_at, no version)
# --------------------------------------------------------------------------

# common_fields: true
class Term(TypedDict):
    id: str
    name: str
    registration_opens_at: str
    add_deadline: str
    drop_deadline: str
    withdraw_deadline: str
    refund_full_pct: float
    refund_partial_pct: float
    per_credit_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Student(TypedDict):
    id: str
    full_name: str
    email: str
    program_id: str
    completed_credit_hours: int
    earned_credit_hours: int
    gpa: float
    academic_standing: str
    tuition_owed_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable reference record, no updated_at / version
class Program(TypedDict):
    id: str
    name: str
    required_credit_hours: int
    min_gpa: float
    created_at: str


# common_fields: true
class Course(TypedDict):
    id: str
    code: str
    title: str
    credit_hours: int
    program_id: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable requirement edge, no updated_at / version
class CourseRequirement(TypedDict):
    id: str
    course_id: str
    required_course_id: str
    requirement_type: str
    min_grade_points: float
    created_at: str


# common_fields: true
class Instructor(TypedDict):
    id: str
    full_name: str
    email: str
    gap_minutes: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Section(TypedDict):
    id: str
    term_id: str
    course_id: str
    instructor_id: str
    section_code: str
    seat_capacity: int
    seats_taken: int
    waitlist_capacity: int
    waitlist_count: int
    meeting_days: str
    meeting_start_min: int
    meeting_end_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class EnrollmentAppointment(TypedDict):
    id: str
    term_id: str
    student_id: str
    priority_tier: int
    window_opens_at: str
    max_credit_hours: int
    enrolled_credit_hours: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Enrollment(TypedDict):
    id: str
    term_id: str
    student_id: str
    section_id: str
    registration_status: str
    grade_status: str
    letter_grade: Optional[str]
    grade_points: Optional[float]
    tuition_charged_cents: int
    refund_cents: int
    waitlist_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Hold(TypedDict):
    id: str
    student_id: str
    hold_type: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class SwapRequest(TypedDict):
    id: str
    student_id: str
    term_id: str
    drop_enrollment_id: str
    add_section_id: str
    status: str
    added_enrollment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — permanent ledger record, no updated_at / version
class RefundTransaction(TypedDict):
    id: str
    enrollment_id: str
    student_id: str
    refund_tier: str
    amount_cents: int
    triggered_by: str
    created_at: str
