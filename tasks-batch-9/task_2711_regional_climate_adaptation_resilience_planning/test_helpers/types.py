"""Typed vocabulary for the Regional Climate Adaptation & Resilience Planning API.

Every literal in this module is transcribed from the PRD: the role names of
section 2.1, the enumerated domains of section 3, and the response field sets of
each entity.
"""

from typing import List, Literal, Optional, TypedDict

# --- Roles (PRD 2.1) -------------------------------------------------------

UserRole = Literal[
    "RegionalAdministrator",
    "HazardAnalyst",
    "ProjectSponsor",
    "BCAReviewer",
    "JurisdictionDelegate",
    "EquityOfficer",
]

ALL_ROLES: List[str] = [
    "RegionalAdministrator",
    "HazardAnalyst",
    "ProjectSponsor",
    "BCAReviewer",
    "JurisdictionDelegate",
    "EquityOfficer",
]

# --- Enumerated domains ----------------------------------------------------

JurisdictionStatus = Literal["ACTIVE", "PROBATION", "SUSPENDED"]
SviTier = Literal["LOW", "MODERATE", "HIGH", "SEVERE"]

HazardType = Literal["HEAT", "FLOOD", "DROUGHT", "STORM"]
Scenario = Literal["RCP45", "RCP85"]
HorizonYear = Literal[2040, 2060, 2080]
HazardProfileStatus = Literal["DRAFT", "PUBLISHED", "SUPERSEDED"]

SubjectType = Literal["INFRASTRUCTURE", "POPULATION", "ECONOMIC_SECTOR"]
VulnerabilityMethod = Literal["COMPOSITE_MULTIPLICATIVE", "ADDITIVE_WEIGHTED"]
AssessmentStatus = Literal["DRAFT", "ASSESSED", "STALE"]
VulnerabilityBand = Literal["LOW", "MODERATE", "HIGH", "EXTREME"]

AssetClass = Literal["WATER", "POWER", "TRANSPORT", "HEALTH", "COMMS"]
CriticalityStatus = Literal["UNRANKED", "RANKED", "RECOMPUTE_REQUIRED"]
CriticalityTier = Literal["TIER_1", "TIER_2", "TIER_3"]

StrategyType = Literal["PROTECT", "ACCOMMODATE", "RETREAT", "AVOID"]
ScreeningStatus = Literal["PROPOSED", "SCREENED_IN", "SCREENED_OUT"]
AnalysisStatus = Literal[
    "NOT_ANALYZED", "BCA_PENDING", "BCA_CERTIFIED", "BCA_REJECTED", "BCA_STALE"
]
ProgramStatus = Literal[
    "UNPROGRAMMED", "PROGRAMMED", "GRANT_SUBMITTED", "AWARDED", "WITHDRAWN"
]
ImplementationStatus = Literal["NOT_STARTED", "ON_TRACK", "AT_RISK", "OFF_TRACK"]

BcaMethod = Literal["DISCOUNTED_NPV", "ANNUALIZED_EQUIVALENT"]
BcaStatus = Literal["DRAFT", "CERTIFIED", "REJECTED", "STALE"]
StaleReason = Literal["NONE", "ASSET_RECOMPUTE", "LINK_ADDED"]

FundingPosture = Literal["OPEN", "OVERSUBSCRIBED", "CLOSED"]
GrantFunder = Literal["BRIC", "HMGP", "STATE_RESILIENCE"]

PlanCycleStatus = Literal[
    "DRAFT", "ENGAGEMENT", "ENDORSEMENT_ROUND", "REVISION", "ADOPTED", "FAILED"
]
SessionModality = Literal["IN_PERSON", "VIRTUAL", "HYBRID"]
SessionStatus = Literal["SCHEDULED", "COMPLETED", "CANCELLED"]
EndorsementDecision = Literal["ENDORSED", "CONDITIONED", "VETOED", "SUPERSEDED"]
ProjectedOutcome = Literal["adopted", "blocked", "short"]

ResourceClass = Literal["CREWS", "PUMPS", "GENERATORS", "COOLING_UNITS"]
PactStatus = Literal["OPEN", "EXHAUSTED", "EXPIRED"]
CommitmentStatus = Literal["COMMITTED", "RELEASED", "FULFILLED"]


# --- Entity response shapes -------------------------------------------------
#
# Per PRD 2.4 every persisted resource carries `id`, `created_at`, `updated_at`
# and `version`, with one documented exception: a project-to-asset link
# "carries only `id` and `created_at`. It has no `updated_at` and no `version`".


class Jurisdiction(TypedDict):
    id: str
    name: str
    jurisdiction_code: str
    population: int
    svi_score: float
    svi_tier: SviTier
    disadvantaged_flag: bool
    endorsement_weight: int
    status: JurisdictionStatus
    created_at: str
    updated_at: str
    version: int


class HazardProfile(TypedDict):
    id: str
    jurisdiction_id: str
    hazard_type: HazardType
    scenario: Scenario
    horizon_year: int
    exposure_index: float
    annual_event_probability: float
    projected_annual_loss_cents: int
    status: HazardProfileStatus
    published_version: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VulnerabilityAssessment(TypedDict):
    id: str
    hazard_profile_id: str
    asset_id: str
    subject_type: SubjectType
    method: VulnerabilityMethod
    sensitivity_score: float
    adaptive_capacity_score: float
    svi_overlay_applied: bool
    vulnerability_score: Optional[float]
    vulnerability_band: Optional[VulnerabilityBand]
    assessed_at: Optional[str]
    assessed_profile_version: Optional[int]
    status: AssessmentStatus
    created_at: str
    updated_at: str
    version: int


