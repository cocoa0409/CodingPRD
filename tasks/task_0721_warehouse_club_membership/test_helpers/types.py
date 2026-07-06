"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CLUB_ADMIN = "ClubAdmin"
    MEMBER = "Member"
    REGISTER_CLERK = "RegisterClerk"
    SERVICE_DESK_CLERK = "ServiceDeskClerk"
    ANONYMOUS = "Anonymous"


class MembershipTier(str, Enum):
    BASIC = "BASIC"
    EXECUTIVE = "EXECUTIVE"


class MembershipStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CardKind(str, Enum):
    INCLUDED = "INCLUDED"
    PAID_ADDON = "PAID_ADDON"


class CardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class Department(str, Enum):
    GENERAL = "GENERAL"
    GAS = "GAS"
    PHARMACY = "PHARMACY"
    OPTICAL = "OPTICAL"


class SavingKind(str, Enum):
    INSTANT_SAVINGS = "INSTANT_SAVINGS"
    MANUFACTURER_REBATE = "MANUFACTURER_REBATE"


class TransactionStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class LedgerEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REVERSAL = "REVERSAL"
    REDEMPTION = "REDEMPTION"
    EXPIRY = "EXPIRY"


class LookupMode(str, Enum):
    RECEIPTED = "RECEIPTED"
    NO_RECEIPT_LOOKUP = "NO_RECEIPT_LOOKUP"
    DENIED = "DENIED"


class ReturnStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FeeKind(str, Enum):
    SIGNUP = "SIGNUP"
    RENEWAL = "RENEWAL"
    ADDON = "ADDON"
    CANCEL_REFUND = "CANCEL_REFUND"


class PaymentPurpose(str, Enum):
    SIGNUP = "SIGNUP"
    RENEWAL = "RENEWAL"


class PaymentOutcome(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


# --- Entity TypedDicts ---

# common_fields: false — id + created_at only.
class MembershipPlan(TypedDict):
    id: str
    created_at: str
    tier: str
    annual_fee_cents: int
    reward_rate_bps: int
    reward_cap_cents: int
    max_household_cards: int
    addon_fee_cents: int


# common_fields: true
class Membership(TypedDict):
    id: str
    plan_id: str
    primary_member_name: str
    status: str
    auto_renew: bool
    term_start_utc: Optional[str]
    term_end_utc: Optional[str]
    reward_accrued_cents: int
    reward_redeemed_cents: int
    fees_paid_cents: int
    household_card_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class HouseholdCard(TypedDict):
    id: str
    membership_id: str
    cardholder_name: str
    card_kind: str
    status: str
    fee_charged_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false
class Product(TypedDict):
    id: str
    created_at: str
    sku: str
    list_price_cents: int
    member_price_cents: int
    member_only: bool
    per_member_limit: int
    department: str
    reward_eligible: bool


# common_fields: false
class InstantSaving(TypedDict):
    id: str
    created_at: str
    product_id: str
    kind: str
    amount_cents: int
    window_start_utc: str
    window_end_utc: str
    max_units: int


# common_fields: true
class Transaction(TypedDict):
    id: str
    membership_id: str
    status: str
    gross_cents: int
    instant_savings_cents: int
    rebate_cents: int
    net_cents: int
    reward_accrued_cents: int
    finalized_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class TransactionLine(TypedDict):
    id: str
    transaction_id: str
    product_id: str
    qty: int
    unit_price_cents: int
    line_instant_savings_cents: int
    line_rebate_cents: int
    returned_qty: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false
class RewardLedgerEntry(TypedDict):
    id: str
    created_at: str
    membership_id: str
    entry_type: str
    amount_cents: int
    source_transaction_id: Optional[str]
    term_start_utc: str


# common_fields: true
class Return(TypedDict):
    id: str
    membership_id: str
    transaction_id: Optional[str]
    product_id: str
    qty: int
    lookup_mode: str
    status: str
    refund_cents: int
    reward_reversal_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false
class FeeEvent(TypedDict):
    id: str
    created_at: str
    membership_id: str
    kind: str
    amount_cents: int
    term_start_utc: str


# common_fields: true
class Payment(TypedDict):
    id: str
    membership_id: str
    purpose: str
    outcome: str
    amount_cents: int
    created_at: str
    updated_at: str
    version: int
