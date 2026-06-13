"""Attendances: check-in + cancel with rank-count compensation (PRD §3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_WAIVER_NOT_SIGNED,
    ERR_MEMBER_NOT_ACTIVE, ERR_PROGRAM_MISMATCH, ERR_CLASS_FULL,
    ERR_ALREADY_CHECKED_IN, ERR_INVALID_STATE,
)
from middleware import (
    get_identity, require_roles, ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER,
)
from response import success
from common import (
    get_json_body, require_fields, parse_pagination, paginate, sort_by_created,
)
from services.serialize import view, view_list
from services import domain

bp = Blueprint("attendances", __name__)
ALL_ROLES = [ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER]


@bp.post("/dojo/attendances")
def create_attendance():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    body = get_json_body()
    require_fields(body, ["enrollment_id", "class_session_id"])

    # FK existence (priority 4)
    enrollment = db.enrollments.get(body["enrollment_id"])
    if enrollment is None:
        raise err(ERR_FK_NOT_FOUND, "enrollment_id references a non-existent enrollment.")
    session = db.class_sessions.get(body["class_session_id"])
    if session is None:
        raise err(ERR_FK_NOT_FOUND, "class_session_id references a non-existent class session.")

    member = db.members.get(enrollment["member_id"])

    # Member ownership: a Member caller may only check in their own enrollment.
    if role == ROLE_MEMBER and enrollment["member_id"] != user_id:
        from errors import ERR_UNAUTHORIZED
        raise err(ERR_UNAUTHORIZED, "Member may only check into their own enrollment.")

    # waiver gate (priority 9)
    if not member["waiver_signed"]:
        raise err(ERR_WAIVER_NOT_SIGNED, "Member waiver not signed.")
    # member-active gate (priority 10)
    if member["account_status"] != "ACTIVE":
        raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE.")
    # program-mismatch gate (priority 16)
    if enrollment["program_id"] != session["program_id"]:
        raise err(ERR_PROGRAM_MISMATCH, "Enrollment program does not match class session program.")
    # already-checked-in (priority 18) — checked before capacity so a duplicate
    # is reported as such regardless of remaining capacity? Per priority order
    # class-full (17) precedes already-checked-in (18); evaluate in priority order.
    # class-full gate (priority 17)
    if session["confirmed_count"] + 1 > session["capacity"]:
        raise err(ERR_CLASS_FULL, "Class session is at capacity.")
    # already-checked-in gate (priority 18)
    for att in db.attendances.values():
        if (att["class_session_id"] == body["class_session_id"]
                and att["status"] == "CONFIRMED"
                and att["enrollment_id"] == body["enrollment_id"]):
            raise err(ERR_ALREADY_CHECKED_IN, "Member already has a CONFIRMED attendance for this session.")
    # Also block a duplicate by the same member across enrollments? Spec ties
    # "a member" to the session; a member could only reach a session via an
    # enrollment, and same-session duplicate is the enrollment row above.

    counts = bool(member["account_status"] == "ACTIVE" and member["waiver_signed"])
    now = db.now_iso()
    aid = db.new_id()
    attendance = {
        "id": aid,
        "enrollment_id": body["enrollment_id"],
        "class_session_id": body["class_session_id"],
        "status": "CONFIRMED",
        "counts_toward_rank": counts,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.attendances[aid] = attendance
    session["confirmed_count"] = session["confirmed_count"] + 1
    domain.touch(session)
    if counts:
        enrollment["rank_attendance_count"] = enrollment["rank_attendance_count"] + 1
        domain.touch(enrollment)
    return success(view(attendance), 201)


@bp.get("/dojo/attendances/<aid>")
def get_attendance(aid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    att = db.attendances.get(aid)
    if att is None:
        raise err(ERR_NOT_FOUND, "Attendance not found.")
    return success(view(att), 200)


@bp.get("/dojo/attendances")
def list_attendances():
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    class_session_id = request.args.get("class_session_id")
    status = request.args.get("status")
    items = []
    for a in db.attendances.values():
        if enrollment_id is not None and a["enrollment_id"] != enrollment_id:
            continue
        if class_session_id is not None and a["class_session_id"] != class_session_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(a)
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.post("/dojo/attendances/<aid>/cancel")
def cancel_attendance(aid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    att = db.attendances.get(aid)
    if att is None:
        raise err(ERR_NOT_FOUND, "Attendance not found.")
    session = db.class_sessions.get(att["class_session_id"])
    # available while attendance CONFIRMED and owning session SCHEDULED
    if att["status"] != "CONFIRMED" or session is None or session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Attendance not cancellable in its current state.")
    att["status"] = "CANCELLED"
    domain.touch(att)
    session["confirmed_count"] = max(0, session["confirmed_count"] - 1)
    domain.touch(session)
    if att.get("counts_toward_rank"):
        enr = db.enrollments.get(att["enrollment_id"])
        if enr is not None:
            enr["rank_attendance_count"] = max(0, enr["rank_attendance_count"] - 1)
            domain.touch(enr)
    return success(view(att), 200)
