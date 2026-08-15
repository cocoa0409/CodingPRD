"""Domain types: entity status enums, field enums, and the role enum (PRD §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    OPERATIONS_CLERK = "OperationsClerk"
    TELLER = "Teller"
    SUPERVISOR = "Supervisor"
    MANAGER = "Manager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ACCOUNT_HOLDER = "AccountHolder"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    CLOSED_VOLUNTARY = "CLOSED_VOLUNTARY"
    CLOSED_CHARGEOFF = "CLOSED_CHARGEOFF"


class ElectionStatus(str, Enum):
    OPTED_IN = "OPTED_IN"
    REVOKED = "REVOKED"


class ElectionChannel(str, Enum):
    BRANCH = "BRANCH"
    ONLINE = "ONLINE"
    PHONE = "PHONE"
    MAIL = "MAIL"


class TransactionType(str, Enum):
    DEBIT_ONE_TIME = "DEBIT_ONE_TIME"
    DEBIT_RECURRING = "DEBIT_RECURRING"
    DEBIT_ACH = "DEBIT_ACH"
    DEBIT_CHECK = "DEBIT_CHECK"
    CREDIT_DEPOSIT = "CREDIT_DEPOSIT"


class TransactionStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    POSTED = "POSTED"
    RETURNED_NSF = "RETURNED_NSF"
    REVERSED = "REVERSED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class FeeType(str, Enum):
    OVERDRAFT = "OVERDRAFT"
    SUSTAINED = "SUSTAINED"


class FeeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    POSTED = "POSTED"
    WAIVED = "WAIVED"
    VOIDED = "VOIDED"


class WaiverKind(str, Enum):
    FULL = "FULL"
    FIXED_AMOUNT = "FIXED_AMOUNT"
    PERCENT_BPS = "PERCENT_BPS"


class WaiverReason(str, Enum):
    HARDSHIP = "HARDSHIP"
    BANK_ERROR = "BANK_ERROR"
    FIRST_TIME = "FIRST_TIME"
    GOODWILL = "GOODWILL"


class WaiverStatus(str, Enum):
    APPLIED = "APPLIED"
    PENDING_SUPERVISOR = "PENDING_SUPERVISOR"
    PENDING_MANAGER = "PENDING_MANAGER"
    PENDING_COMPLIANCE = "PENDING_COMPLIANCE"
    DENIED = "DENIED"
    DENIED_FINAL = "DENIED_FINAL"


class RoutingBand(str, Enum):
    TELLER = "TELLER"
    SUPERVISOR = "SUPERVISOR"
    MANAGER = "MANAGER"
    COMPLIANCE = "COMPLIANCE"


class NoticeParameter(str, Enum):
    FEE_AMOUNT = "FEE_AMOUNT"
    DAILY_CAP_CENTS = "DAILY_CAP_CENTS"
    MAX_DAILY_FEES = "MAX_DAILY_FEES"
    DE_MINIMIS = "DE_MINIMIS"
    POSTING_ORDER = "POSTING_ORDER"
    SUSTAINED_FEE = "SUSTAINED_FEE"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class OfferType(str, Enum):
    LINKED_SAVINGS = "LINKED_SAVINGS"
    OVERDRAFT_LINE_OF_CREDIT = "OVERDRAFT_LINE_OF_CREDIT"
    COUNSELING = "COUNSELING"


class OfferTrigger(str, Enum):
    MANUAL = "MANUAL"
    FEE_THRESHOLD = "FEE_THRESHOLD"
    SUSTAINED_OD = "SUSTAINED_OD"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    SUBMITTED = "SUBMITTED"


class PostingOrderPolicy(str, Enum):
    HIGH_TO_LOW = "HIGH_TO_LOW"
    CHRONOLOGICAL = "CHRONOLOGICAL"


# --- Entity TypedDicts (PRD §2.5 common fields: id, created_at, updated_at,
# version on every primary resource except the waiver request item) ---


class OverdraftProgram(TypedDict, total=False):
    id: str
    name: str
    fee_amount_cents: int
    daily_fee_cap_cents: int
    max_daily_fees_count: int
    de_minimis_threshold_cents: int
    sustained_overdraft_days_threshold: int
    sustained_overdraft_fee_cents: int
    charge_off_grace_business_days: int
    notice_window_days: int
    steering_fee_count_threshold: int
    steering_window_days: int
    offer_expiry_days: int
    posting_order_policy: str
    current_disclosure_version: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DepositAccount(TypedDict, total=False):
    id: str
    program_id: str
    holder_name: str
    status: str
    ledger_balance_cents: int
    consecutive_negative_business_days: int
    restricted_business_days: int
    lifetime_fees_assessed_cents: int
    lifetime_fees_waived_cents: int
    charged_off_cents: int
    recovered_cents: int
    charge_off_original_cents: int
    created_at: str
    updated_at: str
    version: int


class OptInElection(TypedDict, total=False):
    id: str
    account_id: str
    status: str
    channel: str
    disclosure_version: str
    elected_at: str
    last_changed_at: str
    created_at: str
    updated_at: str
    version: int


class AccountTransaction(TypedDict, total=False):
    id: str
    account_id: str
    type: str
    amount_cents: int
    status: str
    authorized_date: str
    batch_id: Optional[str]
    posting_sequence: Optional[int]
    posted_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PostingBatch(TypedDict, total=False):
    id: str
    program_id: str
    business_date: str
    status: str
    items_posted_count: int
    items_returned_count: int
    fees_assessed_count: int
    fees_assessed_cents: int
    created_at: str
    updated_at: str
    version: int


class OverdraftFee(TypedDict, total=False):
    id: str
    account_id: str
    batch_id: str
    transaction_id: Optional[str]
    fee_type: str
    amount_cents: int
    waived_cents: int
    outstanding_cents: int
    status: str
    posted_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeWaiverRequest(TypedDict, total=False):
    id: str
    account_id: str
    fee_ids: list
    kind: str
    amount_cents: Optional[int]
    percent_bps: Optional[int]
    reason_code: str
    computed_total_cents: int
    routing_band: str
    status: str
    created_by_user_id: str
    created_by_role: str
    decided_by_user_id: Optional[str]
    denied_band: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaiverRequestItem(TypedDict, total=False):
    # Immutable allocation row: carries only id + created_at (no updated_at,
    # no version) per PRD §2.5.
    id: str
    waiver_request_id: str
    fee_id: str
    waived_cents: int
    created_at: str


class ProgramChangeNotice(TypedDict, total=False):
    id: str
    program_id: str
    parameter: str
    new_value: str
    old_value: str
    status: str
    sent_at: Optional[str]
    effective_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EducationOffer(TypedDict, total=False):
    id: str
    account_id: str
    offer_type: str
    trigger_reason: str
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryReport(TypedDict, total=False):
    id: str
    program_id: str
    period_start: str
    period_end: str
    status: str
    revenue_provisional_cents: Optional[int]
    revenue_final_cents: Optional[int]
    waiver_ratio_bps: Optional[int]
    avg_fees_per_overdrafter_centi: Optional[int]
    scrutiny_flag: Optional[bool]
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
