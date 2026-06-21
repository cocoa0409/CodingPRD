"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    OWNER = "Owner"
    CONTRACTOR = "Contractor"
    ARCHITECT = "Architect"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ProjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUBSTANTIALLY_COMPLETE = "SUBSTANTIALLY_COMPLETE"
    CLOSED = "CLOSED"


class SovLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PayApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class SubcontractorCommitmentStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RfiBallInCourt(str, Enum):
    ARCHITECT = "ARCHITECT"
    CONTRACTOR = "CONTRACTOR"


class RfiStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"


class SubmittalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    APPROVED_AS_NOTED = "APPROVED_AS_NOTED"
    REVISE_AND_RESUBMIT = "REVISE_AND_RESUBMIT"
    CLOSED = "CLOSED"


class WaiverType(str, Enum):
    CONDITIONAL_PROGRESS = "CONDITIONAL_PROGRESS"
    UNCONDITIONAL_PROGRESS = "UNCONDITIONAL_PROGRESS"
    CONDITIONAL_FINAL = "CONDITIONAL_FINAL"
    UNCONDITIONAL_FINAL = "UNCONDITIONAL_FINAL"


class LienWaiverStatus(str, Enum):
    PENDING = "PENDING"
    EFFECTIVE = "EFFECTIVE"
    VOID = "VOID"


class PunchSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class PunchListItemStatus(str, Enum):
    OPEN = "OPEN"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"


class InspectionWindowStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RetentionReleaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Versioned, audit-bearing records carry id, created_at, updated_at, version.
class Project(TypedDict):
    id: str
    name: str
    owner_user_id: str
    original_contract_sum_cents: int
    default_retainage_pct: float
    revised_contract_sum_cents: int
    total_completed_and_stored_cents: int
    retainage_held_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SovLine(TypedDict):
    id: str
    project_id: str
    item_no: str
    description: str
    scheduled_value_cents: int
    retainage_pct: float
    work_completed_to_date_cents: int
    materials_stored_cents: int
    retainage_withheld_to_date_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    co_number: str
    change_order_amount_cents: int
    line_edits: list
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayApplication(TypedDict):
    id: str
    project_id: str
    application_number: int
    period_from: str
    period_to: str
    total_completed_and_stored_cents: int
    total_retainage_cents: int
    current_payment_due_cents: int
    status: str
    submitted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# PayAppLine: common_fields false — immutable billing fact, only id + created_at.
class PayAppLine(TypedDict):
    id: str
    pay_app_id: str
    sov_line_id: str
    work_completed_this_period_cents: int
    materials_stored_cents: int
    work_completed_previous_cents: int
    line_retainage_cents: int
    created_at: str


class SubcontractorCommitment(TypedDict):
    id: str
    project_id: str
    subcontractor_name: str
    committed_amount_cents: int
    invoiced_to_date_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Rfi(TypedDict):
    id: str
    project_id: str
    subject: str
    question: str
    ball_in_court: str
    status: str
    answer: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Submittal(TypedDict):
    id: str
    project_id: str
    spec_section: str
    title: str
    revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LienWaiver(TypedDict):
    id: str
    project_id: str
    pay_app_id: str
    waiver_type: str
    through_date: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchListItem(TypedDict):
    id: str
    project_id: str
    location: str
    description: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionWindow(TypedDict):
    id: str
    project_id: str
    inspector_name: str
    scheduled_start: str
    scheduled_end: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetentionRelease(TypedDict):
    id: str
    project_id: str
    amount_cents: int
    status: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
