"""RiderWorkOrder endpoints: list, get, submit-measurement, verify, return."""
from decimal import Decimal

from flask import Blueprint

from db import store, touch, D, round2
from errors import ApiError
from response import ok, list_ok, filter_eq
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity
from services import ledger

bp = Blueprint("workorders", __name__)

READ_ROLES = ["DistrictAdmin", "DitchRider"]
AF_PER_CFS_HOUR = Decimal("0.0826")


@bp.get("/district/rider-work-orders")
def list_work_orders():
    uid, role = get_context()
    require_roles(READ_ROLES)
    rows = list(store.rider_work_orders.values())
    for f in ("turnout_order_id", "rider_user_id", "status"):
        rows = filter_eq(rows, f)
    return list_ok(rows)


@bp.get("/district/rider-work-orders/<wid>")
def get_work_order(wid):
    uid, role = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.rider_work_orders, wid))


@bp.post("/district/rider-work-orders/<wid>/submit-measurement")
def submit_measurement(wid):
    uid, role = get_context()
    body = parse_body({
        "measured_cfs": ("number", True, None, "gt0"),
        "measured_hours": ("number", True, None, "gt0"),
    }, allow_empty=False)
    require_roles(["DitchRider"])
    wo = require_path_entity(store.rider_work_orders, wid)
    if wo["rider_user_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the assigned ditch rider may submit this measurement")
    if wo["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_WORK_ORDER_STATE", 409,
                       "Work order must be IN_PROGRESS to submit a measurement")
    wo["measured_cfs"] = body["measured_cfs"]
    wo["measured_hours"] = body["measured_hours"]
    wo["measured_af"] = round2(D(body["measured_cfs"]) * D(body["measured_hours"]) * AF_PER_CFS_HOUR)
    wo["status"] = "MEASUREMENT_SUBMITTED"
    touch(wo)
    return ok(wo)


@bp.post("/district/rider-work-orders/<wid>/verify")
def verify_measurement(wid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    wo = require_path_entity(store.rider_work_orders, wid)
    if wo["status"] != "MEASUREMENT_SUBMITTED":
        raise ApiError("ERR_INVALID_WORK_ORDER_STATE", 409,
                       "Only a MEASUREMENT_SUBMITTED work order may be verified")
    wo["status"] = "VERIFIED"
    touch(wo)
    # Deliver the linked order and post measured water to the allocation ledger.
    order = store.turnout_orders[wo["turnout_order_id"]]
    order["actual_delivered_af"] = wo["measured_af"]
    order["over_delivered"] = D(wo["measured_af"]) > D(order["requested_quantity_af"])
    order["status"] = "DELIVERED"
    touch(order)
    alloc = store.allocations[order["season_allocation_id"]]
    ledger.refresh_allocation(alloc)  # delivered += measured_af; committed -= requested
    return ok(wo)


@bp.post("/district/rider-work-orders/<wid>/return")
def return_measurement(wid):
    uid, role = get_context()
    body = parse_body({"return_reason": ("string", True, None, None)}, allow_empty=False)
    require_roles(["DistrictAdmin"])
    wo = require_path_entity(store.rider_work_orders, wid)
    if wo["status"] != "MEASUREMENT_SUBMITTED":
        raise ApiError("ERR_INVALID_WORK_ORDER_STATE", 409,
                       "Only a MEASUREMENT_SUBMITTED work order may be returned")
    # MEASUREMENT_SUBMITTED -> IN_PROGRESS; the linked order remains FLOWING.
    wo["measured_cfs"] = None
    wo["measured_hours"] = None
    wo["measured_af"] = None
    wo["return_reason"] = body["return_reason"]
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    return ok(wo)
