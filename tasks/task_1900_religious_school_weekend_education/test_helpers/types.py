"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class SchoolYearStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SecurityPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class MembershipStatus(str, Enum):
    MEMBER = "MEMBER"
    NON_MEMBER = "NON_MEMBER"


class Grade(str, Enum):
    K = "K"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"


class HebrewLevel(str, Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class DayOfWeek(str, Enum):
    SUN = "SUN"
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"


class TeacherStatus(str, Enum):
    APPLIED = "APPLIED"
    VETTED = "VETTED"
    HIRED = "HIRED"
    SEPARATED = "SEPARATED"


class SectionStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class StaffingStatus(str, Enum):
    STAFFED = "STAFFED"
    UNSTAFFED = "UNSTAFFED"


class EnrollmentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceKind(str, Enum):
    TUITION = "TUITION"
    VOLUNTEER_FEE = "VOLUNTEER_FEE"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"
    ACH = "ACH"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AwardMethod(str, Enum):
    PERCENT_OF_NET = "PERCENT_OF_NET"
    FLAT_CAP = "FLAT_CAP"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    CLOSURE = "CLOSURE"
    TEACHER_SEPARATION = "TEACHER_SEPARATION"
    MANUAL = "MANUAL"
    YEAR_CLOSE = "YEAR_CLOSE"


class AttendanceMark(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"


class MilestoneStatus(str, Enum):
    TRACKING = "TRACKING"
    ELIGIBLE = "ELIGIBLE"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class CommitmentStatus(str, Enum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    DEFAULTED = "DEFAULTED"
    WAIVED = "WAIVED"


class UserRole(str, Enum):
    SCHOOL_ADMIN = "SchoolAdmin"
    ASSISTANCE_OFFICER = "AssistanceOfficer"
    TEACHER = "Teacher"
    PARENT = "Parent"


class SchoolYear(TypedDict, total=False):
    id: str
    name: str
    start_date: str
    end_date: str
    member_tuition_cents: int
    non_member_tuition_cents: int
    early_bird_pct: float
    early_bird_deadline: str
    sibling_discount_pcts: List[float]
    activity_fee_cents: int
    volunteer_hours_required: int
    volunteer_buyout_fee_cents: int
    late_fee_pct: float
    late_fee_min_balance_cents: int
    tuition_due_date: str
    withdrawal_deadline: str
    refund_pct_after_deadline: float
    attendance_threshold_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SecurityPlan(TypedDict, total=False):
    id: str
    school_year_id: str
    plan_document: str
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CalendarClosure(TypedDict, total=False):
    id: str
    school_year_id: str
    start_date: str
    end_date: str
    reason: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict, total=False):
    id: str
    family_name: str
    primary_email: str
    membership_status: str
    outstanding_balance_cents: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    family_id: str
    full_name: str
    grade: str
    hebrew_level: str
    created_at: str
    updated_at: str
    version: int


class Teacher(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    background_check_cleared: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Section(TypedDict, total=False):
    id: str
    school_year_id: str
    teacher_id: Optional[str]
    grade: str
    hebrew_level: str
    capacity: int
    room: str
    day_of_week: str
    start_time: str
    end_time: str
    enrolled_count: int
    status: str
    staffing_status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    student_id: str
    section_id: str
    family_id: str
    school_year_id: str
    status: str
    sibling_rank: int
    estimated_tuition_cents: int
    withdrawn_at: Optional[str]
    withdrawal_credit_pct: Optional[float]
    credit_applied: bool
    created_at: str
    updated_at: str
    version: int


class TuitionInvoice(TypedDict, total=False):
    id: str
    family_id: str
    school_year_id: str
    status: str
    kind: str
    line_items: List[dict]
    gross_cents: int
    activity_fee_cents: int
    award_cents: int
    assistance_application_id: Optional[str]
    credit_applied_cents: int
    total_due_cents: int
    paid_cents: int
    late_fees_cents: int
    balance_cents: int
    issued_at: str
    due_date: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    family_id: str
    amount_cents: int
    method: str
    status: str
    applications: List[dict]
    remainder_cents: int
    created_at: str
    updated_at: str
    version: int


class AssistanceApplication(TypedDict, total=False):
    id: str
    family_id: str
    school_year_id: str
    reason: str
    requested_amount_cents: Optional[int]
    status: str
    reviewed_by_user_id: Optional[str]
    award_method: Optional[str]
    award_percent: Optional[float]
    award_amount_cents: Optional[int]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    section_id: str
    session_date: str
    status: str
    cancel_reason: Optional[str]
    attendance: List[dict]
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict, total=False):
    id: str
    student_id: str
    family_id: str
    school_year_id: str
    milestone_name: str
    status: str
    current_attendance_pct: float
    projected_attendance_pct: float
    ceremony_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VolunteerCommitment(TypedDict, total=False):
    id: str
    family_id: str
    school_year_id: str
    required_hours: int
    logged_hours: float
    status: str
    entries: List[dict]
    created_at: str
    updated_at: str
    version: int
