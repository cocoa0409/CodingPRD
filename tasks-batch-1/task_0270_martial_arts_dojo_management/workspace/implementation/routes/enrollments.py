"""Enrollments + test-eligibility read (PRD §3.4, §3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST,
)
from middleware import (
    get_identity, require_roles, ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER,
)
from response import success
from common import (
    get_json_body, require_fields, parse_pagination, paginate, sort_by_created,
)
from services.serialize import view, view_list
from services.access import require_version_field, check_occ
from services import domain

bp = Blueprint("enrollments", __name__)
ALL_ROLES = [ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER]


@bp.post("/dojo/enrollments")
def create_enrollment():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    body = get_json_body()
    require_fields(body, ["member_id", "program_id"])

    # FK existence (priority 4)
    member = db.members.get(body["member_id"])
    if member is None:
        raise err(ERR_FK_NOT_FOUND, "member_id references a non-existent member.")
    program = db.programs.get(body["program_id"])
    if program is None:
        raise err(ERR_FK_NOT_FOUND, "program_id references a non-existent program.")

    # version field present (priority 5) then OCC match (priority 7)
    supplied = require_version_field(body, "expected_member_version")
    check_occ(supplied, member["version"])

    entry = domain.entry_rank_for_program(body["program_id"])
    if entry is None:
        raise err(ERR_INVALID_REQUEST, "Program has no entry rank defined.")

    now = db.now_iso()
    eid = db.new_id()
    enrollment = {
        "id": eid,
        "member_id": body["member_id"],
        "program_id": body["program_id"],
        "current_rank_code": entry["code"],
        "rank_attendance_count": 0,
        "rank_acquired_at": now,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.enrollments[eid] = enrollment
    return success(view(enrollment), 201)


@bp.get("/dojo/enrollments/<eid>")
def get_enrollment(eid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    enr = db.enrollments.get(eid)
    if enr is None:
        raise err(ERR_NOT_FOUND, "Enrollment not found.")
    return success(view(enr), 200)


@bp.get("/dojo/enrollments")
def list_enrollments():
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = []
    for e in db.enrollments.values():
        if member_id is not None and e["member_id"] != member_id:
            continue
        if program_id is not None and e["program_id"] != program_id:
            continue
        if status is not None and e["status"] != status:
            continue
        items.append(e)
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.get("/dojo/enrollments/<eid>/test-eligibility")
def test_eligibility(eid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    enr = db.enrollments.get(eid)
    if enr is None:
        raise err(ERR_NOT_FOUND, "Enrollment not found.")
    eligible, readiness, failed = domain.test_eligibility(enr)
    return success({
        "eligible": eligible,
        "readiness": readiness,
        "failed_gates": failed,
    }, 200)
