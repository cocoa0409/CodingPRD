from datetime import timedelta

from flask import Blueprint, request

import store
from auth import authenticate, require_role, deny
from util import ApiError, object_response, array_response, paginate, apply_list, serialize
import validate as v
import services as svc
import lookups as lk

bp = Blueprint("appointments", __name__)

BUFFER = timedelta(minutes=svc.PREMISES_BUFFER_MINUTES)


def _tester_certified_for(tester, when):
    return (tester["status"] == "ACTIVE"
            and tester["cert_effective_date"] <= when <= tester["cert_expiry_date"])


@bp.post("/test-appointments")
def create_appointment():
    user_id, role = authenticate()
    require_role(role, {"Tester"})
    body = v.json_object()

    raw_did = body.get("device_id")
    device = lk.get_device(raw_did) if isinstance(raw_did, str) and raw_did else None
    raw_tid = body.get("tester_id")
    tester = lk.get_tester(raw_tid) if isinstance(raw_tid, str) and raw_tid else None

    # ownership: tester books their own work
    if tester is not None and tester["id"] != user_id:
        deny()

    # resolve any still-missing FKs through validation
    if device is None:
        device = lk.get_device(v.req_nonempty_str(body, "device_id"))
    if tester is None:
        tester = lk.get_tester(v.req_nonempty_str(body, "tester_id"))
        if tester["id"] != user_id:
            deny()

    # state: device testable
    if device["status"] not in ("ACTIVE", "NEEDS_REPAIR"):
        raise ApiError("ERR_DEVICE_NOT_TESTABLE", 409, "device is not testable")

    # certification (status first, then window using scheduled_start)
    if tester["status"] != "ACTIVE":
        raise ApiError("ERR_TESTER_NOT_CERTIFIED", 422, "tester is not certified")
    start = v.req_datetime(body, "scheduled_start")
    if not (tester["cert_effective_date"] <= start <= tester["cert_expiry_date"]):
        raise ApiError("ERR_TESTER_NOT_CERTIFIED", 422, "tester is not certified")

    # well-formed time range
    end = v.req_datetime(body, "scheduled_end")
    if not (end > start):
        raise ApiError("ERR_INVALID_TIME_RANGE", 400, "scheduled_end must be after scheduled_start")

    # tester double-booking (half-open overlap)
    for a in store.appointments.values():
        if a["status"] != "BOOKED" or a["tester_id"] != tester["id"]:
            continue
        if start < a["scheduled_end"] and a["scheduled_start"] < end:
            raise ApiError("ERR_TESTER_DOUBLE_BOOKED", 409, "tester is double-booked")

    # premises buffer (>= 60 min gap between appointments sharing a connection)
    conn_id = device["service_connection_id"]
    for a in store.appointments.values():
        if a["status"] != "BOOKED":
            continue
        other_dev = store.devices.get(a["device_id"])
        if other_dev is None or other_dev["service_connection_id"] != conn_id:
            continue
        if end <= a["scheduled_start"]:
            gap = a["scheduled_start"] - end
        elif a["scheduled_end"] <= start:
            gap = start - a["scheduled_end"]
        else:
            gap = timedelta(seconds=-1)  # overlap
        if gap < BUFFER:
            raise ApiError("ERR_PREMISES_BUFFER_CONFLICT", 409, "premises buffer conflict")

    appt = {
        "device_id": device["id"],
        "tester_id": tester["id"],
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "BOOKED",
    }
    svc.stamp_new(appt)
    store.appointments[appt["id"]] = appt
    return object_response(serialize(appt), 201)


@bp.get("/test-appointments")
def list_appointments():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "Tester"})
    limit, offset = paginate(request.args)

    did = request.args.get("device_id")
    tid = request.args.get("tester_id")
    status = request.args.get("status")

    pool = list(store.appointments.values())
    if role == "Tester":
        pool = [a for a in pool if a["tester_id"] == user_id]
    if did is not None:
        pool = [a for a in pool if a["device_id"] == did]
    if tid is not None:
        pool = [a for a in pool if a["tester_id"] == tid]
    if status is not None:
        pool = [a for a in pool if a["status"] == status]

    items, total = apply_list(pool, limit, offset)
    return array_response(items, limit, offset, total)


@bp.get("/test-appointments/<aid>")
def get_appointment(aid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "Tester"})
    appt = lk.get_appointment(aid)
    if role == "Tester" and appt["tester_id"] != user_id:
        deny()
    return object_response(serialize(appt))


@bp.post("/test-appointments/<aid>/cancel")
def cancel_appointment(aid):
    user_id, role = authenticate()
    require_role(role, {"Tester", "UtilityAdmin"})
    appt = lk.get_appointment(aid)
    if role == "Tester" and appt["tester_id"] != user_id:
        deny()
    if appt["status"] != "BOOKED":
        raise ApiError("ERR_APPOINTMENT_NOT_BOOKED", 409, "appointment is not BOOKED")
    appt["status"] = "CANCELLED"
    svc.touch(appt)
    return object_response(serialize(appt))
