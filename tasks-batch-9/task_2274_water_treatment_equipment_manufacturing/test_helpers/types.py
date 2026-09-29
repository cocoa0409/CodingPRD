"""Typed shapes for every resource the PRD exposes.

Most resources carry the four common fields (``id``, ``created_at``,
``updated_at``, ``version``). A consumable draw is the exception: the PRD says
both ``updated_at`` and ``version`` are absent from a consumable draw -- not
null, absent -- so its shape declares only ``id`` and ``created_at``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyFields(TypedDict):
    id: str
    created_at: str


class Project(CommonFields):
    name: str
    owner_agency_name: str
    procurement_type: str
    bid_due_at: str
    guarantee_deadline_at: str
    footprint_allowance_sf_per_stage: float
    status: str
    delivery_posture: str
    guarantee_status: str
    governing_influent_profile_id: Optional[str]
    om_manual_status: str
    operator_training_status: str
    spare_parts_list_status: str
    base_bid_amount_cents: int
    bond_premium_cents: int
    contingency_cents: int
    evaluated_bid_price_cents: int
    offered_price_cents: int
    contract_amount_cents: int
    liquidated_damages_cents: int
    awarded_at: Optional[str]


class InfluentProfile(CommonFields):
    project_id: str
    sample_label: str
    design_flow_mgd: float
    peak_factor: float
    turbidity_ntu: float
    tds_mg_l: float
    toc_mg_l: float
    chloride_mg_l: float
    temperature_c: float
    ph: float
    qa_status: str
    qa_decided_by_user_id: Optional[str]
    qa_note: Optional[str]


class TreatmentObjective(CommonFields):
    project_id: str
    parameter: str
    limit_value: float
    basis: str
    regulatory_driver: str
    status: str


class ProcessTechnology(CommonFields):
    code: str
    name: str
    role: str
    max_feed_turbidity_ntu: float
    max_feed_tds_mg_l: float
    min_design_flow_mgd: float
    max_design_flow_mgd: float
    unit_capex_cents_per_mgd: int
    energy_kwh_per_mg: float
    footprint_sf_per_mgd: float
    requires_code_stamp: str
    chemical_service_class: str
    consumable_item_code: Optional[str]
    status: str


class MaterialSpec(CommonFields):
    code: str
    max_chloride_ppm: float
    max_temp_c: float
    max_pressure_psig: int
    ph_min: float
    ph_max: float
    asme_u_capable: bool
    nsf61_certified: bool
    awwa_compliant: bool
    cost_index: float
    service_classes_allowed: List[str]


class TreatmentStage(CommonFields):
    project_id: str
    technology_id: str
    upstream_stage_id: Optional[str]
    role: str
    stage_index: int
    design_flow_mgd: float
    evaluated_cost_cents: int
    equipment_base_cost_cents: int
    status: str


class EquipmentPackage(CommonFields):
    treatment_stage_id: str
    material_spec_id: str
    tag_number: str
    design_pressure_psig: int
    design_temp_c: float
    code_stamp_required: str
    budgetary_cost_cents: int
    firm_cost_cents: int
    cost_variance_pct: float
    variance_flag: bool
    status: str
    revision_round: int
    designed_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    approved_at: Optional[str]
    released_at: Optional[str]


class Skid(CommonFields):
    equipment_package_id: str
    serial_no: str
    footprint_sf: float
    requires_exclusive_bay: bool
    mechanical_status: str
    controls_status: str
    fat_readiness: str
    rework_count: int


class TestBay(CommonFields):
    bay_code: str
    max_skid_footprint_sf: float
    changeover_buffer_minutes: int
    crane_capacity_tons: float
    status: str
    reserved_footprint_minutes: float


class FatRun(CommonFields):
    skid_id: str
    test_bay_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    round_no: int
    footprint_sf: float
    duration_minutes: int
    status: str
    punchlist_item_count: int
    witnessed_by_user_id: Optional[str]
    result_note: Optional[str]


class OrEqualSubmittal(CommonFields):
    project_id: str
    spec_section: str
    named_basis_of_design: str
    authored_by_user_id: Optional[str]
    status: str
    revision_round: int
    decided_by_user_id: Optional[str]
    submitted_at: Optional[str]
    compliance_score: float
    open_fundamental_count: int


class SpecDeviation(CommonFields):
    or_equal_submittal_id: str
    spec_paragraph: str
    severity: str
    description: str
    disposition: str
    dispositioned_by_user_id: Optional[str]
    weighted_penalty_points: float


class DemoReading(TypedDict):
    parameter: str
    measured_value: float


class DemoEvaluationLine(TypedDict):
    parameter: str
    basis: str
    limit_value: float
    compared_value: float
    margin_pct: float
    passed: bool


class PerformanceDemo(CommonFields):
    project_id: str
    skid_id: str
    window_start_at: str
    window_end_at: str
    readings: List[DemoReading]
    round_no: int
    evaluation: List[DemoEvaluationLine]
    min_margin_pct: Optional[float]
    result: str
    recorded_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]


class ServiceAgreement(CommonFields):
    project_id: str
    term_months: int
    annual_fee_cents: int
    reserve_funded_cents: int
    membrane_installed_at: str
    reserve_committed_accrual_cents: int
    reserve_committed_settled_cents: int
    reserve_available_cents: int
    settlement_variance_cents: int
    expires_at: Optional[str]
    status: str
    activated_at: Optional[str]


class ConsumableDraw(AppendOnlyFields):
    """Append-only: the PRD gives a consumable draw no updated_at and no version."""

    service_agreement_id: str
    draw_type: str
    item_code: str
    quantity: int
    catalog_unit_cost_cents: int
    invoiced_unit_cost_cents: int
    reverses_draw_id: Optional[str]
    accrual_amount_cents: int
    settled_amount_cents: int
    warranty_credit_cents: int
    posted_by_user_id: Optional[str]


class PaginationMeta(TypedDict):
    total_count: int
    limit: int
    offset: int
    has_more: bool


ApiEnvelope = Dict[str, Any]
