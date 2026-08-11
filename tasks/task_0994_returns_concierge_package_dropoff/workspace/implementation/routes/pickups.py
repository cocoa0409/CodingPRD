"""CourierZone and PickupAppointment endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
from db import store, stamp, touch
from errors import ApiError, bad_request, invalid_state, already_terminal
from services import (
    ORDER_TERMINAL, PICKUP_MAX_ATTEMPTS,
    ser_zone, ser_appointment, get_or_404, issue_label, active_label,
    zone_confirmed_for_window,
)
from util import require_roles, respond, body, req_str, req_int, req_dt, paginate

bp = Blueprint("pickups", __name__)


@bp.post("/courier-zones")
def create_zone():
    require_roles("PlatformAdmin")
    b = body(required=True)
    zone_code = req_str(b, "zone_code")
    capacity = req_int(b, "window_capacity")
    if capacity < 1:
        bad_request("window_capacity must be >= 1")
    for z in store["zones"].values():
        if z["zone_code"] == zone_code:
            bad_request("zone_code must be unique")
    zone = {"zone_code": zone_code, "window_capacity": capacity}
    stamp(zone)
    store["zones"][zone["id"]] = zone
    return respond(ser_zone(zone), 201)


@bp.get("/courier-zones/<zid>")
def get_zone(zid):
    require_roles("PlatformAdmin", "SupportAgent", "Shopper")
    return respond(ser_zone(get_or_404("zones", zid)))


def _own_appointment_order(uid, role, appt):
    order = store["orders"][appt["return_order_id"]]
    if role == "Shopper" and order["shopper_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may act only on its own orders")
    return order


def _validate_window(zone, ws, we):
    """Shape (end > start), then temporal (not past), then zone capacity."""
    if not we > ws:
        bad_request("window_end must be strictly after window_start")
    if ws < db.now():
        raise ApiError("ERR_PICKUP_WINDOW_PAST", 422,
                       "window_start precedes the current logical clock")
    if zone_confirmed_for_window(zone["id"], ws, we) >= zone["window_capacity"]:
        raise ApiError("ERR_PICKUP_WINDOW_FULL", 409,
                       "Zone confirmed overlapping load already at window_capacity")


@bp.post("/pickup-appointments")
def create_appointment():
    uid, role = require_roles("Shopper")
    b = body(required=True)
    order_id = req_str(b, "return_order_id")
    zone_id = req_str(b, "zone_id")
    ws = req_dt(b, "window_start")
    we = req_dt(b, "window_end")
    order = get_or_404("orders", order_id)
    zone = get_or_404("zones", zone_id)
    if order["shopper_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may book pickups only for its own orders")
    if not we > ws:
        bad_request("window_end must be strictly after window_start")
    if order["status"] in ORDER_TERMINAL:
        already_terminal("Order is in a terminal state")
    if order["status"] != "INITIATED":
        invalid_state("Pickup booking requires an INITIATED order")
    if order["method"] != "HOME_PICKUP":
        invalid_state("Pickup booking requires method HOME_PICKUP")
    if ws < db.now():
        raise ApiError("ERR_PICKUP_WINDOW_PAST", 422,
                       "window_start precedes the current logical clock")
    if zone_confirmed_for_window(zone_id, ws, we) >= zone["window_capacity"]:
        raise ApiError("ERR_PICKUP_WINDOW_FULL", 409,
                       "Zone confirmed overlapping load already at window_capacity")
    appt = {
        "return_order_id": order_id,
        "zone_id": zone_id,
        "window_start": ws,
        "window_end": we,
        "status": "SCHEDULED",
        "attempt_count": 0,
    }
    stamp(appt)
    store["appointments"][appt["id"]] = appt
    issue_label(order, "QR_CODE", supersedes=None)
    order["status"] = "LABEL_ISSUED"
    touch(order)
    return respond(ser_appointment(appt), 201)


@bp.get("/pickup-appointments/<aid>")
def get_appointment(aid):
    uid, role = require_roles("Shopper", "SupportAgent", "PlatformAdmin")
    appt = get_or_404("appointments", aid)
    _own_appointment_order(uid, role, appt)
    return respond(ser_appointment(appt))


@bp.get("/pickup-appointments")
def list_appointments():
    require_roles("SupportAgent", "PlatformAdmin")
    items = list(store["appointments"].values())
    order_id = request.args.get("return_order_id")
    zone_id = request.args.get("zone_id")
    status = request.args.get("status")
    if order_id is not None:
        items = [a for a in items if a["return_order_id"] == order_id]
    if zone_id is not None:
        items = [a for a in items if a["zone_id"] == zone_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items)
    return respond([ser_appointment(a) for a in page], page=meta)


def _appt_state(appt, allowed, action):
    if appt["status"] in ("COLLECTED", "CANCELLED"):
        already_terminal("Appointment is in a terminal state")
    if appt["status"] not in allowed:
        invalid_state("Appointment cannot be %sed from %s" % (action, appt["status"]))


@bp.post("/pickup-appointments/<aid>/start")
def start_appointment(aid):
    require_roles("PlatformAdmin")
    appt = get_or_404("appointments", aid)
    _appt_state(appt, ("SCHEDULED",), "start")
    if db.now() < appt["window_start"] - timedelta(hours=1):
        raise ApiError("ERR_PICKUP_TOO_EARLY", 409,
                       "Start attempted before window_start - 1h")
    appt["status"] = "EN_ROUTE"
    touch(appt)
    return respond(ser_appointment(appt))


@bp.post("/pickup-appointments/<aid>/collect")
def collect_appointment(aid):
    require_roles("PlatformAdmin")
    appt = get_or_404("appointments", aid)
    _appt_state(appt, ("EN_ROUTE",), "collect")
    appt["status"] = "COLLECTED"
    touch(appt)
    order = store["orders"][appt["return_order_id"]]
    if order["status"] in ("INITIATED", "LABEL_ISSUED"):
        order["status"] = "IN_TRANSIT"
        touch(order)
        label = active_label(order)
        if label is not None:
            label["status"] = "CONSUMED"
            touch(label)
    return respond(ser_appointment(appt))


@bp.post("/pickup-appointments/<aid>/fail")
def fail_appointment(aid):
    require_roles("PlatformAdmin")
    appt = get_or_404("appointments", aid)
    _appt_state(appt, ("EN_ROUTE",), "fail")
    appt["status"] = "FAILED"
    appt["attempt_count"] += 1
    touch(appt)
    return respond(ser_appointment(appt))


@bp.post("/pickup-appointments/<aid>/reschedule")
def reschedule_appointment(aid):
    uid, role = require_roles("Shopper", "PlatformAdmin")
    appt = get_or_404("appointments", aid)
    _own_appointment_order(uid, role, appt)
    b = body(required=True)
    ws = req_dt(b, "window_start")
    we = req_dt(b, "window_end")
    if not we > ws:
        bad_request("window_end must be strictly after window_start")
    _appt_state(appt, ("FAILED",), "reschedule")
    if appt["attempt_count"] >= PICKUP_MAX_ATTEMPTS:
        raise ApiError("ERR_PICKUP_MAX_ATTEMPTS", 409,
                       "Reschedule attempted with attempt_count >= 3")
    zone = store["zones"][appt["zone_id"]]
    if ws < db.now():
        raise ApiError("ERR_PICKUP_WINDOW_PAST", 422,
                       "window_start precedes the current logical clock")
    if zone_confirmed_for_window(zone["id"], ws, we) >= zone["window_capacity"]:
        raise ApiError("ERR_PICKUP_WINDOW_FULL", 409,
                       "Zone confirmed overlapping load already at window_capacity")
    appt["window_start"] = ws
    appt["window_end"] = we
    appt["status"] = "SCHEDULED"
    touch(appt)
    return respond(ser_appointment(appt))


@bp.post("/pickup-appointments/<aid>/cancel")
def cancel_appointment(aid):
    uid, role = require_roles("Shopper")
    appt = get_or_404("appointments", aid)
    _own_appointment_order(uid, role, appt)
    _appt_state(appt, ("SCHEDULED",), "cancel")
    appt["status"] = "CANCELLED"
    touch(appt)
    return respond(ser_appointment(appt))
