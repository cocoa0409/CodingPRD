"""Domain types for the State Budget Appropriation API: status enums, role enum, entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    AGENCY_BUDGET_OFFICER = "AgencyBudgetOfficer"
    BUDGET_ANALYST = "BudgetAnalyst"
    BUDGET_DIRECTOR = "BudgetDirector"
    LEGISLATIVE_FISCAL_OFFICER = "LegislativeFiscalOfficer"
    STATE_CONTROLLER = "StateController"


# --------------------------------------------------------------------------
# Shared enumerations
# --------------------------------------------------------------------------


class FundType(str, Enum):
    GENERAL = "GENERAL"
    FEDERAL = "FEDERAL"
    DEDICATED = "DEDICATED"


class AgencyType(str, Enum):
    EXECUTIVE = "EXECUTIVE"
    JUDICIAL = "JUDICIAL"
    LEGISLATIVE = "LEGISLATIVE"
    HIGHER_ED = "HIGHER_ED"


class FederalComplianceFlag(str, Enum):
    CLEAR = "CLEAR"
    AT_RISK = "AT_RISK"
    DEFICIENT = "DEFICIENT"


class CyclePhase(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    EXECUTIVE_PREP = "EXECUTIVE_PREP"
    LEGISLATIVE = "LEGISLATIVE"
    ENACTED = "ENACTED"
    EXECUTION = "EXECUTION"
    CLOSED = "CLOSED"


CYCLE_PHASE_ORDER: List[str] = [
    CyclePhase.DEVELOPMENT.value,
    CyclePhase.EXECUTIVE_PREP.value,
    CyclePhase.LEGISLATIVE.value,
    CyclePhase.ENACTED.value,
    CyclePhase.EXECUTION.value,
    CyclePhase.CLOSED.value,
]


class CashPosture(str, Enum):
    NORMAL = "NORMAL"
    CONSTRAINED = "CONSTRAINED"


class ForecastRound(str, Enum):
    CONSENSUS_SPRING = "CONSENSUS_SPRING"
    CONSENSUS_FALL = "CONSENSUS_FALL"
    REVISED = "REVISED"


class RevenueForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class AgencyRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    ACCEPTED = "ACCEPTED"


class PackageType(str, Enum):
    EXPANSION = "EXPANSION"
    REDUCTION = "REDUCTION"
    TECHNICAL = "TECHNICAL"
    FEDERAL_MATCH = "FEDERAL_MATCH"


class DecisionPackageStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RECOMMENDED = "RECOMMENDED"
    DEFERRED = "DEFERRED"


class MeasureUnit(str, Enum):
    COUNT = "COUNT"
    PERCENT = "PERCENT"
    DAYS = "DAYS"
    DOLLARS = "DOLLARS"


class PolicyPriority(str, Enum):
    WORKFORCE = "WORKFORCE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    PUBLIC_SAFETY = "PUBLIC_SAFETY"
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"


class RecommendationStatus(str, Enum):
    PREPARED = "PREPARED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class Feasibility(str, Enum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"


class AuthorityStatus(str, Enum):
    PENDING = "PENDING"
    ENACTED = "ENACTED"
    LAPSED = "LAPSED"
    CLOSED = "CLOSED"


class CashStatus(str, Enum):
    UNRELEASED = "UNRELEASED"
    PARTIALLY_RELEASED = "PARTIALLY_RELEASED"
    FULLY_RELEASED = "FULLY_RELEASED"
    FROZEN = "FROZEN"


class Chamber(str, Enum):
    HOUSE = "HOUSE"
    SENATE = "SENATE"
    CONFERENCE = "CONFERENCE"


class CommitteeActionType(str, Enum):
    SET = "SET"
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    RESTORE = "RESTORE"
    STRIKE = "STRIKE"


class AllotmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class BindingConstraint(str, Enum):
    REQUEST = "REQUEST"
    QUARTER_CAP = "QUARTER_CAP"
    UNRELEASED_AUTHORITY = "UNRELEASED_AUTHORITY"
    CASH_FLOW = "CASH_FLOW"


class TransferType(str, Enum):
    INTRA_AGENCY = "INTRA_AGENCY"
    INTER_AGENCY = "INTER_AGENCY"


class BudgetTransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    REVERSED = "REVERSED"


class TransferSide(str, Enum):
    SOURCE = "SOURCE"
    TARGET = "TARGET"


class ExpenditureStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class MatchStatus(str, Enum):
    UNMET = "UNMET"
    SHORTFALL = "SHORTFALL"
    AT_RISK = "AT_RISK"
    MET = "MET"


class MoeComplianceStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"


class MoeBasis(str, Enum):
    SINGLE_YEAR = "SINGLE_YEAR"
    THREE_YEAR_AVERAGE = "THREE_YEAR_AVERAGE"


class MatchCommitmentStatus(str, Enum):
    COMMITTED = "COMMITTED"
    AT_RISK = "AT_RISK"
    RELEASED_FROM_COMMITMENT = "RELEASED_FROM_COMMITMENT"


# --------------------------------------------------------------------------
# Entities carrying the full audit set (id, created_at, updated_at, version)
# --------------------------------------------------------------------------


class Agency(TypedDict):
    id: str
    agency_code: str
    name: str
    agency_type: str
    federal_compliance_flag: str
    created_at: str
    updated_at: str
    version: int


class BudgetCycle(TypedDict):
    id: str
    fiscal_year: int
    fiscal_year_start_date: str
    reserve_balance_cents: int
    constitutional_reserve_pct: float
    phase: str
    balance_certified: bool
    cash_posture: str
    adopted_general_fund_revenue_cents: int
    total_recommended_cents: int
    required_reserve_cents: int
    emergency_granted_cents: int
    total_released_cents: int
    total_expended_cents: int
    total_reverted_cents: int
    total_carryforward_cents: int
    projected_cumulative_cash_cents: int
    cash_utilization_pct: float
    created_at: str
    updated_at: str
    version: int


class RevenueForecast(TypedDict):
    id: str
    budget_cycle_id: str
    source_code: str
    fund_type: str
    forecast_round: str
    amount_cents: int
    effective_from: str
    effective_to: str
    status: str
    supersedes_forecast_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgencyRequest(TypedDict):
    id: str
    budget_cycle_id: str
    agency_id: str
    base_budget_cents: int
    total_request_cents: int
    status: str
    revision_count: int
    last_return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DecisionPackage(TypedDict):
    id: str
    agency_request_id: str
    package_type: str
    priority_rank: int
    amount_cents: int
    fte_delta: float
    depends_on_package_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExecutiveRecommendation(TypedDict):
    id: str
    agency_request_id: str
    recommended_base_cents: int
    recommended_package_ids: List[str]
    policy_priority: str
    recommended_amount_cents: int
    status: str
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appropriation(TypedDict):
    id: str
    budget_cycle_id: str
    agency_id: str
    fund_type: str
    program_code: str
    introduced_amount_cents: int
    committee_balance_cents: int
    enacted_amount_cents: int
    authority_status: str
    cash_status: str
    is_emergency: bool
    pre_freeze_cash_status: Optional[str]
    freeze_reason: Optional[str]
    release_hold: bool
    transfers_in_cents: int
    transfers_out_cents: int
    released_cents: int
    expended_cents: int
    reverted_cents: int
    carryforward_cents: int
    available_cash_cents: int
    available_authority_cents: int
    created_at: str
    updated_at: str
    version: int


class Allotment(TypedDict):
    id: str
    appropriation_id: str
    quarter: int
    requested_cents: int
    allow_partial: bool
    status: str
    computed_release_cents: int
    binding_constraint: Optional[str]
    released_cents: int
    prepared_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    recall_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BudgetTransfer(TypedDict):
    id: str
    source_appropriation_id: str
    target_appropriation_id: str
    amount_cents: int
    transfer_type: str
    justification: str
    status: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    decision_reason: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Expenditure(TypedDict):
    id: str
    appropriation_id: str
    quarter: int
    amount_cents: int
    object_code: str
    vendor_reference: str
    status: str
    posted_at: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FederalGrant(TypedDict):
    id: str
    agency_id: str
    budget_cycle_id: str
    cfda_number: str
    award_cents: int
    period_start: str
    period_end: str
    moe_baseline_cents: int
    required_match_ratio: float
    moe_prior_year1_spend_cents: int
    moe_prior_year2_spend_cents: int
    required_state_match_cents: int
    committed_match_cents: int
    moe_current_spend_cents: int
    moe_compliance_ratio: float
    moe_assessed_basis: Optional[str]
    match_status: str
    moe_compliance_status: str
    created_at: str
    updated_at: str
    version: int


class MatchCommitment(TypedDict):
    id: str
    federal_grant_id: str
    appropriation_id: str
    committed_match_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Thin records: immutable or append-only, carrying ONLY id and created_at
# --------------------------------------------------------------------------


class PerformanceMeasure(TypedDict):
    id: str
    decision_package_id: str
    measure_code: str
    unit: str
    baseline_value: float
    target_value: float
    created_at: str


class ReductionScenario(TypedDict):
    id: str
    budget_cycle_id: str
    target_reduction_pct: float
    target_reduction_cents: int
    selected_package_ids: List[str]
    achieved_reduction_cents: int
    overshoot_cents: int
    feasibility: str
    created_at: str


class CommitteeAction(TypedDict):
    id: str
    appropriation_id: str
    chamber: str
    committee_name: str
    action_type: str
    amount_cents: int
    sequence_number: int
    running_balance_cents: int
    created_at: str


class BalanceSummary(TypedDict):
    appropriation_id: str
    authority_cents: int
    released_cents: int
    expended_cents: int
    available_cash_cents: int
    available_authority_cents: int
    basis_delta_cents: int
