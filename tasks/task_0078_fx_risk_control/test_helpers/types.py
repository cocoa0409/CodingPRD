"""Domain types: entity TypedDicts, status enums, role enum.

Versioned entities (PRD §2.4) carry id + created_at + updated_at + version.
Append-only entities — Trade, ComplianceReport, AuditLog — carry only id +
created_at.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class TraderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LimitBucket(str, Enum):
    INTRADAY = "INTRADAY"
    OVERNIGHT = "OVERNIGHT"


class LimitAdjustmentRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    EXPIRED = "EXPIRED"


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, Enum):
    BOOKED = "BOOKED"
    NETTED = "NETTED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class WarningStatus(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    BREACH = "BREACH"


class StopLossRuleMode(str, Enum):
    PRICE = "PRICE"
    LOSS_AMOUNT = "LOSS_AMOUNT"
    LOSS_RATIO = "LOSS_RATIO"


class StopLossAction(str, Enum):
    ALERT = "ALERT"
    FORCED_FLATTEN = "FORCED_FLATTEN"


class StopLossState(str, Enum):
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OVERRIDDEN = "OVERRIDDEN"
    EXECUTED = "EXECUTED"
    ARCHIVED = "ARCHIVED"


class CounterpartyExternalRating(str, Enum):
    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"
    B = "B"
    CCC = "CCC"
    NR = "NR"


class CounterpartyRatingBand(str, Enum):
    INVESTMENT = "INVESTMENT"
    STANDARD = "STANDARD"
    SPECULATIVE = "SPECULATIVE"
    WATCH = "WATCH"


class SettlementInstructionStatus(str, Enum):
    GENERATED = "GENERATED"
    SENT = "SENT"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    RECONCILED = "RECONCILED"


class ComplianceReportType(str, Enum):
    LARGE_TRADE = "LARGE_TRADE"
    SUSPICIOUS_TRANSACTION = "SUSPICIOUS_TRANSACTION"
    INTERNAL_CONTROL = "INTERNAL_CONTROL"


class AuditEventType(str, Enum):
    LIMIT_CHANGE = "LIMIT_CHANGE"
    LIMIT_OVERRIDE_APPROVED = "LIMIT_OVERRIDE_APPROVED"
    LIMIT_OVERRIDE_EXPIRED = "LIMIT_OVERRIDE_EXPIRED"
    STOP_LOSS_TRIGGERED = "STOP_LOSS_TRIGGERED"
    STOP_LOSS_OVERRIDDEN = "STOP_LOSS_OVERRIDDEN"
    RATING_CHANGE = "RATING_CHANGE"
    TRADE_BOOKED = "TRADE_BOOKED"
    SETTLEMENT_FAILED = "SETTLEMENT_FAILED"
    REPORT_FILED = "REPORT_FILED"


class UserRole(str, Enum):
    Trader = "Trader"
    RiskOfficer = "RiskOfficer"
    ComplianceOfficer = "ComplianceOfficer"
    SettlementOperator = "SettlementOperator"
    MarketDataSystem = "MarketDataSystem"


class DeskCode(str, Enum):
    G10_SPOT = "G10_SPOT"
    EM_FX = "EM_FX"
    OPTIONS = "OPTIONS"


# ---------------------------------------------------------------------------
# Entity TypedDicts — versioned entities carry id, created_at, updated_at, version
# ---------------------------------------------------------------------------
class Trader(TypedDict):
    id: str
    name: str
    desk_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CurrencyPair(TypedDict):
    id: str
    code: str
    base_ccy: str
    quote_ccy: str
    mid_rate: float
    daily_volatility: float
    created_at: str
    updated_at: str
    version: int


class Limit(TypedDict):
    id: str
    trader_id: str
    pair_code: Optional[str]
    bucket: str
    notional_cap_usd: float
    stop_loss_cap_usd: float
    temporary_override_usd: float
    utilization_usd: float
    utilization_pct: float
    created_at: str
    updated_at: str
    version: int


class LimitAdjustmentRequest(TypedDict):
    id: str
    limit_id: str
    requested_delta_usd: float
    justification: str
    expires_at: str
    status: str
    requester_trader_id: str
    approver_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only — PRD §2.4: Trade carries only id and created_at.
class Trade(TypedDict):
    id: str
    trader_id: str
    pair_code: str
    side: str
    notional_base: float
    entry_rate: float
    executed_at: str
    trading_day: str
    counterparty_id: str
    status: str
    created_at: str


class Position(TypedDict):
    id: str
    trader_id: str
    pair_code: str
    net_base: float
    net_open_usd: float
    mtm_pnl_usd: float
    warning_status: str
    created_at: str
    updated_at: str
    version: int


class StopLossEvent(TypedDict):
    id: str
    trader_id: str
    pair_code: str
    rule_mode: str
    threshold_value: float
    action: str
    state: str
    triggered_at: Optional[str]
    triggering_value: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Counterparty(TypedDict):
    id: str
    name: str
    external_rating: str
    internal_score: int
    rating_band: str
    credit_limit_usd: float
    on_watchlist: bool
    created_at: str
    updated_at: str
    version: int


class SettlementInstruction(TypedDict):
    id: str
    counterparty_id: str
    value_date: str
    ccy: str
    gross_pay_amount: float
    gross_receive_amount: float
    net_amount: float
    status: str
    client_request_id: str
    nostro_balance_delta: float
    created_at: str
    updated_at: str
    version: int


# Append-only — PRD §2.4: ComplianceReport rows are never re-versioned in place;
# amendments are fresh rows with a higher version integer in the family.
class ComplianceReport(TypedDict):
    id: str
    report_type: str
    reference_trade_id: Optional[str]
    version: int
    payload: dict
    filed_at: str
    filed_by_user_id: str
    created_at: str


# Append-only — PRD §2.4: AuditLog rows carry only id and created_at.
class AuditLog(TypedDict):
    id: str
    event_type: str
    actor_user_id: str
    actor_role: str
    subject_entity: str
    subject_id: str
    before_snapshot: Optional[dict]
    after_snapshot: dict
    created_at: str


__all__ = [
    "TraderStatus",
    "LimitBucket",
    "LimitAdjustmentRequestStatus",
    "TradeSide",
    "TradeStatus",
    "WarningStatus",
    "StopLossRuleMode",
    "StopLossAction",
    "StopLossState",
    "CounterpartyExternalRating",
    "CounterpartyRatingBand",
    "SettlementInstructionStatus",
    "ComplianceReportType",
    "AuditEventType",
    "UserRole",
    "DeskCode",
    "Trader",
    "CurrencyPair",
    "Limit",
    "LimitAdjustmentRequest",
    "Trade",
    "Position",
    "StopLossEvent",
    "Counterparty",
    "SettlementInstruction",
    "ComplianceReport",
    "AuditLog",
]
