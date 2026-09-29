"""Entity output shapes.

Refrigerant and EnergyStandard are immutable reference data and carry only
`id` and `created_at` (PRD 2.4); every other resource carries the full common
field set.
"""

from decimal import Decimal

FIELDS = {
    "Refrigerant": [
        "id", "refrigerant_code", "trade_name", "gwp_100yr", "safety_class",
        "max_charge_grams", "allowed_system_types", "created_at",
    ],
    "EnergyStandard": [
        "id", "standard_code", "effective_date", "max_gwp", "limit_coefficient_a",
        "limit_constant_b", "temperature_class", "system_type_scope", "created_at",
    ],
    "TestChamber": [
        "id", "chamber_code", "name", "supported_temperature_classes",
        "turnaround_hours", "max_tda_sqft", "closed_window_start",
        "closed_window_end", "created_at", "updated_at", "version",
    ],
    "CaseModel": [
        "id", "model_code", "application", "temperature_class", "system_type",
        "refrigerant_id", "predecessor_model_id", "nominal_length_ft", "tda_sqft",
        "charge_grams", "line_set_length_ft", "door_type", "glass_door_count",
        "curtain_layers", "discharge_velocity_mps", "case_air_temp_c",
        "ambient_dew_point_c", "lighting_w_per_ft", "fan_w_per_ft",
        "defrost_cycles_per_day", "curtain_factor", "velocity_factor",
        "infiltration_load_w", "lighting_load_w", "fan_load_w", "defrost_load_w",
        "anti_sweat_load_w", "total_design_load_w", "installed_charge_grams",
        "nameplate_co2e_kg", "installed_co2e_kg", "design_revision",
        "submitted_by_user_id", "status", "created_at", "updated_at", "version",
    ],
    "EnergyTest": [
        "id", "case_model_id", "test_chamber_id", "energy_standard_id",
        "window_start", "window_end", "test_ambient_c", "store_ambient_c",
        "pinned_design_revision", "pinned_tda_sqft",
        "pinned_defrost_cycles_per_day", "limit_daily_kwh", "measured_kwh_24h",
        "measured_defrost_cycles", "lab_rated_index", "field_projected_daily_kwh",
        "field_projected_index", "field_exceedance", "status", "created_at",
        "updated_at", "version",
    ],
    "ComplianceLabel": [
        "id", "case_model_id", "energy_test_id", "label_code",
        "pinned_design_revision", "pinned_lab_rated_index", "pinned_standard_code",
        "issued_by_user_id", "label_status", "revocation_reason", "created_at",
        "updated_at", "version",
    ],
    "StorePlan": [
        "id", "banner_name", "store_number", "region_code",
        "remodel_window_start", "remodel_window_end", "credit_limit_cents",
        "commercial_status", "production_status", "priced_by_user_id",
        "approved_by_user_id", "line_count", "unit_count", "subtotal_cents",
        "volume_discount_bps", "volume_discount_cents", "net_cents",
        "freight_cents", "install_allowance_cents", "total_cents",
        "held_line_count", "units_completed_count", "units_shipped_count",
        "warranty_reserve_accrual_cents", "warranty_reserve_incurred_cents",
        "created_at", "updated_at", "version",
    ],
    "StorePlanLine": [
        "id", "store_plan_id", "case_model_id", "length_ft", "quantity",
        "end_cap", "merchandising_options", "unit_price_cents",
        "extended_price_cents", "compliance_hold", "created_at", "updated_at",
        "version",
    ],
    "WorkOrder": [
        "id", "store_plan_id", "store_plan_line_id", "case_model_id",
        "shipment_id", "unit_sequence", "serial_number", "unit_price_cents",
        "rework_count", "warranty_start_date", "status", "created_at",
        "updated_at", "version",
    ],
    "Shipment": [
        "id", "store_plan_id", "ship_date", "delivery_date", "carrier_code",
        "unit_count", "linear_feet", "handoff_at", "received_by_name", "status",
        "created_at", "updated_at", "version",
    ],
    "InstallCrew": [
        "id", "crew_code", "contractor_name", "service_region_codes",
        "daily_case_capacity", "committed_case_days", "created_at", "updated_at",
        "version",
    ],
    "InstallBooking": [
        "id", "shipment_id", "install_crew_id", "start_date", "end_date",
        "cases_committed", "day_count", "status", "created_at", "updated_at",
        "version",
    ],
    "PartInventory": [
        "id", "part_number", "description", "case_model_id", "region_code",
        "on_hand_qty", "reserved_qty", "available_qty", "unit_cost_cents",
        "min_stock_qty", "below_min", "created_at", "updated_at", "version",
    ],
    "WarrantyClaim": [
        "id", "work_order_id", "part_inventory_id", "install_crew_id",
        "claim_type", "reported_date", "requested_qty", "estimated_cost_cents",
        "warranty_term_months", "in_warranty", "parts_cost_cents",
        "labor_cost_cents", "total_cost_cents", "denial_reason", "status",
        "created_at", "updated_at", "version",
    ],
}


def _convert(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_convert(v) for v in value]
    return value


def dump(kind, row):
    return {field: _convert(row.get(field)) for field in FIELDS[kind]}


def dump_many(kind, rows_):
    return [dump(kind, row) for row in rows_]
