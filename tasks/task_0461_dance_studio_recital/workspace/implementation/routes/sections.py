"""ClassSection / ClassSession routes (PRD 3.2)."""
from flask import Blueprint, request

from db import common_fields, db, new_id, touch
from errors import err
from helpers import (DISCIPLINES, LEVELS, lookup, paginate, require_enum,
                     require_fields, require_int, sort_by_created)
from middleware import authenticate, get_json
from response import success
from services.enrollment import cancel_section_cascade
from views import public, public_list

bp = Blueprint("sections", __name__)


@bp.route("/sections", methods=["POST"])
def create_section():
    authenticate({"StudioAdmin"})
    body = get_json()
    require_fields(body, ["term_id", "room_id", "instructor_id", "discipline",
                          "required_level", "min_age", "max_age",
                          "monthly_tuition_cents", "capacity_cap"])
    term = lookup(db.terms, body["term_id"])
    room = lookup(db.rooms, body["room_id"])
    inst = lookup(db.instructors, body["instructor_id"])
    discipline = require_enum(body, "discipline", DISCIPLINES)
    required_level = require_enum(body, "required_level", set(LEVELS))
    min_age = require_int(body, "min_age", lo=0)
    max_age = require_int(body, "max_age", lo=0)
    if max_age < min_age:
        raise err("ERR_INVALID_REQUEST", "max_age must be >= min_age.")
    tuition = require_int(body, "monthly_tuition_cents", lo=0)
    cap = require_int(body, "capacity_cap", lo=1)
    sec = {
        "id": new_id(),
        "term_id": term["id"],
        "room_id": room["id"],
        "instructor_id": inst["id"],
        "discipline": discipline,
        "required_level": required_level,
        "min_age": min_age,
        "max_age": max_age,
        "monthly_tuition_cents": tuition,
        "capacity_cap": cap,
        "enrolled_count": 0,
        "status": "PLANNED",
        **common_fields(),
    }
    db.sections[sec["id"]] = sec
    return success(public(sec), status=201)


@bp.route("/sections/<sid>", methods=["GET"])
def get_section(sid):
    authenticate({"StudioAdmin", "Parent", "Instructor"})
    sec = lookup(db.sections, sid)
    return success(public(sec), status=200)


@bp.route("/sections", methods=["GET"])
def list_sections():
    authenticate({"StudioAdmin", "Parent", "Instructor"})
    items = list(db.sections.values())
    for key in ("term_id", "room_id", "instructor_id"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s[key] == val]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.route("/sections/<sid>/sessions", methods=["POST"])
def add_session(sid):
    authenticate({"StudioAdmin"})
    sec = lookup(db.sections, sid)
    body = get_json()
    require_fields(body, ["day_of_week", "start_minute", "end_minute"])
    dow = require_int(body, "day_of_week", lo=0, hi=6)
    start = require_int(body, "start_minute", lo=0, hi=1439)
    end = require_int(body, "end_minute", lo=1, hi=1440)
    if end <= start:
        raise err("ERR_INVALID_REQUEST", "end_minute must be greater than start_minute.")

    room = db.rooms.get(sec["room_id"])
    buffer = room["turnover_buffer_minutes"] if room else 0

    # Priority 9: room conflict (buffered windows, same room, same day).
    for other in db.sessions.values():
        osec = db.sections.get(other["section_id"])
        if osec is None or osec["room_id"] != sec["room_id"]:
            continue
        if other["day_of_week"] != dow:
            continue
        if _overlaps(start, end + buffer, other["start_minute"], other["end_minute"] + buffer):
            raise err("ERR_ROOM_CONFLICT", "Session room-conflicts in this room.")

    # Priority 10: instructor time conflict (plain windows, same instructor, same day).
    for other in db.sessions.values():
        osec = db.sections.get(other["section_id"])
        if osec is None or osec["instructor_id"] != sec["instructor_id"]:
            continue
        if other["day_of_week"] != dow:
            continue
        if _overlaps(start, end, other["start_minute"], other["end_minute"]):
            raise err("ERR_INSTRUCTOR_CONFLICT", "Session instructor-conflicts.")

    # Priority 11: instructor weekly-session cap.
    inst = db.instructors.get(sec["instructor_id"])
    if inst is not None:
        current = sum(
            1 for s in db.sessions.values()
            if db.sections.get(s["section_id"]) is not None
            and db.sections[s["section_id"]]["instructor_id"] == inst["id"]
        )
        if current + 1 > inst["max_weekly_sessions"]:
            raise err("ERR_INSTRUCTOR_OVERLOADED",
                      "Assignment exceeds instructor max_weekly_sessions.")

    sess = {
        "id": new_id(),
        "section_id": sec["id"],
        "day_of_week": dow,
        "start_minute": start,
        "end_minute": end,
        **common_fields(),
    }
    db.sessions[sess["id"]] = sess

    # First session moves PLANNED -> SCHEDULED.
    if sec["status"] == "PLANNED":
        sec["status"] = "SCHEDULED"
        touch(sec)

    return success(public(sess), status=201)


@bp.route("/sections/<sid>/sessions", methods=["GET"])
def list_sessions(sid):
    authenticate({"StudioAdmin", "Parent", "Instructor"})
    sec = lookup(db.sections, sid)
    items = [s for s in db.sessions.values() if s["section_id"] == sec["id"]]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/sections/<sid>/cancel", methods=["POST"])
def cancel_section(sid):
    authenticate({"StudioAdmin"})
    sec = lookup(db.sections, sid)
    # PRD 3.2: "Cancellation is permitted from PLANNED, SCHEDULED, or OPEN."
    if sec["status"] not in {"PLANNED", "SCHEDULED", "OPEN"}:
        raise err("ERR_INVALID_STATE", "Section cannot be cancelled.")
    # A cancel from a PLANNED section requires no confirmed enrollments.
    if sec["status"] == "PLANNED":
        confirmed = any(
            e["section_id"] == sec["id"] and e["placement_status"] == "CONFIRMED"
            for e in db.enrollments.values()
        )
        if confirmed:
            raise err("ERR_INVALID_STATE",
                      "Planned section with confirmed enrollments cannot be cancelled.")
    cancel_section_cascade(sec)
    sec["status"] = "CANCELLED"
    touch(sec)
    return success(public(sec), status=200)


# --------------------------------------------------------------------------
# Sessions (top-level fetch)
# --------------------------------------------------------------------------
@bp.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    authenticate({"StudioAdmin", "Parent", "Instructor"})
    sess = lookup(db.sessions, sid)
    return success(public(sess), status=200)