class LifelineAsset(TypedDict):
    id: str
    jurisdiction_id: str
    name: str
    asset_class: AssetClass
    replacement_value_cents: int
    service_population: int
    redundancy_factor: float
    is_shared: bool
    upstream_asset_id: Optional[str]
    consequence_score: Optional[float]
    criticality_tier: Optional[CriticalityTier]
    dependency_depth: Optional[int]
    criticality_status: CriticalityStatus
    created_at: str
    updated_at: str
    version: int


class AdaptationProject(TypedDict):
    id: str
    plan_cycle_id: str
    jurisdiction_id: str
    name: str
    hazard_type: HazardType
    strategy_type: StrategyType
    base_cost_cents: int
    service_life_years: int
    cobenefit_points: int
    feasibility_score: float
    prerequisite_project_id: Optional[str]
    indicator_code: Optional[str]
    indicator_target_value: Optional[float]
    escalated_cost_cents: Optional[int]
    admin_rate_bps: Optional[int]
    admin_fee_cents: Optional[int]
    total_program_cost_cents: Optional[int]
    grant_match_share_bps: Optional[int]
    screen_score: Optional[float]
    priority_score: Optional[float]
    equity_benefit_share_bps: Optional[int]
    equity_waiver_granted: bool
    capital_program_id: Optional[str]
    allocated_cents: int
    grant_hold_flag: bool
    grant_funder: Optional[GrantFunder]
    grant_submitted_at: Optional[str]
    awarded_at: Optional[str]
    indicator_latest_value: Optional[float]
    indicator_attainment_pct: Optional[float]
    latest_period_label: Optional[str]
    reported_period_count: int
    screening_status: ScreeningStatus
    analysis_status: AnalysisStatus
    program_status: ProgramStatus
    implementation_status: ImplementationStatus
    created_at: str
    updated_at: str
    version: int


class ProjectAssetLink(TypedDict):
    """Immutable junction row: `id` and `created_at` only (PRD 2.4)."""

    id: str
    project_id: str
    asset_id: str
    avoided_loss_annual_cents: int
    benefit_reaches_disadvantaged: bool
    link_sequence: int
    created_at: str


class BenefitCostAnalysis(TypedDict):
    id: str
    project_id: str
    method: BcaMethod
    discount_rate_bps: int
    analysis_horizon_years: int
    benefit_measure_cents: Optional[int]
    cost_measure_cents: Optional[int]
    bcr: Optional[float]
    grant_eligible: bool
    prepared_by_user_id: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    stale_reason: StaleReason
    status: BcaStatus
    created_at: str
    updated_at: str
    version: int


class CapitalProgram(TypedDict):
    id: str
    fiscal_year: int
    authorized_cents: int
    equity_target_bps: int
    committed_cents: int
    available_cents: int
    equity_committed_cents: int
    equity_achieved_bps: int
    funding_posture: FundingPosture
    created_at: str
    updated_at: str
    version: int


class PlanCycle(TypedDict):
    id: str
    cycle_label: str
    endorsement_deadline: str
    quorum_weight_bps: int
    max_revision_rounds: int
    required_session_count: int
    round_number: int
    revision_count: int
    achieved_weight_bps: Optional[int]
    adopted_at: Optional[str]
    status: PlanCycleStatus
    created_at: str
    updated_at: str
    version: int


class EngagementSession(TypedDict):
    id: str
    plan_cycle_id: str
    host_jurisdiction_id: str
    modality: SessionModality
    window_start: str
    window_end: str
    attendee_count: Optional[int]
    disadvantaged_attendee_count: Optional[int]
    equity_reach_bps: Optional[int]
    preferred_strategy_type: Optional[StrategyType]
    status: SessionStatus
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict):
    id: str
    plan_cycle_id: str
    jurisdiction_id: str
    round_number: int
    decision: EndorsementDecision
    condition_note: Optional[str]
    weight_at_cast: int
    cast_at: str
    created_at: str
    updated_at: str
    version: int


class MutualAidPact(TypedDict):
    id: str
    host_jurisdiction_id: str
    resource_class: ResourceClass
    pledged_units: int
    reserved_units: int
    free_units: int
    window_start: str
    window_end: str
    max_concurrent_commitments: int
    status: PactStatus
    created_at: str
    updated_at: str
    version: int


class MutualAidCommitment(TypedDict):
    id: str
    pact_id: str
    requesting_jurisdiction_id: str
    asset_id: str
    committed_units: int
    window_start: str
    window_end: str
    released_at: Optional[str]
    fulfilled_at: Optional[str]
    status: CommitmentStatus
    created_at: str
    updated_at: str
    version: int


class EndorsementTally(TypedDict):
    """Read-only projection of the current round (PRD 3.8)."""

    round_number: int
    total_active_weight: int
    supporting_weight: int
    veto_weight: int
    achieved_weight_bps: int
    quorum_weight_bps: int
    projected_outcome: str
