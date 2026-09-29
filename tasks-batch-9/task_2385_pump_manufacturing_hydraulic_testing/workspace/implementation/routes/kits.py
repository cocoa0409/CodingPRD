"""Spare-parts repair kits, stock movements and priced allocations."""

from flask import Blueprint

from db import by_seq, db, new_record
from errors import ApiError
from helpers import apply_filters, ensure_unique, paginate, path_lookup, ref_lookup, touch
from middleware import ALL_ROLES, authorize
from response import list_response, object_response
from serializers import dump, dump_all
from services.allocations import (
    ALLOCATABLE_BUILD_STATES,
    create_allocation,
    kit_window_open,
    model_of_build,
)
from validation import (
    check_keys,
    get_body,
    pagination,
    query_value,
    req_datetime,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("kits", __name__)


def _no_body_allowed():
    check_keys(get_body(), ())


def _collection(records, limit, offset):
    window, total = paginate(records, limit, offset)
    return list_response(dump_all(window), limit, offset, total)


# -------------------------------------------------------------- repair kits


@bp.post("/repair-kits")
def create_repair_kit():
    authorize("PlatformAdmin")
    body = get_body()
    check_keys(
        body,
        (
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
        ),
    )
    pump_model_id = req_string(body, "pump_model_id")
    kit_code = req_string(body, "kit_code")
    interchange_group = req_string(body, "interchange_group")
    gen_min = req_int(body, "gen_min", minimum=1)
    gen_max = req_int(body, "gen_max", minimum=1)
    preferred_generation = req_int(body, "preferred_generation", minimum=1)
    penalty = req_number(body, "substitution_penalty_pct", minimum=0)
    unit_price = req_number(body, "unit_price", exclusive_min=0)
    window_start = req_datetime(body, "support_window_start")
    window_end = req_datetime(body, "support_window_end")

    if gen_max < gen_min:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'gen_max' must be at least 'gen_min'")
    if not gen_min <= preferred_generation <= gen_max:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'preferred_generation' must lie between 'gen_min' and 'gen_max' inclusive",
        )

    ref_lookup(db.pump_models, pump_model_id)
    ensure_unique(db.repair_kits, "kit_code", kit_code)

    if window_end <= window_start:
        raise ApiError("ERR_INVALID_WINDOW")

    record = new_record(
        "RepairKit",
        pump_model_id=pump_model_id,
        kit_code=kit_code,
        interchange_group=interchange_group,
        gen_min=gen_min,
        gen_max=gen_max,
        preferred_generation=preferred_generation,
        substitution_penalty_pct=penalty,
        unit_price=unit_price,
        support_window_start=window_start,
        support_window_end=window_end,
        qty_received_total=0,
        qty_on_hand=0,
        qty_reserved=0,
        qty_issued=0,
        qty_consumed_total=0,
        status="ACTIVE",
    )
    db.repair_kits[record["id"]] = record
    return object_response(dump(record), 201)


@bp.get("/repair-kits")
def list_repair_kits():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.repair_kits.values()),
        [
            (query_value("pump_model_id"), "pump_model_id"),
            (query_value("interchange_group"), "interchange_group"),
            (query_value("status"), "status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/repair-kits/<resource_id>")
def read_repair_kit(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.repair_kits, resource_id)))


@bp.post("/repair-kits/<resource_id>/receipts")
def receive_stock(resource_id):
    authorize("ProductionPlanner")
    body = get_body()
    check_keys(body, ("qty",))
    qty = req_int(body, "qty")

    kit = path_lookup(db.repair_kits, resource_id)
    if qty < 1:
        raise ApiError("ERR_ZERO_QUANTITY")
    if kit["status"] != "ACTIVE":
        raise ApiError("ERR_REPAIR_KIT_DISCONTINUED")

    kit["qty_on_hand"] += qty
    kit["qty_received_total"] += qty
    touch(kit)
    return object_response(dump(kit))


@bp.post("/repair-kits/<resource_id>/discontinue")
def discontinue_repair_kit(resource_id):
    authorize("PlatformAdmin")
    _no_body_allowed()
    kit = path_lookup(db.repair_kits, resource_id)
    if kit["status"] != "ACTIVE":
        raise ApiError("ERR_REPAIR_KIT_DISCONTINUED")
    kit["status"] = "DISCONTINUED"
    touch(kit)
    return object_response(dump(kit))


