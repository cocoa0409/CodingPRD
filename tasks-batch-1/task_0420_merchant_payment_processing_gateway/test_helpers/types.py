"""Domain types: entity TypedDicts, status enums, role enum.

Models the Merchant Payment Processing Gateway domain described in the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---

class UserRole(str, Enum):
    MERCHANT_USER = "MerchantUser"
    UNDERWRITING_OFFICER = "UnderwritingOfficer"
    PLATFORM_OPERATOR = "PlatformOperator"
    ANONYMOUS = "Anonymous"


# --- Status enums ---

class MerchantOnboardingStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PayoutMethod(str, Enum):
    BANK_ACCOUNT = "BANK_ACCOUNT"
    DEBIT_CARD = "DEBIT_CARD"


class PricingModel(str, Enum):
    FLAT = "FLAT"
    INTERCHANGE_PLUS = "INTERCHANGE_PLUS"


class ChargeAuthStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class ChargeSettlementStatus(str, Enum):
    PENDING = "PENDING"
    BATCHED = "BATCHED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class RefundReason(str, Enum):
    REQUESTED_BY_CUSTOMER = "REQUESTED_BY_CUSTOMER"
    DUPLICATE = "DUPLICATE"
    FRAUDULENT = "FRAUDULENT"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    REPRESENTED = "REPRESENTED"
    WON = "WON"
    LOST = "LOST"
    ACCEPTED = "ACCEPTED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    FUNDED = "FUNDED"


class PayoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    RETURNED = "RETURNED"


class ReserveStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class RiskDecision(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LedgerAccount(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVE = "RESERVE"


class LedgerEntryType(str, Enum):
    FUNDING = "FUNDING"
    FEE = "FEE"
    REFUND = "REFUND"
    CHARGEBACK = "CHARGEBACK"
    CHARGEBACK_REVERSAL = "CHARGEBACK_REVERSAL"
    RESERVE_HOLD = "RESERVE_HOLD"
    RESERVE_RELEASE = "RESERVE_RELEASE"
    PAYOUT = "PAYOUT"
    PAYOUT_RETURN = "PAYOUT_RETURN"
    ADJUSTMENT = "ADJUSTMENT"


class LedgerSourceType(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"
    DISPUTE = "DISPUTE"
    SETTLEMENT_BATCH = "SETTLEMENT_BATCH"
    RESERVE_ENTRY = "RESERVE_ENTRY"
    PAYOUT = "PAYOUT"
    MANUAL = "MANUAL"


class WebhookEventType(str, Enum):
    CHARGE_CAPTURED = "CHARGE_CAPTURED"
    REFUND_SETTLED = "REFUND_SETTLED"
    DISPUTE_OPENED = "DISPUTE_OPENED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    BATCH_FUNDED = "BATCH_FUNDED"
    PAYOUT_PAID = "PAYOUT_PAID"
    RESERVE_RELEASED = "RESERVE_RELEASED"


# --- Entity TypedDicts ---
# Full first-class resources carry id + created_at + updated_at + version.

class Merchant(TypedDict):
    id: str
    legal_name: str
    mcc: str
    fee_plan_id: str
    onboarding_status: str
    risk_band: Optional[str]
    requested_monthly_volume_cents: int
    reserve_rate_bps: int
    funding_delay_days: int
    available_balance_cents: int
    reserved_balance_cents: int
    payout_method: str
    created_at: str
    updated_at: str
    version: int


class FeePlan(TypedDict):
    id: str
    name: str
    pricing_model: str
    flat_pct_bps: int
    flat_fixed_cents: int
    markup_pct_bps: int
    markup_fixed_cents: int
    volume_tier_threshold_cents: int
    discounted_markup_pct_bps: int
    chargeback_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    merchant_id: str
    auth_amount_cents: int
    captured_amount_cents: int
    refunded_amount_cents: int
    processing_fee_cents: int
    auth_status: str
    settlement_status: str
    settlement_batch_id: Optional[str]
    card_last4: str
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    charge_id: str
    amount_cents: int
    refund_status: str
    reason: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    charge_id: str
    disputed_amount_cents: int
    dispute_status: str
    representment_round: int
    evidence_due_at: str
    chargeback_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict):
    id: str
    merchant_id: str
    business_date: str
    batch_status: str
    gross_captured_cents: int
    total_fees_cents: int
    total_refunds_cents: int
    reserve_held_cents: int
    net_funding_cents: int
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    merchant_id: str
    amount_cents: int
    payout_status: str
    scheduled_for: str
    created_at: str
    updated_at: str
    version: int


class ReserveEntry(TypedDict):
    id: str
    merchant_id: str
    settlement_batch_id: str
    amount_cents: int
    release_date: str
    reserve_status: str
    created_at: str
    updated_at: str
    version: int


class Tax1099K(TypedDict):
    id: str
    merchant_id: str
    tax_year: int
    gross_amount_cents: int
    transaction_count: int
    reportable: bool
    created_at: str
    updated_at: str
    version: int


class RiskReview(TypedDict):
    id: str
    merchant_id: str
    decision: str
    assigned_risk_band: Optional[str]
    notes: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit records carry ONLY id + created_at (no updated_at, no version).

class LedgerEntry(TypedDict):
    id: str
    merchant_id: str
    account: str
    amount_cents: int
    entry_type: str
    source_type: str
    source_id: Optional[str]
    created_at: str


class WebhookEvent(TypedDict):
    id: str
    merchant_id: str
    event_type: str
    source_id: str
    idempotency_key: str
    created_at: str
