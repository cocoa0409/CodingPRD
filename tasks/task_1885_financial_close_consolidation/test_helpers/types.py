"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CONTROLLER = "Controller"
    PREPARER = "Preparer"
    APPROVER = "Approver"
    AUDITOR = "Auditor"


class ClosePeriodStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    UNDER_REVIEW = "UNDER_REVIEW"
    FINALIZED = "FINALIZED"


class ClosePosture(str, Enum):
    OPEN = "OPEN"
    SOFT_CLOSED = "SOFT_CLOSED"
    HARD_CLOSED = "HARD_CLOSED"
    REOPENED = "REOPENED"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"


class TranslationMethod(str, Enum):
    CURRENT_RATE = "CURRENT_RATE"
    TEMPORAL = "TEMPORAL"


class EntityPeriodStatus(str, Enum):
    PREPARING = "PREPARING"
    SUBLEDGER_CUT = "SUBLEDGER_CUT"
    RECONCILED = "RECONCILED"
    READY_FOR_CONSOL = "READY_FOR_CONSOL"
    SOFT_LOCKED = "SOFT_LOCKED"
    HARD_LOCKED = "HARD_LOCKED"
    REOPENED = "REOPENED"


class CloseTaskStatus(str, Enum):
    BLOCKED = "BLOCKED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    WAIVED = "WAIVED"


class Subledger(str, Enum):
    AR = "AR"
    AP = "AP"
    INVENTORY = "INVENTORY"
    FIXED_ASSETS = "FIXED_ASSETS"
    PAYROLL = "PAYROLL"


class CutoffRule(str, Enum):
    INCLUSIVE = "INCLUSIVE"
    EXCLUSIVE_AT_END = "EXCLUSIVE_AT_END"


class SubledgerCutoffStatus(str, Enum):
    OPEN = "OPEN"
    CUT = "CUT"
    CONFIRMED = "CONFIRMED"


class AccrualBasis(str, Enum):
    PRIOR_3M_AVG = "PRIOR_3M_AVG"
    PRIOR_PERIOD = "PRIOR_PERIOD"
    DAYS_OUTSTANDING = "DAYS_OUTSTANDING"


class AccrualEstimateStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    TRUED_UP = "TRUED_UP"
    POSTED = "POSTED"


class JournalEntryType(str, Enum):
    MANUAL = "MANUAL"
    ACCRUAL = "ACCRUAL"
    RECLASS = "RECLASS"
    ELIMINATION = "ELIMINATION"
    CONSOLIDATION_ADJ = "CONSOLIDATION_ADJ"
    TOP_SIDE = "TOP_SIDE"


class JournalEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    POSTED = "POSTED"
    REJECTED = "REJECTED"


class DocState(str, Enum):
    DOC_MISSING = "DOC_MISSING"
    DOC_ATTACHED = "DOC_ATTACHED"
    DOC_VERIFIED = "DOC_VERIFIED"


