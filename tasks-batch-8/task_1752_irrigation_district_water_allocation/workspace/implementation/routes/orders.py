"""TurnoutOrder endpoints: create (OCC on account), list, get, schedule,
reject, cancel, start."""
from decimal import Decimal

from flask import Blueprint

import db
from db import store, new_id, new_common, touch, iso_out, D, round2
from errors import ApiError
from response import ok, created, list_ok, filter_eq
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity
from services import ledger, ordering

bp = Blueprint("orders", __name__)

READ_ROLES = ["DistrictAdmin", "WaterUser", "DitchRider"]
AF_PER_CFS_HOUR = Decimal("0.0826")

_CREATE_SCHEMA = {
    "water_account_id": ("string", True, None, None),
    "season_allocation_id": ("string", True, None, None),
    "canal_reach_id": ("string", True, None, None),
    "requested_cfs": ("number", True, None, "gt0"),
    "requested_start_at": ("datetime", True, None, None),
    "requested_end_at": ("datetime", True, None, None),
    "expected_water_account_version": ("integer", True, None, None),
}


def _order_quantity(cfs, start, end):
    """round_half_up(requested_cfs * window_hours * 0.0826, 2); window measured
    in seconds / 3600."""
    window_seconds = Decimal(int((end - start).total_seconds()))
    window_hours = window_seconds / Decimal(3600)
    return round2(D(cfs) * window_hours * AF_PER_CFS_HOUR)


@bp.post("/district/turnout-orders")
def create_order():
    uid, role = get_context()
    body = parse_body(_CREATE_SCHEMA, allow_empty=False)
    start = body["_requested_start_at_dt"]
    end = body["_requested_end_at_dt"]
    if not end > start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "requested_end_at must be strictly after requested_start_at")
    require_roles(["WaterUser"])
    # Ownership (priority 3): WaterUser may order only against their own account.
    if uid != body["water_account_id"]:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "WaterUser may place orders only on their own account")
    # Existence (priority 4): body FKs in declared input order.
    account = store.water_accounts.get(body["water_account_id"])
    if account is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced water_account_id does not exist")
    alloc = store.allocations.get(body["season_allocation_id"])
    if alloc is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced season_allocation_id does not exist")
    reach = store.canal_reaches.get(body["canal_reach_id"])
    if reach is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced canal_reach_id does not exist")
    # OCC (priority 5) on the water account.
    if body["expected_water_account_version"] != account["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_water_account_version does not match the account's current version")
    # Cross-entity state gates (priority 6).
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Water account is not ACTIVE")
    season = store.seasons.get(alloc["season_id"])
    if season is None or season["status"] != "OPEN":
        raise ApiError("ERR_SEASON_NOT_OPEN", 409, "Season is not OPEN")
    # Temporal (priority 8b): account turnaround gap.
    ordering.check_turnaround(account["id"], start, end)
    # Sufficient water (priority 10), net-of-committed reading.
    quantity = _order_quantity(body["requested_cfs"], start, end)
    ledger.recompute_allocation(alloc)
    if quantity > alloc["available_af"]:
        raise ApiError("ERR_INSUFFICIENT_ALLOCATION", 422,
                       "Requested quantity exceeds the allocation's available balance")
    order = new_common({
        "id": new_id(),
        "water_account_id": account["id"],
        "season_allocation_id": alloc["id"],
        "canal_reach_id": reach["id"],
        "requested_cfs": body["requested_cfs"],
        "requested_start_at": iso_out(start),
        "requested_end_at": iso_out(end),
        "_start_dt": start,
        "_end_dt": end,
        "requested_quantity_af": quantity,
        "actual_delivered_af": None,
        "over_delivered": False,
        "status": "REQUESTED",
    })
    store.turnout_orders[order["id"]] = order
    touch(account)  # order creation bumps the account version (OCC parent)
    ledger.refresh_allocation(alloc)  # commits requested_quantity_af, bumps alloc version
    return created(order)


