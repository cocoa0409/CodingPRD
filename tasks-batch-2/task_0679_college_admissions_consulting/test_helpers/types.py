"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exact PRD field names. Entities that are append-only
permanent records (BillingEntry, EssayVersion) carry only id + created_at;
all other entities carry id + created_at + updated_at + version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    COUNSELOR = "Counselor"
    STUDENT = "Student"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class StudentIntakeStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ONBOARDED = "ONBOARDED"
    ACTIVE = "ACTIVE"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    VOID = "VOID"


class BillingModel(str, Enum):
    PACKAGE = "PACKAGE"
    HOURLY = "HOURLY"


class EntryType(str, Enum):
    CHARGE = "CHARGE"
    CREDIT = "CREDIT"


class SourceKind(str, Enum):
    TASK = "TASK"
    APPOINTMENT = "APPOINTMENT"
    ESSAY = "ESSAY"
    MANUAL = "MANUAL"


class SchoolRound(str, Enum):
    ED = "ED"
    EA = "EA"
    RD = "RD"
    NONE = "NONE"


class SchoolClassification(str, Enum):
    REACH = "REACH"
    TARGET = "TARGET"
    SAFETY = "SAFETY"


class SchoolListItemStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    SELECTED = "SELECTED"
    DROPPED = "DROPPED"


class ApplicationRound(str, Enum):
    ED = "ED"
    EA = "EA"
    RD = "RD"


class PrepStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    SUBMITTED = "SUBMITTED"


class DecisionStatus(str, Enum):
    PENDING = "PENDING"
    ADMITTED = "ADMITTED"
    DENIED = "DENIED"
    WAITLISTED = "WAITLISTED"
    DEFERRED = "DEFERRED"
    APPEALING = "APPEALING"


class TaskType(str, Enum):
    ESSAY = "ESSAY"
    RECOMMENDATION = "RECOMMENDATION"
    FORM = "FORM"
    FEE = "FEE"
    TRANSCRIPT = "TRANSCRIPT"


class TaskStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    WAIVED = "WAIVED"


class EssayStatus(str, Enum):
    DRAFTING = "DRAFTING"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    ABANDONED = "ABANDONED"


class SubmittedByRole(str, Enum):
    STUDENT = "Student"
    COUNSELOR = "Counselor"


class RecType(str, Enum):
    TEACHER = "TEACHER"
    COUNSELOR = "COUNSELOR"
    OTHER = "OTHER"


class RecommendationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    SUBMITTED = "SUBMITTED"
    DECLINED = "DECLINED"


class ActivityCategory(str, Enum):
    ACADEMIC = "ACADEMIC"
    ATHLETIC = "ATHLETIC"
    ARTS = "ARTS"
    SERVICE = "SERVICE"
    WORK = "WORK"
    LEADERSHIP = "LEADERSHIP"


class AwardType(str, Enum):
    MERIT = "MERIT"
    NEED = "NEED"
    EXTERNAL = "EXTERNAL"


class AwardStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class MeetingType(str, Enum):
    STRATEGY = "STRATEGY"
    ESSAY_REVIEW = "ESSAY_REVIEW"
    CHECK_IN = "CHECK_IN"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Entity TypedDicts — full-field entities (id + created_at + updated_at + version)
# --------------------------------------------------------------------------
class Counselor(TypedDict):
    id: str
    full_name: str
    email: str
    hourly_rate_cents: int
    weekly_review_capacity: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    counselor_id: str
    full_name: str
    email: str
    grad_year: int
    gpa: float
    sat_total: int
    intake_status: str
    profile_strength: float
    list_locked: bool
    created_at: str
    updated_at: str
    version: int


class EngagementContract(TypedDict):
    id: str
    student_id: str
    counselor_id: str
    billing_model: str
    package_fee_cents: int
    package_milestones: int
    hourly_rate_cents: int
    retainer_deposit_cents: int
    coverage_start_utc: str
    coverage_end_utc: str
    status: str
    charged_cents: float
    credited_cents: float
    retainer_balance_cents: float
    projected_balance_cents: float
    created_at: str
    updated_at: str
    version: int


class SchoolListItem(TypedDict):
    id: str
    student_id: str
    school_name: str
    admit_rate: float
    median_sat: int
    round: str
    admit_probability: float
    classification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    student_id: str
    school_list_item_id: str
    round: str
    deadline_utc: str
    prep_status: str
    decision_status: str
    open_task_count: int
    created_at: str
    updated_at: str
    version: int


class ApplicationTask(TypedDict):
    id: str
    application_id: str
    title: str
    task_type: str
    due_utc: str
    estimated_cost_cents: int
    blocks_submission: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Essay(TypedDict):
    id: str
    student_id: str
    application_id: Optional[str]
    prompt: str
    word_limit: int
    status: str
    revision_round: int
    latest_version_no: int
    created_at: str
    updated_at: str
    version: int


class RecommendationRequest(TypedDict):
    id: str
    student_id: str
    recommender_name: str
    recommender_email: str
    rec_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ActivityEntry(TypedDict):
    id: str
    student_id: str
    title: str
    category: str
    hours_per_week: int
    weeks_per_year: int
    tier: int
    created_at: str
    updated_at: str
    version: int


class ScholarshipAward(TypedDict):
    id: str
    student_id: str
    application_id: Optional[str]
    award_name: str
    award_type: str
    gross_amount_cents: int
    net_amount_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    student_id: str
    counselor_id: str
    start_utc: str
    end_utc: str
    meeting_type: str
    status: str
    billed_minutes: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only entities — carry ONLY id + created_at (no updated_at, no version)
# --------------------------------------------------------------------------
class BillingEntry(TypedDict):
    id: str
    contract_id: str
    entry_type: str
    source_kind: str
    source_id: Optional[str]
    amount_cents: int
    minutes: int
    memo: str
    created_at: str


class EssayVersion(TypedDict):
    id: str
    essay_id: str
    version_no: int
    word_count: int
    body: str
    submitted_by_role: str
    created_at: str
