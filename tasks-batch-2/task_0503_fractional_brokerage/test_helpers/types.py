"""Domain types: entity TypedDicts, status enums, role enum.

Field names and the carried-field sets are taken directly from the PRD
(commission-free fractional brokerage). Two entities — Security and Fill —
are reference/immutable records that carry only id + created_at (no
updated_at / version per PRD §2.4); every other entity carries the full
common-field set.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class AccountType(str, Enum):
    CASH = "CASH"
    MARGIN = "MARGIN"


class TradingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED_CLOSING_ONLY = "RESTRICTED_CLOSING_ONLY"
    MARGIN_CALL = "MARGIN_CALL"
    FROZEN = "FROZEN"


class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"


class DepositStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderSession(str, Enum):
    REGULAR = "REGULAR"
    EXTENDED = "EXTENDED"


class OrderStatus(str, Enum):
    PENDING_NEW = "PENDING_NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PfofVenue(str, Enum):
    VENUE_A = "VENUE_A"
    VENUE_B = "VENUE_B"
    VENUE_C = "VENUE_C"


class SettlementDirection(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class CostBasisMethod(str, Enum):
    FIFO = "FIFO"
    AVERAGE = "AVERAGE"


class LotStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


class DisposalTerm(str, Enum):
    SHORT = "SHORT"
    LONG = "LONG"


class DividendStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    PAID = "PAID"
    REINVESTED = "REINVESTED"
    REVERSED = "REVERSED"


class OptionsApprovalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class MarginCallStatus(str, Enum):
    ISSUED = "ISSUED"
    MET = "MET"
    LIQUIDATED = "LIQUIDATED"


class UserRole(str, Enum):
    ACCOUNT_HOLDER = "AccountHolder"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLEARING_SYSTEM = "ClearingSystem"
    MARKET_DATA = "MarketData"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version)
# --------------------------------------------------------------------------
class Account(TypedDict, total=False):
    id: str
    holder_email: str
    account_type: str
    options_level: int
    trading_status: str
    settled_cash_cents: int
    unsettled_cash_cents: int
    instant_credit_cents: int
    buying_power_cents: int
    account_equity_cents: int
    maintenance_requirement_cents: int
    maintenance_excess_cents: int
    day_trade_count: int
    pdt_flagged: bool
    compliance_hold: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only (no updated_at, no version)
class Security(TypedDict, total=False):
    id: str
    symbol: str
    instrument_type: str
    last_price_cents: int
    fractional_enabled: bool
    maintenance_rate_bps: int
    required_options_level: int
    extended_hours_eligible: bool
    created_at: str


class Deposit(TypedDict, total=False):
    id: str
    account_id: str
    amount_cents: int
    instant_eligible: bool
    instant_credit_granted_cents: int
    status: str
    settles_on: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    account_id: str
    security_id: str
    side: str
    order_type: str
    notional_cents: int
    quantity: float
    limit_price_cents: int
    session: str
    is_closing: bool
    order_status: str
    filled_quantity: float
    filled_notional_cents: int
    reserved_buying_power_cents: int
    pfof_venue: str
    opened_day_trade: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only (no updated_at, no version)
class Fill(TypedDict, total=False):
    id: str
    order_id: str
    account_id: str
    fill_quantity: float
    fill_price_cents: int
    gross_value_cents: int
    pfof_rebate_cents: int
    settlement_id: str
    created_at: str


class Settlement(TypedDict, total=False):
    id: str
    account_id: str
    fill_id: str
    direction: str
    amount_cents: int
    settles_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict, total=False):
    id: str
    account_id: str
    security_id: str
    quantity: float
    average_cost_cents: int
    cost_basis_method: str
    market_value_cents: int
    realized_pl_cents: int
    drip_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    position_id: str
    acquired_at: str
    original_quantity: float
    remaining_quantity: float
    cost_per_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Disposal(TypedDict, total=False):
    id: str
    position_id: str
    fill_id: str
    lot_id: Optional[str]
    quantity: float
    proceeds_cents: int
    cost_basis_cents: int
    realized_pl_cents: int
    term: str
    created_at: str
    updated_at: str
    version: int


class DividendEvent(TypedDict, total=False):
    id: str
    account_id: str
    position_id: str
    rate_per_share_cents: int
    ex_date: str
    window_end: str
    record_quantity: float
    gross_amount_cents: int
    reinvest_quantity: float
    residual_cash_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OptionsApproval(TypedDict, total=False):
    id: str
    account_id: str
    requested_level: int
    stated_experience_years: int
    liquid_net_worth_cents: int
    granted_level: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MarginCall(TypedDict, total=False):
    id: str
    account_id: str
    deficiency_cents: int
    cure_by: str
    status: str
    created_at: str
    updated_at: str
    version: int
