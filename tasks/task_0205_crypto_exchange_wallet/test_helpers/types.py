"""Domain types: entity TypedDicts, status enums, role enum.

All field names and statuses are PRD-exact (Crypto Exchange Wallet API PRD).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) -----------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    TRADER = "Trader"
    OPERATOR = "Operator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status enums (PRD §3) ----------------------------------------------------
class KycTier(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class KycStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class FeeTier(str, Enum):
    TIER_BASE = "TIER_BASE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class CostBasisMethod(str, Enum):
    FIFO = "FIFO"
    HIFO = "HIFO"


class DepositStatus(str, Enum):
    DETECTED = "DETECTED"
    CONFIRMING = "CONFIRMING"
    CREDITED = "CREDITED"
    ORPHANED = "ORPHANED"


class WithdrawalAddressStatus(str, Enum):
    PENDING_HOLD = "PENDING_HOLD"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class WithdrawalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    TRAVEL_RULE_HOLD = "TRAVEL_RULE_HOLD"
    APPROVED = "APPROVED"
    BROADCAST = "BROADCAST"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class TravelRuleRecordStatus(str, Enum):
    FILED = "FILED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"


class OrderLifecycleStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class CostBasisLotOriginType(str, Enum):
    DEPOSIT = "DEPOSIT"
    TRADE_BUY = "TRADE_BUY"
    STAKING_REWARD = "STAKING_REWARD"


class CostBasisLotStatus(str, Enum):
    OPEN = "OPEN"
    DEPLETED = "DEPLETED"


class StakingPositionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNBONDING = "UNBONDING"
    CLOSED = "CLOSED"


# --- Entity TypedDicts --------------------------------------------------------
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at ONLY (no updated_at, no version)

# Account — common_fields: true
class Account(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    residence_country: str
    kyc_tier: str
    kyc_status: str
    pending_tier: Optional[str]
    account_status: str
    maker_volume_30d_usd: float
    taker_volume_30d_usd: float
    fee_tier: str
    cost_basis_method: str
    created_at: str
    updated_at: str
    version: int


# AssetConfig — common_fields: false (id + created_at only)
class AssetConfig(TypedDict, total=False):
    id: str
    symbol: str
    decimals: int
    required_confirmations: int
    is_fiat: bool
    min_withdrawal_amount: float
    network_fee: float
    spot_price_usd: float
    created_at: str


# FeeSchedule — common_fields: false (id + created_at only)
class FeeSchedule(TypedDict, total=False):
    id: str
    tier_name: str
    min_taker_volume_30d_usd: float
    maker_fee_bps: float
    taker_fee_bps: float
    created_at: str


# Balance — common_fields: true
class Balance(TypedDict, total=False):
    id: str
    account_id: str
    asset: str
    total_amount: float
    reserved_amount: float
    held_amount: float
    available_amount: float
    created_at: str
    updated_at: str
    version: int


# WithdrawalAddress — common_fields: true
class WithdrawalAddress(TypedDict, total=False):
    id: str
    account_id: str
    asset: str
    chain_address: str
    label: str
    status: str
    activates_at: str
    created_at: str
    updated_at: str
    version: int


# Deposit — common_fields: true
class Deposit(TypedDict, total=False):
    id: str
    account_id: str
    asset: str
    amount: float
    confirmations: int
    unit_cost_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Withdrawal — common_fields: true
class Withdrawal(TypedDict, total=False):
    id: str
    account_id: str
    withdrawal_address_id: str
    asset: str
    amount: float
    notional_usd: float
    requires_travel_rule: bool
    replaces_withdrawal_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# TravelRuleRecord — common_fields: true
class TravelRuleRecord(TypedDict, total=False):
    id: str
    withdrawal_id: str
    originator_name: str
    beneficiary_name: str
    beneficiary_vasp: str
    filed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Order — common_fields: true
class Order(TypedDict, total=False):
    id: str
    account_id: str
    base_asset: str
    quote_asset: str
    side: str
    order_type: str
    limit_price: Optional[float]
    quantity: float
    filled_quantity: float
    avg_fill_price: Optional[float]
    reserved_remaining: float
    lifecycle_status: str
    time_in_force: str
    created_at: str
    updated_at: str
    version: int


# Trade — common_fields: false (id + created_at only — append-only execution record)
class Trade(TypedDict, total=False):
    id: str
    maker_order_id: str
    taker_order_id: str
    base_asset: str
    quote_asset: str
    price: float
    quantity: float
    notional_usd: float
    maker_fee: float
    taker_fee: float
    executed_at: str
    created_at: str


# CostBasisLot — common_fields: true
class CostBasisLot(TypedDict, total=False):
    id: str
    account_id: str
    asset: str
    origin_type: str
    origin_id: str
    acquired_at: str
    original_quantity: float
    remaining_quantity: float
    unit_cost_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


# StakingPosition — common_fields: true
class StakingPosition(TypedDict, total=False):
    id: str
    account_id: str
    asset: str
    principal_amount: float
    apr_bps: float
    accrued_rewards: float
    last_accrual_at: str
    status: str
    unbond_started_at: Optional[str]
    unbond_available_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
