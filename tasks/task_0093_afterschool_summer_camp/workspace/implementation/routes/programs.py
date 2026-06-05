"""Program and Session routes (PRD §3.1, §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_INVALID_AGE_RANGE,
    ERR_NO_SESSION_FOR_PUBLISH,
    ERR_PROGRAM_NOT_PUBLISHED,
)
from middleware import require_roles, ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import (
    make_record,
    serialize,
    serialize_list,
    sort_by_created,
    touch,
    audit,
    get_body,
    require_str,
    require_int,
    require_enum,
)
from services.lookups import get_program, get_session
from services.state_machines import cancel_session_cascade

bp = Blueprint("programs", __name__)


# ---------------------------------------------------------------------------
# Program
# ---------------------------------------------------------------------------
@bp.post("/programs")
def create_program():
    require_roles(ROLE_DIRECTOR)
    body = get_body()
    name = require_str(body, "name")
    program_type = require_enum(body, "program_type", {"AFTERSCHOOL", "CAMP"})
    min_age = require_int(body, "min_age", minimum=0)
    max_age = require_int(body, "max_age", minimum=0)
    if max_age < min_age:
        raise APIError(ERR_INVALID_AGE_RANGE, 400, "max_age must be >= min_age")

    rec = make_record(
        {
            "name": name,
            "program_type": program_type,
            "min_age": min_age,
            "max_age": max_age,
            "status": "DRAFT",
        }
    )
    db.programs[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/programs/<pid>")
def fetch_program(pid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING)
    rec = get_program(pid)
    return ok_object(serialize(rec), 200)


@bp.get("/programs/<pid>/sessions")
def list_program_sessions(pid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR)
    get_program(pid)
    limit, offset = paginate_params(request.args)
    items = [s for s in db.sessions.values() if s["program_id"] == pid]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/programs/<pid>/publish")
def publish_program(pid):
    caller = require_roles(ROLE_DIRECTOR)
    program = get_program(pid)
    if program["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Program is not DRAFT")
    # must hold >= 1 session in SCHEDULED or OPEN
    has_session = any(
        s["program_id"] == pid and s["status"] in ("SCHEDULED", "OPEN")
        for s in db.sessions.values()
    )
    if not has_session:
        raise APIError(ERR_NO_SESSION_FOR_PUBLISH, 409, "No SCHEDULED/OPEN session to publish")
    if program["min_age"] > program["max_age"]:
        raise APIError(ERR_INVALID_AGE_RANGE, 400, "Program age band incoherent")
    program["status"] = "PUBLISHED"
    touch(program)
    audit("Program", program["id"], "PROGRAM_PUBLISHED", caller.role)
    return ok_object(serialize(program), 200)


@bp.post("/programs/<pid>/archive")
def archive_program(pid):
    caller = require_roles(ROLE_DIRECTOR)
    program = get_program(pid)
    if program["status"] != "PUBLISHED":
        raise APIError(ERR_INVALID_STATE, 409, "Program is not PUBLISHED")
    has_open = any(
        s["program_id"] == pid and s["status"] == "OPEN" for s in db.sessions.values()
    )
    if has_open:
        raise APIError(ERR_INVALID_STATE, 409, "Cannot archive while a session is OPEN")
    program["status"] = "ARCHIVED"
    touch(program)
    audit("Program", program["id"], "PROGRAM_ARCHIVED", caller.role)
    return ok_object(serialize(program), 200)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
@bp.post("/sessions")
def create_session():
    require_roles(ROLE_DIRECTOR)
    body = get_body()
    program_id = require_str(body, "program_id")
    title = require_str(body, "title")
    age_group_min = require_int(body, "age_group_min", minimum=0)
    age_group_max = require_int(body, "age_group_max", minimum=0)
    age_as_of_date = require_str(body, "age_as_of_date")
    weekly_capacity = require_int(body, "weekly_capacity", minimum=1)
    base_weekly_tuition_cents = require_int(body, "base_weekly_tuition_cents", minimum=0)

    program = get_program(program_id)
    # session group must sit within the program band, and group itself coherent
    if (
        age_group_max < age_group_min
        or age_group_min < program["min_age"]
        or age_group_max > program["max_age"]
    ):
        raise APIError(ERR_INVALID_AGE_RANGE, 400, "Session age group outside program range")

    rec = make_record(
        {
            "program_id": program_id,
            "title": title,
            "age_group_min": age_group_min,
            "age_group_max": age_group_max,
            "age_as_of_date": age_as_of_date,
            "weekly_capacity": weekly_capacity,
            "base_weekly_tuition_cents": base_weekly_tuition_cents,
            "status": "SCHEDULED",
        }
    )
    db.sessions[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/sessions/<sid>")
def fetch_session(sid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING)
    rec = get_session(sid)
    return ok_object(serialize(rec), 200)


@bp.get("/sessions/<sid>/weekly-offerings")
def list_session_offerings(sid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR)
    get_session(sid)
    limit, offset = paginate_params(request.args)
    items = [w for w in db.weekly_offerings.values() if w["session_id"] == sid]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/sessions/<sid>/open")
def open_session(sid):
    caller = require_roles(ROLE_DIRECTOR)
    session = get_session(sid)
    if session["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Session is not SCHEDULED")
    program = db.programs[session["program_id"]]
    if program["status"] != "PUBLISHED":
        raise APIError(ERR_PROGRAM_NOT_PUBLISHED, 409, "Parent program is not PUBLISHED")
    has_offering = any(w["session_id"] == sid for w in db.weekly_offerings.values())
    if not has_offering:
        raise APIError(ERR_INVALID_STATE, 409, "Session has no weekly offering")
    session["status"] = "OPEN"
    touch(session)
    audit("Session", session["id"], "SESSION_OPENED", caller.role)
    return ok_object(serialize(session), 200)


@bp.post("/sessions/<sid>/close")
def close_session(sid):
    caller = require_roles(ROLE_DIRECTOR)
    session = get_session(sid)
    if session["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Session is not OPEN")
    session["status"] = "CLOSED"
    touch(session)
    audit("Session", session["id"], "SESSION_CLOSED", caller.role)
    return ok_object(serialize(session), 200)


@bp.post("/sessions/<sid>/cancel")
def cancel_session(sid):
    caller = require_roles(ROLE_DIRECTOR)
    session = get_session(sid)
    if session["status"] not in ("SCHEDULED", "OPEN"):
        raise APIError(ERR_INVALID_STATE, 409, "Session cannot be cancelled from its current state")
    cancel_session_cascade(session, caller.role)
    return ok_object(serialize(session), 200)
