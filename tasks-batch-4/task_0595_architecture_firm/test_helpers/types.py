"""Domain types for the Architecture Firm API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PRINCIPAL_ARCHITECT = "PrincipalArchitect"
    PROJECT_MANAGER = "ProjectManager"
    STAFF_ARCHITECT = "StaffArchitect"
    CONSULTANT_REP = "ConsultantRep"
    CLIENT_REP = "ClientRep"


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class StaffTitle(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    ARCHITECT = "ARCHITECT"
    DESIGNER = "DESIGNER"


class Discipline(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    MEP = "MEP"
    CIVIL = "CIVIL"
    LANDSCAPE = "LANDSCAPE"


class ConsultantFirmStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BudgetPosture(str, Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    OVER_BUDGET = "OVER_BUDGET"


class CaPosture(str, Enum):
    CLEAR = "CLEAR"
    DEFICIENT = "DEFICIENT"


class FeeBasis(str, Enum):
    PERCENT_OF_CONSTRUCTION = "PERCENT_OF_CONSTRUCTION"
    HOURLY = "HOURLY"


class ReviewClockBasis(str, Enum):
    CALENDAR_DAYS = "CALENDAR_DAYS"
    BUSINESS_DAYS = "BUSINESS_DAYS"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class PhaseCode(str, Enum):
    SD = "SD"
    DD = "DD"
    CD = "CD"
    CA = "CA"


class PhaseStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    MISSED = "MISSED"


class DrawingStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class TimeEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExpenseCategory(str, Enum):
    TRAVEL = "TRAVEL"
    PRINTING = "PRINTING"
    PERMIT_FEE = "PERMIT_FEE"
    MODEL = "MODEL"


class ExpenseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    BILLED = "BILLED"


class RfiStatus(str, Enum):
    OPEN = "OPEN"
    RETURNED_FOR_CLARIFICATION = "RETURNED_FOR_CLARIFICATION"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class RfiOrigin(str, Enum):
    CONTRACTOR = "CONTRACTOR"
    FIELD_REPORT = "FIELD_REPORT"


class SubmittalStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISE_AND_RESUBMIT = "REVISE_AND_RESUBMIT"
    APPROVED = "APPROVED"
    APPROVED_AS_NOTED = "APPROVED_AS_NOTED"
    REJECTED = "REJECTED"


class ChangeOrderType(str, Enum):
    ADDITIONAL_SERVICE = "ADDITIONAL_SERVICE"
    SCOPE_REDUCTION = "SCOPE_REDUCTION"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CLIENT_APPROVED = "CLIENT_APPROVED"
    CLIENT_REJECTED = "CLIENT_REJECTED"
    EXECUTED = "EXECUTED"
    VOID = "VOID"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class PermitType(str, Enum):
    BUILDING = "BUILDING"
    ZONING = "ZONING"
    FIRE = "FIRE"


class PermitReviewStatus(str, Enum):
    PREPARING = "PREPARING"
    SUBMITTED = "SUBMITTED"
    COMMENTS_ISSUED = "COMMENTS_ISSUED"
    RESUBMITTED = "RESUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------- #
# Entities carrying id / created_at / updated_at / version
# --------------------------------------------------------------------------- #
class StaffMember(TypedDict):
    id: str
    full_name: str
    title: str
    billing_rate_cents_per_hour: int
    cost_rate_cents_per_hour: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class ConsultantFirm(TypedDict):
    id: str
    name: str
    discipline: str
    concurrent_review_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    project_number: str
    name: str
    client_rep_user_id: str
    project_manager_staff_id: str
    status: str
    labor_budget_cents: int
    labor_cost_cents: int
    approved_hours: float
    budget_posture: str
    open_rfi_count: int
    ca_posture: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    project_id: str
    fee_basis: str
    construction_cost_estimate_cents: int
    fee_rate_bp: int
    not_to_exceed_cents: int
    review_clock_basis: str
    submittal_review_period_days: int
    status: str
    base_fee_cents: int
    total_fee_cents: int
    earned_to_date_cents: int
    billed_fee_to_date_cents: int
    wip_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Phase(TypedDict):
    id: str
    project_id: str
    phase_code: str
    phase_order: int
    weight_bp: int
    status: str
    percent_complete: int
    fee_allocation_cents: int
    earned_cents: int
    milestone_name: str
    milestone_due_at: str
    milestone_status: str
    is_billing_milestone: bool
    created_at: str
    updated_at: str
    version: int


class Drawing(TypedDict):
    id: str
    phase_id: str
    sheet_number: str
    title: str
    revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    phase_id: str
    staff_member_id: str
    start_utc: str
    end_utc: str
    hours: float
    billable: bool
    cost_cents: int
    billable_cents: int
    status: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Expense(TypedDict):
    id: str
    project_id: str
    staff_member_id: str
    category: str
    amount_cents: int
    reimbursable: bool
    markup_bp: int
    billable_cents: int
    status: str
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RFI(TypedDict):
    id: str
    project_id: str
    drawing_id: Optional[str]
    field_report_id: Optional[str]
    rfi_number: int
    subject: str
    origin: str
    impacts_fee: bool
    status: str
    clarification_rounds: int
    answer_text: Optional[str]
    answered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Submittal(TypedDict):
    id: str
    project_id: str
    consultant_firm_id: str
    spec_section: str
    revision_number: int
    status: str
    review_started_at: Optional[str]
    review_due_at: Optional[str]
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    contract_id: str
    title: str
    co_type: str
    fee_delta_cents: int
    source_rfi_number: Optional[int]
    status: str
    submitted_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    contract_id: str
    period_end: str
    status: str
    payment_status: str
    fee_billed_cents: int
    reimbursable_cents: int
    gross_cents: int
    retainage_bp: int
    retainage_cents: int
    net_due_cents: int
    amount_paid_cents: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitReview(TypedDict):
    id: str
    phase_id: str
    jurisdiction_name: str
    permit_type: str
    status: str
    submission_round: int
    comment_count: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Append-only entity: carries ONLY id + created_at (no updated_at, no version)
# --------------------------------------------------------------------------- #
class FieldReport(TypedDict):
    id: str
    project_id: str
    staff_member_id: str
    visit_date: str
    weather: str
    observations: str
    deficiency_count: int
    created_at: str