class LineDirection(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class DocCategory(str, Enum):
    INVOICE = "INVOICE"
    CONTRACT = "CONTRACT"
    BANK_STATEMENT = "BANK_STATEMENT"
    SCHEDULE = "SCHEDULE"
    OTHER = "OTHER"


class SupportingDocumentStatus(str, Enum):
    ATTACHED = "ATTACHED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ReconType(str, Enum):
    BANK = "BANK"
    INTERCOMPANY = "INTERCOMPANY"
    SUBLEDGER_GL = "SUBLEDGER_GL"
    SUSPENSE = "SUSPENSE"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    STALE = "STALE"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    AGE_1_30 = "AGE_1_30"
    AGE_31_60 = "AGE_31_60"
    AGE_61_90 = "AGE_61_90"
    AGE_OVER_90 = "AGE_OVER_90"


class ReconcilingItemStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ElimPairStatus(str, Enum):
    PROPOSED = "PROPOSED"
    MATCHED = "MATCHED"
    ELIMINATED = "ELIMINATED"
    DISPUTED = "DISPUTED"


class FluxExplanationStatus(str, Enum):
    OPEN = "OPEN"
    EXPLAINED = "EXPLAINED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class FxRateKind(str, Enum):
    PERIOD_END = "PERIOD_END"
    AVERAGE = "AVERAGE"
    HISTORICAL = "HISTORICAL"


class CloseEventKind(str, Enum):
    PERIOD_OPENED = "PERIOD_OPENED"
    SUBLEDGER_CUT = "SUBLEDGER_CUT"
    ACCRUAL_POSTED = "ACCRUAL_POSTED"
    JE_POSTED = "JE_POSTED"
    RECON_CLEARED = "RECON_CLEARED"
    TASK_DONE = "TASK_DONE"
    TRANSLATION_RUN = "TRANSLATION_RUN"
    ELIMINATION_RUN = "ELIMINATION_RUN"
    SOFT_LOCK = "SOFT_LOCK"
    HARD_LOCK = "HARD_LOCK"
    REOPENED = "REOPENED"
    REVIEW_FINALIZED = "REVIEW_FINALIZED"


# --- Entity TypedDicts ---
# All primary resources carry id + created_at + updated_at + version.
# CloseEvent is append-only: only id + created_at.


class ClosePeriod(TypedDict, total=False):
    id: str
    fiscal_year: int
    fiscal_period: int
    period_start: str
    period_end: str
    close_posture: str
    reporting_currency: str
    materiality_threshold_minor: int
    status: str
    locked_entity_count: int
    total_entity_count: int
    reopened_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Entity(TypedDict, total=False):
    id: str
    entity_code: str
    name: str
    functional_currency: str
    parent_entity_id: Optional[str]
    ownership_pct: float
    translation_method: str
    consolidation_tier: int
    is_elimination_counterparty: bool
    created_at: str
    updated_at: str
    version: int


class EntityPeriod(TypedDict, total=False):
    id: str
    close_period_id: str
    entity_id: str
    status: str
    trial_balance_minor: int
    translated_balance_minor: int
    cta_minor: int
    nci_share_minor: int
    unreconciled_count: int
    aged_over_30_count: int
    open_task_count: int
    created_at: str
    updated_at: str
    version: int


class CloseTask(TypedDict, total=False):
    id: str
    close_period_id: str
    entity_period_id: Optional[str]
    task_key: str
    title: str
    depends_on_task_ids: List[str]
    assignee_user_id: str
    due_offset_hours: int
    status: str
    is_late: bool
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubledgerCutoff(TypedDict, total=False):
    id: str
    entity_period_id: str
    subledger: str
    cutoff_at: str
    cutoff_rule: str
    status: str
    pre_cutoff_total_minor: int
    boundary_transaction_count: int
    created_at: str
    updated_at: str
    version: int


class AccrualEstimate(TypedDict, total=False):
    id: str
    entity_period_id: str
    subledger_cutoff_id: str
    account_code: str
    basis: str
    provisional_amount_minor: int
    final_amount_minor: Optional[int]
    true_up_delta_minor: int
    status: str
    created_at: str
    updated_at: str
    version: int


class JournalEntry(TypedDict, total=False):
    id: str
    entity_period_id: str
    je_type: str
    entry_date: str
    preparer_user_id: str
    approver_user_id: Optional[str]
    debit_total_minor: int
    credit_total_minor: int
    functional_currency: str
    status: str
    doc_state: str
    rejection_reason: Optional[str]
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JournalEntryLine(TypedDict, total=False):
    id: str
    journal_entry_id: str
    line_no: int
    account_code: str
    direction: str
    amount_minor: int
    counterparty_entity_id: Optional[str]
    memo: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportingDocument(TypedDict, total=False):
    id: str
    journal_entry_id: str
    file_name: str
    content_hash: str
    doc_category: str
    uploaded_by_user_id: str
    verified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reconciliation(TypedDict, total=False):
    id: str
    entity_period_id: str
    account_code: str
    recon_type: str
    gl_balance_minor: int
    subledger_balance_minor: int
    difference_minor: int
    is_within_tolerance: bool
    status: str
    cleared_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReconcilingItem(TypedDict, total=False):
    id: str
    reconciliation_id: str
    description: str
    amount_minor: int
    item_date: str
    aging_bucket: str
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ElimPair(TypedDict, total=False):
    id: str
    close_period_id: str
    entity_period_id_a: str
    entity_period_id_b: str
    account_code: str
    amount_a_minor: int
    amount_b_minor: int
    eliminated_amount_minor: int
    residual_minor: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FluxExplanation(TypedDict, total=False):
    id: str
    entity_period_id: str
    account_code: str
    prior_balance_minor: int
    current_balance_minor: int
    variance_minor: int
    variance_pct: float
    requires_explanation: bool
    explanation_text: Optional[str]
    reconciliation_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FxRate(TypedDict, total=False):
    id: str
    close_period_id: str
    from_currency: str
    to_currency: str
    rate_kind: str
    rate: float
    effective_at: str
    created_at: str
    updated_at: str
    version: int


class CloseEvent(TypedDict, total=False):
    # Append-only audit log: carries ONLY id + created_at (no updated_at, no version)
    id: str
    close_period_id: str
    entity_period_id: Optional[str]
    event_kind: str
    actor_user_id: str
    detail: str
    created_at: str
