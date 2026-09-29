"""Typed shapes for the resources declared by the PRD.

The PRD states that every resource carries `id`, `created_at`, `updated_at` and
`version`, so every shape below extends :class:`CommonFields`.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class SearchRing(CommonFields, total=False):
    name: str
    market_code: str
    center_lat: float
    center_lon: float
    radius_m: int
    required_agl_m: int
    objective_type: str
    target_rsrp_dbm: int
    target_capacity_gbps: float
    market_benchmark_monthly_rent_usd: float
    capex_budget_usd: float
    priority_rank: int
    status: str
    candidate_count: int
    committed_capex_usd: float
    reopen_count: int
    selected_candidate_id: Optional[str]


class Landlord(CommonFields, total=False):
    legal_name: str
    entity_type: str
    contact_email: str
    market_code: str
    standing: str
    outreach_optout: bool
    executed_lease_count: int


class Jurisdiction(CommonFields, total=False):
    name: str
    market_code: str
    by_right_review_days: int
    conditional_use_review_days: int
    variance_review_days: int
    hearing_cadence_days: int
    requires_visual_simulation: bool
    min_visual_simulations: int
    max_continuances: int
    historic_district_flag: bool
    tribal_consultation_required: bool
    historical_delay_factor: float
    appeal_window_days: int


class Candidate(CommonFields, total=False):
    search_ring_id: str
    landlord_id: str
    jurisdiction_id: str
    owning_agent_user_id: str
    site_type: str
    lat: float
    lon: float
    distance_from_center_m: int
    agl_m: int
    months_to_availability: int
    measured_rsrp_dbm: int
    offered_capacity_gbps: float
    acquisition_status: str
    feasibility_status: str
    rf_qualification_score: Optional[float]
    outreach_event_count: int
    environmental_cleared: bool
    permit_issued: bool


class LeaseAgreement(CommonFields, total=False):
    candidate_id: str
    landlord_id: str
    negotiating_agent_user_id: str
    base_monthly_rent_usd: float
    escalation_type: str
    escalation_pct: Optional[float]
    escalation_step_usd: Optional[float]
    initial_term_years: int
    renewal_option_count: int
    renewal_term_years: int
    equipment_expansion_sqft: int
    revenue_share_pct: float
    status: str
    round_count: int
    last_counter_rent_usd: Optional[float]
    rent_variance_pct: Optional[float]
    committed_rent_provisional_usd: Optional[float]
    committed_rent_final_usd: Optional[float]
    execution_date: Optional[str]


class ZoningApplication(CommonFields, total=False):
    candidate_id: str
    jurisdiction_id: str
    application_type: str
    filed_by_user_id: str
    status: str
    submitted_date: Optional[str]
    decision_date: Optional[str]
    hearing_date: Optional[str]
    hearings_held_count: int
    continuance_count: int
    visual_simulation_count: int
    zoning_fee_total_usd: Optional[float]
    shot_clock_deadline_date: Optional[str]
    tolled_days: int
    incomplete_since_date: Optional[str]


class StructuralAnalysis(CommonFields, total=False):
    candidate_id: str
    analysis_type: str
    existing_load_pct: float
    appurtenance_count: int
    wind_speed_mph: int
    ice_thickness_in: float
    performed_by_user_id: str
    status: str
    capacity_utilization_pct: Optional[float]
    result: Optional[str]


class ModificationDesign(CommonFields, total=False):
    structural_analysis_id: str
    scope: str
    estimated_cost_usd: float
    designed_by_user_id: str
    status: str
    revision_count: int
    certified_by_user_id: Optional[str]
    rejection_reason: Optional[str]


class EnvironmentalReview(CommonFields, total=False):
    candidate_id: str
    nepa_category: str
    section106_required: bool
    status: str
    tribal_consultation_required: bool
    tcns_notice_date: Optional[str]
    tribal_response_deadline_date: Optional[str]
    tribal_branch_status: str
    public_notice_branch_status: str


class ConstructionPermit(CommonFields, total=False):
    candidate_id: str
    permit_type: str
    valid_days: int
    status: str
    issued_date: Optional[str]
    expiry_date: Optional[str]
    revocation_reason: Optional[str]


class UtilityProvider(CommonFields, total=False):
    name: str
    market_code: str
    concurrent_crew_capacity: int
    quoted_interval_days: int
    committed_crew_days: int


class UtilityBackhaulOrder(CommonFields, total=False):
    candidate_id: str
    provider_id: str
    order_type: str
    window_start: str
    window_end: str
    status: str
    crew_days: int
    delivered_date: Optional[str]


class OnAirPlan(CommonFields, total=False):
    search_ring_id: str
    target_on_air_date: str
    status: str
    driver_candidate_id: Optional[str]
    baseline_forecast_date: Optional[str]
    risk_adjusted_forecast_date: Optional[str]
    schedule_risk_score: Optional[float]
    risk_band: Optional[str]
    reset_count: int
    reforecast_count: int
    actual_on_air_date: Optional[str]
    variance_days: Optional[int]


Envelope = Dict[str, Any]
Rows = List[Dict[str, Any]]

__all__ = [
    "CommonFields",
    "SearchRing",
    "Landlord",
    "Jurisdiction",
    "Candidate",
    "LeaseAgreement",
    "ZoningApplication",
    "StructuralAnalysis",
    "ModificationDesign",
    "EnvironmentalReview",
    "ConstructionPermit",
    "UtilityProvider",
    "UtilityBackhaulOrder",
    "OnAirPlan",
    "Envelope",
    "Rows",
]
