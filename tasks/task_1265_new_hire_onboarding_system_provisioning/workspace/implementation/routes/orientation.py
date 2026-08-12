"""OrientationSession endpoints (PRD §3.6)."""

from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from db import store
from errors import (ApiError, ERR_SESSION_NOT_FOUND, ERR_CASE_NOT_FOUND,
                    ERR_SESSION_NOT_BOOKABLE, ERR_SESSION_ROOM_OVERLAP,
                    ERR_NO_BOOKING_TO_CANCEL)
from helpers import (new_record, touch, get_or_404, ser_session, ser_case,
                     sort_created, session_booked_count)
from sweep import refresh_health, reeval_day_one_gate
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_int, as_bool, as_dt, bad, fmt_dt)

bp = Blueprint("orientation", __name__)

SESSION_STATUSES = ("SCHEDULED", "FULL", "CONDUCTED", "CANCELLED")


@bp.post("/api/orientation-sessions")
def create_session():
    require_roles("HRAdmin")
    body = get_body()
    room = as_str(req_present(body, "room"), "room")
    starts = as_dt(req_present(body, "starts_at"), "starts_at")
    ends = as_dt(req_present(body, "ends_at"), "ends_at")
    capacity = as_int(req_present(body, "capacity"), "capacity")
    if capacity < 1:
        bad("capacity must be >= 1")
    if ends <= starts:
        bad("ends_at must be strictly later than starts_at")
    # Stage 9: half-open [starts_at, ends_at) room-overlap per room,
    # ignoring CANCELLED sessions
    for s in store["sessions"].values():
        if s["room"] != room or s["status"] == "CANCELLED":
            continue
        if starts < s["_ends_dt"] and ends > s["_starts_dt"]:
            raise ApiError(ERR_SESSION_ROOM_OVERLAP, 409,
                           "Session overlaps an existing session in this room")
    rec = new_record("sessions", {
        "room": room,
        "starts_at": fmt_dt(starts),
        "ends_at": fmt_dt(ends),
        "capacity": capacity,
        "status": "SCHEDULED",
        "_starts_dt": starts,
        "_ends_dt": ends,
    })
    return success(ser_session(rec), 201)


@bp.get("/api/orientation-sessions")
def list_sessions():
    require_roles(*ALL_ROLES)
    limit, offset = page_params()
    q = request.args
    records = list(store["sessions"].values())
    if "room" in q and q.get("room") is not None:
        records = [s for s in records if s["room"] == q["room"]]
    if "status" in q and q.get("status") is not None:
        if q["status"] not in SESSION_STATUSES:
            bad(f"status must be one of {sorted(SESSION_STATUSES)}")
        records = [s for s in records if s["status"] == q["status"]]
    records = sort_created(records)
    return paged([ser_session(s) for s in records], limit, offset)


@bp.post("/api/orientation-sessions/<sid>/cancel")
def cancel_session(sid):
    require_roles("HRAdmin")
    get_body()
    session = get_or_404("sessions", sid, ERR_SESSION_NOT_FOUND,
                         "OrientationSession")
    if session["status"] not in ("SCHEDULED", "FULL"):
        raise ApiError(ERR_SESSION_NOT_BOOKABLE, 409,
                       "Only a SCHEDULED or FULL session can be cancelled")
    session["status"] = "CANCELLED"
    touch(session)
    # Booked cases flip to SESSION_CANCELLED; the seat is released; a
    # DAY_ONE_READY case reverts to PROVISIONING.
    for case in list(store["cases"].values()):
        if case.get("orientation_session_id") == sid and \
                case.get("orientation_rsvp") == "BOOKED":
            case["orientation_rsvp"] = "SESSION_CANCELLED"
            case["orientation_session_id"] = None
            touch(case)
            reeval_day_one_gate(case)
    return success(ser_session(session))


@bp.post("/api/orientation-sessions/<sid>/attendance")
def mark_attendance(sid):
    require_roles("HRAdmin")
    body = get_body()
    case_id = as_str(req_present(body, "case_id"), "case_id")
    attended = as_bool(req_present(body, "attended"), "attended")
    session = get_or_404("sessions", sid, ERR_SESSION_NOT_FOUND,
                         "OrientationSession")
    case = get_or_404("cases", case_id, ERR_CASE_NOT_FOUND, "OnboardingCase")
    if case.get("orientation_session_id") != session["id"] or \
            case.get("orientation_rsvp") not in ("BOOKED", "ATTENDED",
                                                 "NO_SHOW"):
        raise ApiError(ERR_NO_BOOKING_TO_CANCEL, 409,
                       "Case holds no attendance-markable booking on this "
                       "session")
    case["orientation_rsvp"] = "ATTENDED" if attended else "NO_SHOW"
    touch(case)
    refresh_health(case)
    return success(ser_case(case))
