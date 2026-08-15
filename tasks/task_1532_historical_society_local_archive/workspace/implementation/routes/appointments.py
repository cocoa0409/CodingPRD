"""ReadingRoomAppointment routes (PRD §3.6) — half-open seat intervals,
whole-day item double-booking, no-show strikes with a rolling window."""

from __future__ import annotations

from datetime import datetime, time, timezone

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_REQUEST_NOT_APPROVED, ERR_RESEARCHER_SUSPENDED, ERR_ITEM_NOT_AVAILABLE,
    ERR_ITEM_TOO_FRAGILE, ERR_APPOINTMENT_IN_PAST, ERR_APPOINTMENT_NOT_ENDED,
    ERR_APPOINTMENT_CAPACITY_EXCEEDED, ERR_ITEM_DOUBLE_BOOKED,
    ERR_OWNERSHIP_MISMATCH, ERR_REQUEST_OWNERSHIP_MISMATCH,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from services.rollup import compute_no_show_strikes, STRIKE_SUSPEND_THRESHOLD
from util import (
    get_json_body, as_str, as_int, as_enum, parse_date_field, parse_time_field,
    paginate, public_view,
)

bp = Blueprint("appointments", __name__)

ROOM_CAPACITY = {"MAIN": 8, "MAP_ROOM": 4}
SEAT_HOLDING_STATES = ("CONFIRMED", "CHECKED_IN")


def serialize_appointment(a: dict) -> dict:
    return public_view(a)


