"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Guardian-ad-Litem & CASA PRD (Sections 2-3).
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------- Roles
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    SUPERVISOR = "Supervisor"
    VOLUNTEER = "Volunteer"


# ------------------------------------------------------------------- Statuses
class VolunteerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    SCREENING = "SCREENING"
    TRAINING = "TRAINING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    RESIGNED = "RESIGNED"


class BackgroundStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    EXPIRED = "EXPIRED"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSIGNED = "ASSIGNED"
    UNASSIGNED = "UNASSIGNED"
    CLOSED = "CLOSED"


class CaseOutcome(str, Enum):
    REUNIFICATION = "REUNIFICATION"
    ADOPTION = "ADOPTION"
    GUARDIANSHIP = "GUARDIANSHIP"
    APPEAL = "APPEAL"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class VisitStatus(str, Enum):
    LOGGED = "LOGGED"
    VOIDED = "VOIDED"


class ContactType(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIDEO = "VIDEO"
    PHONE = "PHONE"
    COLLATERAL = "COLLATERAL"


class HearingType(str, Enum):
    STATUS = "STATUS"
    REVIEW = "REVIEW"
    PERMANENCY = "PERMANENCY"
    ADJUDICATION = "ADJUDICATION"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CONTINUED = "CONTINUED"
    CANCELLED = "CANCELLED"


class CourtReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    FILED = "FILED"
    VOIDED = "VOIDED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"


class BackgroundCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    EXPIRED = "EXPIRED"


class CheckType(str, Enum):
    STATE_ONLY = "STATE_ONLY"
    STATE_AND_FEDERAL = "STATE_AND_FEDERAL"


class ExpenseClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# ---------------------------------------------------- Entity shapes (TypedDict)
# Entities with the full common field set carry id/created_at/updated_at/version.
class Volunteer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    home_zip: str
    max_caseload: int
    status: str
    sworn_in_at: Optional[str]
    deactivation_reason: Optional[str]
    training_hours_total: float
    background_status: str
    background_expiry_date: Optional[str]
    active_case_count: int
    created_at: str
    updated_at: str
    version: int


class Supervisor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    child_initials: str
    child_dob: str
    jurisdiction: str
    supervisor_id: str
    status: str
    outcome: Optional[str]
    reimbursement_budget_cents: int
    reimbursement_committed_cents: int
    contact_compliance_pct: float
    audit_compliance_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CaseAssignment(TypedDict, total=False):
    id: str
    case_id: str
    volunteer_id: str
    status: str
    ended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    case_id: str
    volunteer_id: str
    contact_type: str
    contact_start: str
    contact_end: str
    miles: float
    notes: Optional[str]
    status: str
    duration_minutes: float
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict, total=False):
    id: str
    case_id: str
    hearing_type: str
    scheduled_at: str
    status: str
    report_due_date: str
    created_at: str
    updated_at: str
    version: int


class CourtReport(TypedDict, total=False):
    id: str
    case_id: str
    hearing_id: str
    author_volunteer_id: str
    reviewer_supervisor_id: Optional[str]
    content_summary: str
    recommendation: str
    status: str
    submitted_at: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict, total=False):
    id: str
    volunteer_id: str
    check_type: str
    status: str
    cleared_at: Optional[str]
    expiry_date: Optional[str]
    flag_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpenseClaim(TypedDict, total=False):
    id: str
    volunteer_id: str
    case_id: str
    period_month: str
    total_miles: float
    other_expense_cents: int
    status: str
    estimated_reimbursement_cents: int
    final_reimbursement_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Immutable audit entries — id + created_at ONLY (no updated_at, no version).
class ReviewNote(TypedDict, total=False):
    id: str
    report_id: str
    supervisor_id: str
    decision: str
    comments: Optional[str]
    created_at: str


class TrainingRecord(TypedDict, total=False):
    id: str
    volunteer_id: str
    module_name: str
    hours: float
    completed_at: str
    created_at: str
