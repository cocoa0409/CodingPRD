"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full system field set (id, created_at,
updated_at, version) per the PRD's common-resource-properties section.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    INVESTOR = "Investor"
    CUSTODIAL_GUARDIAN = "CustodialGuardian"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ─────────────────────────────────────────────────────────
class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PortfolioStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class OfferStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class KycStatus(str, Enum):
    PENDING_KYC = "PENDING_KYC"
    VERIFIED = "VERIFIED"
    RESTRICTED = "RESTRICTED"


class BillingStatus(str, Enum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CLOSED = "CLOSED"


class CardStatus(str, Enum):
    LINKED = "LINKED"
    PAUSED = "PAUSED"
    UNLINKED = "UNLINKED"


class AccrualStatus(str, Enum):
    PENDING = "PENDING"
    SWEPT = "SWEPT"
    CANCELLED = "CANCELLED"


class ContributionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class BucketType(str, Enum):
    TAXABLE = "TAXABLE"
    UTMA = "UTMA"
    IRA = "IRA"


class BucketStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class OrderKind(str, Enum):
    INVEST = "INVEST"
    WITHDRAW = "WITHDRAW"


class OrderSource(str, Enum):
    SWEEP = "SWEEP"
    RECURRING = "RECURRING"
    FOUND_MONEY = "FOUND_MONEY"
    REFERRAL = "REFERRAL"
    MANUAL = "MANUAL"


class LotSelectionMethod(str, Enum):
    FIFO = "FIFO"
    HIFO = "HIFO"
    SPEC_ID = "SPEC_ID"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TaxLotStatus(str, Enum):
    OPEN = "OPEN"
    DEPLETED = "DEPLETED"


class RewardStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REVERSED = "REVERSED"


class ReferralStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    QUALIFIED = "QUALIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class RebateMode(str, Enum):
    PERCENT = "PERCENT"
    FLAT = "FLAT"


class TxType(str, Enum):
    SUBSCRIPTION_FEE = "SUBSCRIPTION_FEE"
    MANAGEMENT_FEE = "MANAGEMENT_FEE"
    REFERRAL_BONUS = "REFERRAL_BONUS"
    FOUND_MONEY = "FOUND_MONEY"
    WITHDRAW_PROCEEDS = "WITHDRAW_PROCEEDS"
    SWEEP_DEBIT = "SWEEP_DEBIT"
    CONTRIBUTION_DEPOSIT = "CONTRIBUTION_DEPOSIT"


class TxStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    VOID = "VOID"


# ─── Entity TypedDicts (all carry the full system field set) ──────────────
class SubscriptionPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    allows_custodial: bool
    allows_ira: bool
    management_fee_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ModelPortfolio(TypedDict):
    id: str
    risk_tier: int
    name: str
    target_allocation: Dict[str, int]
    drift_band_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FoundMoneyOffer(TypedDict):
    id: str
    brand_name: str
    rebate_mode: str
    rebate_percent_bps: Optional[int]
    rebate_flat_cents: Optional[int]
    max_rebate_cents: int
    min_spend_cents: int
    hold_days: int
    active_from: str
    active_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    email: str
    full_name: str
    plan_id: str
    model_portfolio_id: str
    kyc_status: str
    billing_status: str
    cash_balance_cents: int
    pending_roundup_cents: int
    lifetime_invested_cents: int
    referral_credits_cents: int
    months_billed: int
    sweep_threshold_cents: int
    created_at: str
    updated_at: str
    version: int


class LinkedCard(TypedDict):
    id: str
    account_id: str
    last_four: str
    roundup_multiplier: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RoundUpAccrual(TypedDict):
    id: str
    account_id: str
    linked_card_id: str
    purchase_amount_cents: int
    base_roundup_cents: int
    effective_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecurringContribution(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    cadence: str
    run_day_index: int
    next_run_at: str
    runs_completed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bucket(TypedDict):
    id: str
    account_id: str
    bucket_type: str
    beneficiary_name: Optional[str]
    ytd_ira_contributed_cents: int
    invested_principal_cents: int
    market_value_cents: int
    total_drift_bps: int
    needs_rebalance: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    account_id: str
    bucket_id: str
    order_kind: str
    source: str
    requested_amount_cents: int
    lot_selection_method: Optional[str]
    settled_amount_cents: int
    realized_gain_cents: int
    management_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxLot(TypedDict):
    id: str
    bucket_id: str
    open_order_id: str
    cost_basis_cents: int
    remaining_basis_cents: int
    unit_gain_ratio_bps: int
    market_value_cents: int
    acquired_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FoundMoneyReward(TypedDict):
    id: str
    account_id: str
    offer_id: str
    qualifying_spend_cents: int
    rebate_amount_cents: int
    eligible_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referrer_account_id: str
    referred_account_id: Optional[str]
    code: str
    bonus_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CashTransaction(TypedDict):
    id: str
    account_id: str
    tx_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
