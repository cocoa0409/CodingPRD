"""Nodes, SKUs, inventory rows and packaging rows."""
from flask import Blueprint

from constants import (
    ADJUSTMENT_REASONS, API_PREFIX, NODE_STATUSES, PACKAGE_CLASSES, PACKAGE_TYPES,
    ROLE_ASSOCIATE, ROLE_CARE, ROLE_CARRIER, ROLE_PLANNER,
)
from db import all_of, db, new_row
from errors import ApiError
from middleware import (
    authenticate, body, get_bool, get_int, get_number, get_str, get_enum,
    pagination_args, query_bool, query_enum, query_str,
)
from routes.common import (
    apply_filter, fetch, finish, listing, require_scope, show,
)
from services.derive import (
    create_window, inventory_for, network_epoch, packaging_for, windows_of,
    open_window,
)

bp = Blueprint("nodes", __name__)

ANY_ROLE = (ROLE_PLANNER, ROLE_ASSOCIATE, ROLE_CARRIER, ROLE_CARE)


# ----------------------------------------------------------------- Stores

@bp.route(API_PREFIX + "/stores", methods=["POST"])
def create_store():
    authenticate(ROLE_PLANNER)
    payload = body()
    store_code = get_str(payload, "store_code", max_len=16)
    region_code = get_str(payload, "region_code")
    origin_zone = get_int(payload, "origin_zone", minimum=1, maximum=8)
    daily_unit_capacity = get_int(payload, "daily_unit_capacity", minimum=1)
    staffed_labor_minutes = get_int(payload, "staffed_labor_minutes", minimum=1)
    labor_standard = get_number(payload, "labor_standard_minutes_per_order",
                                exclusive_minimum=0)
    pick_labor = get_number(payload, "pick_labor_minutes_per_unit", exclusive_minimum=0)
    labor_rate = get_int(payload, "labor_rate_cents_per_minute", minimum=1)
    cutoff = get_int(payload, "cutoff_utc_minutes", minimum=0, maximum=1439)
    hazmat = get_bool(payload, "hazmat_certified", required=False, default=False)

    if any(s["store_code"] == store_code for s in db.stores.values()):
        raise ApiError("ERR_DUPLICATE_STORE_CODE")

    epoch = network_epoch()
    store = new_row("stores", {
        "store_code": store_code,
        "region_code": region_code,
        "origin_zone": origin_zone,
        "daily_unit_capacity": daily_unit_capacity,
        "units_committed_epoch": 0,
        "staffed_labor_minutes": staffed_labor_minutes,
        "reserved_labor_minutes": 0.0,
        "labor_standard_minutes_per_order": labor_standard,
        "pick_labor_minutes_per_unit": pick_labor,
        "labor_rate_cents_per_minute": labor_rate,
        "cutoff_utc_minutes": cutoff,
        "hazmat_certified": hazmat,
        "node_status": "ELIGIBLE",
        "eligibility_score": 0.0,
        "eligibility_score_basis": "COLD_START",
        "review_score": 0.0,
        "consecutive_breach_windows": 0,
        "deactivated_at_epoch": None,
        "reactivation_count": 0,
    })
    create_window(store, epoch)
    return finish(store, 201)


@bp.route(API_PREFIX + "/stores", methods=["GET"])
def list_stores():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("stores")
    rows = apply_filter(rows, "node_status", query_enum("node_status", NODE_STATUSES))
    rows = apply_filter(rows, "region_code", query_str("region_code"))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/stores/<store_id>", methods=["GET"])
def read_store(store_id):
    authenticate(*ANY_ROLE)
    return show(fetch("stores", store_id))


