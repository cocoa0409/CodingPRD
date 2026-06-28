"""Session endpoints and lifecycle (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, public, fmt_ts
import errors
import helpers
from middleware import get_auth, require_role, get_body
from response import success
from clock import clock
from services import session_ops

bp = Blueprint("sessions", __name__)

READ_ROLES = {"FranchiseAdmin", "CenterDirector", "Instructor", "Parent"}
INSTRUCTOR_BUFFER_MINUTES = 30


@bp.route("/sessions", methods=["POST"])
def create_session():
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    body = get_body()

    center_id = helpers.require_str(body, "center_id")
    instructor_user_id = helpers.require_str(body, "instructor_user_id")
    start_at_raw = helpers.require_str(body, "start_at")
    end_at_raw = helpers.require_str(body, "end_at")
    seat_cap = helpers.require_int(body, "seat_cap", minimum=1)

    center = db.centers.get(center_id)
    if not center:
        raise errors.not_found()

    start_at = helpers.parse_iso8601(start_at_raw)
    end_at = helpers.parse_iso8601(end_at_raw)
    if start_at is None or end_at is None:
        raise errors.invalid_request("start_at and end_at must be ISO 8601 instants.")
    if end_at <= start_at:
        raise errors.invalid_request("end_at must be strictly after start_at.")

    # priority 7: seat_cap must not exceed center instructor_ratio_cap.
    if seat_cap > center["instructor_ratio_cap"]:
        raise errors.ratio_exceeded()

    # priority 9: instructor double-booking with 30-min buffer. The new
    # session's interval is expanded by the buffer on each side; an overlap with
    # the UNEXPANDED interval of any non-CANCELLED session of the same
    # instructor at the same center is a conflict (closed/adjacency conflict).
    buf = timedelta(minutes=INSTRUCTOR_BUFFER_MINUTES)
    new_lo = start_at - buf
    new_hi = end_at + buf
    for s in db.sessions.values():
        if s["center_id"] != center_id:
            continue
        if s["instructor_user_id"] != instructor_user_id:
            continue
        if s["status"] == "CANCELLED":
            continue
        ex_start = helpers.parse_iso8601(s["start_at"])
        ex_end = helpers.parse_iso8601(s["end_at"])
        if ex_start is None or ex_end is None:
            continue
        # closed-interval overlap: buffered new interval vs unexpanded existing.
        if new_lo <= ex_end and ex_start <= new_hi:
            raise errors.instructor_double_booked()

    obj = {
        "center_id": center_id,
        "instructor_user_id": instructor_user_id,
        "start_at": start_at_raw,
        "end_at": end_at_raw,
        "seat_cap": seat_cap,
        "booked_seat_count": 0,
        "status": "SCHEDULED",
    }
    db.stamp_create(obj)
    db.sessions[obj["id"]] = obj
    return success(public(obj), status=201)


@bp.route("/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    s = db.sessions.get(session_id)
    if not s:
        raise errors.not_found()
    return success(public(s))


@bp.route("/sessions", methods=["GET"])
def list_sessions():
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    args = request.args
    items = list(db.sessions.values())
    for key in ("center_id", "status"):
        val = args.get(key)
        if val:
            items = [s for s in items if s.get(key) == val]
    return helpers.paginate_and_respond(items)


@bp.route("/sessions/<session_id>/open", methods=["POST"])
def open_session(session_id):
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    s = db.sessions.get(session_id)
    if not s:
        raise errors.not_found()
    if s["status"] != "SCHEDULED":
        raise errors.invalid_state()
    center = db.centers.get(s["center_id"])
    if not center or center["status"] != "OPERATING":
        raise errors.center_not_operating()
    s["status"] = "OPEN"
    db.touch(s)
    return success(public(s))


@bp.route("/sessions/<session_id>/close", methods=["POST"])
def close_session(session_id):
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    s = db.sessions.get(session_id)
    if not s:
        raise errors.not_found()
    if s["status"] != "OPEN":
        raise errors.invalid_state()
    start_at = helpers.parse_iso8601(s["start_at"])
    if start_at is None or clock.now() < start_at:
        raise errors.session_not_started()
    s["status"] = "CLOSED"
    db.touch(s)
    # every BOOKED record -> ABSENT, marked_at = clock now
    now_ts = fmt_ts(clock.now())
    for rec in db.attendance.values():
        if rec["session_id"] == session_id and rec["status"] == "BOOKED":
            rec["status"] = "ABSENT"
            rec["marked_at"] = now_ts
            db.touch(rec)
    session_ops.recompute_booked_seat_count(s)
    return success(public(s))


@bp.route("/sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    s = db.sessions.get(session_id)
    if not s:
        raise errors.not_found()
    if s["status"] not in ("SCHEDULED", "OPEN"):
        raise errors.invalid_state()
    session_ops.cancel_session_cascade(s)
    return success(public(s))
