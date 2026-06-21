from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, now_iso
from middleware import require_roles
from response import success_object, success_array
from services import calc
from services.common import (
    get_json_body, parse_pagination, paginate,
    require_int_range,
    get_appointment_or_404, get_stop_or_404,
)
from services.serialize import serialize_appointment

bp = Blueprint("appointments", __name__)


@bp.post("/delivery/appointments")
@require_roles("CustomerServiceAgent")
def create_appointment():
    body = get_json_body()
    stop_id = body.get("stop_id")
    if not isinstance(stop_id, str) or stop_id == "":
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "stop_id must be a non-empty string.")
    req_start = require_int_range(body, "requested_start_min", 0, 1440)
    re = body.get("requested_end_min")
    if isinstance(re, bool) or not isinstance(re, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "requested_end_min must be an integer.")
    if re <= req_start or re > 1440:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "requested_end_min out of range.")
    req_end = re

    # FK existence
    get_stop_or_404(stop_id)

    ts = now_iso()
    aid = db.new_id()
    appt = {
        "id": aid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "stop_id": stop_id,
        "requested_start_min": req_start,
        "requested_end_min": req_end,
        "status": "REQUESTED",
    }
    db.appointments[aid] = appt
    return success_object(serialize_appointment(appt), 201)


@bp.get("/delivery/appointments")
@require_roles("CustomerServiceAgent", "DispatchManager")
def list_appointments():
    limit, offset = parse_pagination()
    stop_id = request.args.get("stop_id")
    items = list(db.appointments.values())
    if stop_id is not None:
        items = [a for a in items if a["stop_id"] == stop_id]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([serialize_appointment(a) for a in page], limit, offset, total)


@bp.get("/delivery/appointments/<appointment_id>")
@require_roles("CustomerServiceAgent", "DispatchManager")
def get_appointment(appointment_id):
    appt = get_appointment_or_404(appointment_id)
    return success_object(serialize_appointment(appt), 200)


@bp.post("/delivery/appointments/<appointment_id>/apply")
@require_roles("CustomerServiceAgent")
def apply_appointment(appointment_id):
    appt = get_appointment_or_404(appointment_id)
    if appt["status"] != "REQUESTED":
        raise ApiError(errors.ERR_APPOINTMENT_NOT_REQUESTED, 409, "Appointment not REQUESTED.")

    stop = db.stops.get(appt["stop_id"])
    if stop is None:
        raise ApiError(errors.ERR_STOP_NOT_FOUND, 404, "Stop not found.")
    if stop["status"] not in ("PENDING", "OUT_FOR_DELIVERY", "REDELIVERY_SCHEDULED"):
        raise ApiError(errors.ERR_STOP_WINDOW_LOCKED, 409, "Stop window locked.")

    req_start = appt["requested_start_min"]
    req_end = appt["requested_end_min"]
    buf = calc.APPOINTMENT_BUFFER_MIN

    # conflict against other non-CANCELLED stops on same route
    for other in db.stops.values():
        if other["id"] == stop["id"]:
            continue
        if other["route_id"] != stop["route_id"]:
            continue
        if other["status"] == "CANCELLED":
            continue
        o_start = other["window_start_min"]
        o_end = other["window_end_min"]
        if (req_start < o_end + buf) and (req_end + buf > o_start):
            raise ApiError(errors.ERR_APPOINTMENT_WINDOW_CONFLICT, 409, "Appointment window conflict.")

    # apply
    stop["window_start_min"] = req_start
    stop["window_end_min"] = req_end
    stop["updated_at"] = now_iso()
    stop["version"] += 1

    # route version bump (stop mutated)
    route = db.routes.get(stop["route_id"])
    if route is not None:
        route["updated_at"] = now_iso()
        route["version"] += 1

    appt["status"] = "APPLIED"
    appt["updated_at"] = now_iso()
    appt["version"] += 1
    return success_object(serialize_appointment(appt), 200)


@bp.post("/delivery/appointments/<appointment_id>/reject")
@require_roles("CustomerServiceAgent")
def reject_appointment(appointment_id):
    appt = get_appointment_or_404(appointment_id)
    if appt["status"] != "REQUESTED":
        raise ApiError(errors.ERR_APPOINTMENT_NOT_REQUESTED, 409, "Appointment not REQUESTED.")
    appt["status"] = "REJECTED"
    appt["updated_at"] = now_iso()
    appt["version"] += 1
    return success_object(serialize_appointment(appt), 200)
