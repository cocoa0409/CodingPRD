"""TypedDict shapes for every resource the PRD defines.

Each shape carries the resource's own fields plus the common identity fields of
§2.4 — ``id``, ``created_at``, ``updated_at`` and ``version``. Load study rows
are the single exception: §2.4 states that a study "carries only `id` and
`created_at`. It has no `updated_at` and no `version` field at all", so
``LoadStudy`` deliberately omits both.
"""

from typing import Optional, TypedDict


class SitingProgram(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    target_load_mw: float
    required_energization_date: str
    capital_budget_usd: float
    program_annual_load_mwh: float
    program_status: str
    committed_load_mw: float
    renewable_coverage_pct: float
    option_exposure_usd: float
    forfeited_premium_usd: float
    capitalized_premium_usd: float
    premium_committed_total_usd: float
    full_land_control_site_count: int


class Utility(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    state_code: str
    balancing_authority: str
    total_transmission_capacity_mw: float
    reserved_capacity_mw: float
    available_capacity_mw: float
    interconnect_study_fee_per_mw_usd: float
    network_upgrade_rate_usd_per_mw: float
    commissioning_buffer_days: int
    energization_lead_days: int
    queue_policy: str


class WaterSource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    basin_code: str
    state_code: str
    annual_permitted_mgal: float
    drought_stage: str
    stage_curtailment_pct: float
    effective_supply_mgal: float
    committed_annual_demand_mgal: float
    last_declaration_effective_date: Optional[str]


class CandidateSite(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    utility_id: str
    water_source_id: str
    name: str
    state_code: str
    county: str
    gross_acres: float
    status: str
    transmission_headroom_mw: Optional[float]
    fiber_route_count: Optional[int]
    seismic_hazard_index: Optional[float]
    flood_hazard_index: Optional[float]
    wind_hazard_index: Optional[float]
    craft_labor_supply_index: Optional[int]
    construction_peak_headcount: Optional[int]
    wage_premium_pct: Optional[float]
    cooling_type: Optional[str]
    annual_water_demand_mgal: Optional[float]
    hazard_tier: Optional[str]
    workforce_availability_ratio: Optional[float]
    water_headroom_mgal: Optional[float]
    water_feasible: bool
    screening_score: Optional[float]
    energization_risk_tier: str
    land_control_pct: float
    land_control_status: str
    site_capital_commitment_usd: float
    screened_by_user_id: Optional[str]
    committed_by_user_id: Optional[str]
    disqualification_reason: Optional[str]


class InterconnectionApplication(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    site_id: str
    utility_id: str
    requested_mw: float
    window_start: str
    window_end: str
    status: str
    submitted_at: Optional[str]
    queue_position: int
    study_round: int
    diversified_peak_mw: Optional[float]
    study_fee_usd: float
    network_upgrade_cost_usd: float
    reserved_mw: float
    committed_energization_date: Optional[str]
    delay_exposure_usd: float
    withdrawal_reason: Optional[str]


class LoadStudy(TypedDict, total=False):
    """Append-only historical artifact: only ``id`` and ``created_at`` accompany
    the study's own fields — no ``updated_at`` and no ``version`` (§2.4)."""

    id: str
    created_at: str
    application_id: str
    study_round: int
    it_load_mw: float
    cooling_load_mw: float
    ancillary_load_mw: float
    diversity_factor: float
    nameplate_peak_mw: float
    diversified_peak_mw: float
    upgrade_required: bool
    network_upgrade_cost_usd: float
    filed_by_user_id: str


class IncentiveNegotiation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    site_id: str
    authority_level: str
    counterparty_name: str
    status: str
    round_count: int
    last_party: Optional[str]
    sales_tax_exemption_pct: Optional[float]
    abatement_years: Optional[int]
    abatement_pct: Optional[float]
    jobs_commitment: Optional[int]
    capex_commitment_usd: Optional[float]
    npv_incentive_usd: float
    sales_tax_benefit_usd: float
    abatement_npv_usd: float
    clawback_exposure_usd: float
    signed_by_user_id: Optional[str]
    ratified_by_user_id: Optional[str]


class ZoningApplication(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    site_id: str
    jurisdiction: str
    hearing_date: str
    noise_limit_dba: float
    projected_noise_dba: float
    visual_mitigation_tier: str
    status: str
    continuance_count: int
    objection_count: int
    weighted_opposition_score: float
    noise_excess_dba: float
    required_mitigation_tier: str
    mitigation_cost_usd: float
    conditions_escrow_usd: float
    decision_note: Optional[str]


class PowerPurchaseAgreement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    counterparty_name: str
    technology: str
    contracted_capacity_mw: float
    annual_generation_mwh: float
    hourly_matched_mwh: float
    strike_price_usd_per_mwh: float
    matching_mode: str
    delivery_start: str
    delivery_end: str
    status: str
    credited_coverage_mwh: float
    annual_cost_usd: float


class LandParcelOption(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    site_id: str
    replaces_option_id: Optional[str]
    parcel_apn: str
    phase_index: int
    acres: float
    option_premium_usd: float
    purchase_price_usd: float
    premium_credit_pct: float
    window_start: str
    window_end: str
    status: str
    premium_credited_usd: float
    net_purchase_usd: float
    exercised_at: Optional[str]
    lapsed_at: Optional[str]


# Field sets that several tests check as a group.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
LOAD_STUDY_IDENTITY_FIELDS = ("id", "created_at")
LOAD_STUDY_FORBIDDEN_FIELDS = ("updated_at", "version")
