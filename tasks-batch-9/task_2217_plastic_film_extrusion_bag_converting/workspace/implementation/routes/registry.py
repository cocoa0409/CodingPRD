"""Clock, products, resin grades, presses, regrind pools and the ledger reads."""

from flask import Blueprint, g

import config as C
from auth import ANY_ROLE, endpoint
from errors import ApiError
from num import D, f, r
from response import object_response
from services import calc, cascade, refs
from store import serialize, store
from validation import (
    fetch,
    get_bool,
    get_datetime,
    get_enum,
    get_int,
    get_num,
    get_str,
    list_endpoint,
    parse_body,
    require_unique,
)

bp = Blueprint("registry", __name__)


def created(entity):
    return object_response(serialize(entity), 201)


def ok(entity):
    return object_response(serialize(entity), 200)


# ==================================================================== clock ==
@bp.post("/_clock/set_current_utc")
@endpoint(["PlantAdmin"])
def set_clock():
    body = parse_body(required=True)
    raw, parsed = get_datetime(body, "current_utc", required=True)
    store.clock = parsed
    return object_response({}, 200)


# ================================================================= products ==
@bp.post("/products")
@endpoint(["PlantAdmin"])
def create_product():
    body = parse_body(required=True)
    product_code = get_str(body, "product_code", max_len=40)
    customer_code = get_str(body, "customer_code")
    bag_style = get_enum(body, "bag_style", C.BAG_STYLES)
    food_contact_required = get_bool(body, "food_contact_required", default=False)
    target_gauge_micron = get_num(body, "target_gauge_micron", gt=0)
    gauge_tolerance_pct = get_num(body, "gauge_tolerance_pct", required=False, default=8.0, gt=0, lt=100)
    layflat_width_mm = get_num(body, "layflat_width_mm", gt=0)
    bag_length_mm = get_num(body, "bag_length_mm", gt=0)
    gusset_depth_mm = get_num(body, "gusset_depth_mm", required=False, default=0.0, ge=0)
    perforation_required = get_bool(body, "perforation_required", default=False)
    min_bottom_seal = get_num(body, "min_bottom_seal_n_per_15mm", gt=0)
    min_strength_index = get_num(body, "min_strength_index", ge=0)
    max_regrind_food = get_num(body, "max_regrind_pct_food", required=False, default=10.0)
    max_regrind_nonfood = get_num(body, "max_regrind_pct_nonfood", required=False, default=35.0)
    declared_recycled = get_num(body, "declared_recycled_content_pct", required=False, default=0.0)
    assumed_regrind_pcr = get_num(body, "assumed_regrind_pcr_pct", required=False, default=0.0)
    bags_per_case = get_int(body, "bags_per_case", gt=0)
    min_partial_case_bags = get_int(body, "min_partial_case_bags", required=False, default=0, ge=0)
    cases_per_pallet = get_int(body, "cases_per_pallet", gt=0)
    count_tolerance = get_num(body, "count_accuracy_tolerance_pct", required=False, default=2.0)
    required_layer_count = get_int(body, "required_layer_count", required=False, default=1, ge=1, le=9)

    if bag_style == "GUSSETED" and not gusset_depth_mm > 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'gusset_depth_mm' must be greater than 0 when bag_style is GUSSETED.",
        )
    if min_partial_case_bags > bags_per_case:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'min_partial_case_bags' must not exceed bags_per_case.",
        )

    require_unique(store.products, "product_code", product_code)

    product = store.new_common()
    product.update(
        {
            "product_code": product_code,
            "customer_code": customer_code,
            "bag_style": bag_style,
            "food_contact_required": food_contact_required,
            "target_gauge_micron": target_gauge_micron,
            "gauge_tolerance_pct": gauge_tolerance_pct,
            "layflat_width_mm": layflat_width_mm,
            "bag_length_mm": bag_length_mm,
            "gusset_depth_mm": gusset_depth_mm,
            "perforation_required": perforation_required,
            "min_bottom_seal_n_per_15mm": min_bottom_seal,
            "min_strength_index": min_strength_index,
            "max_regrind_pct_food": max_regrind_food,
            "max_regrind_pct_nonfood": max_regrind_nonfood,
            "declared_recycled_content_pct": declared_recycled,
            "assumed_regrind_pcr_pct": assumed_regrind_pcr,
            "bags_per_case": bags_per_case,
            "min_partial_case_bags": min_partial_case_bags,
            "cases_per_pallet": cases_per_pallet,
            "count_accuracy_tolerance_pct": count_tolerance,
            "required_layer_count": required_layer_count,
        }
    )
    store.products[product["id"]] = product
    return created(product)


