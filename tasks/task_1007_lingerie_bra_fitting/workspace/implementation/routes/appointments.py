"""FittingAppointment lifecycle: book, confirm, check-in, fit, complete,
reschedule, cancel (PRD §3.2, SCAFFOLD §1.2)."""
from datetime import timedelta

from flask import Blueprint, g

import store
import api as h
import calc
import serialize as s
from errors import ApiError

bp = Blueprint("appointments", __name__)

FITTING_TYPES = {"STANDARD", "POST_SURGICAL", "MASTECTOMY"}
FIT_PREFS = {"SNUG", "STANDARD", "RELAXED"}
ACTIVE_SLOT_STATES = {"CONFIRMED", "CHECKED_IN"}


@bp.post("/boutique/appointments")
def book_appointment():
    h.require_role("Customer", "StoreManager")
    body = h.get_body()
    # existence (priority 3) — validate provided FKs left-to-right
    if body.get("customer_id") is not None:
        customer = h.lookup("customers", body["customer_id"])
    else:
        customer = None
    if body.get("fitter_id") is not None:
        h.lookup("fitters", body["fitter_id"])
    if body.get("room_id") is not None:
        h.lookup("rooms", body["room_id"])
    # ownership (priority 4)
    if customer is not None:
        h.owner_guard(customer["id"])
    # body validation (priority 5)
    h.require_fields(body, ["customer_id", "fitter_id", "room_id", "fitting_type",
                            "scheduled_start"])
    h.check_enum(body["fitting_type"], FITTING_TYPES, "fitting_type")
    start = store.parse_dt(body["scheduled_start"])
    if start is None:
        raise ApiError("ERR_VALIDATION", "scheduled_start must be an ISO-8601 instant")
    duration = body.get("duration_minutes", 30)
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 1:
        raise ApiError("ERR_VALIDATION", "duration_minutes must be a positive integer")
    rec = store.new_record({
        "customer_id": body["customer_id"],
        "fitter_id": body["fitter_id"],
        "room_id": body["room_id"],
        "fitting_type": body["fitting_type"],
        "scheduled_start": start,
        "duration_minutes": duration,
        "scheduled_end": start + timedelta(minutes=duration),
        "underbust_cm": None,
        "bust_cm": None,
        "fit_preference": "STANDARD",
        "recommended_band": None,
        "recommended_cup": None,
        "recommended_size": None,
        "status": "REQUESTED",
    })
    store.appointments[rec["id"]] = rec
    return h.success(s.appointment_out(rec), status=201)


@bp.get("/boutique/appointments/<aid>")
def get_appointment(aid):
    h.require_role("Customer", "Fitter", "StoreManager", "BillingClerk")
    rec = h.lookup("appointments", aid)
    if g.role == "Customer":
        h.owner_guard(rec["customer_id"])
    return h.success(s.appointment_out(rec))


@bp.get("/boutique/appointments")
def list_appointments():
    h.require_role("Customer", "Fitter", "StoreManager", "BillingClerk")
    customer_id = h.filter_arg("customer_id")
    fitter_id = h.filter_arg("fitter_id")
    room_id = h.filter_arg("room_id")
    status = h.filter_arg("status")

    def pred(r):
        if customer_id is not None and r["customer_id"] != customer_id:
            return False
        if fitter_id is not None and r["fitter_id"] != fitter_id:
            return False
        if room_id is not None and r["room_id"] != room_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    return h.list_response("appointments", s.appointment_out, pred)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    # half-open overlap: a.start < b.end and b.start < a.end
    return a_start < b_end and b_start < a_end


