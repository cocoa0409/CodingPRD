"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1) — all roles are opaque: X-User-ID is never compared
# to any entity's id, only to recorded audit fields.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TREASURY_ANALYST = "TreasuryAnalyst"
    RISK_OFFICER = "RiskOfficer"
    TREASURY_OPS = "TreasuryOps"
    LIQUIDITY_COMMITTEE = "LiquidityCommittee"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status / enum vocabularies (PRD §3)
# ---------------------------------------------------------------------------
class ScenarioTier(str, Enum):
    BASELINE = "BASELINE"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class ScenarioStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ModelVariant(str, Enum):
    CONTRACTUAL = "CONTRACTUAL"
    BEHAVIORAL = "BEHAVIORAL"


class ProjectionRunStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"
    DISCARDED = "DISCARDED"


class AssetClass(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2A = "LEVEL_2A"
    LEVEL_2B = "LEVEL_2B"


class EncumbranceStatus(str, Enum):
    UNENCUMBERED = "UNENCUMBERED"
    PLEDGED = "PLEDGED"
    SOLD = "SOLD"


class FundingChannel(str, Enum):
    RETAIL_DEPOSIT = "RETAIL_DEPOSIT"
    WHOLESALE_UNSECURED = "WHOLESALE_UNSECURED"
    WHOLESALE_SECURED = "WHOLESALE_SECURED"
    BROKERED = "BROKERED"


class MetricUnit(str, Enum):
    PCT_BPS = "PCT_BPS"
    DAYS = "DAYS"
    CENTS = "CENTS"


class ThresholdDirection(str, Enum):
    ABOVE_BREACHES = "ABOVE_BREACHES"
    BELOW_BREACHES = "BELOW_BREACHES"


class Band(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class PostureLevel(str, Enum):
    NORMAL = "NORMAL"
    HEIGHTENED = "HEIGHTENED"
    SEVERE = "SEVERE"
    CRISIS = "CRISIS"


# Ordinal scale per PRD §3.6: NORMAL(0) < HEIGHTENED(1) < SEVERE(2) < CRISIS(3)
POSTURE_ORDINAL = {
    PostureLevel.NORMAL.value: 0,
    PostureLevel.HEIGHTENED.value: 1,
    PostureLevel.SEVERE.value: 2,
    PostureLevel.CRISIS.value: 3,
}


class PostureTrigger(str, Enum):
    READING_AUTO = "READING_AUTO"
    MANUAL_EVALUATION = "MANUAL_EVALUATION"


class PlaybookStatus(str, Enum):
    DRAFT = "DRAFT"
    TESTED = "TESTED"
    APPROVED = "APPROVED"
    ACTIVATED = "ACTIVATED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    STOOD_DOWN = "STOOD_DOWN"


class ActionKind(str, Enum):
    ASSET_SALE = "ASSET_SALE"
    LINE_DRAWDOWN = "LINE_DRAWDOWN"


class ActionStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    BLOCKED = "BLOCKED"
    EXECUTING = "EXECUTING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class LineType(str, Enum):
    FED_DISCOUNT_WINDOW = "FED_DISCOUNT_WINDOW"
    FHLB = "FHLB"
    REPO = "REPO"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PledgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class LimitSubject(str, Enum):
    EWI_METRIC = "EWI_METRIC"
    WHOLESALE_RELIANCE_PCT = "WHOLESALE_RELIANCE_PCT"
    TOP_COUNTERPARTY_PCT = "TOP_COUNTERPARTY_PCT"
    SURVIVAL_DAYS = "SURVIVAL_DAYS"
    INTRADAY_NET_POSITION = "INTRADAY_NET_POSITION"


class LimitSeverity(str, Enum):
    BOARD = "BOARD"
    REGULATORY = "REGULATORY"


class BreachStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    REMEDIATED = "REMEDIATED"


class BreachSourceType(str, Enum):
    METRIC_READING = "METRIC_READING"
    FUNDING_EVALUATION = "FUNDING_EVALUATION"
    PROJECTION_FINALIZE = "PROJECTION_FINALIZE"
    INTRADAY_SNAPSHOT = "INTRADAY_SNAPSHOT"


class CapacityTestResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# PRD §2.5: resources other than the three append-only event types carry
# id + created_at + updated_at + version. The append-only event types —
# metric readings, posture snapshots, intraday snapshots — carry only id
# and created_at; updated_at and version are absent from them.
# ---------------------------------------------------------------------------
class StressScenario(TypedDict, total=False):
    id: str
    name: str
    tier: str
    deposit_runoff_pct: int
    wholesale_renewal_pct: int
    level2_addon_bps: int
    horizon_days: int
    status: str
    run_count: int
    created_at: str
    updated_at: str
    version: int


class ProjectionRun(TypedDict, total=False):
    id: str
    scenario_id: str
    model_variant: str
    as_of_date: str
    horizon_days: int
    status: str
    total_inflows_cents: int
    total_outflows_cents: int
    net_cumulative_gap_cents: int
    hqla_available_cents: int
    survival_days: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiquidAsset(TypedDict, total=False):
    id: str
    asset_class: str
    reference: str
    market_value_cents: int
    haircut_bps: int
    encumbrance_status: str
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict, total=False):
    id: str
    counterparty_name: str
    channel: str
    balance_cents: int
    matures_in_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EwiMetric(TypedDict, total=False):
    id: str
    code: str
    name: str
    unit: str
    direction: str
    amber_threshold: int
    red_threshold: int
    min_reading_interval_hours: int
    current_band: str
    last_reading_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only event (PRD §2.5): id + created_at only — NO updated_at/version.
class MetricReading(TypedDict, total=False):
    id: str
    metric_id: str
    observed_at: str
    value: int
    band: str
    created_at: str


# Append-only event (PRD §2.5): id + created_at only — NO updated_at/version.
class PostureSnapshot(TypedDict, total=False):
    id: str
    snapshot_seq: int
    level: str
    prior_level: str
    red_count: int
    amber_count: int
    open_breach_count: int
    trigger: str
    evaluated_by_user_id: str
    created_at: str


class ContingencyPlaybook(TypedDict, total=False):
    id: str
    name: str
    scenario_id: str
    min_activation_posture: str
    target_capacity_cents: int
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    tested_at: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlaybookAction(TypedDict, total=False):
    id: str
    playbook_id: str
    kind: str
    sequence_no: int
    estimated_proceeds_cents: int
    settlement_lag_days: int
    asset_id: Optional[str]
    line_id: Optional[str]
    prerequisite_action_id: Optional[str]
    status: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BorrowingLine(TypedDict, total=False):
    id: str
    provider_name: str
    line_type: str
    total_capacity_cents: int
    advance_rate_bps: int
    pledged_value_cents: int
    drawn_cents: int
    borrowing_power_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CollateralPledge(TypedDict, total=False):
    id: str
    asset_id: str
    line_id: str
    pledged_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardLimit(TypedDict, total=False):
    id: str
    subject: str
    direction: str
    limit_value: int
    severity: str
    ewi_metric_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LimitBreach(TypedDict, total=False):
    id: str
    limit_id: str
    subject: str
    detected_value: int
    limit_value: int
    status: str
    source_type: str
    source_id: Optional[str]
    acknowledged_by_user_id: Optional[str]
    remediated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only event (PRD §2.5): id + created_at only — NO updated_at/version.
class IntradaySnapshot(TypedDict, total=False):
    id: str
    business_date: str
    snapshot_at: str
    opening_balance_cents: int
    payments_received_cents: int
    payments_sent_cents: int
    net_position_cents: int
    created_at: str


# ---------------------------------------------------------------------------
# Computed-read payloads (not persisted entities)
# ---------------------------------------------------------------------------
class HqlaSummary(TypedDict, total=False):
    baseline_total_cents: int
    stress_total_cents: int
    asset_count: int


class FundingEvaluationResult(TypedDict, total=False):
    total_funding_cents: int
    wholesale_reliance_bps: int
    top_counterparty_bps: int
    top_counterparty_name: str
    breaches_created: int


class EwiDashboard(TypedDict, total=False):
    posture_level: str
    red_count: int
    amber_count: int
    metric_count: int


class CapacityTestResponse(TypedDict, total=False):
    result: str
    total_estimated_cents: int
    total_realizable_cents: int
    failures: Any
