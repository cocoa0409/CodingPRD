"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PORTFOLIO_DIRECTOR = "PortfolioDirector"
    ASSET_MANAGER = "AssetManager"
    PROPERTY_MANAGER = "PropertyManager"
    INVESTMENT_COMMITTEE = "InvestmentCommittee"
    LENDER = "Lender"
    ANALYST = "Analyst"


class PortfolioStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class RiskPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    RESTRICTED = "RESTRICTED"


class PropertyManagerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AssetStatus(str, Enum):
    OWNED = "OWNED"
    LISTED_FOR_SALE = "LISTED_FOR_SALE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    SOLD = "SOLD"


class AssetClass(str, Enum):
    OFFICE = "OFFICE"
    RETAIL = "RETAIL"
    INDUSTRIAL = "INDUSTRIAL"
    MULTIFAMILY = "MULTIFAMILY"


class BusinessPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class BudgetCategory(str, Enum):
    RENT_REVENUE = "RENT_REVENUE"
    PARKING_REVENUE = "PARKING_REVENUE"
    OTHER_REVENUE = "OTHER_REVENUE"
    CAM_EXPENSE = "CAM_EXPENSE"
    TAX_EXPENSE = "TAX_EXPENSE"
    INSURANCE_EXPENSE = "INSURANCE_EXPENSE"
    UTILITIES_EXPENSE = "UTILITIES_EXPENSE"
    MANAGEMENT_FEE_EXPENSE = "MANAGEMENT_FEE_EXPENSE"
    OTHER_OPEX = "OTHER_OPEX"
    CAPITAL = "CAPITAL"


class ActualsReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CapitalProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class FundingDrawStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class SpaceType(str, Enum):
    OFFICE_SUITE = "OFFICE_SUITE"
    RETAIL_BAY = "RETAIL_BAY"
    INDUSTRIAL_BAY = "INDUSTRIAL_BAY"
    APARTMENT_UNIT = "APARTMENT_UNIT"


class LeaseStrategyStatus(str, Enum):
    DRAFT = "DRAFT"
    RECOMMENDED = "RECOMMENDED"
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LoanStatus(str, Enum):
    CURRENT = "CURRENT"
    WATCH = "WATCH"
    DEFAULT = "DEFAULT"
    REFINANCED = "REFINANCED"
    PAID_OFF = "PAID_OFF"


class CovenantType(str, Enum):
    MIN_DSCR = "MIN_DSCR"
    MAX_LTV = "MAX_LTV"
    MIN_DEBT_YIELD = "MIN_DEBT_YIELD"


class CovenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IN_BREACH = "IN_BREACH"
    WAIVED = "WAIVED"


class CovenantTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ValuationMethod(str, Enum):
    EXTERNAL_APPRAISAL = "EXTERNAL_APPRAISAL"
    INTERNAL_CAP = "INTERNAL_CAP"


class ValuationStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"


class ScorecardRating(str, Enum):
    EXCELLENT = "EXCELLENT"
    SATISFACTORY = "SATISFACTORY"
    WATCH = "WATCH"
    PROBATION = "PROBATION"


class ScorecardStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVIEWED = "REVIEWED"
    FINALIZED = "FINALIZED"


class ReForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class TriggerType(str, Enum):
    REFINANCE = "REFINANCE"
    HOLD = "HOLD"
    SELL = "SELL"


class DispositionStatus(str, Enum):
    SCREENING = "SCREENING"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    RATIFIED = "RATIFIED"
    EXECUTED = "EXECUTED"
    SHELVED = "SHELVED"


class LenderReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# --- Entity TypedDicts (common fields: id, created_at, updated_at, version) ---


class Portfolio(TypedDict, total=False):
    id: str
    name: str
    base_currency: str
    fiscal_year_start_month: int
    status: str
    risk_posture: str
    total_value_cents: int
    created_at: str
    updated_at: str
    version: int


