"""Domain types for the Rebate Incentive Program API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #

class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    BUDGET_LOCKED = "BUDGET_LOCKED"
    CLOSED = "CLOSED"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class OfferChannel(str, Enum):
    DEALER = "DEALER"
    CONSUMER = "CONSUMER"
    BOTH = "BOTH"


class ClaimantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class ClaimantType(str, Enum):
    DEALER = "DEALER"
    CONSUMER = "CONSUMER"


class AdjudicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    HELD = "HELD"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    WITHDRAWN = "WITHDRAWN"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    NONE = "NONE"
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    ESCHEATED = "ESCHEATED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    REISSUE_PENDING = "REISSUE_PENDING"
    CLEARED = "CLEARED"
    VOIDED = "VOIDED"
    ESCHEATED = "ESCHEATED"


class PayoutMethod(str, Enum):
    CHECK = "CHECK"
    VIRTUAL_CARD = "VIRTUAL_CARD"


class VirtualCardStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVATED = "ACTIVATED"
    PARTIALLY_USED = "PARTIALLY_USED"
    EXHAUSTED = "EXHAUSTED"
    ESCHEATED = "ESCHEATED"


class BudgetEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    COMMIT = "COMMIT"
    RELEASE = "RELEASE"
    PAYMENT = "PAYMENT"
    ESCHEAT_REVERSAL = "ESCHEAT_REVERSAL"
    BUDGET_ADJUSTMENT = "BUDGET_ADJUSTMENT"


class FraudCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    PENDING_INFO = "PENDING_INFO"
    SUBSTANTIATED = "SUBSTANTIATED"
    CLEARED = "CLEARED"


class FraudCaseOpenedBy(str, Enum):
    SYSTEM_AUTO = "SYSTEM_AUTO"
    ANALYST = "ANALYST"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CLAIMS_PROCESSOR = "ClaimsProcessor"
    FINANCE_OFFICER = "FinanceOfficer"
    FRAUD_ANALYST = "FraudAnalyst"
    DEALER = "Dealer"
    CONSUMER = "Consumer"


# --------------------------------------------------------------------------- #
# Entity shapes
# --------------------------------------------------------------------------- #

class Program(TypedDict):
    id: str
    name: str
    fiscal_year: int
    escheat_jurisdiction: str
    budget_total_cents: int
    committed_cents: int
    paid_cents: int
    escheat_recovered_cents: int
    pending_provisional_cents: int
    reserve_cents: int
    available_cents: int
    utilization_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    program_id: str
    name: str
    channel: str
    sku_scope: str
    effective_start_date: str
    effective_end_date: str
    max_rebate_cents_per_claim: int
    dealer_tier_enabled: bool
    status: str
    closed_at: Optional[str]
    active_claim_count: int
    created_at: str
    updated_at: str
    version: int


class Claimant(TypedDict):
    id: str
    type: str
    legal_name: str
    email: str
    mailing_state: str
    status: str
    fraud_score: int
    duplicate_attempt_count: int
    denied_claim_count: int
    open_claim_count: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    offer_id: str
    claimant_id: str
    adjudication_status: str
    payment_status: str
    total_units: int
    provisional_rebate_cents: int
    final_rebate_cents: Optional[int]
    fraud_score_at_submit: Optional[int]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    denied_at: Optional[str]
    approved_by_user_id: Optional[str]
    denial_reason_code: Optional[str]
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class ReceiptLine(TypedDict):
    sku: str
    quantity: int
    unit_price_cents: int


class Receipt(TypedDict):
    id: str
    claim_id: str
    serial_number: str
    purchase_date: str
    retailer_name: str
    lines: List[ReceiptLine]
    line_count: int
    units: int
    gross_amount_cents: int
    validated: bool
    validated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    claim_id: str
    method: str
    gross_cents: int
    fee_cents: int
    net_cents: int
    status: str
    check_number: Optional[str]
    released_at: Optional[str]
    released_by_user_id: Optional[str]
    void_reason: Optional[str]
    reissue_count: int
    created_at: str
    updated_at: str
    version: int


class VirtualCard(TypedDict):
    id: str
    payout_id: str
    initial_balance_cents: int
    remaining_balance_cents: int
    status: str
    issued_at: str
    last_activity_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class FraudCase(TypedDict):
    id: str
    claimant_id: str
    claim_id: Optional[str]
    status: str
    opened_reason: str
    opened_by: str
    heuristic_score_at_open: int
    final_score: Optional[int]
    info_request_count: int
    created_at: str
    updated_at: str
    version: int


# Immutable, append-only rows: only id + created_at (no updated_at, no version).
class EscheatRecord(TypedDict):
    id: str
    payout_id: str
    program_id: str
    amount_cents: int
    jurisdiction: str
    dormancy_days: int
    swept_at: str
    created_at: str


class BudgetEntry(TypedDict):
    id: str
    program_id: str
    claim_id: Optional[str]
    entry_type: str
    amount_cents: int
    committed_after_cents: int
    memo: Optional[str]
    created_at: str
