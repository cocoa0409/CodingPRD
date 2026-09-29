"""Per-entity serialisers.

Every field the PRD declares for a resource is emitted, and nothing else.
Decimals stay Decimal all the way into core.dumps so their declared trailing
zeros survive (0.0000 rather than 0.0); dates and instants are rendered with
the PRD's YYYY-MM-DD and three-fractional-digit ISO 8601 formats.
"""
from datetime import date, datetime

from core import date_str, iso

COMMON = ("id", "created_at", "updated_at", "version")


def _value(v):
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, date):
        return date_str(v)
    if isinstance(v, list):
        return [_value(x) for x in v]
    if isinstance(v, dict):
        return dict((k, _value(x)) for k, x in v.items())
    return v


def _ser(row, fields):
    out = {}
    for name in fields:
        out[name] = _value(row.get(name))
    for name in COMMON:
        out[name] = _value(row.get(name))
    return out


PRODUCT_MODEL = (
    "model_code", "hull_type", "size_class", "resin_grade", "master_color_code",
    "max_color_delta_e", "required_additive_package_code", "max_regrind_pct",
    "min_melt_index_g10min", "max_melt_index_g10min", "nominal_charge_kg",
    "charge_tolerance_pct", "min_cooling_minutes", "target_wall_thickness_mm",
    "wall_thickness_min_mm", "wall_cv_max_pct", "impact_test_min_joules",
    "gross_cube_m3", "nest_factor", "unit_weight_kg", "msrp_cents",
    "warranty_basis", "initial_warranty_reserve_cents", "seasonal_family",
    "warranty_reserve_cents", "warranty_paid_cents",
)

MOLD = (
    "mold_code", "product_model_id", "size_class", "cavity_count",
    "nominal_charge_kg", "service_interval_cycles", "replaces_mold_id",
    "cycles_since_service", "status",
)

OVEN_STATION = (
    "station_code", "arm_count", "max_size_class", "changeover_buffer_min",
    "energy_cents_per_min", "status",
)

COOLING_BAY = ("bay_code", "concurrent_slot_capacity", "airflow_mode", "status")

TECHNICIAN = ("employee_code", "full_name", "role_code", "certifications", "status")

CUSTOMER = (
    "customer_code", "email", "region_code",
    "storage_guidance_acknowledged_at", "status",
)

WAREHOUSE = (
    "site_code", "footprint_capacity_cube_m3", "zones",
    "restricted_threshold_pct", "frozen_threshold_pct", "committed_cube_m3",
    "utilization_pct", "posture",
)

DEMAND_BUCKET = (
    "season_code", "product_model_id", "forecast_qty", "build_ahead_cap_pct",
    "window_start_on", "window_end_on", "build_ahead_cap_qty",
    "build_ahead_committed_qty",
)

RESIN_LOT = (
    "lot_code", "resin_grade", "melt_index_g10min", "color_code",
    "color_delta_e", "additive_package_code", "regrind_pct_by_mass",
    "cost_cents_per_kg", "received_kg", "expires_on", "available_kg",
    "reserved_kg", "consumed_kg", "status",
)

RESIN_CHARGE = (
    "molding_cycle_id", "resin_lot_id", "created_by_technician_id", "charge_kg",
    "regrind_kg", "virgin_kg", "charge_regrind_pct", "status", "released_reason",
)

PRODUCTION_ORDER = (
    "order_code", "product_model_id", "demand_bucket_id", "target_warehouse_id",
    "ordered_qty", "completed_qty", "scrapped_qty", "status", "blocked_reason",
    "material_cost_cents", "oven_energy_cost_cents", "overhead_cents",
    "total_cost_cents", "unit_cost_cents",
)

MOLDING_CYCLE = (
    "production_order_id", "oven_station_id", "arm_index", "cooling_bay_id",
    "operator_technician_id", "mold_id", "oven_start_at",
    "scheduled_oven_minutes", "scheduled_cooling_minutes", "oven_temp_c",
    "arm_rpm_major", "arm_rpm_minor", "cooling_mode", "oven_end_at",
    "cooling_window_start_at", "cooling_window_end_at", "actual_oven_start_at",
    "actual_oven_end_at", "actual_cooling_end_at", "actual_oven_minutes",
    "actual_cooling_minutes", "charged_mass_kg", "weighted_melt_index_g10min",
    "cycle_regrind_pct", "provisional_warpage_index", "status", "abort_reason",
)

FINISHED_UNIT = (
    "molding_cycle_id", "product_model_id", "cavity_index", "hull_serial",
    "warehouse_id", "outfitted_by_technician_id", "inspected_by_technician_id",
    "trim_waste_kg", "hardware_kit_serial", "wall_thickness_points",
    "mean_wall_thickness_mm", "wall_sd_mm", "wall_cv_pct",
    "min_wall_thickness_mm", "impact_test_joules", "cosmetic_defect_grade",
    "final_warpage_index", "inspection_verdict", "rework_count", "build_status",
    "logistics_status", "storage_zone_code", "stored_footprint_cube_m3",
    "is_zone_anchor", "stored_at", "demand_bucket_id", "delivered_at",
)

SHIPMENT = (
    "shipment_code", "customer_id", "origin_warehouse_id", "destination_zone",
    "carrier_code", "trailer_cube_capacity_m3", "trailer_max_payload_kg",
    "loaded_cube_m3", "nested_cube_m3", "loaded_weight_kg",
    "cube_utilization_pct", "density_kg_per_m3", "quoted_freight_cents",
    "billed_freight_cents", "status", "sealed_at", "departed_at", "delivered_at",
)

SHIPMENT_LINE = (
    "shipment_id", "finished_unit_id", "nest_position", "line_gross_cube_m3",
    "line_nested_cube_m3", "line_freight_cents", "status",
)

WARRANTY_CLAIM = (
    "claim_code", "finished_unit_id", "customer_id", "claim_type",
    "reported_deformation_mm", "storage_description", "claim_status",
    "storage_review_status", "months_in_service", "payout_basis",
    "pre_fee_gross_cents", "storage_deduction_cents", "admin_fee_cents",
    "net_payout_cents", "denial_reason",
)

SPEC = {
    "product_models": PRODUCT_MODEL,
    "molds": MOLD,
    "oven_stations": OVEN_STATION,
    "cooling_bays": COOLING_BAY,
    "technicians": TECHNICIAN,
    "customers": CUSTOMER,
    "warehouses": WAREHOUSE,
    "demand_buckets": DEMAND_BUCKET,
    "resin_lots": RESIN_LOT,
    "resin_charges": RESIN_CHARGE,
    "production_orders": PRODUCTION_ORDER,
    "molding_cycles": MOLDING_CYCLE,
    "finished_units": FINISHED_UNIT,
    "shipments": SHIPMENT,
    "shipment_lines": SHIPMENT_LINE,
    "warranty_claims": WARRANTY_CLAIM,
}


def dump(collection, row):
    return _ser(row, SPEC[collection])


def dump_list(collection, items):
    return [dump(collection, r) for r in items]
