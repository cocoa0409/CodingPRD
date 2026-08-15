"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class CallType(str, Enum):
    FED_REG_T = "FED_REG_T"
    MAINTENANCE = "MAINTENANCE"
    HOUSE = "HOUSE"
    DAY_TRADE_MIN_EQUITY = "DAY_TRADE_MIN_EQUITY"


class CallStatus(str, Enum):
    OPEN = "OPEN"
    DISPUTED = "DISPUTED"
    EXPIRED = "EXPIRED"
    LIQUIDATION_IN_PROGRESS = "LIQUIDATION_IN_PROGRESS"
    CURED = "CURED"
    WAIVED = "WAIVED"


class CureMethod(str, Enum):
    DEPOSIT = "DEPOSIT"
    MARKET_RECOVERY = "MARKET_RECOVERY"
    LIQUIDATION = "LIQUIDATION"
    WAIVER = "WAIVER"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    SELL_SHORT = "SELL_SHORT"
    BUY_TO_COVER = "BUY_TO_COVER"


class MarkType(str, Enum):
    REALTIME = "REALTIME"
    OFFICIAL_CLOSE = "OFFICIAL_CLOSE"


class LiquidationOrderStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class CashMovementType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    JOURNAL_CREDIT = "JOURNAL_CREDIT"
    JOURNAL_DEBIT = "JOURNAL_DEBIT"


class InterestEntryType(str, Enum):
    DAILY_ACCRUAL = "DAILY_ACCRUAL"
    MONTHLY_POST = "MONTHLY_POST"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    CLOSED = "CLOSED"


class DisputeDecision(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    MARGIN_ANALYST = "MarginAnalyst"
    MARGIN_SUPERVISOR = "MarginSupervisor"
    LIQUIDATION_DESK = "LiquidationDesk"
    MARKET_DATA_OPS = "MarketDataOps"


# ----- Primary resources (id + created_at + updated_at + version) -----


class Customer(TypedDict):
    id: str
    legal_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class AccountApplication(TypedDict):
    id: str
    customer_id: str
    annual_income_cents: int
    liquid_net_worth_cents: int
    investment_experience_years: int
    application_status: str
    reviewed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    account_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarginAccount(TypedDict):
    id: str
    customer_id: str
    application_id: str
    account_status: str
    cash_balance_cents: int
    equity_realtime_cents: int
    equity_official_cents: int
    reg_req_official_cents: int
    house_req_official_cents: int
    reg_req_realtime_cents: int
    house_req_realtime_cents: int
    buying_power_cents: int
    pdt_flag: bool
    pdt_flagged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecurityProfile(TypedDict):
    id: str
    symbol: str
    marginable: bool
    house_maint_long_bps: int
    house_maint_short_bps: int
    liquidity_tier: int
    concentration_threshold_bps: int
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict):
    id: str
    account_id: str
    security_id: str
    quantity: int
    avg_cost_cents: int
    mv_realtime_cents: int
    mv_official_cents: int
    reserved_qty: int
    opened_at: str
    today_bought_qty: int
    today_sold_qty: int
    last_trade_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarginCall(TypedDict):
    id: str
    account_id: str
    call_type: str
    call_status: str
    call_amount_cents: int
    issued_at: str
    due_at: str
    resolved_at: Optional[str]
    cure_method: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiquidationOrder(TypedDict):
    id: str
    account_id: str
    call_id: str
    position_id: str
    quantity: int
    filled_quantity: int
    proceeds_cents: int
    order_status: str
    created_by_user_id: str
    last_filled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CashMovement(TypedDict):
    id: str
    account_id: str
    movement_type: str
    amount_cents: int
    resulting_cash_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RateTier(TypedDict):
    id: str
    tier_level: int
    min_balance_cents: int
    annual_rate_bps: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    account_id: str
    call_id: str
    reason: str
    dispute_status: str
    reviewed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ----- Ledger-style records (id + created_at ONLY; no updated_at, no version) -----


class TradeFill(TypedDict):
    id: str
    created_at: str
    account_id: str
    security_id: str
    side: str
    quantity: int
    price_cents: int
    fill_date: str
    is_day_trade: bool


class DayTradeEvent(TypedDict):
    id: str
    created_at: str
    account_id: str
    security_id: str
    event_date: str


class PriceMark(TypedDict):
    id: str
    created_at: str
    security_id: str
    mark_type: str
    price_cents: int
    marked_at: str


class InterestLedgerEntry(TypedDict):
    id: str
    created_at: str
    account_id: str
    entry_type: str
    accrual_date: str
    debit_balance_snapshot_cents: int
    rate_bps_applied: int
    amount_cents: int
    posted: bool