@bp.route(API_PREFIX + "/stores/<store_id>", methods=["PATCH"])
def patch_store(store_id):
    authenticate(ROLE_PLANNER)
    payload = body()
    updates = {}
    if "daily_unit_capacity" in payload:
        updates["daily_unit_capacity"] = get_int(payload, "daily_unit_capacity",
                                                 minimum=1)
    if "staffed_labor_minutes" in payload:
        updates["staffed_labor_minutes"] = get_int(payload, "staffed_labor_minutes",
                                                   minimum=1)
    if "labor_standard_minutes_per_order" in payload:
        updates["labor_standard_minutes_per_order"] = get_number(
            payload, "labor_standard_minutes_per_order", exclusive_minimum=0)
    if "pick_labor_minutes_per_unit" in payload:
        updates["pick_labor_minutes_per_unit"] = get_number(
            payload, "pick_labor_minutes_per_unit", exclusive_minimum=0)
    if "labor_rate_cents_per_minute" in payload:
        updates["labor_rate_cents_per_minute"] = get_int(
            payload, "labor_rate_cents_per_minute", minimum=1)
    if "cutoff_utc_minutes" in payload:
        updates["cutoff_utc_minutes"] = get_int(payload, "cutoff_utc_minutes",
                                                minimum=0, maximum=1439)
    if "hazmat_certified" in payload:
        updates["hazmat_certified"] = get_bool(payload, "hazmat_certified")

    store = fetch("stores", store_id)
    store.update(updates)
    return finish(store, 200, explicit=[store])


@bp.route(API_PREFIX + "/stores/<store_id>/reactivate", methods=["POST"])
def reactivate_store(store_id):
    authenticate(ROLE_PLANNER)
    store = fetch("stores", store_id)
    if store["node_status"] != "DEACTIVATED":
        raise ApiError("ERR_STORE_NOT_DEACTIVATED")

    store["node_status"] = "ELIGIBLE"
    store["consecutive_breach_windows"] = 0
    store["deactivated_at_epoch"] = None
    store["reactivation_count"] = store["reactivation_count"] + 1
    if open_window(store["id"]) is None:
        highest = max([w["epoch"] for w in windows_of(store["id"])] or [0])
        create_window(store, max(network_epoch(), highest + 1))
    return finish(store, 200, explicit=[store])


# ------------------------------------------------------------------- SKUs

@bp.route(API_PREFIX + "/skus", methods=["POST"])
def create_sku():
    authenticate(ROLE_PLANNER)
    payload = body()
    sku_code = get_str(payload, "sku_code")
    unit_weight_grams = get_int(payload, "unit_weight_grams", minimum=1)
    unit_price_cents = get_int(payload, "unit_price_cents", minimum=0)
    package_class = get_enum(payload, "package_class", PACKAGE_CLASSES)
    hazmat_flag = get_bool(payload, "hazmat_flag", required=False, default=False)

    if any(s["sku_code"] == sku_code for s in db.skus.values()):
        raise ApiError("ERR_DUPLICATE_SKU_CODE")

    sku = new_row("skus", {
        "sku_code": sku_code,
        "unit_weight_grams": unit_weight_grams,
        "unit_price_cents": unit_price_cents,
        "package_class": package_class,
        "hazmat_flag": hazmat_flag,
    })
    return finish(sku, 201)


@bp.route(API_PREFIX + "/skus", methods=["GET"])
def list_skus():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("skus")
    rows = apply_filter(rows, "package_class",
                        query_enum("package_class", PACKAGE_CLASSES))
    rows = apply_filter(rows, "hazmat_flag", query_bool("hazmat_flag"))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/skus/<sku_id>", methods=["GET"])
def read_sku(sku_id):
    authenticate(*ANY_ROLE)
    return show(fetch("skus", sku_id))


# -------------------------------------------------------------- Inventory

@bp.route(API_PREFIX + "/store-inventories", methods=["POST"])
def create_inventory():
    authenticate(ROLE_PLANNER)
    payload = body()
    store_id = get_str(payload, "store_id")
    sku_id = get_str(payload, "sku_id")
    on_hand_units = get_int(payload, "on_hand_units", minimum=0)
    safety_stock_units = get_int(payload, "safety_stock_units", minimum=0)

    fetch("stores", store_id)
    fetch("skus", sku_id)

    if safety_stock_units > on_hand_units:
        raise ApiError("ERR_SAFETY_STOCK_EXCEEDS_ON_HAND")
    if inventory_for(store_id, sku_id) is not None:
        raise ApiError("ERR_DUPLICATE_INVENTORY_ROW")

    row = new_row("inventories", {
        "store_id": store_id,
        "sku_id": sku_id,
        "on_hand_units": on_hand_units,
        "reserved_units": 0,
        "safety_stock_units": safety_stock_units,
        "available_to_promise_units": max(0, on_hand_units - safety_stock_units),
        "last_adjustment_reason": None,
    })
    return finish(row, 201)


