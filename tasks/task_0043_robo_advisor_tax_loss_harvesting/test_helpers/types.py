"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §2.4)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles (PRD §2.1) ───────────────────────────────────────────────
class UserRole(str, Enum):
    ADVISOR = "Advisor"
    COMPLIANCE = "Compliance"


# ─── Status enums (PRD §3) ──────────────────────────────────────────
class AccountStatus(str, Enum):
    PENDING_PROFILE = "PENDING_PROFILE"
    ACTIVE = "ACTIVE"
    REBALANCE_DUE = "REBALANCE_DUE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class QuestionnaireStatus(str, Enum):
    SCORED = "SCORED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class TaxLotStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class HarvestEventStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class RebalanceEventStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class TaxFormStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class AssetClass(str, Enum):
    US_EQUITY = "US_EQUITY"
    INTL_EQUITY = "INTL_EQUITY"
    BOND = "BOND"
    REIT = "REIT"
    COMMODITY = "COMMODITY"


class LotSelection(str, Enum):
    FIFO = "FIFO"
    HIFO = "HIFO"


# ─── Entity TypedDicts (PRD §3, §2.4) ───────────────────────────────
# Security carries common fields (id, created_at, updated_at, version) per PRD §2.4.
class Security(TypedDict):
    id: str
    ticker: str
    asset_class: str
    price_cents: int
    correlated_with: List[dict]
    is_active: bool
    created_at: str
    updated_at: str
    version: int


# ModelPortfolio carries common fields per PRD §2.4.
class ModelPortfolio(TypedDict):
    id: str
    name: str
    min_risk_score: int
    max_risk_score: int
    targets: List[dict]
    drift_threshold_pct: int
    lot_selection: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


# Account carries common fields per PRD §2.4.
class Account(TypedDict):
    id: str
    client_email: str
    model_portfolio_id: Optional[str]
    risk_score: Optional[int]
    status: str
    cash_balance_cents: int
    invested_value_cents: int
    total_value_cents: int
    max_drift_pct: int
    realized_gain_cents_ytd: int
    wash_sale_disallowed_cents_ytd: int
    created_at: str
    updated_at: str
    version: int


# RiskQuestionnaire is the sole common_fields=false entity (PRD §2.4):
# it carries ONLY id and created_at — no updated_at, no version.
class RiskQuestionnaire(TypedDict):
    id: str
    account_id: str
    horizon_years: int
    loss_tolerance: int
    liquidity_need: int
    income_band: int
    risk_score: int
    assigned_model_portfolio_id: str
    status: str
    created_at: str


# TaxLot carries common fields per PRD §2.4.
class TaxLot(TypedDict):
    id: str
    account_id: str
    security_id: str
    quantity: float
    cost_basis_cents: int
    acquired_at: str
    status: str
    market_value_cents: int
    unrealized_gain_cents: int
    disposed_at: Optional[str]
    proceeds_cents: Optional[int]
    realized_gain_cents: Optional[int]
    wash_sale_disallowed_cents: int
    closed_by_harvest_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# HarvestEvent carries common fields per PRD §2.4.
class HarvestEvent(TypedDict):
    id: str
    account_id: str
    source_lot_id: str
    replacement_security_id: str
    expected_account_version: int
    realized_loss_cents: int
    disallowed_loss_cents: int
    replacement_lot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# RebalanceEvent carries common fields per PRD §2.4.
class RebalanceEvent(TypedDict):
    id: str
    account_id: str
    expected_account_version: int
    quarter_label: str
    trades_count: int
    cash_consumed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# TaxForm1099B carries common fields per PRD §2.4.
class TaxForm1099B(TypedDict):
    id: str
    account_id: str
    tax_year: int
    total_proceeds_cents: int
    total_cost_basis_cents: int
    net_realized_gain_cents: int
    total_wash_sale_disallowed_cents: int
    line_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
