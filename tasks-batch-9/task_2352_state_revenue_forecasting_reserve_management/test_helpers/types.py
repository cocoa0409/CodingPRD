"""Domain types for the State Revenue Forecasting Reserves API.

Entity shapes, status enums and the role enum, as declared by the PRD.
Two entities are immutable audit records and carry only `id` and `created_at`
(no `updated_at`, no `version`): the reserve ledger row and the ballot (PRD §2.6).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    FORECAST_DIRECTOR = "ForecastDirector"
    EXECUTIVE_ECONOMIST = "ExecutiveEconomist"
    LEGISLATIVE_ECONOMIST = "LegislativeEconomist"
    RESERVE_TREASURER = "ReserveTreasurer"
    LEGISLATIVE_VOTER = "LegislativeVoter"
    RATING_ANALYST = "RatingAnalyst"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class ForecastCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    INPUTS_LOCKED = "INPUTS_LOCKED"
    IN_CONSENSUS = "IN_CONSENSUS"
    CONSENSUS_REACHED = "CONSENSUS_REACHED"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class CycleType(str, Enum):
    BASELINE = "BASELINE"
    REVISION = "REVISION"


class ReconciliationPolicy(str, Enum):
    MIDPOINT_AVERAGE = "MIDPOINT_AVERAGE"
    LOWER_OF_TWO = "LOWER_OF_TWO"


class ScenarioLabel(str, Enum):
    BASELINE = "BASELINE"
    OPTIMISTIC = "OPTIMISTIC"
    PESSIMISTIC = "PESSIMISTIC"
    ALTERNATIVE = "ALTERNATIVE"


class TaxType(str, Enum):
    PIT = "PIT"
    CIT = "CIT"
    SALES = "SALES"
    CAPITAL_GAINS = "CAPITAL_GAINS"
    EXCISE = "EXCISE"
    OTHER = "OTHER"


class VolatilityClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RevenueSourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PolicyCategory(str, Enum):
    RATE_CHANGE = "RATE_CHANGE"
    BASE_CHANGE = "BASE_CHANGE"
    CREDIT = "CREDIT"
    COMPLIANCE = "COMPLIANCE"


class AdjustmentKind(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


class PhaseInType(str, Enum):
    FULL = "FULL"
    PRORATED = "PRORATED"
    TIERED = "TIERED"


class OneTimeItemType(str, Enum):
    SETTLEMENT = "SETTLEMENT"
    ASSET_SALE = "ASSET_SALE"
    FEDERAL_AID = "FEDERAL_AID"
    TAX_AMNESTY = "TAX_AMNESTY"


class OneTimeItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ConsensusRoundStatus(str, Enum):
    OPEN = "OPEN"
    COMPARED = "COMPARED"
    DISPUTED = "DISPUTED"
    RATIFIED = "RATIFIED"
    SUPERSEDED = "SUPERSEDED"


class SubmissionStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"


class EstimatingBody(str, Enum):
    EXECUTIVE = "EXECUTIVE"
    LEGISLATIVE = "LEGISLATIVE"


class DisagreementStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    VOIDED = "VOIDED"


class ResolutionMethod(str, Enum):
    EXEC_VALUE = "EXEC_VALUE"
    LEG_VALUE = "LEG_VALUE"
    MIDPOINT = "MIDPOINT"
    DIRECTOR_OVERRIDE = "DIRECTOR_OVERRIDE"


class DepositRuleVariant(str, Enum):
    GROWTH_ABOVE_TREND = "GROWTH_ABOVE_TREND"
    VOLATILE_SOURCE_CAPTURE = "VOLATILE_SOURCE_CAPTURE"


class DepositPosture(str, Enum):
    ACCEPTING = "ACCEPTING"
    AT_CAP = "AT_CAP"


class AdequacyBand(str, Enum):
    INSUFFICIENT = "INSUFFICIENT"
    THIN = "THIN"
    ADEQUATE = "ADEQUATE"
    STRONG = "STRONG"


class TransactionOrigin(str, Enum):
    CERTIFICATION_DEPOSIT = "CERTIFICATION_DEPOSIT"
    MANUAL_DEPOSIT = "MANUAL_DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    REVERSAL = "REVERSAL"


class WithdrawalRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    VOTE_OPEN = "VOTE_OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    LAPSED = "LAPSED"


class JustificationType(str, Enum):
    SHORTFALL_TRIGGER = "SHORTFALL_TRIGGER"
    SUPERMAJORITY_VOTE = "SUPERMAJORITY_VOTE"


class Ballot(str, Enum):
    YES = "YES"
    NO = "NO"
    ABSTAIN = "ABSTAIN"


class ErrorDirection(str, Enum):
    OVER_FORECAST = "OVER_FORECAST"
    UNDER_FORECAST = "UNDER_FORECAST"
    EXACT = "EXACT"


class BriefingStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    STALE = "STALE"
    RETRACTED = "RETRACTED"


class StaleReason(str, Enum):
    RESERVE_BALANCE_CHANGED = "RESERVE_BALANCE_CHANGED"
    CYCLE_SUPERSEDED = "CYCLE_SUPERSEDED"


# --------------------------------------------------------------------------- #
# Entity shapes — carry id / created_at / updated_at / version (PRD §2.6)
# --------------------------------------------------------------------------- #
class ForecastCycle(TypedDict):
    id: str
    fiscal_year: int
    cycle_type: str
    reconciliation_policy: str
    supersedes_cycle_id: Optional[str]
    enacted_appropriation_cents: int
    prior_recurring_baseline_cents: int
    status: str
    scenario_weight_total_bps: int
    ratified_round_id: Optional[str]
    certified_total_cents: Optional[int]
    certified_one_time_cents: Optional[int]
    certified_recurring_total_cents: Optional[int]
    certified_at: Optional[str]
    shortfall_gap_cents: Optional[int]
    shortfall_pct_bps: Optional[int]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class EconomicScenario(TypedDict):
    id: str
    cycle_id: str
    label: str
    weight_bps: int
    employment_growth_bps: int
    wage_income_bps: int
    retail_sales_bps: int
    asset_market_return_bps: int
    created_at: str
    updated_at: str
    version: int


class RevenueSource(TypedDict):
    id: str
    name: str
    tax_type: str
    base_year_receipts_cents: int
    elasticity_employment_bps: int
    elasticity_wage_income_bps: int
    elasticity_retail_bps: int
    elasticity_asset_bps: int
    volatility_class: str
    status: str
    mape_bps: int
    methodology_flag: bool
    posted_actual_count: int
    created_at: str
    updated_at: str
    version: int


class PolicyChangeAdjustment(TypedDict):
    id: str
    source_id: str
    statute_code: str
    policy_category: str
    adjustment_kind: str
    annualized_amount_cents: int
    effective_start_date: str
    effective_end_date: Optional[str]
    phase_in_type: str
    first_effective_fiscal_year: int
    cap_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class OneTimeItem(TypedDict):
    id: str
    cycle_id: str
    source_id: str
    item_type: str
    amount_cents: int
    description: str
    status: str
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsensusRound(TypedDict):
    id: str
    cycle_id: str
    round_number: int
    variance_tolerance_bps: int
    per_source_tolerance_bps: int
    status: str
    exec_submission_status: str
    leg_submission_status: str
    exec_total_cents: Optional[int]
    leg_total_cents: Optional[int]
    variance_bps: Optional[int]
    reconciled_total_cents: Optional[int]
    open_disagreement_count: int
    ratified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SourceEstimate(TypedDict):
    id: str
    round_id: str
    source_id: str
    body: str
    submitted_by_user_id: str
    weighted_scenario_cents: int
    policy_adjustment_cents: int
    judgmental_adjustment_cents: int
    one_time_cents: int
    recurring_component_cents: int
    estimate_amount_cents: int
    locked: bool
    created_at: str
    updated_at: str
    version: int


class DisagreementRecord(TypedDict):
    id: str
    round_id: str
    source_id: str
    exec_amount_cents: int
    leg_amount_cents: int
    variance_bps: int
    status: str
    resolution_method: Optional[str]
    resolved_amount_cents: Optional[int]
    resolved_by_user_id: Optional[str]
    rationale: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReserveFund(TypedDict):
    id: str
    name: str
    cap_pct_bps: int
    trend_growth_rate_bps: int
    capture_rate_bps: int
    deposit_rule_variant: str
    eligible_seats: int
    annual_withdrawal_cap_pct_bps: int
    cooling_off_days: int
    opening_balance_cents: int
    balance_cents: int
    fy_opening_balance_cents: int
    fy_withdrawn_cents: int
    deposit_posture: str
    cap_cents: Optional[int]
    volatility_index_bps: int
    target_pct_bps: int
    required_reserve_cents: Optional[int]
    coverage_ratio_bps: int
    adequacy_band: str
    cushion_credit_bps: int
    disclosed_target_pct_bps: int
    cooling_off_until: Optional[str]
    last_transaction_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WithdrawalRequest(TypedDict):
    id: str
    fund_id: str
    cycle_id: str
    requested_amount_cents: int
    justification_type: str
    requested_by_user_id: str
    deadline_date: str
    status: str
    approval_basis: Optional[str]
    votes_required: int
    quorum_required: int
    yes_votes: int
    no_votes: int
    abstain_votes: int
    vote_closes_at: Optional[str]
    authorized_amount_cents: Optional[int]
    executed_transaction_id: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActualCollection(TypedDict):
    id: str
    source_id: str
    fiscal_year: int
    actual_amount_cents: int
    matched_cycle_id: Optional[str]
    matched_forecast_cents: Optional[int]
    abs_pct_error_bps: Optional[int]
    error_direction: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RatingAgencyBriefing(TypedDict):
    id: str
    fund_id: str
    cycle_id: str
    narrative: str
    snapshot_fund_version: int
    snapshot_adequacy_band: str
    snapshot_coverage_ratio_bps: int
    status: str
    published_at: Optional[str]
    stale_reason: Optional[str]
    retracted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Immutable audit records — id + created_at only (PRD §2.6)
# --------------------------------------------------------------------------- #
class ReserveTransaction(TypedDict):
    id: str
    fund_id: str
    origin: str
    signed_amount_cents: int
    gross_computed_cents: Optional[int]
    overflow_returned_cents: Optional[int]
    reverses_transaction_id: Optional[str]
    source_cycle_id: Optional[str]
    memo: Optional[str]
    created_at: str


class WithdrawalVote(TypedDict):
    id: str
    request_id: str
    voter_user_id: str
    vote: str
    cast_at: str
    created_at: str


ALL_ROLES: List[str] = [r.value for r in UserRole]