@bp.route(API_PREFIX + "/store-inventories", methods=["GET"])
def list_inventories():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("inventories")
    rows = apply_filter(rows, "store_id", query_str("store_id"))
    rows = apply_filter(rows, "sku_id", query_str("sku_id"))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/store-inventories/<inventory_id>", methods=["GET"])
def read_inventory(inventory_id):
    authenticate(*ANY_ROLE)
    return show(fetch("inventories", inventory_id))


@bp.route(API_PREFIX + "/store-inventories/<inventory_id>/adjustments",
          methods=["POST"])
def adjust_inventory(inventory_id):
    actor, role = authenticate(ROLE_PLANNER, ROLE_ASSOCIATE)
    payload = body()
    expected_version = get_int(payload, "expected_inventory_version")
    counted = get_int(payload, "counted_on_hand_units", minimum=0)
    reason = get_enum(payload, "reason", ADJUSTMENT_REASONS)
    safety = get_int(payload, "safety_stock_units", required=False, minimum=0,
                     default=None)

    row = fetch("inventories", inventory_id)
    require_scope(actor, role, row["store_id"])
    if expected_version != row["version"]:
        raise ApiError("ERR_STALE_INVENTORY_VERSION")

    effective_safety = row["safety_stock_units"] if safety is None else safety
    if effective_safety > counted:
        raise ApiError("ERR_SAFETY_STOCK_EXCEEDS_ON_HAND")
    if counted < row["reserved_units"]:
        raise ApiError("ERR_INVENTORY_BELOW_RESERVED")

    row["on_hand_units"] = counted
    row["safety_stock_units"] = effective_safety
    row["last_adjustment_reason"] = reason
    return finish(row, 200, explicit=[row])


# -------------------------------------------------------------- Packaging

@bp.route(API_PREFIX + "/packaging-supplies", methods=["POST"])
def create_packaging():
    authenticate(ROLE_PLANNER)
    payload = body()
    store_id = get_str(payload, "store_id")
    package_type = get_enum(payload, "package_type", PACKAGE_TYPES)
    on_hand_units = get_int(payload, "on_hand_units", minimum=0)
    reorder_point_units = get_int(payload, "reorder_point_units", minimum=0)

    fetch("stores", store_id)
    if packaging_for(store_id, package_type) is not None:
        raise ApiError("ERR_DUPLICATE_PACKAGING_ROW")

    row = new_row("packaging", {
        "store_id": store_id,
        "package_type": package_type,
        "on_hand_units": on_hand_units,
        "reorder_point_units": reorder_point_units,
        "reorder_flag": on_hand_units <= reorder_point_units,
        "lifetime_consumed_units": 0,
    })
    return finish(row, 201)


@bp.route(API_PREFIX + "/packaging-supplies", methods=["GET"])
def list_packaging():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("packaging")
    rows = apply_filter(rows, "store_id", query_str("store_id"))
    rows = apply_filter(rows, "package_type",
                        query_enum("package_type", PACKAGE_TYPES))
    rows = apply_filter(rows, "reorder_flag", query_bool("reorder_flag"))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/packaging-supplies/<supply_id>", methods=["GET"])
def read_packaging(supply_id):
    authenticate(*ANY_ROLE)
    return show(fetch("packaging", supply_id))


@bp.route(API_PREFIX + "/packaging-supplies/<supply_id>/restock", methods=["POST"])
def restock_packaging(supply_id):
    actor, role = authenticate(ROLE_PLANNER, ROLE_ASSOCIATE)
    payload = body()
    added_units = get_int(payload, "added_units", minimum=1)
    row = fetch("packaging", supply_id)
    require_scope(actor, role, row["store_id"])
    row["on_hand_units"] = row["on_hand_units"] + added_units
    return finish(row, 200, explicit=[row])