def _get_appointment(aid: str) -> dict:
    a = db.appointments.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"ReadingRoomAppointment not found: {aid}")
    return a


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Half-open [start, end) overlap; touching bounds do not overlap."""
    return a_start < b_end and b_start < a_end


def _check_capacity(room_code, sched_date, start_min, end_min, seats, exclude_id=None):
    occupied = 0
    for ap in db.appointments.values():
        if ap["id"] == exclude_id:
            continue
        if ap["room_code"] != room_code or ap["_scheduled_date"] != sched_date:
            continue
        if ap["status"] not in SEAT_HOLDING_STATES:
            continue
        if _overlaps(start_min, end_min, ap["_start_min"], ap["_end_min"]):
            occupied += ap["seats"]
    if occupied + seats > ROOM_CAPACITY[room_code]:
        raise_err(ERR_APPOINTMENT_CAPACITY_EXCEEDED, "Overlapping seat total would exceed room capacity")


def _check_double_booking(item_ids, sched_date, exclude_id=None):
    candidate = set(item_ids)
    for ap in db.appointments.values():
        if ap["id"] == exclude_id:
            continue
        if ap["status"] != "CONFIRMED" or ap["_scheduled_date"] != sched_date:
            continue
        other = db.requests.get(ap["research_request_id"])
        if other is None:
            continue
        if candidate.intersection(other["item_ids"]):
            raise_err(ERR_ITEM_DOUBLE_BOOKED, "A request item is already booked on a CONFIRMED appointment that date")


@bp.route("/reading-room-appointments", methods=["POST"])
@require_roles("Researcher")
def create_appointment(_user_id: str, _role: str):
    body = get_json_body()
    # priority 3: shape
    research_request_id = as_str(body, "research_request_id", required=True)
    room_code = as_enum(body, "room_code", set(ROOM_CAPACITY), required=True)
    scheduled_date_raw = as_str(body, "scheduled_date", required=True)
    sched_date = parse_date_field(scheduled_date_raw, "scheduled_date")
    start_raw = as_str(body, "start_time", required=True)
    end_raw = as_str(body, "end_time", required=True)
    start_min = parse_time_field(start_raw, "start_time")
    end_min = parse_time_field(end_raw, "end_time")
    if start_min >= end_min:
        raise_err(ERR_INVALID_REQUEST, "start_time must be strictly before end_time")
    seats = as_int(body, "seats", required=False, default=1, minimum=1)

    # priority 4: existence — caller's researcher record, then the request
    researcher = db.researchers.get(_user_id)
    if researcher is None:
        raise_err(ERR_NOT_FOUND, f"Researcher not found: {_user_id}")
    req = db.requests.get(research_request_id)
    if req is None:
        raise_err(ERR_NOT_FOUND, f"ResearchRequest not found: {research_request_id}")

    # priority 7: cross-entity state gates
    if req["status"] != "APPROVED":
        raise_err(ERR_REQUEST_NOT_APPROVED, "The research request is not APPROVED")
    if researcher["status"] != "ACTIVE":
        raise_err(ERR_RESEARCHER_SUSPENDED, "The researcher is SUSPENDED")
    for iid in req["item_ids"]:
        item = db.items.get(iid)
        if item is not None and item["status"] != "AVAILABLE":
            raise_err(ERR_ITEM_NOT_AVAILABLE, f"Item is not AVAILABLE: {iid}")

    # priority 8: fragile items are never pulled to the reading room
    for iid in req["item_ids"]:
        item = db.items.get(iid)
        if item is not None and item["condition_grade"] == "FRAGILE":
            raise_err(ERR_ITEM_TOO_FRAGILE, f"Item is FRAGILE and cannot be pulled: {iid}")

    # priority 9: the start (scheduled_date at start_time, UTC) must be
    # strictly in the future of the logical clock
    start_dt = datetime.combine(sched_date, time(start_min // 60, start_min % 60), tzinfo=timezone.utc)
    if start_dt <= db.get_now():
        raise_err(ERR_APPOINTMENT_IN_PAST, "Appointment start is not strictly in the future")

    # priority 10: seat capacity, then whole-day item double-booking
    _check_capacity(room_code, sched_date, start_min, end_min, seats)
    _check_double_booking(req["item_ids"], sched_date)

    # priority 11: the caller may book only their own request
    if req["researcher_id"] != _user_id:
        raise_err(ERR_REQUEST_OWNERSHIP_MISMATCH, "The research request belongs to a different researcher")

    appt = {
        **db.make_common_fields(),
        "researcher_id": _user_id,
        "research_request_id": research_request_id,
        "room_code": room_code,
        "scheduled_date": scheduled_date_raw,
        "start_time": start_raw,
        "end_time": end_raw,
        "seats": seats,
        "status": "CONFIRMED",
        "_scheduled_date": sched_date,
        "_start_min": start_min,
        "_end_min": end_min,
    }
    db.appointments[appt["id"]] = appt
    return success_object(serialize_appointment(appt), 201)


@bp.route("/reading-room-appointments", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_appointments(_user_id: str, _role: str):
    researcher_id = request.args.get("researcher_id")
    request_id = request.args.get("research_request_id")
    sched_date = request.args.get("scheduled_date")
    room_code = request.args.get("room_code")
    status = request.args.get("status")
    rows = list(db.appointments.values())
    if researcher_id is not None:
        rows = [a for a in rows if a["researcher_id"] == researcher_id]
    if request_id is not None:
        rows = [a for a in rows if a["research_request_id"] == request_id]
    if sched_date is not None:
        rows = [a for a in rows if a["scheduled_date"] == sched_date]
    if room_code is not None:
        rows = [a for a in rows if a["room_code"] == room_code]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([serialize_appointment(a) for a in page], limit, offset, total)


@bp.route("/reading-room-appointments/<aid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_appointment(aid: str, _user_id: str, _role: str):
    return success_object(serialize_appointment(_get_appointment(aid)))


@bp.route("/reading-room-appointments/<aid>/check-in", methods=["POST"])
@require_roles("ReadingRoomStaff")
def check_in(aid: str, _user_id: str, _role: str):
    ap = _get_appointment(aid)
    if ap["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Only a CONFIRMED appointment may be checked in")
    ap["status"] = "CHECKED_IN"
    db.touch(ap)
    return success_object(serialize_appointment(ap))


@bp.route("/reading-room-appointments/<aid>/complete", methods=["POST"])
@require_roles("ReadingRoomStaff")
def complete(aid: str, _user_id: str, _role: str):
    ap = _get_appointment(aid)
    if ap["status"] != "CHECKED_IN":
        raise_err(ERR_INVALID_STATE, "Only a CHECKED_IN appointment may be completed")
    ap["status"] = "COMPLETED"
    db.touch(ap)
    return success_object(serialize_appointment(ap))


@bp.route("/reading-room-appointments/<aid>/record-no-show", methods=["POST"])
@require_roles("ReadingRoomStaff")
def record_no_show(aid: str, _user_id: str, _role: str):
    ap = _get_appointment(aid)
    if ap["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Only a CONFIRMED appointment may be recorded as a no-show")
    end_dt = datetime.combine(ap["_scheduled_date"], time(ap["_end_min"] // 60, ap["_end_min"] % 60), tzinfo=timezone.utc)
    if db.get_now() < end_dt:
        raise_err(ERR_APPOINTMENT_NOT_ENDED, "The appointment has not ended yet")

    ap["status"] = "NO_SHOW"
    db.touch(ap)

    researcher = db.researchers.get(ap["researcher_id"])
    if researcher is not None:
        strikes = compute_no_show_strikes(researcher["id"])
        if strikes >= STRIKE_SUSPEND_THRESHOLD and researcher["status"] == "ACTIVE":
            researcher["status"] = "SUSPENDED"
            db.touch(researcher)
            # cascade: cancel the researcher's future-dated CONFIRMED appointments
            today = db.get_now().date()
            for other in db.appointments.values():
                if (
                    other["researcher_id"] == researcher["id"]
                    and other["status"] == "CONFIRMED"
                    and other["_scheduled_date"] >= today
                ):
                    other["status"] = "CANCELLED"
                    db.touch(other)
    return success_object(serialize_appointment(ap))


@bp.route("/reading-room-appointments/<aid>/cancel", methods=["POST"])
@require_roles("Researcher")
def cancel(aid: str, _user_id: str, _role: str):
    ap = _get_appointment(aid)
    if ap["status"] not in ("CONFIRMED", "NEEDS_RESCHEDULE"):
        raise_err(ERR_INVALID_STATE, "Only a CONFIRMED or NEEDS_RESCHEDULE appointment may be cancelled")
    if ap["researcher_id"] != _user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Only the owning researcher may cancel the appointment")
    ap["status"] = "CANCELLED"
    db.touch(ap)
    return success_object(serialize_appointment(ap))


@bp.route("/reading-room-appointments/<aid>/reschedule", methods=["POST"])
@require_roles("Researcher")
def reschedule(aid: str, _user_id: str, _role: str):
    body = get_json_body()
    # priority 3: shape
    scheduled_date_raw = as_str(body, "scheduled_date", required=True)
    sched_date = parse_date_field(scheduled_date_raw, "scheduled_date")
    start_raw = as_str(body, "start_time", required=True)
    end_raw = as_str(body, "end_time", required=True)
    start_min = parse_time_field(start_raw, "start_time")
    end_min = parse_time_field(end_raw, "end_time")
    if start_min >= end_min:
        raise_err(ERR_INVALID_REQUEST, "start_time must be strictly before end_time")

    ap = _get_appointment(aid)

    # priority 5
    if ap["status"] != "NEEDS_RESCHEDULE":
        raise_err(ERR_INVALID_STATE, "Only a NEEDS_RESCHEDULE appointment may be rescheduled")

    req = db.requests.get(ap["research_request_id"])
    if req is None:
        raise_err(ERR_NOT_FOUND, f"ResearchRequest not found: {ap['research_request_id']}")

    # priority 7: every item on the underlying request must be AVAILABLE now
    for iid in req["item_ids"]:
        item = db.items.get(iid)
        if item is not None and item["status"] != "AVAILABLE":
            raise_err(ERR_ITEM_NOT_AVAILABLE, f"Item is not AVAILABLE: {iid}")

    # priority 9: future start
    start_dt = datetime.combine(sched_date, time(start_min // 60, start_min % 60), tzinfo=timezone.utc)
    if start_dt <= db.get_now():
        raise_err(ERR_APPOINTMENT_IN_PAST, "Appointment start is not strictly in the future")

    # priority 10: capacity + double-booking with the new interval
    _check_capacity(ap["room_code"], sched_date, start_min, end_min, ap["seats"], exclude_id=ap["id"])
    _check_double_booking(req["item_ids"], sched_date, exclude_id=ap["id"])

    # priority 11: ownership
    if ap["researcher_id"] != _user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Only the owning researcher may reschedule the appointment")

    ap["scheduled_date"] = scheduled_date_raw
    ap["start_time"] = start_raw
    ap["end_time"] = end_raw
    ap["_scheduled_date"] = sched_date
    ap["_start_min"] = start_min
    ap["_end_min"] = end_min
    ap["status"] = "CONFIRMED"
    db.touch(ap)
    return success_object(serialize_appointment(ap))