@bp.get("/products/<product_id>")
@endpoint(ANY_ROLE)
def read_product(product_id):
    return ok(fetch("product", product_id))


@bp.get("/products")
@endpoint(ANY_ROLE)
def list_products():
    return list_endpoint(
        store.products, ("customer_code", "food_contact_required", "bag_style")
    )


# ============================================================ resin grades ==
@bp.post("/resin-grades")
@endpoint(["PlantAdmin"])
def create_resin_grade():
    body = parse_body(required=True)
    grade_code = get_str(body, "grade_code")
    material_class = get_enum(body, "material_class", C.MATERIAL_CLASSES)
    polymer_family = get_enum(body, "polymer_family", C.POLYMER_FAMILIES)
    melt_index = get_num(body, "melt_index")
    density = get_num(body, "density_kg_m3", gt=0)
    food_contact_approved = get_bool(body, "food_contact_approved", default=False)
    pcr_content_pct = get_num(body, "pcr_content_pct", required=False, default=0.0, ge=0, le=100)
    cost_per_kg = get_num(body, "cost_per_kg", ge=0)
    dart_impact_index = get_num(body, "dart_impact_index")
    haze_index = get_num(body, "haze_index")
    cof_index = get_num(body, "cof_index")
    seal_temp = get_num(body, "seal_initiation_temp_c")
    is_barrier = get_bool(body, "is_barrier", default=False)

    require_unique(store.resin_grades, "grade_code", grade_code)

    grade = store.new_common()
    grade.update(
        {
            "grade_code": grade_code,
            "material_class": material_class,
            "polymer_family": polymer_family,
            "melt_index": melt_index,
            "density_kg_m3": density,
            "food_contact_approved": food_contact_approved,
            "pcr_content_pct": pcr_content_pct,
            "cost_per_kg": cost_per_kg,
            "dart_impact_index": dart_impact_index,
            "haze_index": haze_index,
            "cof_index": cof_index,
            "seal_initiation_temp_c": seal_temp,
            "is_barrier": is_barrier,
        }
    )
    store.resin_grades[grade["id"]] = grade
    return created(grade)


@bp.get("/resin-grades/<grade_id>")
@endpoint(ANY_ROLE)
def read_resin_grade(grade_id):
    return ok(fetch("resin_grade", grade_id))


@bp.get("/resin-grades")
@endpoint(ANY_ROLE)
def list_resin_grades():
    return list_endpoint(
        store.resin_grades,
        ("polymer_family", "material_class", "food_contact_approved", "is_barrier"),
    )


# ================================================================= presses ==
@bp.post("/print-presses")
@endpoint(["PlantAdmin"])
def create_press():
    body = parse_body(required=True)
    press_code = get_str(body, "press_code")
    cylinder_capacity = get_int(body, "cylinder_capacity", ge=1)
    max_colors = get_int(body, "max_colors", ge=1)
    registration_tolerance = get_num(body, "registration_tolerance_micron", gt=0)
    max_delta_e = get_num(body, "max_delta_e", required=False, default=2.0)

    require_unique(store.print_presses, "press_code", press_code)

    press = store.new_common()
    press.update(
        {
            "press_code": press_code,
            "cylinder_capacity": cylinder_capacity,
            "max_colors": max_colors,
            "registration_tolerance_micron": registration_tolerance,
            "max_delta_e": max_delta_e,
        }
    )
    store.print_presses[press["id"]] = press
    return created(press)


