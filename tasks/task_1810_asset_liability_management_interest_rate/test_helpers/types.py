"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    TREASURY_ANALYST = "TreasuryAnalyst"
    MODEL_RISK_VALIDATOR = "ModelRiskValidator"
    ALCO_CHAIR = "ALCOChair"
    REGULATOR = "Regulator"


class AlmBookStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class PositionCategory(str, Enum):
    LOAN = "LOAN"
    SECURITY = "SECURITY"
    DEPOSIT = "DEPOSIT"
    BORROWING = "BORROWING"


class DepositSegment(str, Enum):
    RETAIL_NONMATURITY = "RETAIL_NONMATURITY"
    BUSINESS_NONMATURITY = "BUSINESS_NONMATURITY"
    TIME = "TIME"


class PositionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AssumptionDomain(str, Enum):
    PREPAYMENT = "PREPAYMENT"
    DEPOSIT_DECAY = "DEPOSIT_DECAY"
    DEPOSIT_BETA = "DEPOSIT_BETA"


class AssumptionSetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class GovernanceFlag(str, Enum):
    NONE = "NONE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ScenarioKind(str, Enum):
    PARALLEL_SHOCK = "PARALLEL_SHOCK"
    RAMP = "RAMP"
    REGULATORY_PRESET = "REGULATORY_PRESET"


class PresetCode(str, Enum):
    REG_UP_400 = "REG_UP_400"
    REG_UP_300 = "REG_UP_300"
    REG_UP_200 = "REG_UP_200"
    REG_DOWN_200 = "REG_DOWN_200"
    REG_DOWN_300 = "REG_DOWN_300"
    REG_DOWN_400 = "REG_DOWN_400"


class ScenarioStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class BalanceSheetConvention(str, Enum):
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"


class SimulationRunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PUBLISHED = "PUBLISHED"


class BreachSummary(str, Enum):
    NONE = "NONE"
    NII = "NII"
    EVE = "EVE"
    BOTH = "BOTH"


class LimitMetric(str, Enum):
    NII_DELTA_PCT = "NII_DELTA_PCT"
    EVE_DELTA_PCT = "EVE_DELTA_PCT"


class PolicyLimitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BreachMetric(str, Enum):
    NII_DELTA_PCT = "NII_DELTA_PCT"
    EVE_DELTA_PCT = "EVE_DELTA_PCT"
    HEDGE_COVERAGE = "HEDGE_COVERAGE"


class LimitBreachStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REMEDIATION_PLANNED = "REMEDIATION_PLANNED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class Instrument(str, Enum):
    PAYER_SWAP = "PAYER_SWAP"
    RECEIVER_SWAP = "RECEIVER_SWAP"
    CAP = "CAP"
    FLOOR = "FLOOR"


class DesignationType(str, Enum):
    FAIR_VALUE = "FAIR_VALUE"
    CASH_FLOW = "CASH_FLOW"


class EffectivenessMethod(str, Enum):
    DOLLAR_OFFSET = "DOLLAR_OFFSET"
    REGRESSION = "REGRESSION"


class HedgeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DESIGNATED = "DESIGNATED"
    ACTIVE = "ACTIVE"
    DEDESIGNATED = "DEDESIGNATED"
    TERMINATED = "TERMINATED"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class BacktestOutcome(str, Enum):
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    BREACH = "BREACH"


class BacktestStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_ACCEPTED = "CLOSED_ACCEPTED"
    CLOSED_REVISED = "CLOSED_REVISED"


class AlcoReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# --- Entity TypedDicts (PRD §2.5 common fields: id/created_at/updated_at/version) ---


class AlmBook(TypedDict):
    id: str
    name: str
    base_curve_rate_bps: int
    min_hedged_notional_cents: int
    status: str
    total_assets_cents: int
    total_liabilities_cents: int
    hedged_notional_cents: int
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict):
    id: str
    book_id: str
    category: str
    deposit_segment: Optional[str]
    balance_cents: int
    rate_bps: int
    scheduled_runoff_pct: float
    is_prepayment_eligible: bool
    duration_years: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AssumptionSet(TypedDict):
    id: str
    book_id: str
    domain: str
    params: dict
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    governance_flag: str
    created_at: str
    updated_at: str
    version: int


class RateScenario(TypedDict):
    id: str
    book_id: str
    name: str
    kind: str
    shock_bps: Optional[int]
    ramp_total_bps: Optional[int]
    ramp_months: Optional[int]
    preset_code: Optional[str]
    horizon_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SimulationRun(TypedDict):
    id: str
    book_id: str
    scenario_id: str
    prepayment_set_id: str
    decay_set_id: str
    beta_set_id: str
    balance_sheet_convention: str
    annual_growth_pct: Optional[float]
    book_version_pinned: int
    status: str
    period_month: str
    nii_base_cents: int
    nii_scenario_cents: int
    nii_delta_pct: float
    eve_base_cents: int
    eve_scenario_cents: int
    eve_delta_pct: float
    breach_summary: str
    assumption_stale: bool
    created_at: str
    updated_at: str
    version: int


class PolicyLimit(TypedDict):
    id: str
    book_id: str
    metric: str
    applies_to_kinds: List[str]
    threshold_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LimitBreach(TypedDict):
    id: str
    book_id: str
    run_id: Optional[str]
    limit_id: Optional[str]
    metric: str
    observed_delta_pct: Optional[float]
    threshold_pct: Optional[float]
    period_month: str
    status: str
    remediation_note: Optional[str]
    due_date: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HedgeRelationship(TypedDict):
    id: str
    book_id: str
    position_id: str
    instrument: str
    designation_type: str
    notional_cents: int
    fixed_rate_bps: int
    start_month: Optional[str]
    end_month: Optional[str]
    effectiveness_method: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HedgeEffectivenessTest(TypedDict):
    """Append-only event record (PRD §2.5): carries id and created_at only —
    updated_at and version are absent because a recorded test is never modified."""
    id: str
    hedge_id: str
    test_month: str
    method: str
    hedge_value_change_cents: int
    hedged_item_value_change_cents: int
    slope: Optional[float]
    r_squared: Optional[float]
    sample_count: Optional[int]
    offset_ratio: Optional[float]
    result: str
    created_at: str


class BacktestReview(TypedDict):
    id: str
    book_id: str
    assumption_set_id: str
    domain: str
    start_month: str
    observation_months: int
    observed_value_pct: float
    predicted_value_pct: float
    deviation_pct: float
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AlcoReport(TypedDict):
    id: str
    book_id: str
    period_month: str
    status: str
    run_count: int
    worst_nii_delta_pct: Optional[float]
    worst_eve_delta_pct: Optional[float]
    open_breach_count: int
    regulatory_coverage_complete: bool
    submitted_by_user_id: Optional[str]
    acknowledged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
