"""Resource representations.

Every resource carries `id` and `created_at`; most also carry `updated_at` and
`version`. `GradeBundle` is the single exception -- an immutable tally line with
neither `updated_at` nor `version` in its representation (PRD 2.4).
"""

from datetime import date, datetime
from decimal import Decimal

from db import iso

COMMON_TAIL = ("created_at", "updated_at", "version")
BUNDLE_TAIL = ("created_at",)

FIELD_ORDER = {
    "species_profile": (
        "species_code", "common_name", "density_class",
        "tangential_shrinkage_coefficient", "target_moisture_pct",
        "max_moisture_gradient_pp", "green_to_dry_shrink_pct",
    ),
    "drying_schedule": (
        "species_profile_id", "schedule_code", "thickness_in",
        "initial_moisture_pct", "final_moisture_pct", "conditioning_hours",
        "stress_relief_hours", "planned_dry_hours",
    ),
    "green_receipt": (
        "species_profile_id", "supplier_name", "received_board_feet",
        "receipt_grade", "moisture_pct_at_receipt", "accepted_board_feet",
        "kiln_charge_id", "rejection_reason", "status",
    ),
    "kiln_chamber": ("chamber_code", "capacity_board_feet", "maintenance_note", "status"),
    "kiln_charge": (
        "drying_schedule_id", "kiln_chamber_id", "planned_start_utc",
        "planned_dry_hours", "planned_end_utc", "blocked_until_utc",
        "charged_green_bf", "weighted_initial_moisture_pct", "shell_moisture_pct",
        "core_moisture_pct", "moisture_gradient_pp", "average_moisture_pct",
        "dry_bf_out", "remaining_dry_bf", "redry_count", "displaced_reason", "status",
    ),
    "product_line": (
        "line_code", "species_profile_id", "construction_type", "nominal_width_in",
        "nominal_thickness_in", "material_value_cents_per_sf",
        "warranty_funded_total_cents", "warranty_balance_cents",
        "warranty_committed_cents", "freeze_override", "posture",
    ),
    "core_stock": (
        "product_line_id", "core_material", "lot_reference",
        "available_square_feet", "reserved_square_feet",
    ),
    "flooring_lot": (
        "product_line_id", "kiln_charge_id", "core_stock_id", "input_dry_bf",
        "construction_type", "nominal_width_in", "planned_finished_width_in",
        "dimensional_growth_allowance_in", "reserved_core_sf",
        "actual_milled_width_in", "net_flooring_bf", "shorts_bf", "sawdust_tons",
        "shavings_tons", "residue_bf", "waste_bf", "provisional_yield_pct",
        "final_yield_pct", "final_grade_run_id", "quarantine_reason",
        "void_reason", "status",
    ),
    "grade_run": (
        "flooring_lot_id", "inspector_ruleset", "tally_board_feet",
        "tally_value_cents", "credited_board_feet", "superseded_by_run_id", "status",
    ),
    "grade_bundle": (
        "grade_run_id", "grade_class", "bundle_board_feet", "average_length_in",
        "length_factor", "credit_factor", "tally_value_cents",
    ),
    "prefinish_line": ("line_code", "daily_capacity_linear_feet", "coating_passes"),
    "prefinish_run": (
        "prefinish_line_id", "flooring_lot_id", "product_line_id",
        "window_start_utc", "window_end_utc", "scheduled_linear_feet",
        "sanding_grit_sequence", "stain_code", "coating_liters",
        "hold_reason", "status",
    ),
    "byproduct_batch": ("flooring_lot_id", "byproduct_type", "available_tons", "sold_tons"),
    "byproduct_sale": (
        "byproduct_batch_id", "buyer_name", "quantity_tons",
        "unit_price_cents_per_ton", "haul_distance_miles", "gross_cents",
        "discount_cents", "haul_cents", "net_cents",
    ),
    "warranty_claim": (
        "product_line_id", "flooring_lot_id", "claim_type", "affected_square_feet",
        "installation_date", "subfloor_moisture_pct_at_install",
        "ambient_rh_pct_at_install", "estimated_liability_cents",
        "adjudicated_affected_sf", "adjudicated_subfloor_moisture_pct",
        "adjudicated_ambient_rh_pct", "installer_share_pct", "mill_share_pct",
        "service_months", "depreciation_pct", "adjudicated_liability_cents",
        "submitted_by_user_id", "adjudicated_by_user_id", "info_request_note",
        "denial_reason", "reversal_reason", "adjudication_status", "remediation_status",
    ),
}


def jsonable(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def serialize(kind, record):
    if record is None:
        return None
    out = {"id": record["id"]}
    for field in FIELD_ORDER[kind]:
        out[field] = jsonable(record.get(field))
    tail = BUNDLE_TAIL if kind == "grade_bundle" else COMMON_TAIL
    for field in tail:
        out[field] = jsonable(record.get(field))
    return out


def serialize_many(kind, records):
    return [serialize(kind, record) for record in records]
