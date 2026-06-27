"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REVIEW_AGENT = "ReviewAgent"
    FINANCE_ADMIN = "FinanceAdmin"
    MEMBER = "Member"


# --- Status enums ---
class MerchantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class OfferType(str, Enum):
    LINKED = "LINKED"
    RECEIPT_REBATE = "RECEIPT_REBATE"


class OfferStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class MemberAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MemberVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class ReceiptScanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RewardClaimAttribution(str, Enum):
    ONLINE = "ONLINE"
    IN_STORE = "IN_STORE"


class RewardClaimStatus(str, Enum):
    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"
    EXPIRED = "EXPIRED"


class CashOutMethod(str, Enum):
    PAYPAL = "PAYPAL"
    CHECK = "CHECK"
    GIFT_CARD = "GIFT_CARD"


class CashOutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"


class ReferralStatus(str, Enum):
    INVITED = "INVITED"
    SIGNED_UP = "SIGNED_UP"
    QUALIFIED = "QUALIFIED"
    REWARDED = "REWARDED"
    EXPIRED = "EXPIRED"


class LedgerEntryType(str, Enum):
    CLAIM_PENDING = "CLAIM_PENDING"
    CLAIM_MATURED = "CLAIM_MATURED"
    CLAIM_CLAWBACK = "CLAIM_CLAWBACK"
    CLAIM_EXPIRED = "CLAIM_EXPIRED"
    CASHOUT_DEBIT = "CASHOUT_DEBIT"
    CASHOUT_REVERSAL = "CASHOUT_REVERSAL"
    REFERRAL_BONUS = "REFERRAL_BONUS"
    STREAK_BONUS = "STREAK_BONUS"


# --- Entity TypedDicts ---
# common_fields: true -> id + created_at + updated_at + version
class Merchant(TypedDict):
    id: str
    name: str
    online_rate_bps: int
    instore_rate_bps: int
    attribution_window_hours: int
    double_dip_allowed: bool
    maturity_hold_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    merchant_id: str
    offer_type: str
    bonus_rate_bps: int
    rebate_cents: int
    min_spend_cents: int
    starts_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    referred_by_member_id: Optional[str]
    account_status: str
    verification_status: str
    pending_balance_cents: int
    available_balance_cents: int
    reserved_balance_cents: int
    net_cashoutable_cents: int
    lifetime_paid_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> only id + created_at
class ClickThrough(TypedDict):
    id: str
    member_id: str
    merchant_id: str
    offer_id: Optional[str]
    clicked_at: str
    created_at: str


class ReceiptScan(TypedDict):
    id: str
    member_id: str
    merchant_id: str
    offer_id: str
    purchase_total_cents: int
    purchased_at: str
    status: str
    review_note: Optional[str]
    reward_claim_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RewardClaim(TypedDict):
    id: str
    member_id: str
    merchant_id: str
    offer_id: Optional[str]
    click_through_id: Optional[str]
    receipt_scan_id: Optional[str]
    attribution: str
    purchase_amount_cents: int
    amount_cents: int
    status: str
    matures_at: str
    expires_at: str
    cashout_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CashOut(TypedDict):
    id: str
    member_id: str
    method: str
    requested_amount_cents: int
    fee_cents: int
    net_payout_cents: int
    status: str
    expected_member_version: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referrer_member_id: str
    referee_email: str
    referee_member_id: Optional[str]
    referee_qualifying_cents: int
    bonus_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BonusStreak(TypedDict):
    id: str
    member_id: str
    current_streak_weeks: int
    longest_streak_weeks: int
    last_activity_week_index: Optional[int]
    pending_streak_bonus_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> only id + created_at
class LedgerEntry(TypedDict):
    id: str
    member_id: str
    entry_type: str
    amount_cents: int
    reward_claim_id: Optional[str]
    cashout_id: Optional[str]
    referral_id: Optional[str]
    created_at: str


class ReturnEvent(TypedDict):
    id: str
    reward_claim_id: str
    returned_amount_cents: int
    clawback_cents: int
    reported_at: str
    created_at: str
