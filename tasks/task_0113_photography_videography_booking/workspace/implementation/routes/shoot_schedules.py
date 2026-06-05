"""Shoot schedules: create, fetch, list, reschedule, complete (PRD §3.4, §3.7)
and second-shooter overlap rules (PRD §3.5)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_LEAD_PHOTOGRAPHER_BUSY,
    ERR_RESCHEDULE_LIMIT,
    ERR_SCHEDULE_CONFLICT,
    ERR_SHOOT_NOT_ENDED,
)
from middleware import (
    require_auth, ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN,
)
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_str, require_enum, serialize, serialize_list,
    parse_pagination, paginate, order_by_created_at,
)
from services import calculations as calc
from services.common import (
    stamp_create, touch, assignments_for_schedule,
)

bp = Blueprint("shoot_schedules", __name__)

MAX_RESCHEDULES = 3
TRAVEL_BUFFER_MINUTES = 60
RESCHEDULE_REASONS = {"WEATHER", "CLIENT_REQUEST", "PHOTOGRAPHER_REQUEST"}


def _overlap(a_start, a_end, b_start, b_end, buffer_seconds: float = 0.0) -> bool:
    """Half-open [start,end) intersection, optionally expanded by a buffer on
    each side of the candidate. Adjacency (end == start) does not overlap when
    buffer is 0."""
    a_s = calc.parse_iso(a_start).timestamp()
    a_e = calc.parse_iso(a_end).timestamp()
    b_s = calc.parse_iso(b_start).timestamp() - buffer_seconds
    b_e = calc.parse_iso(b_end).timestamp() + buffer_seconds
    return a_s < b_e and b_s < a_e


@bp.post("/studio/shoot-schedules")
def create_schedule():
    require_auth([ROLE_STUDIO_ADMIN, ROLE_PHOTOGRAPHER])
    body = get_body()
    booking_id = require_str(body, "booking_id")
    start_utc = require_str(body, "start_utc")
    end_utc = require_str(body, "end_utc")

    # Body FK existence (priority 5).
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise APIError(ERR_INVALID_REFERENCE, 422, "Booking does not exist")

    # Ownership (priority 4): a Photographer creator must be the lead on the booking.
    if g.user_role == ROLE_PHOTOGRAPHER and g.user_id != booking["lead_photographer_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller is not the lead photographer")

    # Shape validation: end strictly after start (priority 17).
    try:
        s = calc.parse_iso(start_utc)
        e = calc.parse_iso(end_utc)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 422, "start_utc/end_utc must be ISO-8601")
    if not (e > s):
        raise APIError(ERR_INVALID_REQUEST, 422, "end_utc must be strictly after start_utc")

    # Lead-photographer conflict: strict overlap with another non-terminal
    # schedule of the SAME lead photographer; adjacency allowed, no buffer.
    lead_id = booking["lead_photographer_id"]
    for other in db.shoot_schedules.values():
        if other["status"] not in ("SCHEDULED", "RESCHEDULED"):
            continue
        ob = db.bookings.get(other["booking_id"])
        if ob is None or ob["lead_photographer_id"] != lead_id:
            continue
        if _overlap(start_utc, end_utc, other["start_utc"], other["end_utc"]):
            raise APIError(ERR_LEAD_PHOTOGRAPHER_BUSY, 409,
                           "Lead photographer is busy in an overlapping window")

    sched = {
        "booking_id": booking_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "status": "SCHEDULED",
        "reschedule_reason": None,
        "reschedule_count": 0,
    }
    stamp_create(sched)
    db.shoot_schedules[sched["id"]] = sched
    return ok_object(serialize(sched), 201)


def _find_schedule_or_404(id):
    s = db.shoot_schedules.get(id)
    if s is None:
        raise APIError(ERR_NOT_FOUND, 404, "Shoot schedule not found")
    return s


def _assert_schedule_read_owner(sched):
    booking = db.bookings.get(sched["booking_id"])
    if g.user_role == ROLE_CLIENT and (booking is None or g.user_id != booking["client_id"]):
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this schedule")
    if g.user_role == ROLE_PHOTOGRAPHER and (booking is None or g.user_id != booking["lead_photographer_id"]):
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller is not the lead photographer")


@bp.get("/studio/shoot-schedules/<id>")
def get_schedule(id):
    require_auth([ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    s = _find_schedule_or_404(id)
    _assert_schedule_read_owner(s)
    return ok_object(serialize(s), 200)


@bp.get("/studio/shoot-schedules")
def list_schedules():
    require_auth([ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    limit, offset = parse_pagination()
    items = list(db.shoot_schedules.values())
    for field in ("booking_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s[field] == val]
    # Scope to owned bookings for entity-backed readers.
    if g.user_role == ROLE_CLIENT:
        owned = {b["id"] for b in db.bookings.values() if b["client_id"] == g.user_id}
        items = [s for s in items if s["booking_id"] in owned]
    elif g.user_role == ROLE_PHOTOGRAPHER:
        owned = {b["id"] for b in db.bookings.values() if b["lead_photographer_id"] == g.user_id}
        items = [s for s in items if s["booking_id"] in owned]
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/studio/shoot-schedules/<id>/reschedule")
def reschedule(id):
    require_auth([ROLE_STUDIO_ADMIN])
    sched = _find_schedule_or_404(id)
    body = get_body()
    new_start = require_str(body, "new_start_utc")
    new_end = require_str(body, "new_end_utc")
    reason = require_enum(body, "reason", RESCHEDULE_REASONS)

    booking = db.bookings.get(sched["booking_id"])

    # State legality (priority 6): schedule SCHEDULED/RESCHEDULED and booking CONFIRMED.
    if sched["status"] not in ("SCHEDULED", "RESCHEDULED"):
        raise APIError(ERR_INVALID_STATE, 409, "Schedule cannot be rescheduled")
    if booking is None or booking["workflow_status"] != "CONFIRMED":
        raise APIError(ERR_INVALID_STATE, 409, "Booking is not CONFIRMED")

    # Shape validation.
    try:
        ns = calc.parse_iso(new_start)
        ne = calc.parse_iso(new_end)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 422, "new_start_utc/new_end_utc must be ISO-8601")
    if not (ne > ns):
        raise APIError(ERR_INVALID_REQUEST, 422, "new_end_utc must be strictly after new_start_utc")

    # Reschedule limit (priority 12).
    if sched["reschedule_count"] >= MAX_RESCHEDULES:
        raise APIError(ERR_RESCHEDULE_LIMIT, 409, "Reschedule limit reached")

    # Schedule-conflict guard (priority 10): for each second shooter ASSIGNED
    # to THIS schedule, the new window must not overlap that same photographer's
    # other ASSIGNED assignment on a different schedule. Half-open, no buffer.
    this_assignments = [a for a in assignments_for_schedule(sched["id"])
                        if a["status"] == "ASSIGNED"]
    for a in this_assignments:
        photographer_id = a["photographer_id"]
        for other in db.second_shooter_assignments.values():
            if other["id"] == a["id"]:
                continue
            if other["status"] != "ASSIGNED":
                continue
            if other["photographer_id"] != photographer_id:
                continue
            if other["shoot_schedule_id"] == sched["id"]:
                continue
            other_sched = db.shoot_schedules.get(other["shoot_schedule_id"])
            if other_sched is None:
                continue
            if _overlap(new_start, new_end, other_sched["start_utc"], other_sched["end_utc"]):
                raise APIError(ERR_SCHEDULE_CONFLICT, 409,
                               "New window conflicts with a second shooter's other assignment")

    # Side effects: move window, set reason, bump count and version.
    sched["start_utc"] = new_start
    sched["end_utc"] = new_end
    sched["reschedule_reason"] = reason
    sched["reschedule_count"] += 1
    sched["status"] = "RESCHEDULED"
    touch(sched)
    return ok_object(serialize(sched), 200)


@bp.post("/studio/shoot-schedules/<id>/complete")
def complete_schedule(id):
    require_auth([ROLE_PHOTOGRAPHER])
    sched = _find_schedule_or_404(id)
    booking = db.bookings.get(sched["booking_id"])

    # Ownership (priority 4): caller must be the lead photographer.
    if booking is None or g.user_id != booking["lead_photographer_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller is not the lead photographer")

    # State legality (priority 6).
    if sched["status"] not in ("SCHEDULED", "RESCHEDULED"):
        raise APIError(ERR_INVALID_STATE, 409, "Schedule cannot be completed from its state")
    if booking["workflow_status"] != "CONFIRMED":
        raise APIError(ERR_INVALID_STATE, 409, "Booking is not CONFIRMED")
    if booking["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise APIError(ERR_INVALID_STATE, 409, "Booking deposit is not paid")

    # Shoot-end timing gate (priority 16).
    now = calc.parse_iso(db.get_clock_iso())
    end = calc.parse_iso(sched["end_utc"])
    if not (now >= end):
        raise APIError(ERR_SHOOT_NOT_ENDED, 409, "Shoot window has not ended")

    # Side effects: schedule -> COMPLETED, booking -> SHOT, versions bump.
    sched["status"] = "COMPLETED"
    touch(sched)
    booking["workflow_status"] = "SHOT"
    touch(booking)
    return ok_object(serialize(sched), 200)
