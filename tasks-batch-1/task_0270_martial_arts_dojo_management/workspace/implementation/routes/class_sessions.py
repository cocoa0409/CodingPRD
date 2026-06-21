"""Class sessions (PRD §3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_VALIDATION, ERR_INSTRUCTOR_DOUBLE_BOOKED, ERR_INVALID_STATE,
)
from middleware import (
    get_identity, require_roles, ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER,
)
from response import success
from common import (
    get_json_body, require_fields, require_int, parse_pagination, paginate,
    sort_by_created, parse_iso8601,
)
from services.serialize import view, view_list
from services.access import require_version_field, check_occ
from services import domain

bp = Blueprint("class_sessions", __name__)
ALL_ROLES = [ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER]


@bp.post("/dojo/class-sessions")
def create_class_session():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_INSTRUCTOR])
    body = get_json_body()
    require_fields(body, ["program_id", "instructor_id", "starts_at", "ends_at", "capacity"])

    # FK existence (priority 4)
    if body["program_id"] not in db.programs:
        raise err(ERR_FK_NOT_FOUND, "program_id references a non-existent program.")
    if body["instructor_id"] not in db.instructors:
        raise err(ERR_FK_NOT_FOUND, "instructor_id references a non-existent instructor.")

    # structural validity (priority 5): types/ranges
    starts_at = parse_iso8601(body["starts_at"])
    ends_at = parse_iso8601(body["ends_at"])
    require_int(body["capacity"], "capacity", minimum=1)

    # interval well-formedness (priority 14, ERR_VALIDATION)
    if not (ends_at > starts_at):
        raise err(ERR_VALIDATION, "ends_at must be strictly after starts_at.")

    # instructor double-booking (priority 15, ERR_INSTRUCTOR_DOUBLE_BOOKED)
    if domain.instructor_has_overlap(body["instructor_id"], body["starts_at"], body["ends_at"]):
        raise err(ERR_INSTRUCTOR_DOUBLE_BOOKED, "Instructor is double-booked for this interval.")

    now = db.now_iso()
    sid = db.new_id()
    session = {
        "id": sid,
        "program_id": body["program_id"],
        "instructor_id": body["instructor_id"],
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "capacity": body["capacity"],
        "confirmed_count": 0,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.class_sessions[sid] = session
    return success(view(session), 201)


@bp.get("/dojo/class-sessions/<sid>")
def get_class_session(sid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    session = db.class_sessions.get(sid)
    if session is None:
        raise err(ERR_NOT_FOUND, "Class session not found.")
    return success(view(session), 200)


@bp.get("/dojo/class-sessions")
def list_class_sessions():
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    program_id = request.args.get("program_id")
    instructor_id = request.args.get("instructor_id")
    status = request.args.get("status")
    items = []
    for s in db.class_sessions.values():
        if program_id is not None and s["program_id"] != program_id:
            continue
        if instructor_id is not None and s["instructor_id"] != instructor_id:
            continue
        if status is not None and s["status"] != status:
            continue
        items.append(s)
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.post("/dojo/class-sessions/<sid>/cancel")
def cancel_class_session(sid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_INSTRUCTOR])
    session = db.class_sessions.get(sid)
    if session is None:
        raise err(ERR_NOT_FOUND, "Class session not found.")
    body = get_json_body()
    supplied = require_version_field(body, "expected_class_session_version")
    check_occ(supplied, session["version"])
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Class session not in SCHEDULED state.")

    session["status"] = "CANCELLED"
    # compensation sweep over CONFIRMED attendances
    for att in db.attendances.values():
        if att["class_session_id"] == sid and att["status"] == "CONFIRMED":
            att["status"] = "CANCELLED"
            domain.touch(att)
            if att.get("counts_toward_rank"):
                enr = db.enrollments.get(att["enrollment_id"])
                if enr is not None:
                    enr["rank_attendance_count"] = max(0, enr["rank_attendance_count"] - 1)
                    domain.touch(enr)
    session["confirmed_count"] = 0
    domain.touch(session)  # version bump
    return success(view(session), 200)


@bp.post("/dojo/class-sessions/<sid>/complete")
def complete_class_session(sid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_INSTRUCTOR])
    session = db.class_sessions.get(sid)
    if session is None:
        raise err(ERR_NOT_FOUND, "Class session not found.")
    body = get_json_body()
    supplied = require_version_field(body, "expected_class_session_version")
    check_occ(supplied, session["version"])
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Class session not in SCHEDULED state.")
    session["status"] = "COMPLETED"
    domain.touch(session)
    return success(view(session), 200)
