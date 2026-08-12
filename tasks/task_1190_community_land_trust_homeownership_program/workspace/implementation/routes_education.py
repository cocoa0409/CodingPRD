"""EducationCourse endpoints."""
from flask import Blueprint, jsonify

import db
from auth import ALL_ROLES, require
from errors import ApiError, ERR_INVALID_STATE
from scope import get_course_or_404, get_program_or_404
from util import (
    body, new_entity, ok_object, opt_bool, opt_int, paginated, query_bool,
    query_str, req_int, req_str, ser_course,
)

bp = Blueprint("education", __name__)


@bp.post("/programs/<pid>/education-courses")
@require(["ProgramAdmin"])
def create_course(pid):
    get_program_or_404(pid)
    data = body()
    code = req_str(data, "code")
    title = req_str(data, "title")
    credit_hours = req_int(data, "credit_hours")
    is_required = opt_bool(data, "is_required", True)
    validity_months = opt_int(data, "validity_months", 24)

    c = new_entity()
    c.update({
        "program_id": pid,
        "code": code,
        "title": title,
        "credit_hours": credit_hours,
        "is_required": is_required,
        "validity_months": validity_months,
        "status": "OFFERED",
    })
    db.store.courses[c["id"]] = c
    return jsonify(ok_object(ser_course(c))), 201


@bp.get("/programs/<pid>/education-courses")
@require(ALL_ROLES)
def list_courses(pid):
    get_program_or_404(pid)
    items = [c for c in db.store.courses.values() if c["program_id"] == pid]
    is_required = query_bool("is_required")
    if is_required is not None:
        items = [c for c in items if c["is_required"] == is_required]
    status = query_str("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return jsonify(paginated(items, ser_course)), 200


@bp.get("/programs/<pid>/education-courses/<cid>")
@require(ALL_ROLES)
def get_course(pid, cid):
    return jsonify(ok_object(ser_course(get_course_or_404(pid, cid)))), 200


@bp.post("/programs/<pid>/education-courses/<cid>/retire")
@require(["ProgramAdmin"])
def retire_course(pid, cid):
    c = get_course_or_404(pid, cid)
    if c["status"] != "OFFERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OFFERED course can be retired")
    c["status"] = "RETIRED"
    from util import bump
    bump(c)
    return jsonify(ok_object(ser_course(c))), 200
