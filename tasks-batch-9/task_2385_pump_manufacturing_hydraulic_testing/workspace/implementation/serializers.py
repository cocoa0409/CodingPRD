"""Resource representations."""

from datetime import datetime
from decimal import Decimal

from db import iso_business, iso_millis

FIELDS = {
    "Foundry": [
        "foundry_code",
        "name",
        "approved_alloys",
        "concurrent_pour_capacity",
        "status",
        "suspension_reason",
    ],
    "PumpModel": [
        "model_code",
        "generation",
        "interchange_group",
        "max_impeller_diameter_mm",
        "min_impeller_diameter_mm",
        "shutoff_head_m",
        "bep_flow_m3h",
        "bep_head_m",
        "bep_efficiency_pct",
        "npshr_at_bep_m",
        "rated_speed_rpm",
        "max_flow_m3h",
        "rotor_mass_kg",
        "balance_grade",
        "superseded_by_model_id",
        "status",
        "warranty_defect_count",
        "application_error_count",
        "no_defect_count",
    ],
    "PatternAsset": [
        "pump_model_id",
        "foundry_id",
        "pattern_code",
        "wear_threshold",
        "pours_since_refurb",
        "defect_pours_since_refurb",
        "wear_index",
        "refurb_cycles",
        "status",
    ],
    "MaterialSealConfig": [
        "pump_model_id",
        "config_code",
        "casing_material",
        "impeller_material",
        "seal_type",
        "flush_plan",
        "service_class",
        "max_solids_pct",
        "max_viscosity_cst",
        "max_chloride_ppm",
        "max_temp_c",
        "min_running_clearance_mm",
    ],
    "DutyApplication": [
        "application_code",
        "customer_name",
        "duty_flow_m3h",
        "duty_head_m",
        "npsha_available_m",
        "specific_gravity",
        "viscosity_cst",
        "solids_pct",
        "chloride_ppm",
        "process_temp_c",
        "min_efficiency_pct",
        "test_grade",
        "witness_required",
        "service_class_required",
        "status",
    ],
    "Selection": [
        "duty_application_id",
        "pump_model_id",
        "material_seal_config_id",
        "trimmed_impeller_diameter_mm",
        "diameter_ratio",
        "predicted_head_m",
        "predicted_efficiency_pct",
        "predicted_shaft_power_kw",
        "npshr_catalog_m",
        "npsh_provisional_margin_m",
        "npsh_safety_factor",
        "npshr_certified_m",
        "npsh_margin_m",
        "min_motor_kw",
        "proposed_by_user_id",
        "approved_by_user_id",
        "status",
    ],
    "CastingLot": [
        "pattern_asset_id",
        "foundry_id",
        "heat_number",
        "alloy_code",
        "qty_poured",
        "pour_window_start",
        "pour_window_end",
        "qty_scrapped",
        "qty_rework_pending",
        "qty_accepted",
        "committed_build_count",
        "status",
    ],
    "CastingDefect": [
        "casting_lot_id",
        "defect_code",
        "defect_type",
        "severity",
        "affected_qty",
        "reported_by_user_id",
        "dispositioned_by_user_id",
        "disposition",
        "status",
    ],
    "BuildOrder": [
        "selection_id",
        "casting_lot_id",
        "serial_number",
        "running_clearance_mm",
        "residual_unbalance_g_mm",
        "seal_flush_plan_installed",
        "allowable_unbalance_g_mm",
        "rework_cycles",
        "status",
    ],
    "TestRun": [
        "build_order_id",
        "test_speed_rpm",
        "correction_basis",
        "test_grade",
        "witness_required",
        "speed_ratio",
        "head_at_guarantee_m",
        "power_at_guarantee_kw",
        "efficiency_at_guarantee_pct",
        "head_deviation_pct",
        "efficiency_deviation_pct",
        "npshr_tested_m",
        "run_state",
        "hydraulic_status",
        "npsh_status",
    ],
    "TestPoint": [
        "test_run_id",
        "measured_flow_m3h",
        "measured_head_m",
        "measured_power_kw",
        "measured_npsh3_m",
        "is_npsh_point",
    ],
    "PumpPackage": [
        "build_order_id",
        "test_run_id",
        "baseplate_code",
        "motor_kw",
        "motor_frame",
        "control_type",
        "promised_ship_date",
        "actual_ship_date",
        "min_motor_kw",
        "guarantee_basis",
        "application_error_flagged",
        "status",
    ],
    "RepairKit": [
        "pump_model_id",
        "kit_code",
        "interchange_group",
        "gen_min",
        "gen_max",
        "preferred_generation",
        "substitution_penalty_pct",
        "unit_price",
        "support_window_start",
        "support_window_end",
        "qty_received_total",
        "qty_on_hand",
        "qty_reserved",
        "qty_issued",
        "qty_consumed_total",
        "status",
    ],
    "KitAllocation": [
        "repair_kit_id",
        "build_order_id",
        "requested_qty",
        "selected_by",
        "substitution_penalty_applied_pct",
        "parts_extended",
        "handling_rate",
        "handling_fee",
        "total_charge",
        "status",
    ],
    "WarrantyClaim": [
        "pump_package_id",
        "as_found_flow_m3h",
        "as_found_head_m",
        "as_found_npsha_m",
        "as_found_solids_pct",
        "as_found_viscosity_cst",
        "as_found_speed_rpm",
        "claim_lines",
        "submitted_by_user_id",
        "adjudicated_by_user_id",
        "info_request_note",
        "liability_basis",
        "expected_head_m",
        "head_shortfall_pct",
        "application_error_flags",
        "determination",
        "months_since_ship",
        "coverage_factor",
        "settlement_subtotal",
        "admin_fee",
        "settlement_total",
        "status",
    ],
}

# The two immutable entity types carry only id and created_at.
IMMUTABLE = ("MaterialSealConfig", "TestPoint")


def _scalar(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso_business(value)
    if isinstance(value, list):
        return [_scalar(item) for item in value]
    if isinstance(value, dict):
        return dict((k, _scalar(v)) for k, v in value.items())
    return value


def dump(record):
    kind = record["_kind"]
    out = {"id": record["id"]}
    for field in FIELDS[kind]:
        out[field] = _scalar(record.get(field))
    out["created_at"] = iso_millis(record["_created_at"])
    if kind not in IMMUTABLE:
        out["updated_at"] = iso_millis(record["_updated_at"])
        out["version"] = record["version"]
    return out


def dump_all(records):
    return [dump(r) for r in records]