# ---------------------------------------------------------- kit allocations


@bp.post("/kit-allocations")
def create_kit_allocation():
    authorize("ProductionPlanner")
    body = get_body()
    check_keys(
        body,
        ("repair_kit_id", "build_order_id", "requested_qty", "expected_repair_kit_version"),
    )
    repair_kit_id = req_string(body, "repair_kit_id")
    build_order_id = req_string(body, "build_order_id")
    requested_qty = req_int(body, "requested_qty")
    expected_version = req_int(body, "expected_repair_kit_version", minimum=1)

    kit = ref_lookup(db.repair_kits, repair_kit_id)
    order = ref_lookup(db.build_orders, build_order_id)

    if kit["version"] != expected_version:
        raise ApiError("ERR_STALE_REPAIR_KIT_VERSION")
    if requested_qty < 1:
        raise ApiError("ERR_ZERO_QUANTITY")
    if order["status"] not in ALLOCATABLE_BUILD_STATES:
        raise ApiError("ERR_BUILD_ORDER_INVALID_STATE")
    if kit["status"] != "ACTIVE":
        raise ApiError("ERR_REPAIR_KIT_DISCONTINUED")

    model = model_of_build(order)
    if model is None or kit["interchange_group"] != model["interchange_group"]:
        raise ApiError("ERR_KIT_GROUP_MISMATCH")
    if not kit["gen_min"] <= model["generation"] <= kit["gen_max"]:
        raise ApiError("ERR_KIT_GENERATION_NOT_COVERED")
    if not kit_window_open(kit):
        raise ApiError("ERR_KIT_SUPPORT_WINDOW_EXPIRED")
    if kit["qty_on_hand"] < requested_qty:
        raise ApiError("ERR_KIT_STOCK_INSUFFICIENT")

    record = create_allocation(kit, order, requested_qty, "EXPLICIT")
    return object_response(dump(record), 201)


@bp.get("/kit-allocations")
def list_kit_allocations():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.kit_allocations.values()),
        [
            (query_value("repair_kit_id"), "repair_kit_id"),
            (query_value("build_order_id"), "build_order_id"),
            (query_value("status"), "status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/kit-allocations/<resource_id>")
def read_kit_allocation(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.kit_allocations, resource_id)))


def _kit_of(allocation):
    return db.repair_kits.get(allocation["repair_kit_id"])


@bp.post("/kit-allocations/<resource_id>/issue")
def issue_allocation(resource_id):
    authorize("ProductionPlanner")
    _no_body_allowed()
    allocation = path_lookup(db.kit_allocations, resource_id)
    if allocation["status"] != "RESERVED":
        raise ApiError("ERR_ALLOCATION_INVALID_STATE")
    qty = allocation["requested_qty"]
    kit = _kit_of(allocation)
    if kit is not None:
        kit["qty_reserved"] -= qty
        kit["qty_issued"] += qty
        touch(kit)
    allocation["status"] = "ISSUED"
    touch(allocation)
    return object_response(dump(allocation))


@bp.post("/kit-allocations/<resource_id>/consume")
def consume_allocation(resource_id):
    authorize("ProductionPlanner")
    _no_body_allowed()
    allocation = path_lookup(db.kit_allocations, resource_id)
    if allocation["status"] != "ISSUED":
        raise ApiError("ERR_ALLOCATION_INVALID_STATE")
    qty = allocation["requested_qty"]
    kit = _kit_of(allocation)
    if kit is not None:
        kit["qty_issued"] -= qty
        kit["qty_consumed_total"] += qty
        touch(kit)
    allocation["status"] = "CONSUMED"
    touch(allocation)
    return object_response(dump(allocation))


@bp.post("/kit-allocations/<resource_id>/release")
def release_allocation_route(resource_id):
    authorize("ProductionPlanner")
    _no_body_allowed()
    allocation = path_lookup(db.kit_allocations, resource_id)
    if allocation["status"] != "RESERVED":
        raise ApiError("ERR_ALLOCATION_INVALID_STATE")
    qty = allocation["requested_qty"]
    kit = _kit_of(allocation)
    if kit is not None:
        kit["qty_reserved"] -= qty
        kit["qty_on_hand"] += qty
        touch(kit)
    allocation["status"] = "RELEASED"
    touch(allocation)
    return object_response(dump(allocation))
