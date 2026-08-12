"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class FunderType(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    FOUNDATION = "FOUNDATION"
    CORPORATE = "CORPORATE"


class GrantStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSEOUT = "CLOSEOUT"
    CLOSED = "CLOSED"


class ReportingFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMIANNUAL = "SEMIANNUAL"
    ANNUAL = "ANNUAL"


class BudgetLineCategory(str, Enum):
    PERSONNEL = "PERSONNEL"
    FRINGE = "FRINGE"
    TRAVEL = "TRAVEL"
    EQUIPMENT = "EQUIPMENT"
    SUPPLIES = "SUPPLIES"
    CONTRACTUAL = "CONTRACTUAL"
    INDIRECT = "INDIRECT"
    OTHER = "OTHER"


class FundType(str, Enum):
    RESTRICTED = "RESTRICTED"
    UNRESTRICTED = "UNRESTRICTED"


class ExpenseStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ExpenseAllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ReportStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class ReportPeriodType(str, Enum):
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class VarianceExplanationStatus(str, Enum):
    DRAFTED = "DRAFTED"
    LOCKED = "LOCKED"
    SUBMITTED = "SUBMITTED"


class ContributionType(str, Enum):
    CASH = "CASH"
    IN_KIND_GOODS = "IN_KIND_GOODS"
    IN_KIND_SERVICES = "IN_KIND_SERVICES"
    VOLUNTEER_TIME = "VOLUNTEER_TIME"


class ValuationBasis(str, Enum):
    FAIR_MARKET = "FAIR_MARKET"
    ACTUAL_COST = "ACTUAL_COST"
    STANDARD_RATE = "STANDARD_RATE"


class MatchContributionStatus(str, Enum):
    PLEDGED = "PLEDGED"
    DOCUMENTED = "DOCUMENTED"
    VERIFIED = "VERIFIED"


class ModificationRequestType(str, Enum):
    NO_COST_EXTENSION = "NO_COST_EXTENSION"
    BUDGET_REALLOCATION = "BUDGET_REALLOCATION"


class ModificationRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class EngagementType(str, Enum):
    FINANCIAL_AUDIT = "FINANCIAL_AUDIT"
    SITE_VISIT = "SITE_VISIT"
    DESK_REVIEW = "DESK_REVIEW"


class AuditEngagementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PREPARATION = "PREPARATION"
    READY = "READY"
    CONDUCTED = "CONDUCTED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class FindingSeverity(str, Enum):
    OBSERVATION = "OBSERVATION"
    DEFICIENCY = "DEFICIENCY"
    MATERIAL_WEAKNESS = "MATERIAL_WEAKNESS"


class AuditFindingStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    RESOLVED = "RESOLVED"


class RenewalApplicationStatus(str, Enum):
    NOT_OPEN = "NOT_OPEN"
    ELIGIBLE = "ELIGIBLE"
    SUBMITTED = "SUBMITTED"
    RENEWED = "RENEWED"
    DECLINED = "DECLINED"
    LAPSED = "LAPSED"


class RenewalDecision(str, Enum):
    RENEWED = "RENEWED"
    DECLINED = "DECLINED"


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    GRANTS_OFFICER = "GrantsOfficer"
    FINANCE_MANAGER = "FinanceManager"
    PROGRAM_DIRECTOR = "ProgramDirector"
    FUNDER = "Funder"
    AUDITOR = "Auditor"


# All entities carry the common system-managed fields of PRD §2.4:
# id, created_at, updated_at, version.


class Funder(TypedDict, total=False):
    id: str
    name: str
    funder_type: str
    contact_email: str
    requires_match: bool
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict, total=False):
    id: str
    funder_id: str
    award_number: str
    title: str
    award_amount_cents: int
    start_date: str
    end_date: str
    original_end_date: str
    reporting_frequency: str
    interim_report_due_days: int
    final_report_due_days: int
    variance_threshold_pct: float
    indirect_rate_pct: float
    indirect_cap_cents: Optional[int]
    renewal_window_days: int
    required_match_cents: int
    status: str
    total_expended_cents: int
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict, total=False):
    id: str
    grant_id: str
    category: str
    budgeted_cents: int
    adjusted_cents: int
    expended_cents: int
    period_budgets_cents: List[int]
    created_at: str
    updated_at: str
    version: int


class Fund(TypedDict, total=False):
    id: str
    grant_id: str
    fund_type: str
    purpose_restriction: Optional[str]
    allowed_categories: List[str]
    allocated_cents: int
    expended_cents: int
    remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class Expense(TypedDict, total=False):
    id: str
    grant_id: str
    expense_date: str
    vendor: str
    description: str
    amount_cents: int
    status: str
    unallocated_cents: int
    created_by_user_id: str
    posted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpenseAllocation(TypedDict, total=False):
    id: str
    expense_id: str
    budget_line_id: str
    fund_id: str
    amount_cents: int
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class OutcomeEntry(TypedDict, total=False):
    metric_name: str
    target_value: float
    actual_value: float
    unit: str


class Report(TypedDict, total=False):
    id: str
    grant_id: str
    period_index: int
    period_type: str
    period_start: str
    period_end: str
    due_date: str
    status: str
    narrative_draft: str
    outcome_entries: List[OutcomeEntry]
    frozen: bool
    revision_count: int
    submitted_at: Optional[str]
    submitted_late: bool
    prepared_by_user_id: Optional[str]
    returned_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VarianceExplanation(TypedDict, total=False):
    id: str
    report_id: str
    budget_line_id: str
    explanation_text: str
    period_variance_pct_snapshot: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MatchContribution(TypedDict, total=False):
    id: str
    grant_id: str
    source_name: str
    contribution_type: str
    valuation_basis: str
    documented_value_cents: int
    volunteer_hours: float
    recognized_value_cents: int
    status: str
    documented_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineDelta(TypedDict):
    budget_line_id: str
    delta_cents: int


class ModificationRequest(TypedDict, total=False):
    id: str
    grant_id: str
    request_type: str
    justification: str
    requested_end_date: Optional[str]
    line_deltas: List[LineDelta]
    status: str
    created_by_user_id: str
    submitted_by_user_id: Optional[str]
    decided_by_funder_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEngagement(TypedDict, total=False):
    id: str
    grant_id: str
    engagement_type: str
    auditor_org: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    engagement_id: str
    severity: str
    description: str
    status: str
    response_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalApplication(TypedDict, total=False):
    id: str
    grant_id: str
    window_open: str
    window_close: str
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BvaRow(TypedDict, total=False):
    budget_line_id: str
    category: str
    period_index: int
    period_actual_cents: int
    period_budget_cents: int
    period_variance_pct: Optional[float]
    cumulative_actual_cents: int
    cumulative_budget_cents: int
    cumulative_variance_pct: Optional[float]


class GrantSummary(TypedDict, total=False):
    grant_id: str
    status: str
    total_expended_cents: int
    indirect_pool_cents: int
    match_verified_only_cents: int
    match_pledged_inclusive_cents: int
    match_verified_only_pct: Optional[float]
    match_pledged_inclusive_pct: Optional[float]
    burn_trailing_cents: int
    burn_cumulative_cents: int
    pacing_ratio: Optional[float]
    bva: List[BvaRow]
