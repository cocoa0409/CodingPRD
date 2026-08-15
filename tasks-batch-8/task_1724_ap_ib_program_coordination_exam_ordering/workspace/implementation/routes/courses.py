"""Course endpoints (PRD 3.2). Status is derived; courses may be created in SETUP."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, require_roles
from response import success_list, success_object
from routes.helpers import get_pagination
from services.core import new_record
from services.derived import course_status
from services.serialize import serialize_course
from validate import (
    get_body, reject_unknown_fields, req_enum, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("courses", __name__)

ALL_READ = ["ApCoordinator", "Registrar", "Teacher", "Student"]
COURSE_FIELDS = {"cycle_id", "subject_code", "program", "exam_fee_cents", "credit_threshold"}


@bp.post("/courses")
def create_course():
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, COURSE_FIELDS)
    cycle_id = req_str(body, "cycle_id")
    subject_code = req_str(body, "subject_code")
    program = req_enum(body, "program", ("AP", "IB"))
    exam_fee_cents = req_int(body, "exam_fee_cents", positive=True)
    credit_threshold = req_int(body, "credit_threshold")
    hi = 5 if program == "AP" else 7
    if credit_threshold < 1 or credit_threshold > hi:
        raise_error(ERR_INVALID_REQUEST,
                    f"credit_threshold must be within 1..{hi} for program {program}")
    cycle = require_ref("exam_cycles", cycle_id, "cycle_id")
    rec = new_record("courses", {
        "cycle_id": cycle["id"],
        "subject_code": subject_code,
        "program": program,
        "exam_fee_cents": exam_fee_cents,
        "credit_threshold": credit_threshold,
    })
    return success_object(serialize_course(rec), status=201)


@bp.get("/courses")
def list_courses():
    require_roles(get_caller(), ALL_READ)
    items = list(db["courses"].values())
    for field, value in (
        ("cycle_id", request.args.get("cycle_id")),
        ("subject_code", request.args.get("subject_code")),
        ("program", request.args.get("program")),
    ):
        if value is not None:
            items = [c for c in items if c.get(field) == value]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [c for c in items if course_status(c["id"]) == status_filter]
    items.sort(key=lambda r: r["_seq"])
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_course(c) for c in page], len(items), limit, offset)


@bp.get("/courses/<rid>")
def get_course(rid):
    require_roles(get_caller(), ALL_READ)
    course = require_path_resource("courses", rid)
    return success_object(serialize_course(course))
