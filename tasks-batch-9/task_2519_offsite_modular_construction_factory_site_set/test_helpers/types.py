"""Response shapes for the ten resource types of the offsite modular API.

Every resource carries ``id``, ``created_at``, ``updated_at`` and ``version``,
so those four live on a shared base that each entity extends.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """The four properties every resource in this system carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Factory(CommonFields, total=False):
    name: str
    code: str
    takt_minutes: int
    station_count: int
    parallel_station_capacity: int
    wip_unit_value_cents: int
    shift_start_minute_of_day: int
    shift_minutes_per_day: int
    line_state: str
    committed_line_minutes: int


class InspectionAgency(CommonFields, total=False):
    name: str
    agency_code: str
    accredited_state_codes: List[str]
    per_inspection_fee_cents: int
    accreditation_state: str
    hold_authority: bool


class Project(CommonFields, total=False):
    name: str
    factory_id: str
    state_code: str
    ahj_code: str
    planned_module_count: int
    contract_price_cents: int
    deposit_pct: float
    retainage_pct: float
    crane_capacity_chart: List[Dict[str, int]]
    crane_rigging_buffer_minutes: int
    set_sequence_policy: str
    weather_exposure_limit_hours: float
    forecast_precip_probability_pct: int
    forecast_wind_gust_mph: int
    last_weather_observed_at: Optional[str]
    permit_posture: str
    phase: str
    wip_certified_cents: int
    funded_to_date_cents: int
    modules_set_count: int
    modules_connected_count: int


class DesignPackage(CommonFields, total=False):
    project_id: str
    revision_index: int
    module_split_count: int
    connection_detail_state: str
    open_connection_conflicts: int
    field_scope_items_open: int
    supersedes_package_id: Optional[str]
    freeze_state: str
    revision_round: int
    factory_compatibility_score: int
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]


class ModuleUnit(CommonFields, total=False):
    project_id: str
    design_package_id: str
    module_code: str
    set_sequence_index: int
    width_in: int
    length_in: int
    height_in: int
    gross_weight_lb: int
    pair_role: str
    pair_group_code: Optional[str]
    connection_scope_owner: str
    envelope_class: str
    production_status: str
    qc_status: str
    site_status: str
    station_index: int
    line_slot_start: Optional[str]
    line_slot_end: Optional[str]
    line_slot_minutes: int
    wip_earned_cents: int
    shipment_id: Optional[str]
    pick_window_start: Optional[str]
    pick_window_end: Optional[str]
    pick_radius_ft: Optional[int]
    rigging_weight_lb: Optional[int]
    crane_utilization_pct: float
    set_at: Optional[str]
    connected_at: Optional[str]
    exposure_open_hours: float
    defect_count_factory: int
    defect_count_field: int


class PermitRecord(CommonFields, total=False):
    project_id: str
    track: str
    scope: str
    status: str
    conditions_count: int
    insignia_count_issued: int
    pinned_package_id: Optional[str]
    expires_at: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]


class InspectionRecord(CommonFields, total=False):
    module_id: str
    agency_id: str
    stage: str
    result: str
    hold_state: str
    defect_count: int
    severity_max: int
    corrective_note: Optional[str]
    recorded_at: Optional[str]
    recorded_by_user_id: Optional[str]


class Shipment(CommonFields, total=False):
    project_id: str
    carrier_code: str
    route_state_codes: List[str]
    planned_departure_at: str
    planned_arrival_at: str
    status: str
    route_survey_state: str
    max_envelope_class: str
    loaded_module_count: int
    permit_fee_cents: int
    escort_required: bool
    escort_confirmed: bool
    survey_completed_at: Optional[str]
    permit_expires_at: Optional[str]
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    cancel_reason: Optional[str]


class DefectClaim(CommonFields, total=False):
    module_id: str
    inspection_id: Optional[str]
    discovered_phase: str
    description: str
    repair_cost_cents: int
    status: str
    responsibility: str
    adjudication_round: int
    factory_share_pct: float
    field_share_pct: float
    factory_charge_cents: int
    field_charge_cents: int
    warranty_bucket: str
    adjudicated_by_user_id: Optional[str]
    dispute_note: Optional[str]


class DrawRequest(CommonFields, total=False):
    project_id: str
    draw_index: int
    basis_mode: str
    certifying_agency_id: str
    status: str
    basis_module_count: int
    basis_earned_cents: int
    requested_cents: int
    certified_basis_cents: int
    certified_cents: int
    retainage_held_cents: int
    net_funded_cents: int
    certified_at: Optional[str]
    funded_at: Optional[str]
    reject_reason: Optional[str]


JsonDict = Dict[str, Any]
