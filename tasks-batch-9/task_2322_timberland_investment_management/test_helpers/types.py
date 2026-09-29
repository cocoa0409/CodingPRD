"""TypedDict shapes for every resource the Timberland Investment Management API returns.

Field names match the PRD exactly. Per PRD §2.4 every resource carries `id` and
`created_at`; all resources except cruise plots additionally carry `updated_at`
and `version`. A cruise plot is immutable once recorded, so its shape below
deliberately omits both.
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict

UserRole = Literal[
    "FundAdmin",
    "AcquisitionAnalyst",
    "InvestmentCommittee",
    "ForestManager",
    "CertificationAuditor",
    "CarbonDeveloper",
    "IndependentAppraiser",
]

RegionCode = Literal["SOUTH", "WEST", "NORTHEAST"]
CertificationScheme = Literal["SFI", "FSC", "NONE"]
SpeciesCode = Literal["LOBLOLLY_PINE", "DOUGLAS_FIR", "NORTHERN_HARDWOOD"]
GrowthVariant = Literal["YIELD_TABLE", "MAI_LINEAR"]
ProductMix = Literal["SAWTIMBER", "MIXED", "PULPWOOD"]
CarbonRegistry = Literal["ACR", "CAR", "VERRA"]
AppraisalMethodology = Literal["INCOME", "MARKET", "COST"]
AuditType = Literal["SURVEILLANCE", "RECERTIFICATION"]
FindingSeverity = Literal["MAJOR", "MINOR", "OBSERVATION"]
EventType = Literal["WILDFIRE", "INSECT", "WIND_STORM", "ICE_STORM"]
InsuranceRatingBasis = Literal["ACTUARIAL", "EXPERIENCE_RATED"]

MarketAccessTier = Literal["TIER_A", "TIER_B", "TIER_C", "TIER_D"]
PropertyStatus = Literal[
    "PROSPECT",
    "UNDER_UNDERWRITING",
    "APPROVED_FOR_BID",
    "PASSED",
    "OWNED",
    "HBU_MARKETED",
]
AppraisalStatus = Literal["NONE", "SUBMITTED", "SIGNED", "STALE"]
CertificationPosture = Literal["CERTIFIED", "CONDITIONAL", "SUSPENDED", "UNCERTIFIED"]
HarvestPlanStatus = Literal["ALIGNED", "REPLAN_REQUIRED"]
StandStatus = Literal["CRUISE_OPEN", "INVENTORIED", "SALVAGE_PENDING", "DISPOSED"]
CruiseConfidence = Literal["NONE", "LOW", "NORMAL"]
UnderwritingCaseStatus = Literal[
    "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "REJECTED", "WITHDRAWN"
]
HarvestBlockStatus = Literal[
    "RESERVED", "COMMITTED", "COMPLETED", "CANCELLED", "VOIDED"
]
VoidedReason = Literal["HAZARD_LOSS", "HBU_WITHDRAWAL"]
CarbonProjectStatus = Literal[
    "DRAFT", "VALIDATION", "REGISTERED", "REVERSAL_PENDING", "TERMINATED"
]
CarbonDedicationStatus = Literal["PENDING", "ACTIVE", "REDUCED", "RELEASED"]
HbuParcelStatus = Literal[
    "IDENTIFIED", "LISTED", "UNDER_CONTRACT", "CLOSED", "WITHDRAWN"
]
LeaseStatus = Literal["PENDING", "ACTIVE", "TERMINATED", "EXPIRED"]
AuditStatus = Literal[
    "SCHEDULED",
    "FIELD_WORK",
    "FINDINGS_ISSUED",
    "CAR_REVIEW",
    "SUSPENDED",
    "CLOSED_CONFORMING",
]
FindingStatus = Literal["OPEN", "CAR_SUBMITTED", "CLOSED"]
HazardEventStatus = Literal["REPORTED", "SETTLED"]


class Fund(TypedDict, total=False):
    id: str
    name: str
    vintage_year: int
    committed_capital_usd: float
    target_cash_yield_bps: int
    opening_cash_usd: float
    cash_balance_usd: float
    net_operating_cash_usd: float
    cash_yield_bps: int
    harvest_acceleration_required: bool
    nav_usd: float
    replan_property_count: int
    valuation_basis_stale_count: int
    created_at: str
    updated_at: str
    version: int


class InvestorReport(TypedDict, total=False):
    nav_usd: float
    cash_balance_usd: float
    net_operating_cash_usd: float
    cash_yield_bps: int
    target_cash_yield_bps: int
    harvest_acceleration_required: bool
    replan_property_count: int
    valuation_basis_stale_count: int
    owned_property_count: int
    appraised_value_total_usd: float
    standing_inventory_tons: float


class Property(TypedDict, total=False):
    id: str
    fund_id: str
    name: str
    region_code: RegionCode
    total_acres: float
    haul_distance_miles: int
    insured_value_usd: float
    hbu_acres: float
    hbu_price_per_acre_usd: float
    annual_rec_income_usd: float
    certification_scheme: CertificationScheme
    market_access_tier: MarketAccessTier
    market_access_discount_pct: float
    status: PropertyStatus
    appraisal_status: AppraisalStatus
    certification_posture: CertificationPosture
    harvest_plan_status: HarvestPlanStatus
    appraised_value_usd: Optional[float]
    appraisal_methodology: Optional[AppraisalMethodology]
    appraisal_submitted_by_user_id: Optional[str]
    appraisal_signed_by_user_id: Optional[str]
    appraisal_signed_at: Optional[str]
    acquisition_price_usd: Optional[float]
    wildfire_hazard_index: Optional[float]
    insect_hazard_index: Optional[float]
    weather_hazard_index: Optional[float]
    composite_risk_score: Optional[float]
    insurance_rating_basis: Optional[InsuranceRatingBasis]
    insurance_premium_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Stand(TypedDict, total=False):
    id: str
    property_id: str
    stand_code: str
    acres: float
    species_code: SpeciesCode
    age_years: int
    site_index: int
    status: StandStatus
    plot_count: int
    mean_net_tons_per_acre: Optional[float]
    cruise_confidence: CruiseConfidence
    gross_merch_tons: float
    net_merch_tons: float
    reserved_tons: float
    committed_tons: float
    dedicated_tons: float
    hbu_withdrawn_tons: float
    available_tons: float
    split_from_stand_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CruisePlot(TypedDict, total=False):
    """A cruise plot is immutable once recorded: it carries only `id` and `created_at`."""

    id: str
    stand_id: str
    plot_number: int
    tons_per_acre: float
    defect_pct: float
    net_tons_per_acre: float
    measured_at: str
    measured_by_user_id: str
    created_at: str


class UnderwritingCase(TypedDict, total=False):
    id: str
    property_id: str
    growth_variant: GrowthVariant
    discount_rate_bps: int
    stumpage_price_usd_per_ton: float
    bid_price_usd: float
    status: UnderwritingCaseStatus
    revision_count: int
    timber_pv_usd: float
    hbu_premium_usd: float
    rec_income_pv_usd: float
    pre_fee_value_usd: float
    acquisition_fee_pct: float
    acquisition_fee_usd: float
    underwritten_value_usd: float
    authored_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HarvestBlock(TypedDict, total=False):
    id: str
    stand_id: str
    planned_start_date: str
    planned_end_date: str
    planned_tons: float
    product_mix: ProductMix
    expected_stumpage_price_usd_per_ton: float
    price_index_factor: float
    expected_haul_distance_miles: int
    growth_variant: GrowthVariant
    status: HarvestBlockStatus
    years_to_start: int
    projected_available_tons: float
    severance_tax_usd: float
    provisional_net_revenue_usd: float
    actual_tons: Optional[float]
    realized_price_index_factor: Optional[float]
    final_net_revenue_usd: Optional[float]
    voided_reason: Optional[VoidedReason]
    created_at: str
    updated_at: str
    version: int


class CarbonProject(TypedDict, total=False):
    id: str
    property_id: str
    registry: CarbonRegistry
    crediting_period_years: int
    permanence_term_years: int
    baseline_tons_per_acre: float
    status: CarbonProjectStatus
    dedicated_tons_total: float
    buffer_pool_tons: float
    buffer_deficit_tons: float
    created_at: str
    updated_at: str
    version: int


class CarbonDedication(TypedDict, total=False):
    id: str
    carbon_project_id: str
    stand_id: str
    dedicated_tons: float
    reduced_tons: float
    status: CarbonDedicationStatus
    permanence_end_date: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HbuParcel(TypedDict, total=False):
    id: str
    stand_id: str
    parcel_code: str
    acres: float
    ask_price_usd: float
    status: HbuParcelStatus
    withdrawn_tons: float
    contract_price_usd: Optional[float]
    closing_costs_usd: Optional[float]
    commission_usd: Optional[float]
    net_proceeds_usd: Optional[float]
    derived_stand_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecreationalLease(TypedDict, total=False):
    id: str
    property_id: str
    lessee_name: str
    leased_acres: float
    rent_per_acre_usd: float
    term_start_date: str
    term_end_date: str
    blackout_start_date: str
    blackout_end_date: str
    status: LeaseStatus
    annual_rent_usd: float
    term_days: int
    first_year_prorated_rent_usd: Optional[float]
    earned_rent_usd: Optional[float]
    refunded_rent_usd: Optional[float]
    termination_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificationAudit(TypedDict, total=False):
    id: str
    property_id: str
    audit_type: AuditType
    scheduled_date: str
    status: AuditStatus
    major_finding_count: int
    open_major_count: int
    open_minor_count: int
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    certification_audit_id: str
    finding_code: str
    severity: FindingSeverity
    indicator_ref: str
    due_date: str
    status: FindingStatus
    rejection_count: int
    car_text: Optional[str]
    car_submitted_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReallocationLogEntry(TypedDict, total=False):
    target_type: Literal["HARVEST_BLOCK", "CARBON_DEDICATION"]
    target_id: str
    tons_cut: float
    resulting_status: str


class HazardEvent(TypedDict, total=False):
    id: str
    stand_id: str
    event_type: EventType
    occurred_at: str
    damaged_tons: float
    status: HazardEventStatus
    salvageable_tons: float
    insurance_claim_usd: float
    settled_claim_usd: Optional[float]
    salvage_sold_tons: Optional[float]
    inventory_shortfall_tons: float
    reallocation_log: List[ReallocationLogEntry]
    created_at: str
    updated_at: str
    version: int


JsonDict = Dict[str, Any]
