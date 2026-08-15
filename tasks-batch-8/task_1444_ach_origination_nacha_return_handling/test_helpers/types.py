"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2.5, 3, 4)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ORIGINATOR_OPS = "OriginatorOps"
    ODFI_UNDERWRITER = "OdfiUnderwriter"
    ODFI_OPERATIONS = "OdfiOperations"
    ODFI_RISK_OFFICER = "OdfiRiskOfficer"
    ODFI_FINANCE = "OdfiFinance"


class OriginatorStatus(str, Enum):
    PENDING_UNDERWRITING = "PENDING_UNDERWRITING"
    ACTIVE = "ACTIVE"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class WindowKind(str, Enum):
    SAME_DAY_1 = "SAME_DAY_1"
    SAME_DAY_2 = "SAME_DAY_2"
    SAME_DAY_3 = "SAME_DAY_3"
    NEXT_DAY = "NEXT_DAY"


class SecCode(str, Enum):
    PPD = "PPD"
    CCD = "CCD"
    WEB = "WEB"
    TEL = "TEL"


class AchFileStatus(str, Enum):
    WAREHOUSED = "WAREHOUSED"
    RELEASED = "RELEASED"
    DISPATCHED = "DISPATCHED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class EntryDirection(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AchEntryStatus(str, Enum):
    WAREHOUSED = "WAREHOUSED"
    TRANSMITTED = "TRANSMITTED"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReturnCode(str, Enum):
    R01 = "R01"
    R02 = "R02"
    R05 = "R05"
    R07 = "R07"
    R10 = "R10"


class ReturnCaseDisposition(str, Enum):
    OPEN = "OPEN"
    REPRESENTED = "REPRESENTED"
    FINAL = "FINAL"


class NocCode(str, Enum):
    C01 = "C01"
    C02 = "C02"
    C03 = "C03"


class NocStatus(str, Enum):
    RECEIVED = "RECEIVED"
    OVERDUE = "OVERDUE"
    APPLIED = "APPLIED"


class ReversalReason(str, Enum):
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    WRONG_AMOUNT = "WRONG_AMOUNT"
    WRONG_ACCOUNT = "WRONG_ACCOUNT"


class ReversalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    TRANSMITTED = "TRANSMITTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RiskCaseSource(str, Enum):
    RATE_BREACH = "RATE_BREACH"
    MANUAL = "MANUAL"


class RiskCaseStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ResolutionAction(str, Enum):
    SUSPEND = "SUSPEND"
    WATCH = "WATCH"
    REINSTATE = "REINSTATE"
    TERMINATE = "TERMINATE"
    DISMISS = "DISMISS"


class SettlementBatchStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    SETTLED = "SETTLED"
    RECONCILED = "RECONCILED"


class GlAccountCode(str, Enum):
    SETTLEMENT_CLEARING = "SETTLEMENT_CLEARING"
    ORIGINATOR_RECEIVABLE = "ORIGINATOR_RECEIVABLE"
    FEE_INCOME = "FEE_INCOME"


class Originator(TypedDict, total=False):
    id: str
    legal_name: str
    sec_codes_allowed: List[str]
    exposure_limit_cents: int
    fee_discount_bps: int
    status: str
    unauth_rate_bps_trailing: int
    unauth_rate_bps_mtd: int
    outstanding_exposure_gross_cents: int
    outstanding_exposure_debit_cents: int
    created_at: str
    updated_at: str
    version: int


class CutoffWindow(TypedDict, total=False):
    id: str
    window_kind: str
    opens_at_utc: str
    closes_at_utc: str
    per_entry_fee_cents: int
    file_fee_cents: int
    large_entry_surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class AchFile(TypedDict, total=False):
    id: str
    originator_id: str
    sec_code: str
    requested_window_kind: str
    effective_date: str
    assigned_window_kind: Optional[str]
    settlement_date: Optional[str]
    settlement_batch_id: Optional[str]
    entry_count: int
    total_amount_cents: int
    quoted_fee_cents: int
    assessed_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AchEntry(TypedDict, total=False):
    id: str
    file_id: str
    direction: str
    amount_cents: int
    receiver_account: str
    receiver_routing: str
    representment_count: int
    last_return_code: Optional[str]
    first_transmitted_at: Optional[str]
    settled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnCase(TypedDict, total=False):
    id: str
    entry_id: str
    return_code: str
    received_at: str
    is_unauthorized: bool
    representment_number: int
    gl_posted: bool
    disposition: str
    created_at: str
    updated_at: str
    version: int


class NocRecord(TypedDict, total=False):
    id: str
    entry_id: str
    noc_code: str
    corrected_data: str
    received_at: str
    due_date: str
    late_applied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReversalRequest(TypedDict, total=False):
    id: str
    entry_id: str
    reason: str
    requested_at: str
    window_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable audit record (PRD section 2.5): carries only id + created_at;
# updated_at and version are absent by design.
class ReturnRateSnapshot(TypedDict, total=False):
    id: str
    originator_id: str
    computed_at: str
    unauth_returns_60d: int
    debits_60d: int
    unauth_returns_mtd: int
    debits_mtd: int
    rate_bps_trailing_60d: int
    rate_bps_mtd: int
    breach: bool
    created_at: str


class RiskCase(TypedDict, total=False):
    id: str
    originator_id: str
    source: str
    status: str
    resolution_action: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict, total=False):
    id: str
    window_kind: str
    settlement_date: str
    status: str
    expected_net_cents: Optional[int]
    posted_net_cents: Optional[int]
    recon_variance_cents: Optional[int]
    dispatched_by_user_id: Optional[str]
    reconciled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger event (PRD section 2.5): carries only id + created_at;
# updated_at and version are absent by design.
class GlPosting(TypedDict, total=False):
    id: str
    settlement_batch_id: str
    account_code: str
    debit_cents: int
    credit_cents: int
    memo: str
    posted_at: str
    created_at: str
