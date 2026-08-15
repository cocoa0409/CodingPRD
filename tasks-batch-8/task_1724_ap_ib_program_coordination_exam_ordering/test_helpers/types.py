"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    AP_COORDINATOR = "ApCoordinator"
    STUDENT = "Student"
    TEACHER = "Teacher"
    REGISTRAR = "Registrar"


class ExamCycleStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"


class CourseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CourseProgram(str, Enum):
    AP = "AP"
    IB = "IB"


class TeacherAuthorizationStatus(str, Enum):
    PENDING_TRAINING = "PENDING_TRAINING"
    AUTHORIZED = "AUTHORIZED"
    EXPIRED = "EXPIRED"


class SubgroupCode(str, Enum):
    GEN = "GEN"
    FRL = "FRL"
    IEP = "IEP"
    ELL = "ELL"


class FeeApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class EligibilityBasis(str, Enum):
    FREE_LUNCH = "FREE_LUNCH"
    REDUCED_LUNCH = "REDUCED_LUNCH"
    INCOME = "INCOME"
    OTHER = "OTHER"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SAT = "SAT"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ScoreStatus(str, Enum):
    PENDING = "PENDING"
    HELD = "HELD"
    RELEASED = "RELEASED"
    POSTED = "POSTED"
    NO_SCORE = "NO_SCORE"
    VOID = "VOID"


class AccommodationType(str, Enum):
    NONE = "NONE"
    EXTENDED_TIME = "EXTENDED_TIME"
    SEPARATE_ROOM = "SEPARATE_ROOM"


class ExamOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    RECONCILED = "RECONCILED"


class ExamSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ADMINISTERED = "ADMINISTERED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


class ProctorAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class IrregularityCategory(str, Enum):
    SECURITY_BREACH = "SECURITY_BREACH"
    TIMING_ERROR = "TIMING_ERROR"
    ACCOMMODATION_VIOLATION = "ACCOMMODATION_VIOLATION"
    MISCONDUCT = "MISCONDUCT"
    MATERIALS = "MATERIALS"


class IrregularityReportStatus(str, Enum):
    FILED = "FILED"
    RESOLVED = "RESOLVED"
    SCORES_CANCELLED = "SCORES_CANCELLED"


# All resources carry the common system-managed properties of PRD §2.5:
# id, created_at, updated_at, version.


class ExamCycle(TypedDict):
    id: str
    name: str
    status: str
    registration_deadline_at: str
    order_deadline_at: str
    score_release_at: str
    exam_window_start_at: str
    exam_window_end_at: str
    late_fee_cents: int
    unused_exam_penalty_cents: int
    fee_reduction_cents: int
    budget_cap_cents: int
    rebate_rate_bp: int
    registered_exam_count: int
    rebate_cents: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    cycle_id: str
    subject_code: str
    program: str
    exam_fee_cents: int
    credit_threshold: int
    status: str
    authorized_teacher_count: int
    registered_count: int
    created_at: str
    updated_at: str
    version: int


class Teacher(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class TeacherAuthorization(TypedDict):
    id: str
    teacher_id: str
    course_id: str
    status: str
    training_completed_at: Optional[str]
    authorized_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    grade_level: int
    subgroup_code: str
    balance_cents: int
    projected_balance_cents: int
    transcript_posted_count: int
    created_at: str
    updated_at: str
    version: int


class FeeReductionApplication(TypedDict):
    id: str
    student_id: str
    cycle_id: str
    eligibility_basis: str
    annual_income_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExamRegistration(TypedDict):
    id: str
    student_id: str
    course_id: str
    cycle_id: str
    accommodation_type: str
    registration_status: str
    score_status: str
    score: Optional[int]
    is_late: bool
    fee_cents: int
    late_fee_applied_cents: int
    subsidy_cents: int
    net_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ExamOrderLine(TypedDict):
    course_id: str
    ordered_count: int
    fee_cents: int
    late_fee_total_cents: int
    line_total_cents: int


class ExamOrderAdjustment(TypedDict):
    course_id: str
    delta: int


class ExamOrder(TypedDict):
    id: str
    cycle_id: str
    status: str
    adjustments: List[ExamOrderAdjustment]
    lines: List[ExamOrderLine]
    estimate_total_cents: int
    final_total_cents: Optional[int]
    submitted_late: Optional[bool]
    submitted_at: Optional[str]
    locked_at: Optional[str]
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamSession(TypedDict):
    id: str
    course_id: str
    room_name: str
    room_capacity: int
    room_supports_accommodations: bool
    start_at: str
    end_at: str
    status: str
    seats_reserved: int
    created_at: str
    updated_at: str
    version: int


class ProctorAssignment(TypedDict):
    id: str
    session_id: str
    teacher_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IrregularityReport(TypedDict):
    id: str
    session_id: str
    proctor_teacher_id: str
    category: str
    details: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StudentStatement(TypedDict):
    student_id: str
    balance_cents: int
    projected_balance_cents: int
    transcript_posted_count: int
