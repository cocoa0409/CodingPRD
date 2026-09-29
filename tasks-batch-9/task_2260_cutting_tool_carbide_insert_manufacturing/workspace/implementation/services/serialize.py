"""Wire representations of every entity, including the computed fields."""

import db
from services import derive

COMMON = ("id", "created_at", "updated_at", "version")


def _base(row):
    return {k: row[k] for k in COMMON}


def _copy(row, out, fields):
    for f in fields:
        out[f] = row.get(f)
    return out


GRADE_FIELDS = (
    "grade_code",
    "target_workpiece_group",
    "co_binder_pct",
    "wc_grain_um",
    "hardness_hv",
    "trs_mpa",
    "status",
    "revision",
    "authored_by_user_id",
)


def grade(row):
    out = _copy(row, _base(row), GRADE_FIELDS)
    out["qualified_product_count"] = derive.grade_qualified_product_count(row)
    return out


BATCH_FIELDS = (
    "grade_id",
    "batch_code",
    "planned_mass_kg",
    "pinned_grade_revision",
    "stage",
    "qc_status",
    "pressed_units",
    "sintered_units",
    "scrap_units",
    "remaining_units",
    "measured_density_gcc",
    "measured_hardness_hv",
    "yield_pct",
)


def batch(row):
    return _copy(row, _base(row), BATCH_FIELDS)


GEOMETRY_FIELDS = (
    "geometry_code",
    "iso_designation",
    "application_class",
    "chipbreaker_code",
    "rake_angle_deg",
    "nose_radius_mm",
    "max_depth_of_cut_mm",
    "edge_prep",
    "status",
    "revision",
)


def geometry(row):
    return _copy(row, _base(row), GEOMETRY_FIELDS)


RECIPE_FIELDS = (
    "recipe_code",
    "deposition_type",
    "layers",
    "total_thickness_um",
    "revision",
)


def recipe(row):
    out = _copy(row, _base(row), RECIPE_FIELDS)
    out["adhesion_class"] = derive.recipe_adhesion_class(row)
    out["is_validated"] = derive.recipe_is_validated(row)
    return out


COATING_RUN_FIELDS = (
    "recipe_id",
    "chamber_id",
    "window_start",
    "window_end",
    "loaded_area_cm2",
    "pinned_recipe_revision",
    "adhesion_hf_class",
    "measured_thickness_um",
    "status",
)


def coating_run(row):
    return _copy(row, _base(row), COATING_RUN_FIELDS)


WHEEL_FIELDS = (
    "wheel_code",
    "spec_code",
    "initial_life_units",
    "consumed_life_units",
    "dress_count",
    "status",
)


def wheel(row):
    out = _copy(row, _base(row), WHEEL_FIELDS)
    out["remaining_life_units"] = derive.wheel_remaining(row)
    return out


GRINDING_RUN_FIELDS = (
    "wheel_id",
    "product_id",
    "cell_id",
    "window_start",
    "window_end",
    "planned_units",
    "produced_units",
    "scrap_units",
    "measured_diameter_dev_um",
    "tolerance_class",
    "consumed_life_units",
    "status",
)


def grinding_run(row):
    return _copy(row, _base(row), GRINDING_RUN_FIELDS)


PRODUCT_FIELDS = (
    "sku",
    "order_class",
    "base_catalog_product_id",
    "grade_id",
    "geometry_id",
    "coating_recipe_id",
    "tool_type",
    "list_price_cents",
    "min_order_qty",
    "nominal_length_mm",
    "min_regrind_length_mm",
    "regrind_step_mm",
    "grind_units_per_tool",
    "release_status",
    "supply_status",
    "pinned_grade_revision",
    "pinned_geometry_revision",
    "pinned_coating_revision",
    "engineering_lead_time_days",
    "expedite_eligible",
    "tool_life_index",
    "qualified_workpiece_groups",
)


def product(row):
    out = _copy(row, _base(row), PRODUCT_FIELDS)
    out["open_order_units"] = derive.product_open_order_units(row)
    return out


DOSSIER_FIELDS = (
    "product_id",
    "dossier_code",
    "required_trial_count",
    "status",
    "submitted_by_user_id",
    "decided_by_user_id",
    "decision_note",
)


def dossier(row):
    out = _copy(row, _base(row), DOSSIER_FIELDS)
    completed, passed, score = derive.dossier_counters(row)
    out["completed_trial_count"] = completed
    out["passed_trial_count"] = passed
    out["composite_score"] = score
    return out


TRIAL_FIELDS = (
    "dossier_id",
    "batch_id",
    "trial_code",
    "workpiece_material_code",
    "workpiece_group",
    "units_consumed",
    "cutting_speed_vc",
    "feed_fz",
    "depth_ap",
    "coolant",
    "operator_user_id",
    "wear_measurements",
    "measured_surface_ra_um",
    "rated_life_min",
    "projected_life_min",
    "censored",
    "verdict",
    "status",
)


def trial(row):
    return _copy(row, _base(row), TRIAL_FIELDS)


CUSTOMER_FIELDS = (
    "customer_code",
    "name",
    "tier",
    "account_status",
    "regrind_credit_cents",
)


def customer(row):
    out = _copy(row, _base(row), CUSTOMER_FIELDS)
    out["reserved_credit_cents"] = derive.customer_reserved_credit(row)
    return out


ORDER_FIELDS = (
    "customer_id",
    "product_id",
    "order_code",
    "order_class",
    "quantity",
    "expedite_requested",
    "status",
    "per_unit_net_cents",
    "total_price_cents",
    "promised_lead_time_days",
    "requires_reconfirmation",
    "hold_reason",
    "shipped_at",
)


def order(row):
    return _copy(row, _base(row), ORDER_FIELDS)


JOB_FIELDS = (
    "customer_id",
    "product_id",
    "predecessor_job_id",
    "job_code",
    "units_received",
    "reserved_credit_cents",
    "regrind_pass_no",
    "wheel_id",
    "units_inspected",
    "measured_length_mm",
    "measured_corner_wear_um",
    "remaining_regrinds",
    "life_extension_pct",
    "warranted_life_extension_pct",
    "scrap_recommended",
    "recoat_applied",
    "units_returned",
    "rebate_cents",
    "status",
)


def job(row):
    return _copy(row, _base(row), JOB_FIELDS)


SERIALIZERS = {
    "grades": grade,
    "batches": batch,
    "geometries": geometry,
    "recipes": recipe,
    "coating_runs": coating_run,
    "wheels": wheel,
    "grinding_runs": grinding_run,
    "products": product,
    "dossiers": dossier,
    "trials": trial,
    "customers": customer,
    "orders": order,
    "jobs": job,
}


def many(name, rows):
    fn = SERIALIZERS[name]
    return [fn(r) for r in rows]
