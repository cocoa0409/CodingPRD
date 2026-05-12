"""Domain types for the Fund Sales and Clearing test suite.

Status enums and entity TypedDicts are derived directly from PRD §3 and the
entity definitions referenced in PRD §2.4 / §2.6 / §2.8. Each TypedDict's
shape mirrors the PRD prose:

  - Common-fields entities (Investor, Fund, Order, Holding, DividendPlan,
    ReconciliationRun) carry id + created_at + updated_at + version.

  - Append-only / snapshot entities (NavSnapshot, LotEntry,
    DividendDistribution, ReconciliationException, SettlementInstruction,
    AuditLog, Clock) carry only id + created_at and never expose
    updated_at / version (PRD §2.4).
"""
from __future__ import annotations
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ===========================================================================
# Roles (PRD §2.1)
# ===========================================================================
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCT_OPERATOR = "ProductOperator"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    NAV_OPERATOR = "NavOperator"
    CLEARING_OPERATOR = "ClearingOperator"
    INVESTOR = "Investor"


# ===========================================================================
# Investor enums (PRD §3.1)
# ===========================================================================
class InvestorType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    INSTITUTIONAL = "INSTITUTIONAL"


class RiskTolerance(str, Enum):
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"
    C5 = "C5"


class TaxResidentStatus(str, Enum):
    DOMESTIC = "DOMESTIC"
    FOREIGN = "FOREIGN"
    EXEMPT = "EXEMPT"


class KycStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ===========================================================================
# Fund enums (PRD §3.2)
# ===========================================================================
class FundType(str, Enum):
    EQUITY = "EQUITY"
    BOND = "BOND"
    HYBRID = "HYBRID"
    MONEY_MARKET = "MONEY_MARKET"
    QDII = "QDII"


