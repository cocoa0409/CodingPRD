"""ViolationRecord, TrainingCourse, TrainingAssignment endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import clock
from db import db
from errors import (err_duplicate_course, err_invalid_state, err_not_found,
                    err_ownership)
from middleware import require_roles
from serializers import assignment_out, course_out, violation_out
from services.core import (POINTS, create_training_assignment,
                           recompute_offender_points, touch,
                           violation_effective_points)
from util import (get_pagination, new_id, paginate, parse_body, require_enum,
                  require_positive_int, require_string, success_envelope)

bp = Blueprint("violations_training", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


# ---------------- ViolationRecord ----------------

@bp.route("/damage-recovery/violation-records", methods=["POST"])
def create_violation():
    require_roles("RecoveryManager")
    body = parse_body(required_fields=["excavator_id", "damage_case_id"])
    excavator_id = require_string(body["excavator_id"], "excavator_id")
    exc = db.excavators.get(excavator_id)
    if exc is None:
        raise err_not_found("excavator not found")
    case = db.damage_cases.get(body["damage_case_id"])
    if case is None:
        raise err_not_found("damage case not found")
    now = clock.get_current_utc()
    vid = new_id()
    points = POINTS[case["severity"]]
    v = {
        "id": vid,
        "excavator_id": excavator_id,
        "damage_case_id": case["id"],
        "points": points,
        "effective_points": points,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.violation_records[vid] = v
    recompute_offender_points(exc)
    return success_envelope(violation_out(v), "object", 201)


@bp.route("/damage-recovery/violation-records/<vid>", methods=["GET"])
def get_violation(vid):
    require_roles(*ALL_ROLES)
    v = db.violation_records.get(vid)
    if v is None:
        raise err_not_found("violation record not found")
    v["effective_points"] = violation_effective_points(v)
    return success_envelope(violation_out(v), "object", 200)


@bp.route("/damage-recovery/violation-records", methods=["GET"])
def list_violations():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.violation_records.values())
    excavator_id = request.args.get("excavator_id")
    case_id = request.args.get("damage_case_id")
    status = request.args.get("status")
    if excavator_id is not None:
        items = [v for v in items if v["excavator_id"] == excavator_id]
    if case_id is not None:
        items = [v for v in items if v["damage_case_id"] == case_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for v in items:
        v["effective_points"] = violation_effective_points(v)
    page, meta = paginate(items, limit, offset)
    return success_envelope([violation_out(v) for v in page], "array", 200, meta)


@bp.route("/damage-recovery/violation-records/<vid>/overturn", methods=["POST"])
def overturn_violation(vid):
    require_roles("RecoveryManager")
    v = db.violation_records.get(vid)
    if v is None:
        raise err_not_found("violation record not found")
    if v["status"] != "ACTIVE":
        raise err_invalid_state("violation is not ACTIVE")
    v["status"] = "OVERTURNED"
    v["updated_at"] = clock.get_current_utc()
    v["version"] += 1
    exc = db.excavators.get(v["excavator_id"])
    if exc is not None:
        recompute_offender_points(exc)
    return success_envelope(violation_out(v), "object", 200)


# ---------------- TrainingCourse ----------------

@bp.route("/damage-recovery/training-courses", methods=["POST"])
def create_course():
    require_roles("RecoveryManager")
    body = parse_body(required_fields=["course_code", "title", "required_for_status", "credit_hours"])
    course_code = require_string(body["course_code"], "course_code")
    title = require_string(body["title"], "title")
    rfs = require_enum(body["required_for_status"], ("WATCH", "PROBATION", "SUSPENDED"), "required_for_status")
    credit_hours = require_positive_int(body["credit_hours"], "credit_hours")
    for c in db.training_courses.values():
        if c["course_code"] == course_code:
            raise err_duplicate_course()
    now = clock.get_current_utc()
    cid = new_id()
    course = {
        "id": cid,
        "course_code": course_code,
        "title": title,
        "required_for_status": rfs,
        "credit_hours": credit_hours,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.training_courses[cid] = course
    return success_envelope(course_out(course), "object", 201)


@bp.route("/damage-recovery/training-courses/<cid>", methods=["GET"])
def get_course(cid):
    require_roles(*ALL_ROLES)
    c = db.training_courses.get(cid)
    if c is None:
        raise err_not_found("training course not found")
    return success_envelope(course_out(c), "object", 200)


@bp.route("/damage-recovery/training-courses", methods=["GET"])
def list_courses():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.training_courses.values())
    rfs = request.args.get("required_for_status")
    if rfs is not None:
        items = [c for c in items if c["required_for_status"] == rfs]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([course_out(c) for c in page], "array", 200, meta)


# ---------------- TrainingAssignment ----------------

@bp.route("/damage-recovery/training-assignments", methods=["POST"])
def create_assignment():
    require_roles("RecoveryManager")
    body = parse_body(required_fields=["excavator_id", "course_id"])
    excavator_id = require_string(body["excavator_id"], "excavator_id")
    if excavator_id not in db.excavators:
        raise err_not_found("excavator not found")
    course_id = require_string(body["course_id"], "course_id")
    if course_id not in db.training_courses:
        raise err_not_found("training course not found")
    a = create_training_assignment(excavator_id, course_id)
    return success_envelope(assignment_out(a), "object", 201)


@bp.route("/damage-recovery/training-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require_roles(*ALL_ROLES)
    a = db.training_assignments.get(aid)
    if a is None:
        raise err_not_found("training assignment not found")
    return success_envelope(assignment_out(a), "object", 200)


@bp.route("/damage-recovery/training-assignments", methods=["GET"])
def list_assignments():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.training_assignments.values())
    excavator_id = request.args.get("excavator_id")
    course_id = request.args.get("course_id")
    status = request.args.get("status")
    if excavator_id is not None:
        items = [a for a in items if a["excavator_id"] == excavator_id]
    if course_id is not None:
        items = [a for a in items if a["course_id"] == course_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([assignment_out(a) for a in page], "array", 200, meta)


@bp.route("/damage-recovery/training-assignments/<aid>/complete", methods=["POST"])
def complete_assignment(aid):
    user_id, _ = require_roles("Excavator")
    a = db.training_assignments.get(aid)
    if a is None:
        raise err_not_found("training assignment not found")
    if a["status"] != "ASSIGNED":
        raise err_invalid_state("assignment is not ASSIGNED")
    if a["excavator_id"] != user_id:
        raise err_ownership("caller is not the assignee")
    a["status"] = "COMPLETED"
    a["completed_at"] = clock.get_current_utc()
    a["updated_at"] = clock.get_current_utc()
    a["version"] += 1
    return success_envelope(assignment_out(a), "object", 200)
