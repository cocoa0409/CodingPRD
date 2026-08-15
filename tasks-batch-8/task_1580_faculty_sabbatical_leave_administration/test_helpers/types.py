"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class DepartmentPosture(str, Enum):
    OPEN = "OPEN"
    CONSTRAINED = "CONSTRAINED"
    FROZEN = "FROZEN"


class FacultyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    SEPARATED = "SEPARATED"


class AcademicRank(str, Enum):
    ASSISTANT_PROFESSOR = "ASSISTANT_PROFESSOR"
    ASSOCIATE_PROFESSOR = "ASSOCIATE_PROFESSOR"
    FULL_PROFESSOR = "FULL_PROFESSOR"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ALLOCATED = "ALLOCATED"
    FINALIZED = "FINALIZED"


class LeaveType(str, Enum):
    SABBATICAL = "SABBATICAL"
    MEDICAL = "MEDICAL"
    PERSONAL = "PERSONAL"
    PROFESSIONAL = "PROFESSIONAL"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    AWARDED = "AWARDED"
    NOT_AWARDED = "NOT_AWARDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    RESCINDED = "RESCINDED"


class FundingStatus(str, Enum):
    NONE = "NONE"
    COVERAGE_SUBMITTED = "COVERAGE_SUBMITTED"
    COVERAGE_APPROVED = "COVERAGE_APPROVED"
    COVERAGE_CONFIRMED = "COVERAGE_CONFIRMED"
    COVERAGE_SETTLED = "COVERAGE_SETTLED"
    COVERAGE_RELEASED = "COVERAGE_RELEASED"


class AwardOutcome(str, Enum):
    AWARDED = "AWARDED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    INCOMPLETE_REVIEWS = "INCOMPLETE_REVIEWS"
    NO_APPROVED_COVERAGE = "NO_APPROVED_COVERAGE"
    INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SUPERSEDED = "SUPERSEDED"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"


class GrantStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CURTAILED = "CURTAILED"
    CANCELLED = "CANCELLED"


class FellowshipStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    APPLIED = "APPLIED"
    DECLINED = "DECLINED"


class ObligationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"
    BREACHED = "BREACHED"


class RepaymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class ReportStatus(str, Enum):
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REVISION_REQUIRED = "REVISION_REQUIRED"


class LedgerEntryType(str, Enum):
    EARN = "EARN"
    CONSUME = "CONSUME"
    RESTORE = "RESTORE"
    ADJUST = "ADJUST"


class UserRole(str, Enum):
    FACULTY = "Faculty"
    COMMITTEE_MEMBER = "CommitteeMember"
    DEPARTMENT_CHAIR = "DepartmentChair"
    PROVOST_OFFICE = "ProvostOffice"
    LEAVE_ADMINISTRATOR = "LeaveAdministrator"


class Department(TypedDict, total=False):
    id: str
    name: str
    chair_faculty_id: Optional[str]
    replacement_pool: float
    reserved_amount: float
    spent_amount: float
    available_amount: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class FacultyMember(TypedDict, total=False):
    id: str
    employee_number: str
    full_name: str
    department_id: str
    academic_rank: str
    hire_date: str
    annual_base_salary: float
    status: str
    lifetime_service_months: int
    credit_balance: int
    last_accrued_month: str
    created_at: str
    updated_at: str
    version: int


class LeaveCycle(TypedDict, total=False):
    id: str
    name: str
    academic_year: str
    award_quota: int
    status: str
    awarded_count: int
    created_at: str
    updated_at: str
    version: int


class LeaveApplication(TypedDict, total=False):
    id: str
    applicant_faculty_id: str
    cycle_id: Optional[str]
    leave_type: str
    requested_duration_semesters: int
    requested_salary_pct: int
    proposed_start_date: str
    proposed_end_date: str
    proposal_text: Optional[str]
    status: str
    funding_status: str
    composite_score: Optional[float]
    submitted_review_count: int
    quorum_met: bool
    final_rank: Optional[int]
    award_outcome: Optional[str]
    current_coverage_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeReview(TypedDict, total=False):
    id: str
    application_id: str
    reviewer_faculty_id: str
    scholarly_merit: float
    curriculum_benefit: float
    feasibility: float
    comments: Optional[str]
    weighted_total: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CoveragePlan(TypedDict, total=False):
    id: str
    application_id: str
    department_id: str
    supersedes_plan_id: Optional[str]
    courses_to_cover: int
    provisional_cost: float
    final_cost: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaveGrant(TypedDict, total=False):
    id: str
    application_id: str
    faculty_id: str
    leave_type: str
    start_date: str
    end_date: str
    duration_semesters: int
    salary_pct: int
    gross_salary: Optional[float]
    fellowship_offset_total: Optional[float]
    net_salary: Optional[float]
    actual_months: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExternalFellowship(TypedDict, total=False):
    id: str
    faculty_id: str
    application_id: str
    name: str
    amount: float
    window_start_date: str
    window_end_date: str
    applied_offset: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceObligation(TypedDict, total=False):
    id: str
    faculty_id: str
    grant_id: str
    required_months: int
    fulfilled_months: int
    last_credited_month: str
    projected_liability: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RepaymentObligation(TypedDict, total=False):
    id: str
    obligation_id: str
    faculty_id: str
    base_amount: float
    fulfilled_months_at_breach: int
    monthly_forgiveness: float
    amount_owed: float
    amount_outstanding: float
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD: payments carry only id + created_at; no updated_at, no version)
class RepaymentPayment(TypedDict, total=False):
    id: str
    repayment_id: str
    amount: float
    resulting_outstanding: float
    created_at: str


class AccomplishmentReport(TypedDict, total=False):
    id: str
    grant_id: str
    faculty_id: str
    due_date: str
    report_text: Optional[str]
    submitted_at: Optional[str]
    submitted_late: bool
    decision_comments: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD: ledger entries carry only id + created_at; no updated_at, no version)
class AccrualLedgerEntry(TypedDict, total=False):
    id: str
    faculty_id: str
    entry_type: str
    credits_delta: int
    affects_lifetime: bool
    month: Optional[str]
    note: Optional[str]
    created_at: str