class RiskRating(str, Enum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


class FundStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    ON_SHELF = "ON_SHELF"
    SUSPENDED = "SUSPENDED"
    OFF_SHELF = "OFF_SHELF"


# ===========================================================================
# Order enums (PRD §3.3, §3.4)
# ===========================================================================
class OrderType(str, Enum):
    SUBSCRIBE = "SUBSCRIBE"
    REDEEM = "REDEEM"
    CONVERT = "CONVERT"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    LARGE_REDEMPTION_DEFERRED = "LARGE_REDEMPTION_DEFERRED"


# ===========================================================================
# NAV / LotEntry / Dividend enums (PRD §3.4, §3.5, §3.6)
# ===========================================================================
class NavStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    PUBLISHED = "PUBLISHED"
    ADJUSTED = "ADJUSTED"


class LotEntryStatus(str, Enum):
    OPEN = "OPEN"
    DEPLETED = "DEPLETED"


class DividendPlanStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    EX_DIVIDEND = "EX_DIVIDEND"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class DividendOption(str, Enum):
    CASH = "CASH"
    REINVEST = "REINVEST"


# ===========================================================================
# Reconciliation enums (PRD §3.7)
# ===========================================================================
class ReconciliationScope(str, Enum):
    TA_VS_CUSTODIAN = "TA_VS_CUSTODIAN"
    TA_VS_CHANNEL = "TA_VS_CHANNEL"
    TA_VS_BANK = "TA_VS_BANK"


class ReconciliationRunStatus(str, Enum):
    OPEN = "OPEN"
    EXCEPTIONS_FOUND = "EXCEPTIONS_FOUND"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ReconciliationExceptionKind(str, Enum):
    MISSING_INTERNAL = "MISSING_INTERNAL"
    MISSING_EXTERNAL = "MISSING_EXTERNAL"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    SHARE_MISMATCH = "SHARE_MISMATCH"


class ExceptionResolutionStatus(str, Enum):
    OPEN = "OPEN"
    ADJUSTED = "ADJUSTED"
    WAIVED = "WAIVED"


class SettlementTargetSystem(str, Enum):
    BANK = "BANK"
    CUSTODIAN = "CUSTODIAN"
    TA = "TA"
    REGULATOR = "REGULATOR"


class SettlementInstructionType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
    TRANSFER = "TRANSFER"
    REPORT = "REPORT"


# ===========================================================================
# Audit (PRD §2.8, §3.8)
# ===========================================================================
class AuditAction(str, Enum):
    ORDER_STATUS_CHANGE = "ORDER_STATUS_CHANGE"
    NAV_PUBLISHED = "NAV_PUBLISHED"
    NAV_ADJUSTED = "NAV_ADJUSTED"
    DIVIDEND_EXECUTED = "DIVIDEND_EXECUTED"
    RECONCILIATION_RESOLVED = "RECONCILIATION_RESOLVED"
    FUND_SHELF_CHANGE = "FUND_SHELF_CHANGE"


# ===========================================================================
# Common-fields entities (PRD §2.4: id + created_at + updated_at + version)
# ===========================================================================
class Investor(TypedDict, total=False):
    id: str
    legal_name: str
    investor_type: str
    country_code: str
    risk_tolerance: str
    tax_resident_status: str
    kyc_status: str
    bank_account_number: str
    cash_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeTier(TypedDict, total=False):
    min_amount_cents: int
    max_amount_cents: Optional[int]
    rate_bps: int


class HoldingPeriodTier(TypedDict, total=False):
    min_holding_days: int
    max_holding_days: Optional[int]
    rate_bps: int


class Fund(TypedDict, total=False):
    id: str
    fund_code: str
    fund_name: str
    fund_type: str
    risk_rating: str
    allowed_country_codes: List[str]
    status: str
    shelf_review_actor_id: Optional[str]
    shelf_creator_actor_id: Optional[str]
    management_fee_bps_annual: int
    custodian_fee_bps_annual: int
    sales_service_fee_bps_annual: int
    subscription_fee_tiers: List[FeeTier]
    redemption_fee_tiers: List[HoldingPeriodTier]
    back_end_load_enabled: bool
    conversion_fee_bps: int
    large_redemption_threshold_pct_bps: int
    min_subscription_amount_cents: int
    max_subscription_amount_cents: Optional[int]
    min_redemption_shares: int
    confirmation_cycle_days: int
    total_outstanding_shares: int
    portfolio_market_value_cents: int
    portfolio_accrued_income_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    fund_id: str
    investor_id: str
    order_type: str
    target_fund_id: Optional[str]
    gross_amount_cents: Optional[int]
    requested_shares: Optional[int]
    submitted_at: str
    trade_date: str
    confirm_date: str
    status: str
    confirmed_nav_per_share_micros: Optional[int]
    confirmed_shares: Optional[int]
    confirmed_amount_cents: Optional[int]
    subscription_fee_cents: Optional[int]
    redemption_fee_cents: Optional[int]
    back_end_load_fee_cents: Optional[int]
    conversion_fee_cents: Optional[int]
    large_redemption_pct_bps: Optional[int]
    rejection_error_id: Optional[str]
    idempotency_key: str
    created_at: str
    updated_at: str
    version: int


class Holding(TypedDict, total=False):
    id: str
    investor_id: str
    fund_id: str
    shares: int
    cost_basis_cents: int
    created_at: str
    updated_at: str
    version: int


class DividendPlan(TypedDict, total=False):
    id: str
    fund_id: str
    announcement_date: str
    record_date: str
    ex_dividend_date: str
    payment_date: str
    dividend_per_share_micros: int
    status: str
    tax_rate_bps_domestic: int
    tax_rate_bps_foreign: int
    created_at: str
    updated_at: str
    version: int


class ReconciliationRun(TypedDict, total=False):
    id: str
    as_of_date: str
    scope: str
    external_records: List[dict]
    status: str
    total_internal_amount_cents: int
    total_external_amount_cents: int
    net_break_cents: int
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only entities (PRD §2.4: ONLY id + created_at, no updated_at/version)
# ===========================================================================
class NavSnapshot(TypedDict, total=False):
    id: str
    fund_id: str
    nav_date: str
    published_at: Optional[str]
    gross_assets_cents: int
    management_fee_accrued_cents: int
    custodian_fee_accrued_cents: int
    sales_service_fee_accrued_cents: int
    net_assets_cents: int
    shares_outstanding_at_nav: int
    nav_per_share_micros: int
    status: str
    adjustment_reason: Optional[str]
    created_at: str


class LotEntry(TypedDict, total=False):
    id: str
    holding_id: str
    order_id: str
    acquired_at: str
    shares: int
    cost_cents: int
    status: str
    created_at: str


class DividendDistribution(TypedDict, total=False):
    id: str
    dividend_plan_id: str
    investor_id: str
    eligible_shares: int
    gross_dividend_cents: int
    tax_withheld_cents: int
    net_dividend_cents: int
    option: str
    reinvested_shares: int
    created_at: str


class ReconciliationException(TypedDict, total=False):
    id: str
    reconciliation_run_id: str
    ref_id: str
    kind: str
    internal_amount_cents: Optional[int]
    external_amount_cents: Optional[int]
    resolution_status: str
    adjustment_amount_cents: Optional[int]
    created_at: str


class SettlementInstruction(TypedDict, total=False):
    id: str
    reconciliation_run_id: str
    target_system: str
    instruction_type: str
    amount_cents: int
    dispatched_at: str
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_user_id: str
    actor_role: str
    action: str
    subject_entity: str
    subject_id: str
    from_state: Optional[str]
    to_state: Optional[str]
    payload_json: Any
    created_at: str


class Clock(TypedDict, total=False):
    id: str
    now: str
    created_at: str


__all__ = [
    "UserRole",
    "InvestorType",
    "RiskTolerance",
    "TaxResidentStatus",
    "KycStatus",
    "FundType",
    "RiskRating",
    "FundStatus",
    "OrderType",
    "OrderStatus",
    "NavStatus",
    "LotEntryStatus",
    "DividendPlanStatus",
    "DividendOption",
    "ReconciliationScope",
    "ReconciliationRunStatus",
    "ReconciliationExceptionKind",
    "ExceptionResolutionStatus",
    "SettlementTargetSystem",
    "SettlementInstructionType",
    "AuditAction",
    "FeeTier",
    "HoldingPeriodTier",
    "Investor",
    "Fund",
    "Order",
    "Holding",
    "DividendPlan",
    "ReconciliationRun",
    "NavSnapshot",
    "LotEntry",
    "DividendDistribution",
    "ReconciliationException",
    "SettlementInstruction",
    "AuditLog",
    "Clock",
]
