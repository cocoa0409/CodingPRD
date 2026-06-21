"""Domain types: entity TypedDicts, status enums, role enum for the P2P money transfer API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class RiskTier(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class FundingSourceStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REMOVED = "REMOVED"


class FundingSourceKind(str, Enum):
    BANK = "BANK"
    DEBIT = "DEBIT"


class RecipientVerificationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"


class VerificationChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"


class TransferStatus(str, Enum):
    SENT = "SENT"
    HELD = "HELD"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class MoneyRequestStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class SplitRequestStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class SplitMode(str, Enum):
    EVEN = "EVEN"
    WEIGHTED = "WEIGHTED"


class SplitParticipantStatus(str, Enum):
    OWED = "OWED"
    PAID = "PAID"
    FORGIVEN = "FORGIVEN"


class RiskHoldStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class RiskHoldReason(str, Enum):
    HIGH_TIER = "HIGH_TIER"
    LARGE_AMOUNT = "LARGE_AMOUNT"
    UNVERIFIED_RECIPIENT = "UNVERIFIED_RECIPIENT"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    NEEDS_INFO = "NEEDS_INFO"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class DisputeReason(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_RECEIVED = "NOT_RECEIVED"
    DUPLICATE = "DUPLICATE"


class ReversalStatus(str, Enum):
    APPLIED = "APPLIED"


class WithdrawalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WithdrawalSpeed(str, Enum):
    INSTANT = "INSTANT"
    STANDARD = "STANDARD"


class LedgerDirection(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class LedgerSourceKind(str, Enum):
    TRANSFER = "TRANSFER"
    WITHDRAWAL = "WITHDRAWAL"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    ACCOUNT_HOLDER = "AccountHolder"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Primary resources carry id + created_at + updated_at + version.

class Account(TypedDict):
    id: str
    email: str
    display_name: str
    status: str
    available_balance_cents: int
    held_balance_cents: int
    risk_score: int
    risk_tier: str
    daily_send_limit_cents: int
    weekly_send_limit_cents: int
    is_recipient_verified: bool
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict):
    id: str
    account_id: str
    kind: str
    last4: str
    status: str
    micro_deposit_code: str
    is_default_payout: bool
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict):
    id: str
    sender_account_id: str
    recipient_account_id: str
    amount_cents: int
    memo: str
    status: str
    risk_flagged: bool
    hold_id: Optional[str]
    source_money_request_id: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoneyRequest(TypedDict):
    id: str
    requester_account_id: str
    payer_account_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SplitRequest(TypedDict):
    id: str
    organizer_account_id: str
    total_amount_cents: int
    split_mode: str
    status: str
    collected_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class SplitParticipant(TypedDict):
    id: str
    split_request_id: str
    participant_account_id: str
    weight: int
    share_amount_cents: int
    status: str
    settled_transfer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskHold(TypedDict):
    id: str
    transfer_id: str
    reason_code: str
    status: str
    reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    transfer_id: str
    opener_account_id: str
    reason: str
    status: str
    resolver_user_id: Optional[str]
    reversal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reversal(TypedDict):
    id: str
    transfer_id: str
    dispute_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Withdrawal(TypedDict):
    id: str
    account_id: str
    funding_source_id: str
    gross_amount_cents: int
    speed: str
    fee_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Leaner resources (common_fields: false) carry only id + created_at.

class RecipientVerification(TypedDict):
    id: str
    account_id: str
    channel: str
    status: str
    confirm_token: str
    expires_at: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    account_id: str
    direction: str
    amount_cents: int
    source_kind: str
    source_ref_id: Optional[str]
    memo: str
    created_at: str
