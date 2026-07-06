"""Domain types: entity TypedDicts, status enums, role enum.

All amounts are integer cents. Every entity in this domain carries the common
fields id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    CFO = "CFO"
    BOOKKEEPER = "Bookkeeper"
    CLIENT_CONTACT = "ClientContact"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status enums ---
class ClientOnboardingStatus(str, Enum):
    LEAD = "LEAD"
    KICKOFF_SCHEDULED = "KICKOFF_SCHEDULED"
    LEDGER_SETUP = "LEDGER_SETUP"
    ONBOARDED = "ONBOARDED"


class ClientEngagementStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    OFFBOARDED = "OFFBOARDED"


class RetainerTier(str, Enum):
    ESSENTIALS = "ESSENTIALS"
    GROWTH = "GROWTH"
    CFO = "CFO"


class LedgerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class LedgerAccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class CatchupProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SCOPED = "SCOPED"
    IN_PROGRESS = "IN_PROGRESS"
    CLIENT_REVIEW = "CLIENT_REVIEW"
    REVISION = "REVISION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MonthlyCloseStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    FINALIZED = "FINALIZED"
    REOPENED = "REOPENED"


class MonthlyCloseReviewStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class CloseTaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"
    WAIVED = "WAIVED"
    BLOCKED = "BLOCKED"


class ARInvoiceStatus(str, Enum):
    OPEN = "OPEN"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class APBillStatus(str, Enum):
    ENTERED = "ENTERED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    VOID = "VOID"


class PayrollRunStatus(str, Enum):
    DRAFT = "DRAFT"
    ALLOCATED = "ALLOCATED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class CashFlowForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ForecastDirection(str, Enum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class TaxHandoffStatus(str, Enum):
    PREPARING = "PREPARING"
    BOOKS_REVIEW = "BOOKS_REVIEW"
    ADVISORY_REVIEW = "ADVISORY_REVIEW"
    READY = "READY"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class RetainerInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# --- Entity TypedDicts (all common_fields: true) ---
class Client(TypedDict):
    id: str
    legal_name: str
    state_code: str
    retainer_tier: str
    onboarding_status: str
    engagement_status: str
    included_txn_count: int
    catchup_active: bool
    covenant_floor_cents: int
    open_close_count: int
    created_at: str
    updated_at: str
    version: int


class LedgerAccount(TypedDict):
    id: str
    client_id: str
    parent_account_id: Optional[str]
    account_code: str
    account_type: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CatchupProject(TypedDict):
    id: str
    client_id: str
    months_behind: int
    status: str
    revision_rounds: int
    quoted_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class MonthlyClose(TypedDict):
    id: str
    client_id: str
    period_year: int
    period_month: int
    status: str
    review_status: str
    txn_count: int
    completion_pct: float
    provisional_completion_pct: float
    created_at: str
    updated_at: str
    version: int


class CloseTask(TypedDict):
    id: str
    monthly_close_id: str
    name: str
    weight: int
    status: str
    blocking_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ARInvoice(TypedDict):
    id: str
    client_id: str
    counterparty_name: str
    amount_cents: int
    issue_date: str
    due_date: str
    status: str
    paid_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class APBill(TypedDict):
    id: str
    client_id: str
    vendor_name: str
    amount_cents: int
    due_date: str
    status: str
    scheduled_pay_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollRun(TypedDict):
    id: str
    client_id: str
    monthly_close_id: str
    pay_date: str
    pay_period_start: str
    pay_period_end: str
    total_employer_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayrollAllocation(TypedDict):
    id: str
    payroll_run_id: str
    department_name: str
    dept_gross_cents: int
    allocated_cents: int
    created_at: str
    updated_at: str
    version: int


class CashFlowForecast(TypedDict):
    id: str
    client_id: str
    opening_balance_cents: int
    status: str
    ending_balance_cents: int
    min_projected_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ForecastLine(TypedDict):
    id: str
    forecast_id: str
    effective_date: str
    direction: str
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class TaxHandoff(TypedDict):
    id: str
    client_id: str
    tax_year: int
    status: str
    books_signoff: bool
    advisory_signoff: bool
    created_at: str
    updated_at: str
    version: int


class RetainerInvoice(TypedDict):
    id: str
    client_id: str
    monthly_close_id: str
    base_fee_cents: int
    overage_cents: int
    surcharge_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
