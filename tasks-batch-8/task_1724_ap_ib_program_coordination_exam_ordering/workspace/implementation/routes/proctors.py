"""ProctorAssignment endpoints (PRD 3.5): subject-conflict ban + 30-minute buffer."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DUPLICATE_PROCTOR,
    ERR_INVALID_STATE,
    ERR_PROCTOR_OVERLAP,
    ERR_PROCTOR_SUBJECT_CONFLICT,
)
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch
from services.serialize import serialize_proctor_assignment
from validate import (
    get_body, reject_unknown_fields, req_str, require_path_resource, require_ref,
)

bp = Blueprint("proctor_assignments", __name__)

PROCTOR_BUFFER = timedelta(minutes=30)


@bp.post("/proctor-assignments")
def create_proctor_assignment():
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"session_id", "teacher_id"})
    session_id = req_str(body, "session_id")
    teacher_id = req_str(body, "teacher_id")
    session = require_ref("exam_sessions", session_id, "session_id")
    teacher = require_ref("teachers", teacher_id, "teacher_id")
    # Priority 6 state: the session must still be SCHEDULED.
    if session["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"session in {session['status']} cannot accept proctor assignments")
    # Priority 7 safety: conflict of interest — the proctor must not hold an
    # AUTHORIZED authorization for the session's own course.
    for ta in db["teacher_authorizations"].values():
        if (ta["teacher_id"] == teacher["id"] and ta["course_id"] == session["course_id"]
                and ta["status"] == "AUTHORIZED"):
            raise_error(ERR_PROCTOR_SUBJECT_CONFLICT,
                        "teacher holds an AUTHORIZED authorization for the session's course")
    # Priority 8 temporal: 30-minute buffered overlap against the teacher's other
    # ASSIGNED assignments (the target session itself excluded). Gap >= 30 min is allowed.
    for pa in db["proctor_assignments"].values():
        if (pa["teacher_id"] == teacher["id"] and pa["status"] == "ASSIGNED"
                and pa["session_id"] != session["id"]):
            other = db["exam_sessions"].get(pa["session_id"])
            if other is None:
                continue
            separation = max(session["start_at"] - other["end_at"],
                             other["start_at"] - session["end_at"])
            if separation < PROCTOR_BUFFER:
                raise_error(ERR_PROCTOR_OVERLAP,
                            "teacher has another assignment whose session window is "
                            "separated by less than 30 minutes")
    # Priority 9 uniqueness: one ASSIGNED row per (session, teacher).
    for pa in db["proctor_assignments"].values():
        if (pa["session_id"] == session["id"] and pa["teacher_id"] == teacher["id"]
                and pa["status"] == "ASSIGNED"):
            raise_error(ERR_DUPLICATE_PROCTOR,
                        "teacher already has an ASSIGNED assignment on this session")
    rec = new_record("proctor_assignments", {
        "session_id": session["id"],
        "teacher_id": teacher["id"],
        "status": "ASSIGNED",
    })
    return success_object(serialize_proctor_assignment(rec), status=201)


@bp.get("/proctor-assignments")
def list_proctor_assignments():
    require_roles(get_caller(), ["ApCoordinator", "Teacher"])
    filters = [
        ("session_id", request.args.get("session_id")),
        ("teacher_id", request.args.get("teacher_id")),
        ("status", request.args.get("status")),
    ]
    return list_response(db["proctor_assignments"].values(), filters,
                         serialize_proctor_assignment)


@bp.get("/proctor-assignments/<rid>")
def get_proctor_assignment(rid):
    require_roles(get_caller(), ["ApCoordinator", "Teacher"])
    pa = require_path_resource("proctor_assignments", rid)
    return success_object(serialize_proctor_assignment(pa))


@bp.post("/proctor-assignments/<rid>/release")
def release_proctor_assignment(rid):
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    pa = require_path_resource("proctor_assignments", rid)
    if pa["status"] != "ASSIGNED":
        raise_error(ERR_INVALID_STATE,
                    f"assignment in {pa['status']} cannot be released")
    pa["status"] = "RELEASED"
    touch(pa)
    return success_object(serialize_proctor_assignment(pa))
