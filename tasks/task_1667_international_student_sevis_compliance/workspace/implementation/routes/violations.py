"""Status violations: open, recommend reinstatement, resolve (PDSO), dismiss
(PRD §3.9)."""

from flask import Blueprint

import db
import services
from db import touch
from errors import (
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_RECORD_NOT_TERMINATED,
    ERR_RESOURCE_NOT_OWNED,
    ERR_VIOLATION_INVALID_STATE,
    raise_error,
)
from helpers import (
    body, get_or_404, get_student_or_404, list_response, opt_str, req_enum,
    req_str,
)
from middleware import ALL_ROLES, STAFF_ROLES, require_roles
from response import success_object
from serializers import status_violation_out

bp = Blueprint("violations", __name__)

VIOLATION_TYPES = (
    "FAILURE_TO_ENROLL",
    "UNAUTHORIZED_EMPLOYMENT",
    "UNEMPLOYMENT_LIMIT_EXCEEDED",
    "ADDRESS_REPORT_OVERDUE",
    "OTHER",
)
VIOLATION_ACTIONS = ("RECOMMEND_REINSTATEMENT", "RESOLVE", "DISMISS")
RESOLVE_OUTCOMES = ("REINSTATED", "DENIED")


@bp.route("/sevis/students/<sid>/status-violations", methods=["POST"])
def create_status_violation(sid):
    require_roles(STAFF_ROLES)
    student = get_student_or_404(sid)
    data = body()
    violation_type = req_enum(data, "violation_type", VIOLATION_TYPES)
    description = req_str(data, "description")
    violation = services.open_violation(student["id"], violation_type, description)
    return success_object(status_violation_out(violation), 201)


@bp.route("/sevis/students/<sid>/status-violations", methods=["GET"])
def list_status_violations(sid):
    user_id, role = require_roles(ALL_ROLES)
    if role == "Student" and user_id != sid:
        raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only read their own resources")
    student = get_student_or_404(sid)
    items = [v for v in db.status_violations.values() if v["student_id"] == student["id"]]
    return list_response(items, status_violation_out)


@bp.route("/sevis/status-violations/<vid>/transition", methods=["POST"])
def transition_status_violation(vid):
    user_id, role = require_roles(STAFF_ROLES)
    violation = get_or_404(db.status_violations, vid, "StatusViolation")
    data = body()
    action = req_enum(data, "action", VIOLATION_ACTIONS)
    # Action-specific role rule (priority 2): RESOLVE is PDSO-exclusive.
    if action == "RESOLVE" and role != "PDSO":
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "RESOLVE is a PDSO action")

    record = services.record_of_student(violation["student_id"])

    if action == "RECOMMEND_REINSTATEMENT":
        if violation["status"] != "OPEN":
            raise_error(ERR_VIOLATION_INVALID_STATE, "Violation must be OPEN to recommend reinstatement")
        if record is None or record["status"] != "TERMINATED":
            raise_error(ERR_RECORD_NOT_TERMINATED, "Record must be TERMINATED for reinstatement recommendation")
        violation["status"] = "REINSTATEMENT_PENDING"
        touch(violation)
        record["status"] = "REINSTATEMENT_PENDING"
        touch(record)
        services.recompute_posture(violation["student_id"])

    elif action == "RESOLVE":
        outcome = req_enum(data, "outcome", RESOLVE_OUTCOMES)
        if violation["status"] != "REINSTATEMENT_PENDING":
            raise_error(ERR_VIOLATION_INVALID_STATE, "Violation must be REINSTATEMENT_PENDING to resolve")
        if outcome == "REINSTATED":
            violation["status"] = "RESOLVED_REINSTATED"
            if record is not None and record["status"] == "REINSTATEMENT_PENDING":
                record["status"] = "ACTIVE"
                touch(record)
        else:
            violation["status"] = "RESOLVED_DENIED"
            if record is not None and record["status"] == "REINSTATEMENT_PENDING":
                record["status"] = "TERMINATED"
                touch(record)
        touch(violation)
        services.recompute_posture(violation["student_id"])

    else:  # DISMISS
        if violation["status"] != "OPEN":
            raise_error(ERR_VIOLATION_INVALID_STATE, "Violation must be OPEN to dismiss")
        violation["status"] = "DISMISSED"
        touch(violation)
        services.recompute_posture(violation["student_id"])

    return success_object(status_violation_out(violation), 200)
