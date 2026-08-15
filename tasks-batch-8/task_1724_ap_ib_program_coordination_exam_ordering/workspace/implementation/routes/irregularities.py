"""IrregularityReport endpoints (PRD 3.6): filing, resolution, score cancellation."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_FORBIDDEN, ERR_INVALID_STATE
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch
from services.serialize import serialize_irregularity_report
from validate import (
    get_body, reject_unknown_fields, req_enum, req_str, req_str_allow_empty,
    require_path_resource, require_ref,
)

bp = Blueprint("irregularity_reports", __name__)

READ_ROLES = ["ApCoordinator", "Teacher", "Registrar"]
CATEGORIES = ("SECURITY_BREACH", "TIMING_ERROR", "ACCOMMODATION_VIOLATION",
              "MISCONDUCT", "MATERIALS")


def _course_registrations(course_id):
    return [r for r in db["registrations"].values() if r["course_id"] == course_id]


@bp.post("/irregularity-reports")
def create_irregularity_report():
    caller = require_roles(get_caller(), ["Teacher"])
    body = get_body()
    reject_unknown_fields(body, {"session_id", "category", "details"})
    session_id = req_str(body, "session_id")
    category = req_enum(body, "category", CATEGORIES)
    details = req_str_allow_empty(body, "details")
    session = require_ref("exam_sessions", session_id, "session_id")
    # Ownership: the caller must hold an ASSIGNED ProctorAssignment on the session.
    assigned = any(
        pa["session_id"] == session["id"] and pa["teacher_id"] == caller.user_id
        and pa["status"] == "ASSIGNED"
        for pa in db["proctor_assignments"].values()
    )
    if not assigned:
        raise_error(ERR_FORBIDDEN,
                    "only a teacher with an ASSIGNED proctor assignment on the session "
                    "may file an irregularity report")
    if session["status"] not in ("ADMINISTERED", "UNDER_INVESTIGATION"):
        raise_error(ERR_INVALID_STATE,
                    f"session in {session['status']} cannot accept irregularity reports")
    rec = new_record("irregularity_reports", {
        "session_id": session["id"],
        "proctor_teacher_id": caller.user_id,
        "category": category,
        "details": details,
        "status": "FILED",
    })
    # Filing cascade: first report moves ADMINISTERED -> UNDER_INVESTIGATION and
    # holds every SAT x PENDING score record of the course.
    if session["status"] == "ADMINISTERED":
        session["status"] = "UNDER_INVESTIGATION"
        touch(session)
    for r in _course_registrations(session["course_id"]):
        if r["registration_status"] == "SAT" and r["score_status"] == "PENDING":
            r["score_status"] = "HELD"
            touch(r)
    return success_object(serialize_irregularity_report(rec), status=201)


@bp.get("/irregularity-reports")
def list_irregularity_reports():
    require_roles(get_caller(), READ_ROLES)
    filters = [
        ("session_id", request.args.get("session_id")),
        ("status", request.args.get("status")),
        ("proctor_teacher_id", request.args.get("proctor_teacher_id")),
    ]
    return list_response(db["irregularity_reports"].values(), filters,
                         serialize_irregularity_report)


@bp.get("/irregularity-reports/<rid>")
def get_irregularity_report(rid):
    require_roles(get_caller(), READ_ROLES)
    ir = require_path_resource("irregularity_reports", rid)
    return success_object(serialize_irregularity_report(ir))


@bp.post("/irregularity-reports/<rid>/resolve")
def resolve_irregularity_report(rid):
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    ir = require_path_resource("irregularity_reports", rid)
    if ir["status"] != "FILED":
        raise_error(ERR_INVALID_STATE,
                    f"report in {ir['status']} cannot be resolved")
    ir["status"] = "RESOLVED"
    touch(ir)
    session = db["exam_sessions"][ir["session_id"]]
    remaining = any(
        other["session_id"] == session["id"] and other["status"] == "FILED"
        for other in db["irregularity_reports"].values()
    )
    # Last FILED report resolved: session returns to ADMINISTERED, HELD -> PENDING.
    if not remaining and session["status"] == "UNDER_INVESTIGATION":
        session["status"] = "ADMINISTERED"
        touch(session)
        for r in _course_registrations(session["course_id"]):
            if r["score_status"] == "HELD":
                r["score_status"] = "PENDING"
                touch(r)
    return success_object(serialize_irregularity_report(ir))


@bp.post("/irregularity-reports/<rid>/cancel-scores")
def cancel_scores_irregularity_report(rid):
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    ir = require_path_resource("irregularity_reports", rid)
    if ir["status"] != "FILED":
        raise_error(ERR_INVALID_STATE,
                    f"report in {ir['status']} cannot cancel scores")
    ir["status"] = "SCORES_CANCELLED"
    touch(ir)
    session = db["exam_sessions"][ir["session_id"]]
    if session["status"] in ("ADMINISTERED", "UNDER_INVESTIGATION"):
        session["status"] = "INVALIDATED"
        touch(session)
    for r in _course_registrations(session["course_id"]):
        if (r["registration_status"] == "SAT"
                and r["score_status"] in ("PENDING", "HELD")):
            r["score_status"] = "VOID"
            touch(r)
    return success_object(serialize_irregularity_report(ir))