class PropertyManager(TypedDict, total=False):
    id: str
    firm_name: str
    contact_email: str
    status: str
    probation_streak: int
    composite_score_avg: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    portfolio_id: str
    property_manager_id: str
    name: str
    address: str
    asset_class: str
    net_rentable_sqft: int
    acquisition_price_cents: int
    acquisition_date: str
    hold_period_years: int
    status: str
    current_value_cents: Optional[int]
    current_annualized_noi_cents: Optional[int]
    current_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BusinessPlan(TypedDict, total=False):
    id: str
    asset_id: str
    fiscal_year: int
    status: str
    total_revenue_budget_cents: int
    total_opex_budget_cents: int
    total_capital_budget_cents: int
    budgeted_noi_cents: int
    ytd_actual_noi_cents: int
    available_capital_cents: int
    reserved_capital_cents: int
    drawn_capital_cents: int
    reforecast_count: int
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict, total=False):
    id: str
    plan_id: str
    category: str
    month_index: int
    budget_amount_cents: int
    actual_amount_cents: int
    has_actual: bool
    variance_cents: Optional[int]
    variance_bps: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ActualsReport(TypedDict, total=False):
    id: str
    plan_id: str
    month_index: int
    lines: List[Dict[str, Any]]
    status: str
    submitted_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict, total=False):
    id: str
    asset_id: str
    plan_id: str
    name: str
    is_emergency: bool
    requested_amount_cents: int
    sched_start_month: int
    sched_end_month: int
    approved_amount_cents: int
    monthly_spend_cents: int
    final_month_spend_cents: int
    drawn_cents: int
    proposed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingDraw(TypedDict, total=False):
    id: str
    project_id: str
    amount_cents: int
    status: str
    requested_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class LeaseStrategy(TypedDict, total=False):
    id: str
    asset_id: str
    space_type: str
    current_occupancy_pct: int
    proposed_asking_rate_psf_cents: int
    market_comp_rate_psf_cents: int
    recommended_rate_psf_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    asset_id: str
    lender_name: str
    principal_balance_cents: int
    annual_interest_rate_bps: int
    origination_date: str
    maturity_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Covenant(TypedDict, total=False):
    id: str
    loan_id: str
    covenant_type: str
    threshold_bps: int
    test_frequency: str
    cure_period_days: int
    status: str
    last_breach_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CovenantTest(TypedDict, total=False):
    # Append-only measurement record: carries only id + created_at (PRD §2.4);
    # updated_at and version are both absent.
    id: str
    covenant_id: str
    period_label: str
    measured_value_bps: int
    annualized_noi_cents_used: Optional[int]
    result: str
    created_at: str


class Valuation(TypedDict, total=False):
    id: str
    asset_id: str
    effective_date: str
    method: str
    appraised_value_cents: Optional[int]
    cap_rate_bps: Optional[int]
    noi_used_cents: Optional[int]
    implied_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceScorecard(TypedDict, total=False):
    id: str
    asset_id: str
    property_manager_id: str
    period_label: str
    occupancy_pct: int
    collections_pct: int
    renewal_rate_pct: int
    expense_variance_bps: int
    composite_score: int
    rating: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReForecast(TypedDict, total=False):
    id: str
    plan_id: str
    label: str
    effective_from_month: int
    lines: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class DispositionDecision(TypedDict, total=False):
    id: str
    asset_id: str
    trigger_type: str
    dscr_bps_snapshot: Optional[int]
    ltv_bps_snapshot: Optional[int]
    hold_years_elapsed: int
    value_gain_bps: Optional[int]
    refinance_signal: bool
    sell_signal: bool
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LenderReport(TypedDict, total=False):
    id: str
    loan_id: str
    period_label: str
    quarter_end_date: str
    due_date: str
    submitted_at: Optional[str]
    is_late: bool
    noi_ttm_cents: Optional[int]
    dscr_bps: Optional[int]
    ltv_bps: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
