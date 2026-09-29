"""Response shapes published by the Pavement Management & Resurfacing Program API.

Every resource carries the four identity and audit fields the PRD mandates:
``id``, ``created_at``, ``updated_at`` and an integer ``version`` that is
incremented on every mutation.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class NetworkSegment(CommonFields, total=False):
    street_name: str
    from_node: str
    to_node: str
    geo_zone: str
    functional_class: str
    surface_type: str
    length_ft: float
    width_ft: float
    area_sy: float
    baseline_condition_index: float
    last_treatment_type: str
    last_treatment_date: Optional[str]
    decay_coefficient: float
    decay_knee_coefficient: float
    condition_index: float
    condition_index_source: str
    condition_band: str
    moratorium_until: Optional[str]
    active_project_count: int
    open_service_request_count: int


class ConditionSurvey(CommonFields, total=False):
    survey_year: int
    collection_method: str
    survey_status: str
    observation_count: int
    accepted_observation_count: int
    network_condition_index: Optional[float]
    sealed_at: Optional[str]


class DistressObservation(CommonFields, total=False):
    survey_id: str
    segment_id: str
    alligator_cracking_sqft: float
    longitudinal_cracking_lf: float
    rutting_depth_in: float
    patching_sqft: float
    iri_in_per_mi: float
    sample_coverage_pct: float
    deduct_total: float
    measured_condition_index: float
    qc_status: str
    qc_note: Optional[str]


class TreatmentCandidate(CommonFields, total=False):
    survey_id: str
    segment_id: str
    treatment_type: str
    selection_condition_index: float
    expected_service_life_years: int
    treatment_pci_gain: float
    estimated_cost_cents: int
    benefit_cost_ratio: float
    candidate_status: str
    override_reason: Optional[str]


class BudgetScenario(CommonFields, total=False):
    survey_id: str
    scenario_name: str
    funding_cents: int
    strategy: str
    horizon_years: int
    analysis_date: str
    scenario_status: str
    allocation_count: int
    funded_cost_cents: int
    backlog_cents: int
    committed_cents: int
    uncommitted_cents: int
    projected_network_pci: Optional[float]
    do_nothing_network_pci: Optional[float]
    adopted_by_user_id: Optional[str]


class ScenarioAllocation(CommonFields, total=False):
    scenario_id: str
    candidate_id: str
    rank: int
    allocation_status: str
    allocated_cents: int
    source: str


class Contractor(CommonFields, total=False):
    legal_name: str
    max_concurrent_projects: int
    standing: str
    interim_performance_score: Optional[float]
    final_performance_score: Optional[float]
    passed_test_count: int
    failed_test_count: int
    remediation_event_count: int
    days_late_total: int
    accepted_project_count: int


class ResurfacingProject(CommonFields, total=False):
    scenario_id: str
    contractor_id: Optional[str]
    project_name: str
    geo_zone: str
    planned_start_date: str
    planned_end_date: str
    delivery_status: str
    quality_status: str
    segment_count: int
    planned_area_sy: float
    bundle_base_cents: int
    contingency_cents: int
    utility_share_cents: int
    project_total_estimate_cents: int
    award_amount_cents: Optional[int]
    clearance_outstanding_count: int
    open_remediation_count: int
    accepted_at: Optional[str]
    days_late: int
    substantial_completion_at: Optional[str]
    accepting_inspector_user_id: Optional[str]


class ProjectSegment(CommonFields, total=False):
    project_id: str
    segment_id: str
    candidate_id: str
    treatment_type: str
    line_area_sy: float
    line_cost_cents: int
    design_thickness_in: float
    work_window_start: str
    work_window_end: str
    work_state: str
    notice_state: str
    parking_restriction_start: Optional[str]
    parking_restriction_end: Optional[str]
    driveway_access_plan: Optional[str]
    notice_delivered_at: Optional[str]
    notice_round: int
    pay_factor: Optional[float]
    test_count: int


class UtilityCoordination(CommonFields, total=False):
    project_id: str
    utility: str
    coordination_status: str
    planned_work_start: Optional[str]
    planned_work_end: Optional[str]
    work_completed_at: Optional[str]
    round_count: int
    response_note: Optional[str]


class CutPermit(CommonFields, total=False):
    segment_id: str
    applicant_utility: str
    requested_start: str
    requested_end: str
    cut_area_sqft: float
    emergency: bool
    permit_status: str
    moratorium_remaining_days: int
    fee_multiplier: float
    degradation_fee_cents: int
    waiver_reason: Optional[str]
    decided_at: Optional[str]
    cut_completed_at: Optional[str]


class AcceptanceTest(CommonFields, total=False):
    project_segment_id: str
    core_density_pct: float
    iri_in_per_mi: float
    thickness_in: float
    witness_inspector_user_id: str
    test_round: int
    computed_pay_factor: float
    computed_outcome: str
    test_status: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]


class ServiceRequest(CommonFields, total=False):
    segment_id: str
    capital_project_id: Optional[str]
    complaint_type: str
    reported_severity: str
    location_note: str
    request_status: str
    sla_due_at: str
    sla_breached: bool
    triaged_at: Optional[str]
    closed_at: Optional[str]
    closure_code: Optional[str]


class ContractorScorecard(TypedDict, total=False):
    contractor_id: str
    interim_performance_score: Optional[float]
    final_performance_score: Optional[float]
    quality_component: float
    schedule_component: float
    remediation_component: float
    standing: str
    passed_test_count: int
    failed_test_count: int
    remediation_event_count: int
    days_late_total: int
    accepted_project_count: int


ResponseEnvelope = Dict[str, Any]
EntityList = List[Dict[str, Any]]
