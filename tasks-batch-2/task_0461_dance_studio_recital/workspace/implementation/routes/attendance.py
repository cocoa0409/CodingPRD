"""Attendance routes (PRD 3.5). Attendance is append-only: id + created_at only."""
from flask import Blueprint

from db import db, new_id, now_iso
from errors import err
from helpers import (ATTENDANCE_RESULTS, lookup, paginate, parse_date,
                     require_enum, require_fields, sort_by_created)
from middleware import authenticate, get_json, require_owner
from response import success
from views import public, public_list

bp = Blueprint("attendance", __name__)


def _recompute_makeup_eligible(att):
    att["makeup_eligible"] = (att["result"] == "ABSENT_EXCUSED"
                              and not att["makeup_consumed"])


@bp.route("/enrollments/<eid>/attendance", methods=["POST"])
def mark_attendance(eid):
    authenticate({"StudioAdmin", "Instructor"})
    enr = lookup(db.enrollments, eid)
    body = get_json()
    require_fields(body, ["session_id", "occurred_on", "result"])
    session = lookup(db.sessions, body["session_id"])
    result = require_enum(body, "result", ATTENDANCE_RESULTS)
    occurred = parse_date(body, "occurred_on")

    # occurred_on must fall on the session's day_of_week and inside the section's
    # term window.
    section = db.sections.get(session["section_id"])
    if section is None:
        raise err("ERR_NOT_FOUND", "Session references a missing section.")
    # Python weekday(): Monday=0 .. Sunday=6, matching day_of_week.
    if occurred.weekday() != session["day_of_week"]:
        raise err("ERR_INVALID_REQUEST", "occurred_on is not on the session's day_of_week.")
    term = db.terms.get(section["term_id"])
    if term is not None:
        t_start = parse_date(term, "start_date")
        t_end = parse_date(term, "end_date")
        if not (t_start <= occurred <= t_end):
            raise err("ERR_INVALID_REQUEST", "occurred_on is outside the term window.")

    att = {
        "id": new_id(),
        "enrollment_id": enr["id"],
        "session_id": session["id"],
        "occurred_on": body["occurred_on"],
        "result": result,
        "makeup_eligible": False,
        "makeup_consumed": False,
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    _recompute_makeup_eligible(att)
    db.attendance[att["id"]] = att
    return success(public(att), status=201)


@bp.route("/enrollments/<eid>/attendance", methods=["GET"])
def list_enrollment_attendance(eid):
    user_id, role = authenticate({"StudioAdmin", "Instructor", "Parent"})
    enr = lookup(db.enrollments, eid)
    require_owner(role, user_id, enr["family_id"])
    items = [a for a in db.attendance.values() if a["enrollment_id"] == enr["id"]]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/attendance/<aid>", methods=["GET"])
def get_attendance(aid):
    user_id, role = authenticate({"StudioAdmin", "Instructor", "Parent"})
    att = lookup(db.attendance, aid)
    enr = db.enrollments.get(att["enrollment_id"])
    if enr is not None:
        require_owner(role, user_id, enr["family_id"])
    return success(public(att), status=200)


@bp.route("/attendance/<aid>/amend", methods=["POST"])
def amend_attendance(aid):
    authenticate({"StudioAdmin", "Instructor"})
    att = lookup(db.attendance, aid)
    body = get_json()
    require_fields(body, ["result"])
    result = require_enum(body, "result", ATTENDANCE_RESULTS)
    att["result"] = result
    _recompute_makeup_eligible(att)
    return success(public(att), status=200)


@bp.route("/sessions/<sid>/attendance", methods=["GET"])
def list_session_attendance(sid):
    authenticate({"StudioAdmin", "Instructor"})
    session = lookup(db.sessions, sid)
    items = [a for a in db.attendance.values() if a["session_id"] == session["id"]]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)