@bp.get("/district/turnout-orders")
def list_orders():
    uid, role = get_context()
    require_roles(READ_ROLES)
    rows = list(store.turnout_orders.values())
    for f in ("water_account_id", "season_allocation_id", "canal_reach_id", "status"):
        rows = filter_eq(rows, f)
    return list_ok(rows)


@bp.get("/district/turnout-orders/<oid>")
def get_order(oid):
    uid, role = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.turnout_orders, oid))


@bp.post("/district/turnout-orders/<oid>/schedule")
def schedule_order(oid):
    uid, role = get_context()
    body = parse_body({"rider_user_id": ("string", True, None, None)}, allow_empty=False)
    require_roles(["DistrictAdmin"])
    order = require_path_entity(store.turnout_orders, oid)
    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_ORDER_STATE", 409,
                       "Only a REQUESTED order may be scheduled")
    account = store.water_accounts[order["water_account_id"]]
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Water account is not ACTIVE")
    alloc = store.allocations[order["season_allocation_id"]]
    season = store.seasons[alloc["season_id"]]
    if season["status"] != "OPEN":
        raise ApiError("ERR_SEASON_NOT_OPEN", 409, "Season is not OPEN")
    reach = store.canal_reaches[order["canal_reach_id"]]
    start, end = order["_start_dt"], order["_end_dt"]
    # Temporal (priority 8): (a) maintenance-window conflict, (b) turnaround gap.
    ordering.check_window_time_conflict(reach["id"], start, end)
    ordering.check_turnaround(account["id"], start, end, exclude_order_id=order["id"])
    # Capacity (priority 9): instantaneous summed flow on the reach.
    ordering.check_reach_capacity(reach, start, end, order["requested_cfs"])
    order["status"] = "SCHEDULED"
    touch(order)
    wo = new_common({
        "id": new_id(),
        "turnout_order_id": order["id"],
        "rider_user_id": body["rider_user_id"],
        "measured_cfs": None,
        "measured_hours": None,
        "measured_af": None,
        "return_reason": None,
        "status": "ASSIGNED",
    })
    store.rider_work_orders[wo["id"]] = wo
    return ok(order)


@bp.post("/district/turnout-orders/<oid>/reject")
def reject_order(oid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    order = require_path_entity(store.turnout_orders, oid)
    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_ORDER_STATE", 409,
                       "Only a REQUESTED order may be rejected")
    order["status"] = "REJECTED"
    touch(order)
    alloc = store.allocations[order["season_allocation_id"]]
    ledger.refresh_allocation(alloc)  # releases committed water
    return ok(order)


@bp.post("/district/turnout-orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin", "WaterUser"])
    order = require_path_entity(store.turnout_orders, oid)
    if role == "WaterUser" and uid != order["water_account_id"]:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "WaterUser may cancel only their own orders")
    if order["status"] not in ("REQUESTED", "SCHEDULED"):
        raise ApiError("ERR_INVALID_ORDER_STATE", 409,
                       "Only a REQUESTED or SCHEDULED order may be cancelled")
    ordering.cascade_cancel_order(order)
    alloc = store.allocations[order["season_allocation_id"]]
    ledger.refresh_allocation(alloc)  # releases committed water
    return ok(order)


@bp.post("/district/turnout-orders/<oid>/start")
def start_order(oid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DitchRider"])
    order = require_path_entity(store.turnout_orders, oid)
    wo = ordering.linked_work_order(order)
    if wo is not None and wo["rider_user_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the assigned ditch rider may start this order")
    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_ORDER_STATE", 409,
                       "Only a SCHEDULED order may be started")
    reach = store.canal_reaches[order["canal_reach_id"]]
    if reach["status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_ORDER_STATE", 409,
                       "Cannot start while the reach is SHUTDOWN")
    now = db.LOGICAL_CLOCK
    if not (order["_start_dt"] <= now < order["_end_dt"]):
        raise ApiError("ERR_OUTSIDE_DELIVERY_WINDOW", 422,
                       "Logical clock is outside the order's delivery window")
    order["status"] = "FLOWING"
    touch(order)
    if wo is not None and wo["status"] == "ASSIGNED":
        wo["status"] = "IN_PROGRESS"
        touch(wo)
    return ok(order)
