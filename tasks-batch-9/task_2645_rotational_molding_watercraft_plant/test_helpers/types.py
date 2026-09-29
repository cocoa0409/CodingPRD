"""Typed shapes for the entities and computed projections in PRD.md.

These are documentation-grade ``TypedDict``s: every one is ``total=False`` so a
partial response body still type-checks, and their only job is to give the test
suite a single authoritative spelling for every field name PRD.md declares.
Numeric fields arrive as JSON numbers; tests that compare them must first
convert to ``Decimal`` at the scale PRD.md section 2.4 declares for that field.
"""

from typing import Any, TypedDict


class CommonFields(TypedDict, total=False):
    """Fields PRD.md section 2.4 puts on every entity in this API."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ProductModel(CommonFields, total=False):
    """A ProductModel row as PRD.md section 2.8 declares it."""

    model_code: str
    hull_type: str
    size_class: str
    resin_grade: str
    master_color_code: str
    max_color_delta_e: float
    required_additive_package_code: str
    max_regrind_pct: float
    min_melt_index_g10min: float
    max_melt_index_g10min: float
    nominal_charge_kg: float
    charge_tolerance_pct: float
    min_cooling_minutes: int
    target_wall_thickness_mm: float
    wall_thickness_min_mm: float
    wall_cv_max_pct: float
    impact_test_min_joules: float
    gross_cube_m3: float
    nest_factor: float
    unit_weight_kg: float
    msrp_cents: int
    warranty_basis: str
    initial_warranty_reserve_cents: int
    warranty_reserve_cents: int
    warranty_paid_cents: int
    seasonal_family: str


class Mold(CommonFields, total=False):
    """A Mold row as PRD.md section 2.8 declares it."""

    mold_code: str
    product_model_id: str
    size_class: str
    cavity_count: int
    nominal_charge_kg: float
    service_interval_cycles: int
    cycles_since_service: int
    status: str
    replaces_mold_id: str


class OvenStation(CommonFields, total=False):
    """A OvenStation row as PRD.md section 2.8 declares it."""

    station_code: str
    arm_count: int
    max_size_class: str
    changeover_buffer_min: int
    energy_cents_per_min: int
    status: str


class CoolingBay(CommonFields, total=False):
    """A CoolingBay row as PRD.md section 2.8 declares it."""

    bay_code: str
    concurrent_slot_capacity: int
    airflow_mode: str
    status: str


class Technician(CommonFields, total=False):
    """A Technician row as PRD.md section 2.8 declares it."""

    employee_code: str
    full_name: str
    role_code: str
    certifications: list[Any]
    status: str


class Customer(CommonFields, total=False):
    """A Customer row as PRD.md section 2.8 declares it."""

    customer_code: str
    email: str
    region_code: str
    storage_guidance_acknowledged_at: str
    status: str


class Warehouse(CommonFields, total=False):
    """A Warehouse row as PRD.md section 2.8 declares it."""

    site_code: str
    footprint_capacity_cube_m3: float
    zones: list[Any]
    restricted_threshold_pct: float
    frozen_threshold_pct: float
    committed_cube_m3: float
    utilization_pct: float
    posture: str


class DemandForecastBucket(CommonFields, total=False):
    """A DemandForecastBucket row as PRD.md section 2.8 declares it."""

    season_code: str
    product_model_id: str
    forecast_qty: int
    build_ahead_cap_pct: float
    build_ahead_cap_qty: int
    build_ahead_committed_qty: int
    window_start_on: str
    window_end_on: str


class ResinLot(CommonFields, total=False):
    """A ResinLot row as PRD.md section 2.8 declares it."""

    lot_code: str
    resin_grade: str
    melt_index_g10min: float
    color_code: str
    color_delta_e: float
    additive_package_code: str
    regrind_pct_by_mass: float
    cost_cents_per_kg: int
    received_kg: float
    available_kg: float
    reserved_kg: float
    consumed_kg: float
    expires_on: str
    status: str


class ResinCharge(CommonFields, total=False):
    """A ResinCharge row as PRD.md section 2.8 declares it."""

    molding_cycle_id: str
    resin_lot_id: str
    created_by_technician_id: str
    charge_kg: float
    regrind_kg: float
    virgin_kg: float
    charge_regrind_pct: float
    status: str
    released_reason: str


class ProductionOrder(CommonFields, total=False):
    """A ProductionOrder row as PRD.md section 2.8 declares it."""

    order_code: str
    product_model_id: str
    demand_bucket_id: str
    target_warehouse_id: str
    ordered_qty: int
    completed_qty: int
    scrapped_qty: int
    status: str
    blocked_reason: str
    material_cost_cents: int
    oven_energy_cost_cents: int
    overhead_cents: int
    total_cost_cents: int
    unit_cost_cents: int


class MoldingCycle(CommonFields, total=False):
    """A MoldingCycle row as PRD.md section 2.8 declares it."""

    production_order_id: str
    mold_id: str
    oven_station_id: str
    arm_index: int
    cooling_bay_id: str
    operator_technician_id: str
    oven_start_at: str
    scheduled_oven_minutes: int
    oven_end_at: str
    scheduled_cooling_minutes: int
    cooling_window_start_at: str
    cooling_window_end_at: str
    oven_temp_c: float
    arm_rpm_major: float
    arm_rpm_minor: float
    cooling_mode: str
    actual_oven_start_at: str
    actual_oven_end_at: str
    actual_cooling_end_at: str
    actual_oven_minutes: int
    actual_cooling_minutes: int
    charged_mass_kg: float
    weighted_melt_index_g10min: float
    cycle_regrind_pct: float
    provisional_warpage_index: float
    status: str
    abort_reason: str


class FinishedUnit(CommonFields, total=False):
    """A FinishedUnit row as PRD.md section 2.8 declares it."""

    molding_cycle_id: str
    product_model_id: str
    warehouse_id: str
    outfitted_by_technician_id: str
    inspected_by_technician_id: str
    hull_serial: str
    cavity_index: int
    trim_waste_kg: float
    hardware_kit_serial: str
    wall_thickness_points: list[Any]
    mean_wall_thickness_mm: float
    wall_sd_mm: float
    wall_cv_pct: float
    min_wall_thickness_mm: float
    impact_test_joules: float
    cosmetic_defect_grade: str
    final_warpage_index: float
    inspection_verdict: str
    rework_count: int
    build_status: str
    logistics_status: str
    storage_zone_code: str
    stored_footprint_cube_m3: float
    is_zone_anchor: bool
    stored_at: str
    demand_bucket_id: str
    delivered_at: str


class Shipment(CommonFields, total=False):
    """A Shipment row as PRD.md section 2.8 declares it."""

    shipment_code: str
    origin_warehouse_id: str
    destination_zone: str
    carrier_code: str
    trailer_cube_capacity_m3: float
    trailer_max_payload_kg: float
    loaded_cube_m3: float
    nested_cube_m3: float
    loaded_weight_kg: float
    cube_utilization_pct: float
    density_kg_per_m3: float
    quoted_freight_cents: int
    billed_freight_cents: int
    status: str
    sealed_at: str
    departed_at: str
    delivered_at: str


class ShipmentLine(CommonFields, total=False):
    """A ShipmentLine row as PRD.md section 2.8 declares it."""

    shipment_id: str
    finished_unit_id: str
    nest_position: int
    line_gross_cube_m3: float
    line_nested_cube_m3: float
    line_freight_cents: int
    status: str


class WarrantyClaim(CommonFields, total=False):
    """A WarrantyClaim row as PRD.md section 2.8 declares it."""

    claim_code: str
    finished_unit_id: str
    customer_id: str
    claim_type: str
    reported_deformation_mm: float
    storage_description: str
    claim_status: str
    storage_review_status: str
    months_in_service: int
    payout_basis: str
    pre_fee_gross_cents: int
    storage_deduction_cents: int
    admin_fee_cents: int
    net_payout_cents: int
    denial_reason: str

class FootprintZone(TypedDict, total=False):
    """One zone row inside the warehouse footprint projection."""

    zone_code: str
    capacity_cube_m3: float
    committed_cube_m3: float
    remaining_cube_m3: float
    anchor_product_model_ids: list[str]
    stored_unit_count: int


class FootprintSummary(TypedDict, total=False):
    """GET /warehouses/{warehouse_id}/footprint-summary projection."""

    warehouse_id: str
    footprint_capacity_cube_m3: float
    committed_cube_m3: float
    remaining_cube_m3: float
    utilization_pct: float
    posture: str
    zones: list[FootprintZone]
    blocked_production_order_count: int


class CostSummary(TypedDict, total=False):
    """GET /production-orders/{production_order_id}/cost-summary projection."""

    production_order_id: str
    consumed_charge_count: int
    material_cost_cents: int
    demolded_cycle_count: int
    oven_energy_cost_cents: int
    pre_overhead_subtotal_cents: int
    overhead_rate_pct: float
    overhead_cents: int
    total_cost_cents: int
    completed_qty: int
    unit_cost_cents: int | None


class FreightLine(TypedDict, total=False):
    """One line row inside the shipment freight projection."""

    shipment_line_id: str
    hull_serial: str
    nest_position: int
    line_gross_cube_m3: float
    line_nested_cube_m3: float
    chargeable_kg_nested: float
    chargeable_kg_gross: float
    line_freight_cents: int


class FreightSummary(TypedDict, total=False):
    """GET /shipments/{shipment_id}/freight-summary projection."""

    shipment_id: str
    loaded_line_count: int
    loaded_cube_m3: float
    nested_cube_m3: float
    loaded_weight_kg: float
    cube_utilization_pct: float
    density_kg_per_m3: float
    discount_rate_pct: float
    quoted_pre_discount_cents: int
    quoted_freight_cents: int | None
    billed_pre_discount_cents: int
    billed_freight_cents: int | None
    lines: list[FreightLine]


class ClockState(TypedDict, total=False):
    """GET /_clock/current_utc projection (PRD.md section 2.5)."""

    current_utc: str
    default_utc: str


class ClockAdvanceResult(ClockState, total=False):
    """POST /_clock/set_current_utc result, including the expiry cascade counters."""

    expired_resin_lot_count: int
    released_resin_charge_count: int
    aborted_molding_cycle_count: int
    blocked_production_order_count: int


class PageMeta(TypedDict, total=False):
    """Pagination metadata as PRD.md section 2.3 declares it."""

    total_count: int
    has_more: bool
    limit: int
    offset: int


# A set of request headers: X-User-ID plus X-User-Role.
Headers = dict[str, str]
