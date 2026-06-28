"""ClassSession endpoints (PRD §3.2, §3.4)."""
from flask import Blueprint, request

from clock import clock
from constants import (
    ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR, DEFAULT_WAITLIST_CAPACITY,
)
from db import db, stamp_new
from errors import (
    err, ERR_VALIDATION, ERR_SCHEDULE_CONFLICT, ERR_INVALID_STATE, ERR_WINDOW_CLOSED,
)
from middleware import require_auth, require_role
from response import success_object, success_array
from serializers import session_out
from services import lookup, validate, paging, booking

bp = Blueprint("sessions", __name__)

READ_ROLES = {ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: intervals overlap iff start < other_end and
    other_start < end (touching endpoints do not overlap)."""
    return a_start < b_end and b_start < a_end


@bp.route("/studios/<studio_id>/sessions", methods=["POST"])
def create_session(studio_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    studio = lookup.get_studio(studio_id)
    body = validate.get_body()
    room_id = validate.require_str(body, "room_id")
    instructor_id = validate.require_str(body, "instructor_id")
    start_utc = validate.require_iso(body, "start_utc")
    end_utc = validate.require_iso(body, "end_utc")
    waitlist_capacity = validate.opt_int(body, "waitlist_capacity", DEFAULT_WAITLIST_CAPACITY, minimum=0)

    if end_utc <= start_utc:
        raise err(ERR_VALIDATION, "end_utc must be strictly after start_utc")

    # Existence + scope: room must belong to studio; instructor must exist.
    room = lookup.get_room_in_studio(studio_id, room_id)
    lookup.get_instructor(instructor_id)

    # Capacity snapshot: count of ACTIVE bikes in the room at this instant; >= 1.
    capacity = sum(
        1 for b in db.bikes.values()
        if b["room_id"] == room_id and b["status"] == "ACTIVE"
    )
    if capacity < 1:
        raise err(ERR_VALIDATION, "Room has no ACTIVE bikes; capacity must be >= 1")

    # Schedule conflict: instructor or room committed to an overlapping SCHEDULED
    # session (PRD §3.2).
    for s in db.sessions.values():
        if s["status"] != "SCHEDULED":
            continue
        if s["room_id"] == room_id or s["instructor_id"] == instructor_id:
            if _overlaps(start_utc, end_utc, s["start_utc"], s["end_utc"]):
                raise err(ERR_SCHEDULE_CONFLICT, "Instructor or room double-booked")

    rec = {
        "studio_id": studio_id,
        "room_id": room_id,
        "instructor_id": instructor_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "capacity": capacity,
        "waitlist_capacity": waitlist_capacity,
        "status": "SCHEDULED",
    }
    stamp_new(rec)
    db.sessions[rec["id"]] = rec
    return success_object(session_out(rec), 201)


@bp.route("/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    rec = lookup.get_session(session_id)
    return success_object(session_out(rec), 200)


@bp.route("/sessions", methods=["GET"])
def list_sessions():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = paging.get_pagination()
    studio_id = request.args.get("studio_id")
    room_id = request.args.get("room_id")
    instructor_id = request.args.get("instructor_id")
    records = []
    for s in db.sessions.values():
        if studio_id is not None and s["studio_id"] != studio_id:
            continue
        if room_id is not None and s["room_id"] != room_id:
            continue
        if instructor_id is not None and s["instructor_id"] != instructor_id:
            continue
        records.append(s)
    records = paging.sort_default(records)
    page, total = paging.apply_page(records, limit, offset)
    return success_array([session_out(s) for s in page], limit, offset, total)


@bp.route("/studios/<studio_id>/sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(studio_id, session_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    session = lookup.get_session_in_studio(studio_id, session_id)
    # State precondition then timing window.
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED")
    if clock.now() >= session["start_utc"]:
        raise err(ERR_WINDOW_CLOSED, "Cannot cancel a session at or after its start")
    booking.cancel_session(session)
    return success_object(session_out(session), 200)


@bp.route("/studios/<studio_id>/sessions/<session_id>/complete", methods=["POST"])
def complete_session(studio_id, session_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    session = lookup.get_session_in_studio(studio_id, session_id)
    studio = db.studios[session["studio_id"]]
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED")
    if clock.now() < session["end_utc"]:
        raise err(ERR_WINDOW_CLOSED, "Cannot complete a session before its end")
    booking.complete_session(session, studio)
    return success_object(session_out(session), 200)
