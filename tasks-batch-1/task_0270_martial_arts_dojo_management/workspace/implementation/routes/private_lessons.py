"""Private lessons: request, confirm, complete, cancel (PRD §3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_VALIDATION,
    ERR_MEMBER_NOT_ACTIVE, ERR_INSTRUCTOR_DOUBLE_BOOKED, ERR_INVALID_STATE,
    ERR_UNAUTHORIZED,
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
from services import domain

bp = Blueprint("private_lessons", __name__)
ALL_ROLES = [ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER]


@bp.post("/dojo/private-lessons")
def request_lesson():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    body = get_json_body()
    require_fields(body, ["member_id", "instructor_id", "starts_at", "ends_at", "hourly_rate_cents"])

    # FK existence (priority 4)
    member = db.members.get(body["member_id"])
    if member is None:
        raise err(ERR_FK_NOT_FOUND, "member_id references a non-existent member.")
    instructor = db.instructors.get(body["instructor_id"])
    if instructor is None:
        raise err(ERR_FK_NOT_FOUND, "instructor_id references a non-existent instructor.")

    # Member ownership
    if role == ROLE_MEMBER and body["member_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Member may only book their own private lessons.")

    # structural validity (priority 5)
    starts_at = parse_iso8601(body["starts_at"])
    ends_at = parse_iso8601(body["ends_at"])
    require_int(body["hourly_rate_cents"], "hourly_rate_cents", minimum=0)

    # member-active gate (priority 10)
    if member["account_status"] != "ACTIVE":
        raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE.")

    # interval well-formedness (priority 14, ERR_VALIDATION)
    if not (ends_at > starts_at):
        raise err(ERR_VALIDATION, "ends_at must be strictly after starts_at.")

    now = db.now_iso()
    pid = db.new_id()
    lesson = {
        "id": pid,
        "member_id": body["member_id"],
        "instructor_id": body["instructor_id"],
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "hourly_rate_cents": body["hourly_rate_cents"],
        "status": "REQUESTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.private_lessons[pid] = lesson
    return success(view(lesson), 201)


@bp.get("/dojo/private-lessons/<pid>")
def get_lesson(pid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    lesson = db.private_lessons.get(pid)
    if lesson is None:
        raise err(ERR_NOT_FOUND, "Private lesson not found.")
    return success(view(lesson), 200)


@bp.get("/dojo/private-lessons")
def list_lessons():
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    instructor_id = request.args.get("instructor_id")
    status = request.args.get("status")
    items = []
    for l in db.private_lessons.values():
        if member_id is not None and l["member_id"] != member_id:
            continue
        if instructor_id is not None and l["instructor_id"] != instructor_id:
            continue
        if status is not None and l["status"] != status:
            continue
        items.append(l)
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.post("/dojo/private-lessons/<pid>/confirm")
def confirm_lesson(pid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_INSTRUCTOR])
    lesson = db.private_lessons.get(pid)
    if lesson is None:
        raise err(ERR_NOT_FOUND, "Private lesson not found.")
    if lesson["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Private lesson not in REQUESTED state.")
    instructor = db.instructors.get(lesson["instructor_id"])
    if instructor is None or not instructor["is_available"]:
        raise err(ERR_INVALID_STATE, "Instructor is not available.")
    # overlap check (priority 15, ERR_INSTRUCTOR_DOUBLE_BOOKED)
    if domain.instructor_has_overlap(lesson["instructor_id"], lesson["starts_at"],
                                     lesson["ends_at"], exclude_lesson_id=pid):
        raise err(ERR_INSTRUCTOR_DOUBLE_BOOKED, "Instructor is double-booked for this interval.")
    lesson["status"] = "CONFIRMED"
    domain.touch(lesson)
    return success(view(lesson), 200)


@bp.post("/dojo/private-lessons/<pid>/complete")
def complete_lesson(pid):
    _, role = get_identity()
    require_roles(role, [ROLE_INSTRUCTOR])
    lesson = db.private_lessons.get(pid)
    if lesson is None:
        raise err(ERR_NOT_FOUND, "Private lesson not found.")
    if lesson["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Private lesson not in CONFIRMED state.")
    lesson["status"] = "COMPLETED"
    domain.touch(lesson)
    amount = domain.private_lesson_amount(lesson["hourly_rate_cents"],
                                          lesson["starts_at"], lesson["ends_at"])
    domain.make_invoice(lesson["member_id"], "PRIVATE_LESSON", amount, contract_id=None)
    domain.recompute_member_balance(lesson["member_id"])
    return success(view(lesson), 200)


@bp.post("/dojo/private-lessons/<pid>/cancel")
def cancel_lesson(pid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_MEMBER, ROLE_FRONTDESK])
    lesson = db.private_lessons.get(pid)
    if lesson is None:
        raise err(ERR_NOT_FOUND, "Private lesson not found.")
    if role == ROLE_MEMBER and lesson["member_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Member may only cancel their own private lessons.")
    if lesson["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "Private lesson not cancellable in its current state.")
    lesson["status"] = "CANCELLED"
    domain.touch(lesson)
    return success(view(lesson), 200)
