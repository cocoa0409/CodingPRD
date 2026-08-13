"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    TEACHER = "Teacher"
    BUILDING_ADMIN = "BuildingAdmin"
    INSTRUCTOR = "Instructor"
    PD_COORDINATOR = "PDCoordinator"
    BUSINESS_OFFICER = "BusinessOfficer"
    AUDITOR = "Auditor"


class BuildingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class EmployeeKind(str, Enum):
    TEACHER = "TEACHER"
    ADMIN = "ADMIN"
    SPECIALIST = "SPECIALIST"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    SEPARATED = "SEPARATED"


class Lane(str, Enum):
    BA = "BA"
    BA15 = "BA15"
    MA = "MA"
    MA15 = "MA15"
    MA30 = "MA30"
    DOC = "DOC"


class ComplianceStanding(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class BudgetStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DeliveryMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"
    HYBRID = "HYBRID"


class CourseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SectionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"


class AttendanceStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    ABSENT = "ABSENT"


class SurveyStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    WAIVED = "WAIVED"


class AttendanceMark(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"


class TranscriptSourceType(str, Enum):
    COURSE_COMPLETION = "COURSE_COMPLETION"
    EXTERNAL_WORKSHOP = "EXTERNAL_WORKSHOP"
    AUDIT_REVERSAL = "AUDIT_REVERSAL"


class TranscriptEntryStatus(str, Enum):
    AWARDED = "AWARDED"
    REVERSED = "REVERSED"


class WorkshopStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ATTENDED = "ATTENDED"
    REIMBURSED = "REIMBURSED"
    REIMBURSEMENT_DENIED = "REIMBURSEMENT_DENIED"
    EXPIRED = "EXPIRED"


class GrowthPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SATISFIED = "SATISFIED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    WAIVED = "WAIVED"


class AuditCaseStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_RAISED = "FINDINGS_RAISED"
    RESOLVED = "RESOLVED"
    CLOSED_CLEAN = "CLOSED_CLEAN"


# --- Entity TypedDicts ---
# All primary resources carry id/created_at/updated_at/version (PRD §2.5),
# except SurveyResponse which is immutable and carries only id + created_at.

class Building(TypedDict, total=False):
    id: str
    name: str
    building_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    employee_kind: str
    primary_building_id: str
    base_lane: str
    current_lane: str
    status: str
    lane_credit_balance: float
    last_advancement_fiscal_year: Optional[int]
    compliance_standing: str
    created_at: str
    updated_at: str
    version: int


class BuildingBudget(TypedDict, total=False):
    id: str
    building_id: str
    fiscal_year: int
    allocated_cents: int
    status: str
    encumbered_cents: int
    spent_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict, total=False):
    id: str
    course_code: str
    title: str
    delivery_mode: str
    clock_hours: float
    fee_cents: int
    compliance_tag: Optional[str]
    recurrence_months: Optional[int]
    prerequisite_course_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Section(TypedDict, total=False):
    id: str
    course_id: str
    term: str
    instructor_id: str
    building_id: str
    room: str
    seat_capacity: int
    fee_cents: int
    starts_at: str
    ends_at: str
    registration_opens_at: str
    registration_closes_at: str
    status: str
    seats_registered: int
    seats_open: int
    created_at: str
    updated_at: str
    version: int


class SectionMeeting(TypedDict, total=False):
    id: str
    section_id: str
    starts_at: str
    ends_at: str
    room: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    teacher_id: str
    section_id: str
    growth_plan_id: Optional[str]
    aligned_focus_area: Optional[str]
    status: str
    attendance_status: str
    survey_status: str
    waitlist_seq: Optional[int]
    encumbered_cents: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict, total=False):
    id: str
    registration_id: str
    meeting_id: str
    mark: str
    recorded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class SurveyResponse(TypedDict, total=False):
    # Immutable once submitted: only id + created_at (PRD §2.5). No updated_at/version.
    id: str
    registration_id: str
    overall_rating: int
    would_recommend: bool
    comments: Optional[str]
    submitted_at: str
    created_at: str


class TranscriptEntry(TypedDict, total=False):
    id: str
    employee_id: str
    source_type: str
    source_id: str
    growth_plan_id: Optional[str]
    fiscal_year: int
    clock_hours: float
    district_credit: float
    state_ceu: float
    counts_toward_lane: bool
    status: str
    awarded_at: str
    reversed_by_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExternalWorkshopRequest(TypedDict, total=False):
    id: str
    teacher_id: str
    building_id: str
    title: str
    provider: str
    starts_at: str
    ends_at: str
    est_cost_cents: int
    clock_hours_claimed: float
    growth_plan_id: Optional[str]
    status: str
    revision_count: int
    reject_reason: Optional[str]
    approved_by_user_id: Optional[str]
    actual_hours: Optional[float]
    receipt_cents: Optional[int]
    reimbursed_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class GrowthPlan(TypedDict, total=False):
    id: str
    teacher_id: str
    school_year: str
    focus_areas: List[str]
    target_credits: float
    status: str
    aligned_credits: float
    created_at: str
    updated_at: str
    version: int


class ComplianceAssignment(TypedDict, total=False):
    id: str
    employee_id: str
    course_id: str
    due_date: str
    status: str
    assigned_by_user_id: str
    satisfied_at: Optional[str]
    extension_count: int
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    employee_id: str
    fiscal_year: int
    status: str
    findings_count: int
    opened_by_user_id: str
    created_at: str
    updated_at: str
    version: int