@bp.get("/print-presses/<press_id>")
@endpoint(ANY_ROLE)
def read_press(press_id):
    return ok(fetch("print_press", press_id))


@bp.get("/print-presses")
@endpoint(ANY_ROLE)
def list_presses():
    return list_endpoint(store.print_presses, ())


# =========================================================== regrind pools ==
@bp.post("/regrind-pools")
@endpoint(["PlantAdmin"])
def create_pool():
    body = parse_body(required=True)
    pool_code = get_str(body, "pool_code")
    food_contact_status = get_enum(body, "food_contact_status", C.FOOD_CONTACT_STATUSES)
    polymer_family = get_enum(body, "polymer_family", C.POOL_POLYMER_FAMILIES)

    require_unique(store.regrind_pools, "pool_code", pool_code)

    pool = store.new_common()
    pool.update(
        {
            "pool_code": pool_code,
            "food_contact_status": food_contact_status,
            "polymer_family": polymer_family,
            "available_kg": 0.0,
            "cumulative_in_kg": 0.0,
            "cumulative_out_kg": 0.0,
            "cumulative_in_pcr_kg": 0.0,
            "embedded_pcr_pct": 0.0,
            "generation_count": 0,
            "reincorporation_count": 0,
        }
    )
    store.regrind_pools[pool["id"]] = pool
    return created(pool)


@bp.get("/regrind-pools/<pool_id>")
@endpoint(ANY_ROLE)
def read_pool(pool_id):
    return ok(fetch("regrind_pool", pool_id))


@bp.get("/regrind-pools")
@endpoint(ANY_ROLE)
def list_pools():
    return list_endpoint(store.regrind_pools, ("food_contact_status", "polymer_family"))


@bp.get("/regrind-pools/<pool_id>/balance")
@endpoint(ANY_ROLE)
def pool_balance(pool_id):
    pool = fetch("regrind_pool", pool_id)
    calc.recompute_pool(pool)
    return ok(pool)


# ==================================================== regrind transactions ==
@bp.get("/regrind-transactions/<transaction_id>")
@endpoint(ANY_ROLE)
def read_transaction(transaction_id):
    return ok(fetch("regrind_transaction", transaction_id))


@bp.get("/regrind-transactions")
@endpoint(ANY_ROLE)
def list_transactions():
    return list_endpoint(
        store.regrind_transactions,
        ("pool_id", "extrusion_run_id", "reverses_transaction_id", "direction", "origin_kind"),
    )


@bp.post("/regrind-transactions/<transaction_id>/reverse")
@endpoint(["QualityManager"])
def reverse_transaction(transaction_id):
    body = parse_body(required=True)
    reason = get_str(body, "reversal_reason")
    target = fetch("regrind_transaction", transaction_id)
    pool = store.regrind_pools.get(target["pool_id"])

    if refs.is_reversed(target):
        raise ApiError(
            "ERR_TRANSACTION_ALREADY_REVERSED",
            "Transaction %s has already been reversed." % transaction_id,
        )
    if target["origin_kind"] == "REVERSAL":
        raise ApiError(
            "ERR_TRANSACTION_NOT_REVERSIBLE", "A REVERSAL transaction cannot be reversed."
        )
    projected = calc.simulate_pool_available_without(pool, target["id"])
    if projected < 0:
        raise ApiError(
            "ERR_TRANSACTION_NOT_REVERSIBLE",
            "Reversing this transaction would drive the pool's available_kg below zero.",
        )

    direction = "OUT" if target["direction"] == "IN" else "IN"
    row = cascade.book_transaction(
        pool,
        direction=direction,
        origin_kind="REVERSAL",
        kg=target["kg"],
        pcr_kg=0.0,
        reverses_transaction_id=target["id"],
        reversal_reason=reason,
    )

    if target["origin_kind"] == "REINCORPORATION" and target.get("extrusion_run_id"):
        run = store.extrusion_runs.get(target["extrusion_run_id"])
        if run is not None:
            calc.recompute_run_regrind(run)
            store.touch(run)

    return created(row)
