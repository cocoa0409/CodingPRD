"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    SPONSORED_PROGRAMS_OFFICER = "SponsoredProgramsOfficer"
    GRANT_COORDINATOR = "GrantCoordinator"
    GRANTS_ACCOUNTANT = "GrantsAccountant"
    SPONSOR_OFFICIAL = "SponsorOfficial"
    PRINCIPAL_INVESTIGATOR = "PrincipalInvestigator"
    RESEARCH_STAFF = "ResearchStaff"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class AwardStatus(str, Enum):
    PENDING_SETUP = "PENDING_SETUP"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSEOUT_PENDING = "CLOSEOUT_PENDING"
    CLOSED = "CLOSED"


class AwardPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ExpenditureStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    POSTED = "POSTED"
    DISALLOWED = "DISALLOWED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class CostTransferStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING_COUNTERSIGN = "PENDING_COUNTERSIGN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class EffortCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CERTIFYING = "CERTIFYING"
    CLOSED = "CLOSED"


class EffortStatementStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    REOPENED = "REOPENED"
    RECERTIFIED = "RECERTIFIED"


class SubawardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SubawardInvoiceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PAID = "PAID"
    REJECTED = "REJECTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"


class ReportStatus(str, Enum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class DrawdownStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SETTLED = "SETTLED"
    REJECTED_BY_SPONSOR = "REJECTED_BY_SPONSOR"
    CANCELLED = "CANCELLED"


class ReceivableStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    D31_60 = "D31_60"
    D61_90 = "D61_90"
    D91_120 = "D91_120"
    OVER_120 = "OVER_120"


class ModificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SPONSOR_REVIEW = "SPONSOR_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class FfrStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class SponsorType(str, Enum):
    FEDERAL = "FEDERAL"
    FEDERAL_FLOW_THROUGH = "FEDERAL_FLOW_THROUGH"
    INDUSTRY = "INDUSTRY"
    FOUNDATION = "FOUNDATION"
    STATE = "STATE"


class PaymentMethod(str, Enum):
    LETTER_OF_CREDIT = "LETTER_OF_CREDIT"
    COST_REIMBURSABLE_INVOICE = "COST_REIMBURSABLE_INVOICE"
    FIXED_PRICE_SCHEDULE = "FIXED_PRICE_SCHEDULE"


class PersonRoleType(str, Enum):
    PRINCIPAL_INVESTIGATOR = "PRINCIPAL_INVESTIGATOR"
    RESEARCH_STAFF = "RESEARCH_STAFF"


class BudgetCategory(str, Enum):
    PERSONNEL_SALARIES = "PERSONNEL_SALARIES"
    FRINGE_BENEFITS = "FRINGE_BENEFITS"
    EQUIPMENT = "EQUIPMENT"
    TRAVEL = "TRAVEL"
    PARTICIPANT_SUPPORT = "PARTICIPANT_SUPPORT"
    MATERIALS_SUPPLIES = "MATERIALS_SUPPLIES"
    SUBAWARDS = "SUBAWARDS"
    OTHER_DIRECT = "OTHER_DIRECT"
    F_AND_A = "F_AND_A"


class ExpenditureType(str, Enum):
    SALARY = "SALARY"
    TRAVEL = "TRAVEL"
    EQUIPMENT = "EQUIPMENT"
    SUPPLIES = "SUPPLIES"
    PARTICIPANT_SUPPORT = "PARTICIPANT_SUPPORT"
    OTHER_DIRECT = "OTHER_DIRECT"
    SUBAWARD_PAYMENT = "SUBAWARD_PAYMENT"


class RiskRating(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReportType(str, Enum):
    ANNUAL_PROGRESS = "ANNUAL_PROGRESS"
    TECHNICAL_QUARTERLY = "TECHNICAL_QUARTERLY"
    MILESTONE = "MILESTONE"
    FINAL_TECHNICAL = "FINAL_TECHNICAL"


class ModType(str, Enum):
    NO_COST_EXTENSION = "NO_COST_EXTENSION"
    REBUDGET = "REBUDGET"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Per PRD §2.4 every resource carries id + created_at +
# updated_at + version, EXCEPT EffortCommitment which carries only
# id + created_at (immutable once recorded).
# ---------------------------------------------------------------------------

class Sponsor(TypedDict, total=False):
    id: str
    name: str
    sponsor_type: str
    payment_method: str
    salary_cap_annual_cents: Optional[int]
    f_and_a_rate_bps: int
    late_payment_apr_bps: int
    created_at: str
    updated_at: str
    version: int


class Person(TypedDict, total=False):
    id: str
    full_name: str
    role_type: str
    institutional_base_salary_annual_cents: int
    appointment_months: int
    created_at: str
    updated_at: str
    version: int


class GrantAward(TypedDict, total=False):
    id: str
    sponsor_id: str
    pi_id: str
    award_number: str
    title: str
    project_start_date: str
    original_end_date: str
    current_end_date: str
    total_obligated_cents: int
    salary_cap_annual_cents: Optional[int]
    f_and_a_rate_bps: int
    payment_method: str
    fringe_rate_bps: int
    cost_share_committed_cents: int
    status: str
    posture: str
    mtdc_spent_cents: int
    f_and_a_accrued_cents: int
    total_direct_spent_cents: int
    cost_share_met_cents: int
    cumulative_drawn_cents: int
    reserved_draw_cents: int
    available_draw_pool_cents: int
    nce_count: int
    residual_deobligated_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict, total=False):
    id: str
    award_id: str
    category: str
    authorized_cents: int
    baseline_authorized_cents: int
    spent_cents: int
    mtdc_eligible_cents: int
    created_at: str
    updated_at: str
    version: int


class EffortCommitment(TypedDict, total=False):
    # PRD §2.4 / §3.2: commitments carry ONLY id and created_at — no
    # updated_at, no version — because a commitment is immutable once recorded.
    id: str
    award_id: str
    person_id: str
    committed_effort_pct: float
    is_key_personnel: bool
    created_at: str


class Expenditure(TypedDict, total=False):
    id: str
    award_id: str
    budget_line_id: str
    person_id: Optional[str]
    transferred_from_id: Optional[str]
    expenditure_type: str
    amount_cents: int
    fringe_cents: int
    over_cap_cents: int
    mtdc_eligible_cents: int
    effort_pct: Optional[float]
    period_months: Optional[float]
    transaction_date: str
    is_cost_share: bool
    cash_disbursed: bool
    is_allocable: bool
    is_reasonable: bool
    is_consistent: bool
    description: Optional[str]
    status: str
    disallow_reason: Optional[str]
    posted_at: Optional[str]
    invoiced_receivable_id: Optional[str]
    submitted_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class CostTransfer(TypedDict, total=False):
    id: str
    source_expenditure_id: str
    target_award_id: str
    target_budget_line_id: str
    justification: str
    enhanced_justification: Optional[str]
    is_retroactive: bool
    days_since_posting: int
    status: str
    created_by_user_id: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    countersigned_by_user_id: Optional[str]
    deny_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EffortCycle(TypedDict, total=False):
    id: str
    cycle_code: str
    period_start: str
    period_end: str
    cycle_months: int
    actual_fringe_rate_bps: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class EffortStatement(TypedDict, total=False):
    id: str
    cycle_id: str
    person_id: str
    award_id: Optional[str]
    statement_kind: str
    committed_effort_pct: float
    charged_effort_pct: float
    certified_effort_pct: Optional[float]
    variance_pp: Optional[float]
    payroll_adjustment_note: Optional[str]
    key_reduction_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Subaward(TypedDict, total=False):
    id: str
    award_id: str
    subrecipient_name: str
    total_subaward_cents: int
    risk_rating: str
    start_date: str
    end_date: str
    status: str
    invoiced_to_date_cents: int
    mtdc_consumed_cents: int
    created_at: str
    updated_at: str
    version: int


class SubawardInvoice(TypedDict, total=False):
    id: str
    subaward_id: str
    invoice_number: str
    period_start: str
    period_end: str
    current_period_direct_cents: int
    current_period_f_and_a_cents: int
    cumulative_direct_cents: int
    mtdc_portion_cents: int
    audit_reference: Optional[str]
    return_reason: Optional[str]
    status: str
    prime_expenditure_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReportRequirement(TypedDict, total=False):
    id: str
    award_id: str
    report_type: str
    due_date: str
    status: str
    submitted_at: Optional[str]
    days_overdue: int
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrawdownRequest(TypedDict, total=False):
    id: str
    award_id: str
    amount_cents: int
    status: str
    eligible_pool_at_submission: Optional[int]
    reject_reason: Optional[str]
    submitted_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Receivable(TypedDict, total=False):
    id: str
    award_id: str
    period_start: str
    period_end: str
    amount_cents: int
    invoice_date: str
    days_outstanding: int
    aging_bucket: str
    accrued_interest_cents: int
    disputed_at: Optional[str]
    total_disputed_days: int
    interest_paid_cents: int
    principal_paid_cents: int
    outstanding_total_cents: int
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModificationRequest(TypedDict, total=False):
    id: str
    award_id: str
    mod_type: str
    extension_months: Optional[int]
    rebudget_lines: Optional[list]
    justification: str
    requires_sponsor: bool
    status: str
    sponsor_decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinalFinancialReport(TypedDict, total=False):
    id: str
    award_id: str
    status: str
    unliquidated_obligations_cents: Optional[int]
    total_expenditures_cents: Optional[int]
    cost_share_shortfall_cents: int
    residual_cents: Optional[int]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
