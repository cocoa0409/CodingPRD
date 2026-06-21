"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model. Versioned mutable entities carry id,
created_at, updated_at, and version; immutable audit records (FxRate,
SanctionsListEntry, SanctionsHit, LedgerEntry) carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class CorridorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SenderKycTier(str, Enum):
    TIER0 = "TIER0"
    TIER1 = "TIER1"
    TIER2 = "TIER2"


class SenderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class RecipientKycStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PayoutMethod(str, Enum):
    BANK = "BANK"
    CASH_PICKUP = "CASH_PICKUP"
    WALLET = "WALLET"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    FUNDED = "FUNDED"


class ComplianceStatus(str, Enum):
    SCREENING = "SCREENING"
    CLEARED = "CLEARED"
    HELD = "HELD"
    REJECTED = "REJECTED"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class ComplianceCaseStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_INFO = "AWAITING_INFO"
    ESCALATED = "ESCALATED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class ComplianceCaseReason(str, Enum):
    SANCTIONS_SCORE = "SANCTIONS_SCORE"
    MANUAL = "MANUAL"


class SubjectKind(str, Enum):
    SENDER = "SENDER"
    RECIPIENT = "RECIPIENT"


class PayoutOutcome(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class PayoutFailureReason(str, Enum):
    INVALID_ACCOUNT = "INVALID_ACCOUNT"
    PICKUP_EXPIRED = "PICKUP_EXPIRED"
    WALLET_REJECTED = "WALLET_REJECTED"


class RefundReason(str, Enum):
    SENDER_CANCEL = "SENDER_CANCEL"
    COMPLIANCE_REJECT = "COMPLIANCE_REJECT"
    DELIVERY_FAILED = "DELIVERY_FAILED"


class RefundStatus(str, Enum):
    ISSUED = "ISSUED"


class LedgerEntryType(str, Enum):
    SENDER_DEBIT = "SENDER_DEBIT"
    RECIPIENT_CREDIT = "RECIPIENT_CREDIT"
    FEE_REVENUE = "FEE_REVENUE"
    REFUND_CREDIT = "REFUND_CREDIT"
    FEE_REVERSAL = "FEE_REVERSAL"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REMITTANCE_AGENT = "RemittanceAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PAYOUT_OPERATOR = "PayoutOperator"


# ─── Entity TypedDicts ────────────────────────────────────────────────────

# Versioned mutable entity — id + created_at + updated_at + version.
class Corridor(TypedDict):
    id: str
    name: str
    send_country: str
    receive_country: str
    send_currency: str
    receive_currency: str
    enabled_payout_methods: List[str]
    fx_margin_bps: int
    fee_flat_minor: int
    fee_pct_bps: int
    fee_tier_threshold_minor: int
    fee_pct_tier2_bps: int
    per_transfer_max_minor: int
    rolling_window_hours: int
    rolling_window_cap_minor: int
    rate_lock_ttl_seconds: int
    reserved_minor: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable audit record — id + created_at only.
class FxRate(TypedDict):
    id: str
    corridor_id: str
    mid_rate_micro: int
    effective_at: str
    created_at: str


class Sender(TypedDict):
    id: str
    full_name: str
    country: str
    date_of_birth: str
    kyc_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Recipient(TypedDict):
    id: str
    sender_id: str
    full_name: str
    country: str
    payout_method: str
    payout_account_ref: str
    kyc_status: str
    kyc_doc_ref: Optional[str]
    kyc_review_count: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    corridor_id: str
    sender_id: str
    send_principal_minor: int
    payout_method: str
    mid_rate_micro: int
    locked_rate_micro: int
    fee_minor: int
    recipient_amount_minor: int
    total_pay_minor: int
    locked_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict):
    id: str
    quote_id: str
    corridor_id: str
    sender_id: str
    recipient_id: str
    send_principal_minor: int
    fee_minor: int
    recipient_amount_minor: int
    locked_rate_micro: int
    funding_status: str
    compliance_status: str
    delivery_status: str
    sanctions_score: int
    refundable_minor: int
    created_at: str
    updated_at: str
    version: int


class ComplianceCase(TypedDict):
    id: str
    transfer_id: str
    sanctions_hit_id: Optional[str]
    opened_reason: str
    assigned_officer_id: str
    info_request_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable audit record — id + created_at only.
class SanctionsListEntry(TypedDict):
    id: str
    listed_name: str
    listed_country: str
    program: str
    weight_name_bps: int
    weight_country_bps: int
    created_at: str


# Immutable audit record — id + created_at only.
class SanctionsHit(TypedDict):
    id: str
    transfer_id: str
    list_entry_id: str
    subject_kind: str
    subject_id: str
    score: int
    created_at: str


class PayoutAttempt(TypedDict):
    id: str
    transfer_id: str
    payout_method: str
    attempt_index: int
    outcome: str
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    transfer_id: str
    reason: str
    principal_refunded_minor: int
    fee_refunded_minor: int
    total_refunded_minor: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable audit record — id + created_at only.
class LedgerEntry(TypedDict):
    id: str
    transfer_id: str
    entry_type: str
    amount_minor: int
    memo: Optional[str]
    created_at: str
