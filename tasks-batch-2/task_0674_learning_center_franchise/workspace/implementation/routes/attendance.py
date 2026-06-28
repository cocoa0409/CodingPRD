"""AttendanceRecord endpoints and lifecycle (PRD §3.5, §2.7)."""
from flask import Blueprint, request

from db import db, public, fmt_ts
import errors
import helpers
from middleware import get_auth, require_role, get_body
from response import success
from clock import clock
from services import session_ops

bp = Blueprint("attendance", __name__)

READ_ROLES = {"FranchiseAdmin", "CenterDirector", "Instructor", "Parent"}


def _parent_owns_enrollment(uid, enrollment_id):
    fam = helpers.family_id_of_enrollment(enrollment_id)
    return helpers.parent_owns_family(uid, fam)


@bp.route("/attendance-records", methods=["POST"])
def book_seat():
    uid, role = get_auth()
    require_role(role, {"CenterDirector", "Parent"})
    body = get_body()

    session_id = helpers.require_str(body, "session_id")
    enrollment_id = helpers.require_str(body, "enrollment_id")
    expected_session_version = helpers.require_int(body, "expected_session_version", minimum=0)

    # existence (priority 3)
    session = db.sessions.get(session_id)
    if not session:
        raise errors.not_found()
    enr = db.enrollments.get(enrollment_id)
    if not enr:
        raise errors.not_found()

    # ownership scope: Parent may only book own enrollments (priority 2 family scope)
    if role == "Parent" and not _parent_owns_enrollment(uid, enrollment_id):
        raise errors.forbidden()

    # OCC (priority 5): expected_session_version must match session.version
    if expected_session_version != session["version"]:
        raise errors.stale_version()

    # state guard (priority 6): session must be bookable (SCHEDULED or OPEN).
    if session["status"] not in ("SCHEDULED", "OPEN"):
        raise errors.invalid_state()

    # ratio / seat capacity (priority 7): booking must not push booked_seat_count
    # above seat_cap.
    if session["booked_seat_count"] + 1 > session["seat_cap"]:
        raise errors.ratio_exceeded()

    # per-enrollment session overlap (priority 8): the enrollment may not hold
    # two BOOKED/PRESENT records at the same center on overlapping half-open
    # intervals [start_at, end_at). Touching (end==start) is allowed.
    new_start = helpers.parse_iso8601(session["start_at"])
    new_end = helpers.parse_iso8601(session["end_at"])
    for rec in db.attendance.values():
        if rec["enrollment_id"] != enrollment_id:
            continue
        if rec["status"] not in ("BOOKED", "PRESENT"):
            continue
        other = db.sessions.get(rec["session_id"])
        if not other or other["center_id"] != session["center_id"]:
            continue
        o_start = helpers.parse_iso8601(other["start_at"])
        o_end = helpers.parse_iso8601(other["end_at"])
        if None in (new_start, new_end, o_start, o_end):
            continue
        # half-open overlap: max(starts) < min(ends)
        if max(new_start, o_start) < min(new_end, o_end):
            raise errors.session_overlap()

    obj = {
        "session_id": session_id,
        "enrollment_id": enrollment_id,
        "status": "BOOKED",
        "marked_at": None,
    }
    db.stamp_create(obj)
    db.attendance[obj["id"]] = obj

    # increment booked_seat_count and session version
    session["booked_seat_count"] += 1
    db.touch(session)
    return success(public(obj), status=201)


@bp.route("/attendance-records/<record_id>", methods=["GET"])
def get_record(record_id):
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    rec = db.attendance.get(record_id)
    if not rec:
        raise errors.not_found()
    if role == "Parent" and not _parent_owns_enrollment(uid, rec["enrollment_id"]):
        raise errors.forbidden()
    return success(public(rec))


@bp.route("/attendance-records", methods=["GET"])
def list_records():
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    args = request.args
    items = list(db.attendance.values())
    for key in ("session_id", "enrollment_id", "status"):
        val = args.get(key)
        if val:
            items = [r for r in items if r.get(key) == val]
    if role == "Parent":
        items = [r for r in items if _parent_owns_enrollment(uid, r["enrollment_id"])]
    return helpers.paginate_and_respond(items)


@bp.route("/attendance-records/<record_id>/check-in", methods=["POST"])
def check_in(record_id):
    _uid, role = get_auth()
    require_role(role, {"Instructor"})
    rec = db.attendance.get(record_id)
    if not rec:
        raise errors.not_found()
    if rec["status"] != "BOOKED":
        raise errors.invalid_state()
    session = db.sessions.get(rec["session_id"])
    if not session or session["status"] != "OPEN":
        raise errors.session_not_open()
    rec["status"] = "PRESENT"
    rec["marked_at"] = fmt_ts(clock.now())
    db.touch(rec)
    return success(public(rec))


@bp.route("/attendance-records/<record_id>/mark-absent", methods=["POST"])
def mark_absent(record_id):
    _uid, role = get_auth()
    require_role(role, {"Instructor"})
    rec = db.attendance.get(record_id)
    if not rec:
        raise errors.not_found()
    if rec["status"] != "BOOKED":
        raise errors.invalid_state()
    session = db.sessions.get(rec["session_id"])
    # permitted while parent session is OPEN or CLOSED
    if not session or session["status"] not in ("OPEN", "CLOSED"):
        raise errors.invalid_state()
    rec["status"] = "ABSENT"
    rec["marked_at"] = fmt_ts(clock.now())
    db.touch(rec)
    session_ops.recompute_booked_seat_count(session)
    return success(public(rec))


@bp.route("/attendance-records/<record_id>/cancel", methods=["POST"])
def cancel_record(record_id):
    uid, role = get_auth()
    require_role(role, {"CenterDirector", "Parent"})
    rec = db.attendance.get(record_id)
    if not rec:
        raise errors.not_found()
    if role == "Parent" and not _parent_owns_enrollment(uid, rec["enrollment_id"]):
        raise errors.forbidden()
    if rec["status"] != "BOOKED":
        raise errors.invalid_state()
    rec["status"] = "CANCELLED"
    db.touch(rec)
    session = db.sessions.get(rec["session_id"])
    if session:
        session_ops.recompute_booked_seat_count(session)
    return success(public(rec))
