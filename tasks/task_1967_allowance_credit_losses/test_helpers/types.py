"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CREDIT_ANALYST = "CreditAnalyst"
    MODEL_VALIDATOR = "ModelValidator"
    CHIEF_CREDIT_OFFICER = "ChiefCreditOfficer"
    EXTERNAL_AUDITOR = "ExternalAuditor"


class LossModelStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class LossModelMethod(str, Enum):
    LOSS_RATE = "LOSS_RATE"
    DISCOUNTED_CASH_FLOW = "DISCOUNTED_CASH_FLOW"
    VINTAGE = "VINTAGE"


class ReversionMethod(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    STRAIGHT_LINE = "STRAIGHT_LINE"


class SegmentStatus(str, Enum):
    OPEN = "OPEN"
    WATCH = "WATCH"


class ProductType(str, Enum):
    CREDIT_CARD = "CREDIT_CARD"
    AUTO = "AUTO"
    MORTGAGE = "MORTGAGE"
    SMALL_BUSINESS = "SMALL_BUSINESS"
    PERSONAL = "PERSONAL"


class RiskRatingBand(str, Enum):
    PRIME = "PRIME"
    NEAR_PRIME = "NEAR_PRIME"
    SUBPRIME = "SUBPRIME"
    DEEP_SUBPRIME = "DEEP_SUBPRIME"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CHARGED_OFF = "CHARGED_OFF"


class RiskRating(str, Enum):
    PASS = "PASS"
    SPECIAL_MENTION = "SPECIAL_MENTION"
    SUBSTANDARD = "SUBSTANDARD"
    DOUBTFUL = "DOUBTFUL"
    LOSS = "LOSS"


class ScenarioType(str, Enum):
    BASELINE = "BASELINE"
    ADVERSE = "ADVERSE"
    OPTIMISTIC = "OPTIMISTIC"


class ScenarioStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class FactorCode(str, Enum):
    CONCENTRATION_RISK = "CONCENTRATION_RISK"
    POLICY_CHANGE = "POLICY_CHANGE"
    ECONOMIC_UNCERTAINTY = "ECONOMIC_UNCERTAINTY"
    COLLATERAL_VALUATION = "COLLATERAL_VALUATION"
    MODEL_LIMITATION = "MODEL_LIMITATION"


class FactorStatus(str, Enum):
    DRAFT = "DRAFT"
    DOCUMENTED = "DOCUMENTED"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class ModelRunStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    FINALIZED = "FINALIZED"


class EvaluationMethod(str, Enum):
    COLLATERAL_FAIR_VALUE = "COLLATERAL_FAIR_VALUE"
    DISCOUNTED_CASH_FLOW = "DISCOUNTED_CASH_FLOW"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVIEWED = "REVIEWED"


class AdjustmentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DisclosureStatus(str, Enum):
    PREPARED = "PREPARED"
    UNDER_AUDIT_REVIEW = "UNDER_AUDIT_REVIEW"
    RELEASED = "RELEASED"


class BacktestOutcome(str, Enum):
    PASS = "PASS"
    BREACH = "BREACH"


class LossModel(TypedDict):
    id: str
    name: str
    method: str
    forecast_period_quarters: int
    reversion_method: str
    reversion_period_quarters: int
    historical_lookback_quarters: int
    version_label: str
    parent_model_id: Optional[str]
    status: str
    consecutive_backtest_breach_count: int
    refresh_required: bool
    created_at: str
    updated_at: str
    version: int


class PortfolioSegment(TypedDict):
    id: str
    segment_code: str
    name: str
    product_type: str
    risk_rating_band: str
    vintage_year: int
    status: str
    origination_total_cents: int
    ytd_gross_charge_offs_cents: int
    ytd_recoveries_cents: int
    charge_off_rate_bps: int
    base_loss_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    segment_id: str
    loan_number: str
    amortized_cost_cents: int
    risk_rating: str
    delinquency_days: int
    collateral_value_cents: int
    individually_evaluated: bool
    status: str
    charged_off_total_cents: int
    recovered_total_cents: int
    created_at: str
    updated_at: str
    version: int


class EconomicScenario(TypedDict):
    id: str
    name: str
    scenario_type: str
    unemployment_rate_bps: int
    gdp_growth_bps: int
    effective_from_period: str
    effective_to_period: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QualitativeFactor(TypedDict):
    id: str
    segment_id: str
    factor_code: str
    adjustment_bps: int
    effective_from_period: str
    effective_to_period: str
    documentation_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ModelRun(TypedDict):
    id: str
    as_of_period: str
    loss_model_id: str
    scenario_weights: List[dict]
    status: str
    executed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    model_version_label: Optional[str]
    needs_segmentation_review: bool
    individual_evaluation_count: int
    reviewed_evaluation_count: int
    total_exposure_cents: int
    quantitative_reserve_cents: int
    qualitative_adjustment_cents: int
    individual_reserve_cents: int
    management_adjustment_cents: int
    total_allowance_cents: int
    segments_breakdown: List[dict]
    rework_notes: str
    created_at: str
    updated_at: str
    version: int


class IndividualEvaluation(TypedDict):
    id: str
    run_id: str
    loan_id: str
    method: str
    collateral_value_cents: int
    expected_quarterly_cash_flows_cents: List[int]
    discount_rate_bps: Optional[int]
    analysis_notes: str
    specific_reserve_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ManagementAdjustment(TypedDict):
    id: str
    run_id: str
    amount_cents: int
    rationale: str
    status: str
    created_by_user_id: str
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureReport(TypedDict):
    id: str
    run_id: str
    beginning_allowance_cents: int
    ending_allowance_cents: int
    period_charge_offs_cents: int
    period_recoveries_cents: int
    provision_cents: int
    status: str
    audit_reference: str
    revision_notes: str
    created_at: str
    updated_at: str
    version: int


class BacktestResult(TypedDict):
    """Append-only observation: carries only id + created_at (PRD §2.4)."""
    id: str
    loss_model_id: str
    backtest_period: str
    actual_loss_rate_bps: int
    backtested_run_id: str
    predicted_loss_rate_bps: int
    variance_bps: int
    outcome: str
    created_at: str
