"""
TypedDict shapes for every resource the API returns.

Field names and nullability follow the PRD entity narrative. Every resource
carries the four audit columns id, created_at, updated_at and version, so those
live on a shared base.
"""

from typing import Any, Dict, List, Optional, TypedDict


class AuditColumns(TypedDict):
    """The four columns every resource in this API carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Plant(AuditColumns, total=False):
    plant_code: str
    name: str
    grid_x: int
    grid_y: int
    market_radius_miles: int
    freight_rate_cents_per_ton_mile: int
    base_capacity_green_units_per_day: int
    unloading_equipment_available: List[str]
    status: str
    fired_scrap_units: int
    idled_at: Optional[str]


class ClayPit(AuditColumns, total=False):
    plant_id: str
    pit_name: str
    material_type: str
    proven_reserve_tons: float
    iron_oxide_pct: float
    lime_pct: float
    committed_tons: float
    consumed_tons: float
    available_tons: float
    status: str


class BodyFormulation(AuditColumns, total=False):
    plant_id: str
    supersedes_formulation_id: Optional[str]
    formulation_code: str
    target_color_family: str
    target_cdi: float
    target_soak_hours: float
    clay_tons_per_thousand_units: float
    components: List[Dict[str, Any]]
    component_share_total_pct: float
    blend_iron_oxide_pct: Optional[float]
    blend_lime_pct: Optional[float]
    shale_share_pct: Optional[float]
    absorption_index: Optional[float]
    computed_durability_grade: Optional[str]
    status: str
    qualified_at: Optional[str]
    dequalified_count: int


class Kiln(AuditColumns, total=False):
    plant_id: str
    kiln_code: str
    position_count: int
    setpoint_peak_c: int
    cooldown_buffer_hours: float
    status: str


class KilnCar(AuditColumns, total=False):
    plant_id: str
    car_code: str
    capacity_green_units: int
    status: str
    current_production_run_id: Optional[str]


class ProductionRun(AuditColumns, total=False):
    plant_id: str
    formulation_id: str
    kiln_car_id: str
    kiln_run_id: Optional[str]
    run_code: str
    texture: str
    green_units_set: int
    kiln_position: Optional[int]
    projected_net_green_units: int
    green_loss_units: Optional[int]
    net_green_units: Optional[int]
    green_loss_pct: Optional[float]
    green_loss_variance_units: Optional[int]
    clay_tons_committed: float
    scrap_units: int
    status: str


class KilnRun(AuditColumns, total=False):
    kiln_id: str
    formulation_id: str
    run_code: str
    start_at: str
    end_at: str
    planned_peak_temp_c: int
    planned_soak_hours: float
    actual_peak_temp_c: Optional[int]
    actual_soak_hours: Optional[float]
    base_cdi: Optional[float]
    firing_curve_deviation: Optional[float]
    loaded_units: int
    graded_by_user_id: Optional[str]
    status: str


class FiredLot(AuditColumns, total=False):
    production_run_id: str
    lot_code: str
    kiln_position: int
    fired_units: int
    grade: str
    position_cdi: float
    color_index: float
    color_family: str
    texture: str
    durability_grade: str
    dye_lot_code: str
    source_formulation_id: str
    reserved_units: int
    consumed_units: int
    available_units: int
    quarantine_reason: Optional[str]
    status: str


class Order(AuditColumns, total=False):
    plant_id: Optional[str]
    order_code: str
    jobsite_grid_x: int
    jobsite_grid_y: int
    requested_units: int
    color_family: str
    texture: str
    durability_grade: str
    is_special_order: bool
    requires_panel_approval: bool
    unloading_equipment_required: str
    banding_type: str
    pallet_count: Optional[int]
    band_count: Optional[int]
    unloading_equipment_provided: Optional[str]
    distance_miles: Optional[int]
    estimated_billable_tons: Optional[float]
    estimated_base_freight_cents: Optional[int]
    estimated_fuel_surcharge_cents: Optional[int]
    estimated_freight_cents: Optional[int]
    final_billable_tons: Optional[float]
    final_base_freight_cents: Optional[int]
    final_fuel_surcharge_cents: Optional[int]
    final_freight_cents: Optional[int]
    freight_variance_cents: Optional[int]
    lead_time_days: Optional[int]
    promised_ship_date: Optional[str]
    assigned_by_user_id: Optional[str]
    packaged_by_user_id: Optional[str]
    assigned_at: Optional[str]
    delivered_at: Optional[str]
    invoiced_at: Optional[str]
    cancellation_reason: Optional[str]
    fulfillment_status: str
    freight_status: str


class ShippedBlend(AuditColumns, total=False):
    order_id: str
    blend_code: str
    target_color_index_min: float
    target_color_index_max: float
    target_color_index_midpoint: float
    requested_units: int
    allocated_units: int
    weighted_color_index: Optional[float]
    color_range_span: Optional[float]
    dye_lot_count: int
    panel_delta_e: Optional[float]
    composed_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    rejection_reason: Optional[str]
    rejection_count: int
    status: str


class BlendComponent(AuditColumns, total=False):
    blend_id: str
    fired_lot_id: str
    units: int
    color_index_at_allocation: float
    contribution_index: float
    source: str
    status: str


class SamplePanel(AuditColumns, total=False):
    order_id: str
    formulation_id: str
    dye_lot_id: str
    panel_code: str
    panel_color_index: float
    tolerance_delta_e: float
    pinned_formulation_version: Optional[int]
    pinned_dye_lot_code: Optional[str]
    approved_color_index: Optional[float]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    expires_at: Optional[str]
    revision_round: int
    revision_note: Optional[str]
    status: str
