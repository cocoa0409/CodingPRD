"""Build orders, assembly standards and the selector-driven kit reservation."""

from flask import Blueprint

from db import by_seq, db, new_record
from errors import ApiError
from helpers import (
    apply_filters,
    config_of_selection,
    duty_of_selection,
    ensure_unique,
    model_of_selection,
    paginate,
    path_lookup,
    ref_lookup,
    touch,
)
from middleware import ALL_ROLES, authorize
from response import list_response, object_response
from serializers import dump, dump_all
from services import calc
from services.allocations import (
    ALLOCATABLE_BUILD_STATES,
    create_allocation,
    kit_window_open,
)
from services.cascades import recompute_committed_build_count
from validation import (
    FLUSH_PLANS,
    check_keys,
    get_body,
    pagination,
    query_value,
    req_enum,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("builds", __name__)


def _no_body_allowed():
    check_keys(get_body(), ())


def _collection(records, limit, offset):
    window, total = paginate(records, limit, offset)
    return list_response(dump_all(window), limit, offset, total)


def _lot_pattern_model(lot):
    pattern = db.pattern_assets.get(lot["pattern_asset_id"])
    if pattern is None:
        return None
    return pattern["pump_model_id"]


@bp.post("/build-orders")
def create_build_order():
    authorize("ProductionPlanner")
    body = get_body()
    check_keys(body, ("selection_id", "casting_lot_id", "serial_number"))
    selection_id = req_string(body, "selection_id")
    casting_lot_id = req_string(body, "casting_lot_id")
    serial_number = req_string(body, "serial_number")

    selection = ref_lookup(db.selections, selection_id)
    lot = ref_lookup(db.casting_lots, casting_lot_id)

    ensure_unique(db.build_orders, "serial_number", serial_number)

    # Rung 22 sits above rung 24, so an unaccepted lot is reported first.
    if lot["status"] != "ACCEPTED":
        raise ApiError("ERR_CASTING_LOT_NOT_ACCEPTED")
    if selection["status"] != "APPROVED":
        raise ApiError("ERR_SELECTION_NOT_APPROVED")
    if _lot_pattern_model(lot) != selection["pump_model_id"]:
        raise ApiError("ERR_LOT_MODEL_MISMATCH")

    record = new_record(
        "BuildOrder",
        selection_id=selection_id,
        casting_lot_id=casting_lot_id,
        serial_number=serial_number,
        running_clearance_mm=None,
        residual_unbalance_g_mm=None,
        seal_flush_plan_installed=None,
        allowable_unbalance_g_mm=None,
        rework_cycles=0,
        status="PLANNED",
    )
    db.build_orders[record["id"]] = record

    recompute_committed_build_count(lot)
    touch(lot)
    duty = duty_of_selection(selection)
    if duty is not None and duty["status"] == "SELECTION_LOCKED":
        duty["status"] = "CONTRACTED"
        touch(duty)
    return object_response(dump(record), 201)


@bp.get("/build-orders")
def list_build_orders():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.build_orders.values()),
        [
            (query_value("selection_id"), "selection_id"),
            (query_value("casting_lot_id"), "casting_lot_id"),
            (query_value("status"), "status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/build-orders/<resource_id>")
def read_build_order(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.build_orders, resource_id)))


@bp.post("/build-orders/<resource_id>/assembly")
def record_assembly(resource_id):
    authorize("ProductionPlanner")
    body = get_body()
    check_keys(
        body,
        ("running_clearance_mm", "residual_unbalance_g_mm", "seal_flush_plan_installed"),
    )
    running_clearance = req_number(body, "running_clearance_mm", exclusive_min=0)
    residual_unbalance = req_number(body, "residual_unbalance_g_mm", minimum=0)
    flush_plan = req_enum(body, "seal_flush_plan_installed", FLUSH_PLANS)

    order = path_lookup(db.build_orders, resource_id)
    if order["status"] != "PLANNED":
        raise ApiError("ERR_BUILD_ORDER_INVALID_STATE")

    selection = db.selections.get(order["selection_id"])
    model = model_of_selection(selection)
    config = config_of_selection(selection)

    allowable = calc.allowable_unbalance(model)
    if calc.D(residual_unbalance) > allowable:
        raise ApiError("ERR_UNBALANCE_EXCEEDS_ALLOWANCE")
    low, high = calc.clearance_band(config)
    measured = calc.D(running_clearance)
    if measured < low or measured > high:
        raise ApiError("ERR_CLEARANCE_OUT_OF_BAND")
    if flush_plan != config["flush_plan"]:
        raise ApiError("ERR_FLUSH_PLAN_MISMATCH")

    order["running_clearance_mm"] = running_clearance
    order["residual_unbalance_g_mm"] = residual_unbalance
    order["seal_flush_plan_installed"] = flush_plan
    order["allowable_unbalance_g_mm"] = allowable
    order["status"] = "ASSEMBLED"
    touch(order)
    return object_response(dump(order))


