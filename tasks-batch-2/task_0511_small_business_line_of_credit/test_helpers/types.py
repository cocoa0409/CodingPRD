"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Small-Business Line of Credit PRD (§2.4, §3.1-§3.8).
LedgerEntry is immutable (PRD §2.4 / §2.8): it carries only id + created_at —
no updated_at and no version.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────
class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    SERVICER = "Servicer"
    CREDIT_OFFICER = "CreditOfficer"


# ─── Status enums (PRD §3.1-§3.8) ─────────────────────────────────────
class MerchantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKLISTED = "BLOCKLISTED"


class BankFeedStatus(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    NEEDS_REVISION = "NEEDS_REVISION"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class PricingTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class CreditLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    CHARGED_OFF = "CHARGED_OFF"
    CLOSED = "CLOSED"


class RemittanceCadence(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"


class DrawStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    REPAID = "REPAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class RemittanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RemittanceFailureReason(str, Enum):
    NSF = "NSF"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"


class LineIncreaseStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RenewalOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class LedgerEntryType(str, Enum):
    DRAW_PRINCIPAL = "DRAW_PRINCIPAL"
    DRAW_FEE = "DRAW_FEE"
    PRINCIPAL_REPAYMENT = "PRINCIPAL_REPAYMENT"
    FEE_REPAYMENT = "FEE_REPAYMENT"
    WRITE_OFF = "WRITE_OFF"


# ─── Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ─
class Merchant(TypedDict):
    id: str
    legal_name: str
    ein: str
    state_code: str
    status: str
    monthly_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class BankFeed(TypedDict):
    id: str
    merchant_id: str
    plaid_item_id: str
    pulled_at: str
    avg_daily_balance_cents: int
    nsf_count_90d: int
    deposit_volume_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    merchant_id: str
    bank_feed_id: str
    requested_limit_cents: int
    submitted_by_user_id: Optional[str]
    status: str
    risk_score: Optional[int]
    approved_limit_cents: Optional[int]
    pricing_tier: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditLine(TypedDict):
    id: str
    application_id: str
    merchant_id: str
    credit_limit_cents: int
    pricing_tier: str
    fee_factor_bps: int
    remittance_cadence: str
    outstanding_principal_cents: int
    outstanding_fee_cents: int
    available_credit_cents: int
    nsf_strike_count: int
    status: str
    defaulted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Draw(TypedDict):
    id: str
    credit_line_id: str
    principal_cents: int
    fee_cents: int
    principal_repaid_cents: int
    fee_repaid_cents: int
    drawn_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict):
    id: str
    credit_line_id: str
    scheduled_for: str
    amount_cents: int
    principal_applied_cents: int
    fee_applied_cents: int
    attempt_count: int
    status: str
    failure_reason: Optional[str]
    next_retry_remittance_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineIncreaseRequest(TypedDict):
    id: str
    credit_line_id: str
    latest_bank_feed_id: str
    requested_limit_cents: int
    approved_limit_cents: Optional[int]
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalOffer(TypedDict):
    id: str
    credit_line_id: str
    new_fee_factor_bps: int
    term_days: int
    total_fee_cents: int
    equivalent_apr_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict):
    id: str
    credit_line_id: str
    period_start: str
    period_end: str
    opening_principal_cents: int
    draws_total_cents: int
    fees_assessed_cents: int
    remittances_total_cents: int
    closing_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only immutable ledger row: id + created_at ONLY.
class LedgerEntry(TypedDict):
    id: str
    credit_line_id: str
    draw_id: Optional[str]
    remittance_id: Optional[str]
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    created_at: str
