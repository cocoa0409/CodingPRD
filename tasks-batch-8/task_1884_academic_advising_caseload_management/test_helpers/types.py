"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ADVISING_DIRECTOR = "AdvisingDirector"
    ADVISOR = "Advisor"
    FRONT_DESK_STAFF = "FrontDeskStaff"
    FACULTY_REFERRER = "FacultyReferrer"


class AdvisorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CareStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AdvisingRequirementStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    SATISFIED = "SATISFIED"


class RegistrationClearance(str, Enum):
    BLOCKED = "BLOCKED"
    CLEARED = "CLEARED"


class AssignmentMode(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class EndedReason(str, Enum):
    SUPERSEDED = "SUPERSEDED"
    MANUAL_END = "MANUAL_END"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class TicketStatus(str, Enum):
    QUEUED = "QUEUED"
    CALLED = "CALLED"
    SERVED = "SERVED"
    LEFT = "LEFT"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    OUTREACH_IN_PROGRESS = "OUTREACH_IN_PROGRESS"
    NO_RESPONSE = "NO_RESPONSE"
    RESPONDED = "RESPONDED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class ReferralSource(str, Enum):
    FACULTY = "FACULTY"
    STAFF = "STAFF"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OutreachOutcome(str, Enum):
    NO_ANSWER = "NO_ANSWER"
    REACHED = "REACHED"


class InterventionType(str, Enum):
    ACADEMIC_COACHING = "ACADEMIC_COACHING"
    TUTORING_REFERRAL = "TUTORING_REFERRAL"
    COUNSELING_REFERRAL = "COUNSELING_REFERRAL"
    FINANCIAL_AID_REFERRAL = "FINANCIAL_AID_REFERRAL"


class InterventionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class InterventionOutcome(str, Enum):
    SUCCESSFUL = "SUCCESSFUL"
    UNSUCCESSFUL = "UNSUCCESSFUL"


class HoldType(str, Enum):
    ADVISING = "ADVISING"
    FINANCIAL = "FINANCIAL"
    ACADEMIC_STANDING = "ACADEMIC_STANDING"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class NoteVisibility(str, Enum):
    SHARED = "SHARED"
    CONFIDENTIAL = "CONFIDENTIAL"


class RankingMode(str, Enum):
    WEIGHTED = "WEIGHTED"
    HEADCOUNT = "HEADCOUNT"


class RetentionVariant(str, Enum):
    COHORT_PERSISTED = "COHORT_PERSISTED"
    TERM_OVER_TERM = "TERM_OVER_TERM"


# All resources carry the common fields id, created_at, updated_at, version (PRD §2.5).


class Advisor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    major_codes: List[str]
    max_caseload: int
    status: str
    assigned_active_count: int
    weighted_load: int
    scheduled_minutes: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    major_code: str
    cohort_year: int
    current_term_code: str
    gpa: float
    care_status: str
    advising_required_flag: bool
    enrolled_term_codes: List[str]
    no_show_count: int
    at_risk_score: int
    risk_tier: str
    advising_requirement_status: str
    registration_clearance: str
    created_at: str
    updated_at: str
    version: int


class AdvisorAssignment(TypedDict, total=False):
    id: str
    student_id: str
    advisor_id: str
    assignment_mode: str
    status: str
    ended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    student_id: str
    advisor_id: str
    term_code: str
    scheduled_start_at: str
    scheduled_end_at: str
    duration_minutes: int
    status: str
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DropInTicket(TypedDict, total=False):
    id: str
    student_id: str
    reason: str
    queue_date: str
    position: int
    status: str
    called_by_advisor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EarlyAlertReferral(TypedDict, total=False):
    id: str
    student_id: str
    source: str
    severity: str
    reason: str
    status: str
    attempt_count: int
    due_at: str
    is_sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class Intervention(TypedDict, total=False):
    id: str
    student_id: str
    referral_id: Optional[str]
    intervention_type: str
    note: Optional[str]
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegistrationHold(TypedDict, total=False):
    id: str
    student_id: str
    hold_type: str
    requires_approved_plan: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CourseEntry(TypedDict):
    course_code: str
    credits: float


class TermEntry(TypedDict):
    term_code: str
    courses: List[CourseEntry]


class DegreePlan(TypedDict, total=False):
    id: str
    student_id: str
    catalog_year: int
    required_credits: int
    terms: List[TermEntry]
    mapped_credits_total: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdvisingNote(TypedDict, total=False):
    id: str
    student_id: str
    author_user_id: str
    visibility: str
    body: str
    created_at: str
    updated_at: str
    version: int