@bp.post("/build-orders/<resource_id>/rework-complete")
def complete_rework(resource_id):
    authorize("ProductionPlanner")
    _no_body_allowed()
    order = path_lookup(db.build_orders, resource_id)
    if order["status"] != "REWORK_REQUIRED":
        raise ApiError("ERR_BUILD_ORDER_INVALID_STATE")
    if order["rework_cycles"] >= calc.MAX_REWORK_CYCLES:
        raise ApiError("ERR_REWORK_LIMIT_EXCEEDED")
    order["status"] = "ASSEMBLED"
    order["rework_cycles"] += 1
    touch(order)
    return object_response(dump(order))


@bp.post("/build-orders/<resource_id>/reassign-lot")
def reassign_lot(resource_id):
    authorize("ProductionPlanner")
    body = get_body()
    check_keys(body, ("casting_lot_id",))
    casting_lot_id = req_string(body, "casting_lot_id")

    order = path_lookup(db.build_orders, resource_id)
    lot = ref_lookup(db.casting_lots, casting_lot_id)

    if order["status"] != "CASTING_SHORT":
        raise ApiError("ERR_BUILD_ORDER_INVALID_STATE")
    if lot["status"] != "ACCEPTED":
        raise ApiError("ERR_CASTING_LOT_NOT_ACCEPTED")
    selection = db.selections.get(order["selection_id"])
    if _lot_pattern_model(lot) != (selection or {}).get("pump_model_id"):
        raise ApiError("ERR_LOT_MODEL_MISMATCH")

    order["casting_lot_id"] = casting_lot_id
    order["status"] = "PLANNED"
    # The physical casting has changed, so assembly must be recorded again.
    order["running_clearance_mm"] = None
    order["residual_unbalance_g_mm"] = None
    order["seal_flush_plan_installed"] = None
    order["allowable_unbalance_g_mm"] = None
    touch(order)

    recompute_committed_build_count(lot)
    touch(lot)
    return object_response(dump(order))


@bp.post("/build-orders/<resource_id>/kit-allocations/auto")
def auto_allocate_kit(resource_id):
    authorize("ProductionPlanner")
    body = get_body()
    check_keys(body, ("requested_qty",))
    requested_qty = req_int(body, "requested_qty")

    order = path_lookup(db.build_orders, resource_id)

    if requested_qty < 1:
        raise ApiError("ERR_ZERO_QUANTITY")
    if order["status"] not in ALLOCATABLE_BUILD_STATES:
        raise ApiError("ERR_BUILD_ORDER_INVALID_STATE")

    selection = db.selections.get(order["selection_id"])
    model = model_of_selection(selection)

    candidates = []
    for kit in by_seq(db.repair_kits.values()):
        if kit["status"] != "ACTIVE":
            continue
        if model is None or kit["interchange_group"] != model["interchange_group"]:
            continue
        if not kit["gen_min"] <= model["generation"] <= kit["gen_max"]:
            continue
        if not kit_window_open(kit):
            continue
        if kit["qty_on_hand"] < requested_qty:
            continue
        candidates.append(kit)
    if not candidates:
        raise ApiError("ERR_NO_INTERCHANGEABLE_KIT")

    def rank(kit):
        exact = 1 if kit["preferred_generation"] == model["generation"] else 0
        return (
            -exact,
            calc.D(kit["substitution_penalty_pct"]),
            calc.D(kit["unit_price"]),
            kit["_created_at"],
            kit["_seq"],
        )

    winner = sorted(candidates, key=rank)[0]
    record = create_allocation(winner, order, requested_qty, "SELECTOR")
    return object_response(dump(record), 201)
