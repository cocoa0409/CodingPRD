"""TeacherAuthorization endpoints (PRD 3.2): the training/authorization loop."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DUPLICATE_AUTHORIZATION,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
)
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch
from services.serialize import serialize_teacher_authorization
from util import CLOCK, VALIDITY_DAYS
from validate import (
    get_body, reject_unknown_fields, req_str, require_path_resource, require_ref,
)

bp = Blueprint("teacher_authorizations", __name__)


@bp.post("/teacher-authorizations")
def create_authorization():
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"teacher_id", "course_id"})
    teacher_id = req_str(body, "teacher_id")
    course_id = req_str(body, "course_id")
    teacher = require_ref("teachers", teacher_id, "teacher_id")
    course = require_ref("courses", course_id, "course_id")
    # At most one row per (teacher, course) ever — even an EXPIRED row counts.
    for ta in db["teacher_authorizations"].values():
        if ta["teacher_id"] == teacher["id"] and ta["course_id"] == course["id"]:
            raise_error(ERR_DUPLICATE_AUTHORIZATION,
                        "a TeacherAuthorization already exists for this teacher and course")
    rec = new_record("teacher_authorizations", {
        "teacher_id": teacher["id"],
        "course_id": course["id"],
        "status": "PENDING_TRAINING",
        "training_completed_at": None,
        "authorized_until": None,
    })
    return success_object(serialize_teacher_authorization(rec), status=201)


@bp.get("/teacher-authorizations")
def list_authorizations():
    require_roles(get_caller(), ["ApCoordinator", "Teacher"])
    filters = [
        ("teacher_id", request.args.get("teacher_id")),
        ("course_id", request.args.get("course_id")),
        ("status", request.args.get("status")),
    ]
    return list_response(db["teacher_authorizations"].values(), filters,
                         serialize_teacher_authorization)


@bp.get("/teacher-authorizations/<rid>")
def get_authorization(rid):
    require_roles(get_caller(), ["ApCoordinator", "Teacher"])
    ta = require_path_resource("teacher_authorizations", rid)
    return success_object(serialize_teacher_authorization(ta))


@bp.post("/teacher-authorizations/<rid>/complete-training")
def complete_training(rid):
    """PENDING_TRAINING or EXPIRED -> AUTHORIZED; only the record's teacher may attest."""
    caller = require_roles(get_caller(), ["Teacher"])
    body = get_body()
    reject_unknown_fields(body, set())
    ta = require_path_resource("teacher_authorizations", rid)
    if ta["teacher_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN,
                    "only the teacher on the record may attest completed training")
    if ta["status"] not in ("PENDING_TRAINING", "EXPIRED"):
        raise_error(ERR_INVALID_STATE,
                    f"authorization in {ta['status']} cannot complete training")
    now = CLOCK.now()
    ta["status"] = "AUTHORIZED"
    ta["training_completed_at"] = now
    ta["authorized_until"] = now + timedelta(days=VALIDITY_DAYS)
    touch(ta)
    return success_object(serialize_teacher_authorization(ta))
