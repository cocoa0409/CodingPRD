"""Purchase order endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ADMIN, ANY_ROLE, PARTICIPANT, auth, check_ownership
from response import ok
from services import (
    ORDER_STATUSES,
    filter_enum,
    get_enrollment,
    get_order,
    get_plan,
    get_window,
    list_response,
    recompute_window_total,
    ser_order,
    stamp,
    touch,
)
from util import as_pos_int, as_str, body, required

bp = Blueprint("orders", __name__)


@bp.post("/purchase-windows/<window_id>/purchase-orders")
def submit_order(window_id):
    user_id, role = auth(PARTICIPANT)
    w = get_window(window_id)
    data = body()
    enrollment_id = as_str(required(data, "enrollment_id"), "enrollment_id")
    amount = as_pos_int(required(data, "amount_cents"), "amount_cents")
    e = DB["enrollments"].get(enrollment_id)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Enrollment not found")
    check_ownership(e["participant_id"], user_id, role)
    plan = get_plan(w["plan_id"])
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    if w["status"] != "OPEN":
        raise ApiError("ERR_WINDOW_NOT_OPEN", 409, "Window is not OPEN")
    if e["status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE"
        )
    if amount < plan["ocp_min_cents"]:
        raise ApiError(
            "ERR_PURCHASE_BELOW_MIN",
            422,
            "Order amount is below plan.ocp_min_cents",
        )
    existing = sum(
        o["amount_cents"]
        for o in DB["purchase_orders"].values()
        if o["window_id"] == w["id"]
        and o["enrollment_id"] == e["id"]
        and o["status"] == "SUBMITTED"
    )
    # Boundary: equality is allowed; only a strict overshoot is rejected.
    if existing + amount > plan["ocp_max_cents"]:
        raise ApiError(
            "ERR_PURCHASE_LIMIT_EXCEEDED",
            422,
            "Cumulative SUBMITTED orders would exceed plan.ocp_max_cents",
        )
    rec = {
        "id": new_id(),
        "window_id": w["id"],
        "enrollment_id": e["id"],
        "amount_cents": amount,
        "status": "SUBMITTED",
        "settled_shares": None,
    }
    stamp(rec)
    DB["purchase_orders"][rec["id"]] = rec
    recompute_window_total(w)
    return ok(ser_order(rec), status=201)


@bp.get("/purchase-windows/<window_id>/purchase-orders")
def list_window_orders(window_id):
    auth(ADMIN)
    get_window(window_id)
    items = [
        o for o in DB["purchase_orders"].values() if o["window_id"] == window_id
    ]
    items = filter_enum(
        items, request.args.get("status"), "status", ORDER_STATUSES, "status"
    )
    return list_response(items, ser_order)


@bp.get("/purchase-orders/<oid>")
def get_one_order(oid):
    user_id, role = auth(ANY_ROLE)
    o = get_order(oid)
    e = get_enrollment(o["enrollment_id"])
    check_ownership(e["participant_id"], user_id, role)
    return ok(ser_order(o))


@bp.get("/purchase-orders")
def list_orders():
    user_id, role = auth(ANY_ROLE)
    items = list(DB["purchase_orders"].values())
    if role == "Participant":
        own = {
            e["id"]
            for e in DB["enrollments"].values()
            if e["participant_id"] == user_id
        }
        items = [o for o in items if o["enrollment_id"] in own]
    enrollment_id = request.args.get("enrollment_id")
    if enrollment_id is not None:
        items = [o for o in items if o["enrollment_id"] == enrollment_id]
    window_id = request.args.get("window_id")
    if window_id is not None:
        items = [o for o in items if o["window_id"] == window_id]
    items = filter_enum(
        items, request.args.get("status"), "status", ORDER_STATUSES, "status"
    )
    return list_response(items, ser_order)


@bp.post("/purchase-orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = auth(PARTICIPANT)
    o = get_order(oid)
    e = get_enrollment(o["enrollment_id"])
    check_ownership(e["participant_id"], user_id, role)
    if o["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not SUBMITTED")
    w = get_window(o["window_id"])
    if w["status"] != "OPEN":
        raise ApiError("ERR_WINDOW_NOT_OPEN", 409, "Window is not OPEN")
    o["status"] = "CANCELLED"
    touch(o)
    recompute_window_total(w)
    return ok(ser_order(o))
