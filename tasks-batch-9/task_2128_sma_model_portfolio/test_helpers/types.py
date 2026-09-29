"""Domain types for the SMA Model Delivery API: entity TypedDicts, status enums,
role enum. Every persisted resource carries id / created_at / updated_at / version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PORTFOLIO_MANAGER = "PortfolioManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SPONSOR_OPERATOR = "SponsorOperator"
    BILLING_OFFICER = "BillingOfficer"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class AssetClass(str, Enum):
    US_EQUITY = "US_EQUITY"
    GLOBAL_EQUITY = "GLOBAL_EQUITY"
    FIXED_INCOME = "FIXED_INCOME"
    CASH_EQUIV = "CASH_EQUIV"


class ModelVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class DistributionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class ImplementationStatus(str, Enum):
    PENDING_IMPLEMENTATION = "PENDING_IMPLEMENTATION"
    SYNCED = "SYNCED"
    DRIFTED = "DRIFTED"
    SUSPENDED = "SUSPENDED"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    INVOICED = "INVOICED"
    DELINQUENT = "DELINQUENT"
    WRITTEN_OFF = "WRITTEN_OFF"


class DriftBasis(str, Enum):
    SETTLED = "SETTLED"
    TRADE_DATE = "TRADE_DATE"


class DispersionBasis(str, Enum):
    EQUAL_WEIGHTED = "EQUAL_WEIGHTED"
    ASSET_WEIGHTED = "ASSET_WEIGHTED"


class RestrictionType(str, Enum):
    DO_NOT_BUY = "DO_NOT_BUY"
    DO_NOT_HOLD = "DO_NOT_HOLD"
    MAX_POSITION = "MAX_POSITION"


class RestrictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class TradeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    BLOCKED = "BLOCKED"
    ALLOCATED = "ALLOCATED"
    CANCELLED = "CANCELLED"
    STALE = "STALE"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderSource(str, Enum):
    IMPLEMENTATION = "IMPLEMENTATION"
    REBALANCE = "REBALANCE"


class BlockStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    ALLOCATED = "ALLOCATED"


class TaxLotStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REVERSED = "REVERSED"


class TaxLotOrigin(str, Enum):
    TRANSFER_IN = "TRANSFER_IN"
    TRADE = "TRADE"


class HarvestProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"
    WRITTEN_OFF = "WRITTEN_OFF"


# ---------------------------------------------------------------------------
# Entity shapes — every resource carries the four housekeeping properties
# ---------------------------------------------------------------------------
class Security(TypedDict):
    id: str
    ticker: str
    name: str
    asset_class: str
    last_price_cents: int
    restricted_globally: bool
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict):
    id: str
    name: str
    platform_code: str
    revenue_share_bps: int
    implementation_lag_days: int
    min_account_value_cents: int
    account_count: int
    created_at: str
    updated_at: str
    version: int


class Model(TypedDict):
    id: str
    manager_name: str
    name: str
    strategy_code: str
    asset_class: str
    base_fee_bps: int
    drift_threshold_bps: int
    published_model_version_id: Optional[str]
    version_count: int
    created_at: str
    updated_at: str
    version: int


class Sleeve(TypedDict):
    security_id: str
    target_weight_bps: int
    max_position_bps: int


class ModelVersion(TypedDict):
    id: str
    model_id: str
    version_number: int
    status: str
    sleeves: List[Sleeve]
    sleeve_count: int
    total_target_weight_bps: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_note: Optional[str]
    published_at: Optional[str]
    superseded_at: Optional[str]
    distribution_count: int
    created_at: str
    updated_at: str
    version: int


class SponsorDistribution(TypedDict):
    id: str
    sponsor_id: str
    model_version_id: str
    model_id: str
    status: str
    effective_from: str
    effective_until: Optional[str]
    activated_at: Optional[str]
    lapsed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    sponsor_id: str
    model_id: str
    account_number: str
    current_model_version_id: Optional[str]
    pending_model_version_id: Optional[str]
    implementation_status: str
    billing_status: str
    cash_cents: int
    cash_reserve_bps: int
    market_value_cents: int
    drift_basis: str
    drift_bps: Optional[int]
    drift_basis_used: Optional[str]
    drift_evaluated_at: Optional[str]
    tax_overlay_enabled: bool
    harvest_budget_cents: int
    realized_loss_ytd_cents: int
    fees_billed_ytd_cents: int
    notified_at: Optional[str]
    implementation_deadline: Optional[str]
    last_implementation_lag_days: Optional[int]
    implemented_late: bool
    latest_return_bps: Optional[int]
    latest_return_period_end: Optional[str]
    latest_ending_value_cents: Optional[int]
    next_order_sequence: int
    created_at: str
    updated_at: str
    version: int


class AccountRestriction(TypedDict):
    id: str
    account_id: str
    security_id: str
    restriction_type: str
    max_position_bps: Optional[int]
    status: str
    lifted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeOrder(TypedDict):
    id: str
    account_id: str
    security_id: str
    model_version_id: str
    block_id: Optional[str]
    sequence_number: int
    side: str
    shares: int
    status: str
    source: str
    target_shares: int
    effective_weight_bps: int
    allocated_shares: int
    fill_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Block(TypedDict):
    id: str
    security_id: str
    side: str
    status: str
    requested_shares: int
    filled_shares: int
    allocated_shares: int
    unallocated_shares: int
    avg_fill_price_cents: Optional[int]
    order_count: int
    executed_at: Optional[str]
    allocated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxLot(TypedDict):
    id: str
    account_id: str
    security_id: str
    parent_tax_lot_id: Optional[str]
    opening_trade_order_id: Optional[str]
    closing_trade_order_id: Optional[str]
    sequence_number: int
    origin: str
    open_date: str
    shares_open: int
    shares_closed: int
    cost_basis_cents: int
    status: str
    realized_gain_cents: Optional[int]
    close_date: Optional[str]
    wash_window_start: Optional[str]
    wash_window_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HarvestProposal(TypedDict):
    id: str
    account_id: str
    security_id: str
    replacement_security_id: Optional[str]
    shares: int
    status: str
    quoted_price_cents: int
    target_loss_cents: int
    proposed_loss_cents: int
    realized_loss_cents: Optional[int]
    approved_by_user_id: Optional[str]
    rejection_note: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict):
    id: str
    account_id: str
    period_start: str
    period_end: str
    billing_days: int
    average_daily_value_cents: int
    tier1_fee_cents: int
    tier2_fee_cents: int
    tier3_fee_cents: int
    gross_fee_cents: int
    sponsor_share_cents: int
    platform_share_cents: int
    manager_share_cents: int
    status: str
    issued_at: Optional[str]
    paid_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