@bp.post("/boutique/appointments/<aid>/confirm")
def confirm_appointment(aid):
    h.require_role("Fitter")
    appt = h.lookup("appointments", aid)
    # state (priority 7)
    if appt["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    fitter = store.fitters.get(appt["fitter_id"])
    room = store.rooms.get(appt["room_id"])
    if fitter is None or not fitter["is_active"]:
        raise ApiError("ERR_INVALID_STATE", "Assigned fitter is not active")
    if room is None or not room["is_active"]:
        raise ApiError("ERR_INVALID_STATE", "Assigned room is not active")
    # business safety (priority 9)
    if appt["fitting_type"] in ("POST_SURGICAL", "MASTECTOMY"):
        if not fitter["post_surgical_certified"]:
            raise ApiError("ERR_FITTER_NOT_CERTIFIED")
        if not room["is_private"]:
            raise ApiError("ERR_ROOM_NOT_PRIVATE")
    # scheduling conflicts (priority 10)
    cand_start = appt["scheduled_start"]
    cand_end = appt["scheduled_end"]
    buf = timedelta(minutes=calc.FITTER_BUFFER_MIN)
    # fitter buffered double-booking
    for other in store.appointments.values():
        if other["id"] == appt["id"]:
            continue
        if other["fitter_id"] != appt["fitter_id"]:
            continue
        if other["status"] not in ACTIVE_SLOT_STATES:
            continue
        if _intervals_overlap(cand_start, cand_end + buf,
                              other["scheduled_start"], other["scheduled_end"] + buf):
            raise ApiError("ERR_FITTER_DOUBLE_BOOKED")
    # room aggregate capacity (no buffer)
    overlap_count = 0
    for other in store.appointments.values():
        if other["id"] == appt["id"]:
            continue
        if other["room_id"] != appt["room_id"]:
            continue
        if other["status"] not in ACTIVE_SLOT_STATES:
            continue
        if _intervals_overlap(cand_start, cand_end,
                              other["scheduled_start"], other["scheduled_end"]):
            overlap_count += 1
    if overlap_count >= room["capacity"]:
        raise ApiError("ERR_ROOM_AT_CAPACITY")

    appt["status"] = "CONFIRMED"
    store.touch(appt)
    return h.success(s.appointment_out(appt))


@bp.post("/boutique/appointments/<aid>/check-in")
def check_in_appointment(aid):
    h.require_role("Fitter")
    appt = h.lookup("appointments", aid)
    if appt["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    appt["status"] = "CHECKED_IN"
    store.touch(appt)
    return h.success(s.appointment_out(appt))


@bp.post("/boutique/appointments/<aid>/fit")
def fit_appointment(aid):
    h.require_role("Fitter")
    appt = h.lookup("appointments", aid)
    body = h.get_body()
    # body validation (priority 5)
    h.require_fields(body, ["underbust_cm", "bust_cm", "expected_appointment_version"])
    underbust = h.require_number(body, "underbust_cm")
    bust = h.require_number(body, "bust_cm")
    expected = h.require_int(body, "expected_appointment_version")
    pref = body.get("fit_preference", "STANDARD")
    if pref is None:
        pref = "STANDARD"
    h.check_enum(pref, FIT_PREFS, "fit_preference")
    # measurement range (priority 6)
    if not (calc.UNDERBUST_MIN_CM <= underbust <= calc.UNDERBUST_MAX_CM):
        raise ApiError("ERR_MEASUREMENT_OUT_OF_RANGE")
    if not (calc.BUST_MIN_CM <= bust <= calc.BUST_MAX_CM):
        raise ApiError("ERR_MEASUREMENT_OUT_OF_RANGE")
    try:
        band, cup, size = calc.bra_size(underbust, bust, pref)
    except calc.MeasurementOutOfRange:
        raise ApiError("ERR_MEASUREMENT_OUT_OF_RANGE")
    # state (priority 7)
    if appt["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE")
    # OCC (priority 8)
    if expected != appt["version"]:
        raise ApiError("ERR_STALE_APPOINTMENT_VERSION")
    # side effects: supersede recommendation, bump version
    appt["underbust_cm"] = underbust
    appt["bust_cm"] = bust
    appt["fit_preference"] = pref
    appt["recommended_band"] = band
    appt["recommended_cup"] = cup
    appt["recommended_size"] = size
    store.touch(appt)
    return h.success(s.appointment_out(appt))


@bp.post("/boutique/appointments/<aid>/complete")
def complete_appointment(aid):
    h.require_role("Fitter")
    appt = h.lookup("appointments", aid)
    if appt["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE")
    if appt["recommended_size"] is None:
        raise ApiError("ERR_FIT_NOT_SUBMITTED")
    appt["status"] = "COMPLETED"
    store.touch(appt)
    return h.success(s.appointment_out(appt))


@bp.post("/boutique/appointments/<aid>/reschedule")
def reschedule_appointment(aid):
    h.require_role("Customer", "StoreManager")
    appt = h.lookup("appointments", aid)
    h.owner_guard(appt["customer_id"])
    if appt["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    body = h.get_body()
    if body.get("scheduled_start") is not None:
        start = store.parse_dt(body["scheduled_start"])
        if start is None:
            raise ApiError("ERR_VALIDATION", "scheduled_start must be an ISO-8601 instant")
        appt["scheduled_start"] = start
        appt["scheduled_end"] = start + timedelta(minutes=appt["duration_minutes"])
    appt["status"] = "REQUESTED"
    store.touch(appt)
    return h.success(s.appointment_out(appt))


@bp.post("/boutique/appointments/<aid>/cancel")
def cancel_appointment(aid):
    h.require_role("Customer", "StoreManager")
    appt = h.lookup("appointments", aid)
    h.owner_guard(appt["customer_id"])
    if appt["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE")
    appt["status"] = "CANCELLED"
    store.touch(appt)
    return h.success(s.appointment_out(appt))
