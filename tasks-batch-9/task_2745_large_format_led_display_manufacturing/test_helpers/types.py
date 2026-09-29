"""Typed shapes for every record the LED Display Manufacturing API persists.

All eleven record types carry ``id``, ``created_at``, ``updated_at`` and
``version``; no record type in this system omits ``updated_at`` or ``version``.
``CommonFields`` captures that shared identity block and every record shape
inherits it.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    """The identity block every persisted record carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class DisplayModel(CommonFields, total=False):
    name: str
    pixel_pitch_mm: float
    rated_brightness_nits: int
    environmental_rating: str
    module_width_mm: int
    module_height_mm: int
    module_pixel_cols: int
    module_pixel_rows: int
    cabinet_width_mm: int
    cabinet_height_mm: int
    modules_per_cabinet: int
    cabinet_weight_kg: float
    price_per_sqm_cents: int
    dead_pixel_ppm_limit: float
    module_dead_pixel_max: int
    module_cluster_max: int
    reference_color_x: float
    reference_color_y: float
    burn_in_hours_required: int
    max_drive_pct: int
    # Derived at registration time.
    module_area_sqm: float
    cabinet_area_sqm: float
    module_pixel_count: int
    cabinet_pixel_count: int
    recommended_min_viewing_distance_m: float
    required_load_kg_per_sqm: float


class BurnInChamber(CommonFields, total=False):
    name: str
    slot_capacity: int
    turnaround_minutes: int
    certified_max_drive_pct: int
    reserved_slot_total: int
    scheduled_run_count: int


class CommissioningCrew(CommonFields, total=False):
    name: str
    region_code: str
    certification_level: str
    scheduled_visit_count: int


class DisplayProject(CommonFields, total=False):
    customer_name: str
    install_environment: str
    site_region_code: str
    display_model_id: str
    cabinet_grid_cols: int
    cabinet_grid_rows: int
    min_viewing_distance_m: float
    target_brightness_nits: int
    redundancy_mode: str
    output_port_count: int
    port_bandwidth_mbps: int
    color_depth_bits: int
    refresh_rate_hz: int
    player_count: int
    # Derived sizing, price and bandwidth.
    cabinet_count: int
    module_count: int
    total_area_sqm: float
    contract_amount_cents: int
    required_data_mbps: int
    effective_capacity_mbps: int
    data_load_pct: float
    # Two independent state dimensions plus the computed posture.
    engineering_state: str
    production_state: str
    service_posture: str
    approved_revision_number: Optional[int]
    qa_passed_cabinet_count: int
    mounted_cabinet_count: int
    quarantined_cabinet_count: int


class DrawingRevision(CommonFields, total=False):
    project_id: str
    revision_number: int
    structural_load_kg_per_sqm: float
    wind_load_kph: int
    mounting_type: str
    service_access_side: str
    required_load_kg_per_sqm: float
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    revision_state: str


class Cabinet(CommonFields, total=False):
    project_id: str
    grid_row: int
    grid_col: int
    cabinet_state: str
    installed_module_count: int
    occupied_slot_indexes: List[int]
    total_dead_pixel_count: int
    dead_pixel_ppm: float
    as_built_uniformity_score: Optional[float]
    baseline_uniformity_score: Optional[float]
    baseline_module_ids: List[str]
    qa_approved_by_user_id: Optional[str]


class Module(CommonFields, total=False):
    display_model_id: str
    serial_no: str
    cabinet_id: Optional[str]
    slot_index: Optional[int]
    replaces_module_id: Optional[str]
    reserved_service_contract_id: Optional[str]
    dead_pixel_count: Optional[int]
    max_cluster_size: Optional[int]
    measured_brightness_nits: Optional[int]
    measured_color_x: Optional[float]
    measured_color_y: Optional[float]
    color_bin: Optional[str]
    color_bin_rank: Optional[int]
    rework_cycles: int
    calibrated_by_user_id: Optional[str]
    module_state: str


class BurnInRun(CommonFields, total=False):
    cabinet_id: str
    burn_in_chamber_id: str
    window_start: str
    window_end: str
    slots_required: int
    drive_pct: int
    ambient_c: float
    occupied_until: str
    new_dead_pixel_count: Optional[int]
    measured_brightness_nits: Optional[int]
    measured_uniformity_pct: Optional[float]
    cabinet_dead_pixel_ppm: Optional[float]
    run_state: str
    abort_reason: Optional[str]
    completed_by_user_id: Optional[str]


class CommissioningVisit(CommonFields, total=False):
    project_id: str
    commissioning_crew_id: str
    window_start: str
    window_end: str
    visit_state: str
    measured_brightness_nits: Optional[int]
    measured_uniformity_pct: Optional[float]
    arrived_at: Optional[str]
    signed_off_at: Optional[str]
    abort_reason: Optional[str]


class ServiceContract(CommonFields, total=False):
    project_id: str
    tier: str
    spare_pct_bp: int
    term_months: int
    response_hours: int
    spare_required_count: int
    spare_reserved_count: int
    gross_fee_cents: int
    subtotal_fee_cents: int
    volume_discount_pct: float
    annual_fee_cents: int
    sla_breach_count: int
    warranty_start_at: Optional[str]
    contract_state: str


class ServiceCase(CommonFields, total=False):
    service_contract_id: str
    cabinet_id: str
    faulty_module_id: Optional[str]
    case_type: str
    severity: str
    symptom: str
    measured_brightness_nits: Optional[int]
    reported_at: str
    response_deadline_at: str
    responded_at: Optional[str]
    response_breached: bool
    elapsed_warranty_months: Optional[int]
    allowed_degradation_pct: Optional[float]
    degradation_pct: Optional[float]
    shortfall_pct: Optional[float]
    assessment_basis: Optional[str]
    credit_cents: Optional[int]
    denial_reason: Optional[str]
    resolved_faulty_module_id: Optional[str]
    replacement_module_id: Optional[str]
    case_state: str
