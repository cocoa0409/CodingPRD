"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ENGAGEMENT_MANAGER = "EngagementManager"
    BOOKKEEPER = "Bookkeeper"
    REVIEWER = "Reviewer"
    TAX_PREPARER = "TaxPreparer"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class EntityType(str, Enum):
    SOLE_PROP = "SOLE_PROP"
    PARTNERSHIP = "PARTNERSHIP"
    S_CORP = "S_CORP"
    C_CORP = "C_CORP"
    LLC = "LLC"


class AccountingBasis(str, Enum):
    CASH = "CASH"
    ACCRUAL = "ACCRUAL"


class WorkflowStatus(str, Enum):
    DRAFT = "DRAFT"
    SCOPING = "SCOPING"
    RECONSTRUCTION = "RECONSTRUCTION"
    RECONCILIATION = "RECONCILIATION"
    TAX_HANDOFF = "TAX_HANDOFF"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    QUOTED = "QUOTED"
    PHASED = "PHASED"
    SETTLED = "SETTLED"


class ReconStatus(str, Enum):
    PENDING = "PENDING"
    IN_BALANCE = "IN_BALANCE"
    OUT_OF_BALANCE = "OUT_OF_BALANCE"


class ComplexityTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ScopeEstimateStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class NormalSide(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerAccountStatus(str, Enum):
    DRAFT = "DRAFT"
    CATEGORIZED = "CATEGORIZED"
    RECONCILED = "RECONCILED"
    EXCLUDED = "EXCLUDED"


class EntrySide(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class BankStatementStatus(str, Enum):
    IMPORTED = "IMPORTED"
    RECONCILING = "RECONCILING"
    RECONCILED = "RECONCILED"


class MatchKind(str, Enum):
    EXACT = "EXACT"
    TOLERANCE = "TOLERANCE"


class ReconciliationItemStatus(str, Enum):
    MATCHED = "MATCHED"
    DISPUTED = "DISPUTED"
    UNMATCHED = "UNMATCHED"


class PhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    BILLABLE = "BILLABLE"
    INVOICED = "INVOICED"
    PAID = "PAID"


class PhaseInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class TaxPackageStatus(str, Enum):
    BUILT = "BUILT"
    HANDED_OFF = "HANDED_OFF"
    AMENDED = "AMENDED"


class ServicePlanStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ExceptionKind(str, Enum):
    MISSING_DOC = "MISSING_DOC"
    UNCATEGORIZED = "UNCATEGORIZED"
    UNRECONCILED_DIFF = "UNRECONCILED_DIFF"
    DUPLICATE = "DUPLICATE"


class ExceptionSeverity(str, Enum):
    NORMAL = "NORMAL"
    BLOCKING = "BLOCKING"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    WAITING_DOCS = "WAITING_DOCS"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


# ---- Entity TypedDicts (all entities carry common_fields: true) ----

class Client(TypedDict):
    id: str
    legal_name: str
    entity_type: str
    accounting_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CleanupEngagement(TypedDict):
    id: str
    client_id: str
    title: str
    period_start: str
    period_end: str
    complexity_tier: str
    workflow_status: str
    billing_status: str
    scope_locked: bool
    estimated_txn_volume: int
    reconciled_account_count: int
    total_account_count: int
    open_blocking_exception_count: int
    readiness_score: int
    recon_status: str
    created_at: str
    updated_at: str
    version: int


class ScopeEstimate(TypedDict):
    id: str
    engagement_id: str
    monthly_txn_rate: int
    period_month_count: int
    txn_volume_estimate: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LedgerAccount(TypedDict):
    id: str
    engagement_id: str
    account_code: str
    name: str
    account_type: str
    normal_side: str
    is_bank_account: bool
    book_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    id: str
    engagement_id: str
    account_id: str
    txn_date: str
    side: str
    amount_cents: int
    memo: str
    cash_settled: bool
    reconciliation_item_id: Optional[str]
    reversed_entry_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BankStatement(TypedDict):
    id: str
    engagement_id: str
    account_id: str
    statement_start: str
    statement_end: str
    ending_balance_cents: int
    deposits_in_transit_cents: int
    outstanding_checks_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconciliationItem(TypedDict):
    id: str
    statement_id: str
    engagement_id: str
    ledger_entry_id: str
    statement_line_amount_cents: int
    match_kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Phase(TypedDict):
    id: str
    engagement_id: str
    phase_index: int
    label: str
    weight_bp: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PhaseInvoice(TypedDict):
    id: str
    engagement_id: str
    phase_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxPackage(TypedDict):
    id: str
    engagement_id: str
    basis: str
    net_book_income_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict):
    id: str
    engagement_id: str
    monthly_fee_cents: int
    conversion_date: str
    first_month_prorated_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Exception(TypedDict):
    id: str
    engagement_id: str
    account_id: str
    kind: str
    severity: str
    doc_due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CompletionReport(TypedDict):
    id: str
    engagement_id: str
    final_readiness_score: int
    reconciled_account_count: int
    total_billed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
