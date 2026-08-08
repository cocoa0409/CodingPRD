"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CONSUMER = "Consumer"
    CLAIM_REVIEWER = "ClaimReviewer"
    FRAUD_ANALYST = "FraudAnalyst"
    PROGRAM_MANAGER = "ProgramManager"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status enums --------------------------------------------------------
class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXHAUSTED = "EXHAUSTED"


class ProgramCategory(str, Enum):
    PRODUCT_REBATE = "PRODUCT_REBATE"
    CLASS_ACTION = "CLASS_ACTION"
    WARRANTY = "WARRANTY"
    PRICE_ADJUSTMENT = "PRICE_ADJUSTMENT"


class DistributionMethod(str, Enum):
    FIXED = "FIXED"
    PRO_RATA = "PRO_RATA"


class ConsumerIdentityStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"


class MatchStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    CONVERTED = "CONVERTED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ClaimEligibilityStatus(str, Enum):
    UNASSESSED = "UNASSESSED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class ClaimFraudStatus(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    CONFIRMED = "CONFIRMED"


class DocumentType(str, Enum):
    RECEIPT = "RECEIPT"
    PROOF_OF_PURCHASE = "PROOF_OF_PURCHASE"
    ID = "ID"
    OTHER = "OTHER"


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PayoutStatus(str, Enum):
    INITIATED = "INITIATED"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class FraudReason(str, Enum):
    DUPLICATE = "DUPLICATE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    SUSPICIOUS_DOCS = "SUSPICIOUS_DOCS"
    INELIGIBLE_PURCHASE = "INELIGIBLE_PURCHASE"
    OTHER = "OTHER"


class FraudFlagStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    CLEARED = "CLEARED"


class FundTransactionType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class FundTransactionReason(str, Enum):
    PAYOUT_COMMIT = "PAYOUT_COMMIT"
    PAYOUT_REVERSAL = "PAYOUT_REVERSAL"


class NotificationEventType(str, Enum):
    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
    NEEDS_INFO = "NEEDS_INFO"
    CLAIM_APPROVED = "CLAIM_APPROVED"
    CLAIM_REJECTED = "CLAIM_REJECTED"
    CLAIM_EXPIRED = "CLAIM_EXPIRED"
    PAYOUT_CLEARED = "PAYOUT_CLEARED"
    PAYOUT_FAILED = "PAYOUT_FAILED"
    FRAUD_FLAGGED = "FRAUD_FLAGGED"


# --- Entity TypedDicts ---------------------------------------------------
# Fully-versioned entities carry id + created_at + updated_at + version.

class RebateProgram(TypedDict, total=False):
    id: str
    name: str
    settlement_case_id: str
    category: str
    distribution_method: str
    fund_total_cents: int
    fund_remaining_cents: int
    advertised_amount_cents: int
    per_claim_cap_cents: int
    eligibility_min_purchase_cents: int
    requires_proof: bool
    min_documents: int
    claim_window_open_at: str
    claim_window_close_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Consumer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    identity_status: str
    total_recovered_cents: int
    optimistic_risk_score: int
    pessimistic_risk_score: int
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict, total=False):
    id: str
    consumer_id: str
    program_id: str
    match_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    consumer_id: str
    program_id: str
    benefit_period_start: str
    benefit_period_end: str
    claimed_amount_cents: int
    provisional_payout_cents: Optional[int]
    final_payout_cents: Optional[int]
    contingency_fee_cents: Optional[int]
    net_payout_cents: Optional[int]
    eligibility_status: str
    fraud_status: str
    document_count: int
    needs_info_count: int
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimDocument(TypedDict, total=False):
    id: str
    claim_id: str
    doc_type: str
    file_ref: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict, total=False):
    id: str
    claim_id: str
    gross_amount_cents: int
    fee_amount_cents: int
    net_amount_cents: int
    attempt_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FraudFlag(TypedDict, total=False):
    id: str
    claim_id: str
    raised_by_user_id: str
    reason: str
    status: str
    cleared_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityAssessment(TypedDict, total=False):
    id: str
    claim_id: str
    assessed_by_user_id: str
    eligible: bool
    min_purchase_met: bool
    documents_sufficient: bool
    reasons: List[str]
    assessed_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger records: id + created_at only (no updated_at, no version).

class FundTransaction(TypedDict, total=False):
    id: str
    program_id: str
    related_claim_id: Optional[str]
    type: str
    amount_cents: int
    reason: str
    balance_after_cents: int
    created_at: str


class Notification(TypedDict, total=False):
    id: str
    consumer_id: str
    related_claim_id: Optional[str]
    channel: str
    event_type: str
    body: str
    read: bool
    created_at: str
