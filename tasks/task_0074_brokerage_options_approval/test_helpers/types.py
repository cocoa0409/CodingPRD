"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ACCOUNT_HOLDER = "AccountHolder"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTODIAN = "Custodian"


class AccountStatus(str, Enum):
    PENDING_KYC = "PENDING_KYC"
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class MarginType(str, Enum):
    CASH = "CASH"
    REG_T = "REG_T"
    PMA = "PMA"


class InvestmentExperience(str, Enum):
    NONE = "NONE"
    LIMITED = "LIMITED"
    GOOD = "GOOD"
    EXTENSIVE = "EXTENSIVE"


class ApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    STOP = "STOP"
    TAKE_PROFIT = "TAKE_PROFIT"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"


class AcatStatus(str, Enum):
    REQUESTED = "REQUESTED"
    VALIDATED = "VALIDATED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class AcatDirection(str, Enum):
    IN = "IN"
    OUT = "OUT"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# --- Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ---

class Account(TypedDict):
    id: str
    account_holder_user_id: str
    legal_name: str
    tax_id: str
    date_of_birth: str
    w9_certified: bool
    liquid_net_worth_cents: int
    annual_income_cents: int
    investment_experience: str
    status: str
    options_level: int
    margin_type: str
    cash_balance_cents: int
    maintenance_margin_cents: int
    buying_power_cents: int
    equity_cents: int
    day_trade_count: int
    pdt_flagged: bool
    created_at: str
    updated_at: str
    version: int


class OptionsApproval(TypedDict):
    id: str
    account_id: str
    requested_level: int
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarginUpgrade(TypedDict):
    id: str
    account_id: str
    requested_margin_type: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict):
    id: str
    account_id: str
    symbol: str
    instrument_type: str
    quantity: int
    market_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    account_id: str
    symbol: str
    instrument_type: str
    side: str
    order_type: str
    quantity: int
    limit_price_cents: Optional[int]
    stop_price_cents: Optional[int]
    notional_cents: int
    opened_position_same_day: bool
    trade_date: str
    status: str
    filled_quantity: int
    created_at: str
    updated_at: str
    version: int


class AcatTransfer(TypedDict):
    id: str
    account_id: str
    direction: str
    counterparty_dtc: str
    transfer_value_cents: int
    status: str
    reject_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false → append-only event row, ONLY id + created_at
class DayTrade(TypedDict):
    id: str
    account_id: str
    closing_order_id: str
    symbol: str
    trade_date: str
    created_at: str
