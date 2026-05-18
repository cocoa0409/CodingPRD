"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Persisted resources carrying id + created_at + updated_at + version:
  Client, Account, Position, Lot, Trade, HarvestOpportunity,
  RebalanceRun, Form1099B.
- Append-only / immutable association entities carrying ONLY id +
  created_at: RiskQuestionnaire, ModelPortfolio, Security,
  CorrelationLink, WashSaleEvent, DividendEvent.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CLIENT_USER = "ClientUser"
    ADVISOR = "Advisor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TAX_ADMIN = "TaxAdmin"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class ClientKycStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RiskBand(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    MODERATE = "MODERATE"
    AGGRESSIVE = "AGGRESSIVE"


class HorizonBand(str, Enum):
    SHORT = "SHORT"
    MID = "MID"
    LONG = "LONG"


class ScoringMethod(str, Enum):
    STANDARD = "STANDARD"
    AGE_ADJUSTED = "AGE_ADJUSTED"


class AssetClass(str, Enum):
    US_EQUITY = "US_EQUITY"
    INTL_EQUITY = "INTL_EQUITY"
    US_BOND = "US_BOND"
    INTL_BOND = "INTL_BOND"
    CASH = "CASH"


class AccountComplianceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN_DOC_REVIEW = "FROZEN_DOC_REVIEW"


class AccountInvestmentStatus(str, Enum):
    ACCUMULATING = "ACCUMULATING"
    REBALANCING = "REBALANCING"
    HARVESTING = "HARVESTING"


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class CostBasisMethod(str, Enum):
    FIFO = "FIFO"
    SPECIFIC_LOT = "SPECIFIC_LOT"


class TradeStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class LotStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


class HarvestOpportunityStatus(str, Enum):
    DETECTED = "DETECTED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    DISMISSED = "DISMISSED"
    BLOCKED = "BLOCKED"


class RebalanceRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED_BY_WASH_SALE = "BLOCKED_BY_WASH_SALE"
    FAILED = "FAILED"


class Form1099BStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version — PRD §2.4
# ---------------------------------------------------------------------------
class Client(TypedDict, total=False):
    id: str
    full_name: str
    birth_date: str
    age: int
    kyc_status: str
    risk_band: Optional[str]
    time_horizon_years: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    client_id: str
    model_portfolio_id: Optional[str]
    cash_balance_cents: int
    compliance_status: str
    investment_status: str
    max_drift_pct: float
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict, total=False):
    id: str
    account_id: str
    security_id: str
    shares: float
    total_cost_basis_cents: int
    market_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    position_id: str
    buy_trade_id: str
    acquired_at: str
    shares_opened: float
    shares_remaining: float
    unit_cost_cents: int
    adjusted_unit_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Trade(TypedDict, total=False):
    id: str
    account_id: str
    security_id: str
    side: str
    requested_shares: float
    cost_basis_method: Optional[str]
    specific_lot_id: Optional[str]
    rebalance_run_id: Optional[str]
    status: str
    executed_at: Optional[str]
    execution_price_cents: Optional[int]
    gross_proceeds_cents: Optional[int]
    realized_gain_loss_cents: Optional[int]
    disallowed_loss_cents: int
    created_at: str
    updated_at: str
    version: int


class HarvestOpportunity(TypedDict, total=False):
    id: str
    account_id: str
    position_id: str
    unrealized_loss_cents: int
    replacement_security_id: Optional[str]
    status: str
    detected_at: str
    created_at: str
    updated_at: str
    version: int


class RebalanceRun(TypedDict, total=False):
    id: str
    account_id: str
    quarter_key: str
    max_drift_pct_at_start: float
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Form1099B(TypedDict, total=False):
    id: str
    client_id: str
    tax_year: int
    short_term_proceeds_cents: int
    short_term_cost_basis_cents: int
    short_term_realized_gain_loss_cents: int
    long_term_proceeds_cents: int
    long_term_cost_basis_cents: int
    long_term_realized_gain_loss_cents: int
    total_disallowed_wash_sale_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only / immutable entities — id + created_at ONLY (no updated_at,
# no version). PRD §2.4: "Append-only or immutable association entities —
# RiskQuestionnaire, ModelPortfolio, Security, CorrelationLink,
# WashSaleEvent, DividendEvent — carry only id and created_at".
# ---------------------------------------------------------------------------
class RiskQuestionnaire(TypedDict, total=False):
    id: str
    client_id: str
    submitted_at: str
    q1_loss_tolerance: int
    q2_volatility_comfort: int
    q3_growth_vs_stability: int
    q4_liquidity_need: int
    q5_experience: int
    scoring_method: str
    raw_score: int
    assigned_band: str
    created_at: str


class ModelPortfolio(TypedDict, total=False):
    id: str
    risk_band: str
    horizon_band: str
    target_allocation: dict
    is_active: bool
    created_at: str


class Security(TypedDict, total=False):
    id: str
    ticker: str
    asset_class: str
    substantially_identical_group_id: str
    is_investable: bool
    last_price_cents: int
    created_at: str


class CorrelationLink(TypedDict, total=False):
    id: str
    security_a_id: str
    security_b_id: str
    correlation: float
    created_at: str


class WashSaleEvent(TypedDict, total=False):
    id: str
    sell_trade_id: str
    replacement_trade_id: str
    group_id: str
    matched_shares: float
    disallowed_loss_cents: int
    replacement_lot_id: str
    recorded_at: str
    created_at: str


class DividendEvent(TypedDict, total=False):
    id: str
    account_id: str
    security_id: str
    amount_cents: int
    received_at: str
    reinvest_trade_id: Optional[str]
    created_at: str


__all__ = [
    "UserRole",
    "ClientKycStatus",
    "RiskBand",
    "HorizonBand",
    "ScoringMethod",
    "AssetClass",
    "AccountComplianceStatus",
    "AccountInvestmentStatus",
    "TradeSide",
    "CostBasisMethod",
    "TradeStatus",
    "LotStatus",
    "HarvestOpportunityStatus",
    "RebalanceRunStatus",
    "Form1099BStatus",
    "Client",
    "Account",
    "Position",
    "Lot",
    "Trade",
    "HarvestOpportunity",
    "RebalanceRun",
    "Form1099B",
    "RiskQuestionnaire",
    "ModelPortfolio",
    "Security",
    "CorrelationLink",
    "WashSaleEvent",
    "DividendEvent",
]
