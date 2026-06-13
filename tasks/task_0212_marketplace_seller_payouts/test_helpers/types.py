"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Marketplace Seller Payouts PRD (Sections 2 and 3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---

class UserRole(str, Enum):
    SELLER = "Seller"
    PLATFORM_REVIEWER = "PlatformReviewer"
    PLATFORM_FINANCE = "PlatformFinance"


# --- Seller status dimensions (PRD §3.1, §3.2) ---

class KycStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class W9Status(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class AccountStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


# --- PayoutMethod (PRD §3.3) ---

class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


# --- Order dimensions (PRD §3.4, §3.5) ---

class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    PAID = "PAID"


class ClawbackStatus(str, Enum):
    NONE = "NONE"
    REFUND_CLAWED = "REFUND_CLAWED"
    CHARGEBACK_CLAWED = "CHARGEBACK_CLAWED"


# --- LedgerEntry (PRD §2.6) ---

class LedgerSourceType(str, Enum):
    ORDER_PROCEEDS = "ORDER_PROCEEDS"
    REFUND_CLAWBACK = "REFUND_CLAWBACK"
    CHARGEBACK_CLAWBACK = "CHARGEBACK_CLAWBACK"
    CHARGEBACK_FEE = "CHARGEBACK_FEE"
    RESERVE_HOLD = "RESERVE_HOLD"
    RESERVE_RELEASE = "RESERVE_RELEASE"
    PAYOUT = "PAYOUT"


class HoldState(str, Enum):
    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    REVERSED = "REVERSED"


# --- Reserve (PRD §3.10) ---

class ReserveStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"


# --- Refund (PRD §3.6) ---

class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class RefundReason(str, Enum):
    BUYER_REMORSE = "BUYER_REMORSE"
    NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"
    DAMAGED = "DAMAGED"
    NOT_RECEIVED = "NOT_RECEIVED"


# --- Chargeback (PRD §3.7) ---

class ChargebackStatus(str, Enum):
    RECEIVED = "RECEIVED"
    REPRESENTED = "REPRESENTED"
    WON = "WON"
    LOST = "LOST"


# --- Dispute (PRD §3.8) ---

class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SELLER_RESPONDED = "SELLER_RESPONDED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class ClaimType(str, Enum):
    ITEM_NOT_RECEIVED = "ITEM_NOT_RECEIVED"
    ITEM_NOT_AS_DESCRIBED = "ITEM_NOT_AS_DESCRIBED"
    RETURN_NOT_REFUNDED = "RETURN_NOT_REFUNDED"


# --- Payout (PRD §3.9) ---

class PayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


# --- TaxForm (PRD §3.11) ---

class FormStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CORRECTED = "CORRECTED"


class ThresholdBasis(str, Enum):
    FEDERAL_5000 = "FEDERAL_5000"
    LEGACY_20K_200 = "LEGACY_20K_200"
    NONE = "NONE"


# --- Enum value lists for assertions ---

COUNTRY_CODES = ["US", "CA", "GB", "DE", "AU"]
TAX_CLASSIFICATIONS = ["INDIVIDUAL", "SOLE_PROP", "C_CORP", "S_CORP", "LLC", "PARTNERSHIP"]
PRODUCT_CATEGORIES = ["ELECTRONICS", "APPAREL", "MEDIA", "GROCERY", "HANDMADE"]
METHOD_TYPES = ["ACH", "WIRE", "PAYPAL"]
CURRENCIES = ["USD", "CAD", "GBP", "EUR"]


# =========================================================================
# Entity TypedDicts
# =========================================================================
# common_fields: true entities carry id + created_at + updated_at + version.
# common_fields: false entities (LedgerEntry, BalanceStatement) carry ONLY
# id + created_at — no updated_at, no version (PRD §2.4).


class Seller(TypedDict):
    id: str
    legal_name: str
    email: str
    country_code: str
    tax_classification: str
    tin_last4: str
    kyc_status: str
    w9_status: str
    account_status: str
    risk_tier: str
    seller_risk_score: int
    available_balance_cents: int
    pending_balance_cents: int
    reserve_held_cents: int
    ytd_gross_cents: int
    ytd_transaction_count: int
    kyc_reviewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayoutMethod(TypedDict):
    id: str
    seller_id: str
    method_type: str
    account_last4: str
    currency: str
    verification_status: str
    micro_deposit_code: Optional[str]
    is_default: bool
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    category: str
    commission_bps: int
    fixed_fee_cents: int
    payment_processing_bps: int
    payment_processing_fixed_cents: int
    reserve_pct_standard: int
    reserve_pct_elevated: int
    reserve_pct_high: int
    maturation_days: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    seller_id: str
    fee_schedule_id: str
    category: str
    gross_amount_cents: int
    commission_cents: int
    platform_fee_cents: int
    processing_fee_cents: int
    net_earnings_cents: int
    settlement_status: str
    clawback_status: str
    refunded_amount_cents: int
    settled_at: Optional[str]
    matured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false) — NO updated_at, NO version.
class LedgerEntry(TypedDict):
    id: str
    seller_id: str
    source_type: str
    source_id: str
    amount_cents: int
    hold_state: str
    memo: str
    created_at: str


class Reserve(TypedDict):
    id: str
    seller_id: str
    reserve_status: str
    held_amount_cents: int
    reserve_pct_applied: int
    release_due_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    order_id: str
    seller_id: str
    refund_amount_cents: int
    reason: str
    refund_status: str
    commission_returned_cents: int
    clawback_cents: int
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict):
    id: str
    order_id: str
    seller_id: str
    chargeback_status: str
    dispute_fee_cents: int
    clawback_cents: int
    representment_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    order_id: str
    seller_id: str
    claim_type: str
    dispute_status: str
    response_round: int
    granted_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    seller_id: str
    payout_method_id: Optional[str]
    payout_status: str
    gross_available_cents: int
    reserve_withheld_cents: int
    payout_amount_cents: int
    order_ids: List[str]
    finance_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxForm(TypedDict):
    id: str
    seller_id: str
    tax_year: int
    gross_reported_cents: int
    transaction_count: int
    threshold_basis: str
    form_status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false) — NO updated_at, NO version.
class BalanceStatement(TypedDict):
    id: str
    seller_id: str
    period_year: int
    period_month: int
    opening_balance_cents: int
    closing_balance_cents: int
    total_credits_cents: int
    total_debits_cents: int
    total_payouts_cents: int
    created_at: str
