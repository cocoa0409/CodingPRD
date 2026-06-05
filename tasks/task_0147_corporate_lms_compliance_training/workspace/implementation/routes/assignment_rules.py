"""AssignmentRule endpoints + sweep (PRD §3.3)."""

from flask import Blueprint, request

import errors
import serializers as ser
from db import db
from middleware import authenticate, require_roles, ROLE_ADMIN, ROLE_MANAGER
from response import object_response, array_response
from services.common import (
    require_body, req_field, opt_field, check_enum, check_str, check_nonneg_int,
    stamp_create, fk_or_404, get_or_404, parse_pagination, paginate,
)
from services import path_enrollment_svc
from timeutil import parse_iso, add_days

bp = Blueprint("assignment_rules", __name__)

DEPARTMENTS_ANY = {"ENGINEERING", "SALES", "FINANCE", "HR", "OPERATIONS", "ANY"}
JOB_ROLES_ANY = {"IC", "MANAGER", "DIRECTOR", "ANY"}


@bp.route("/assignment-rules", methods=["POST"])
def create_rule():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    body = require_body()

    target_department = check_enum(req_field(body, "target_department"),
                                   DEPARTMENTS_ANY, "target_department")
    target_job_role = check_enum(req_field(body, "target_job_role"),
                                 JOB_ROLES_ANY, "target_job_role")
    course_id = opt_field(body, "course_id", None)
    learning_path_id = opt_field(body, "learning_path_id", None)
    due_in_days = req_field(body, "due_in_days")
    check_nonneg_int(due_in_days, "due_in_days")
    effective_from = check_str(req_field(body, "effective_from"), "effective_from")
    effective_to = check_str(req_field(body, "effective_to"), "effective_to")

    # exactly one of course_id / learning_path_id
    if (course_id is None) == (learning_path_id is None):
        raise errors.invalid_request("Exactly one of course_id / learning_path_id required")

    if course_id is not None:
        fk_or_404(db.courses, course_id)
    if learning_path_id is not None:
        fk_or_404(db.learning_paths, learning_path_id)

    try:
        ef = parse_iso(effective_from)
        et = parse_iso(effective_to)
    except (ValueError, TypeError):
        raise errors.invalid_request("effective_from/effective_to must be ISO 8601")
    if et < ef:
        raise errors.invalid_request("effective_to must be >= effective_from")

    # window-overlap check vs ACTIVE rules for the same target
    for r in db.assignment_rules.values():
        if r["status"] != "ACTIVE":
            continue
        if (r["target_department"] == target_department
                and r["target_job_role"] == target_job_role
                and r.get("course_id") == course_id
                and r.get("learning_path_id") == learning_path_id):
            rf = parse_iso(r["effective_from"])
            rt = parse_iso(r["effective_to"])
            # closed-interval intersection
            if ef <= rt and rf <= et:
                raise errors.ApiError(errors.ERR_ASSIGNMENT_RULE_OVERLAP, 409,
                                      "Overlapping assignment rule window")

    rec = {
        "target_department": target_department,
        "target_job_role": target_job_role,
        "course_id": course_id,
        "learning_path_id": learning_path_id,
        "due_in_days": due_in_days,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.assignment_rules[rec["id"]] = rec
    return object_response(ser.assignment_rule(rec), status=201)


@bp.route("/assignment-rules", methods=["GET"])
def list_rules():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER])
    limit, offset = parse_pagination()
    course_id = request.args.get("course_id")
    learning_path_id = request.args.get("learning_path_id")
    status = request.args.get("status")
    items = list(db.assignment_rules.values())
    if course_id is not None:
        items = [r for r in items if r.get("course_id") == course_id]
    if learning_path_id is not None:
        items = [r for r in items if r.get("learning_path_id") == learning_path_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([ser.assignment_rule(r) for r in page], limit, offset, total)


@bp.route("/assignment-rules/<rid>", methods=["GET"])
def get_rule(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER])
    rec = get_or_404(db.assignment_rules, rid)
    return object_response(ser.assignment_rule(rec))


@bp.route("/assignment-rules/<rid>/apply", methods=["POST"])
def apply_rule(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    rule = get_or_404(db.assignment_rules, rid)

    created_enrollment_ids = []
    created_path_enrollment_ids = []

    matching = _matching_employees(rule)
    due_date = add_days(db.now(), rule["due_in_days"])

    for emp in matching:
        if rule.get("course_id") is not None:
            # skip employees already in an open cycle for this course
            if _has_open_course_cycle(emp["id"], rule["course_id"]):
                continue
            enr = _create_rule_enrollment(emp, rule, due_date)
            created_enrollment_ids.append(enr["id"])
        else:
            # path-targeted
            if _has_open_path_cycle(emp["id"], rule["learning_path_id"]):
                continue
            pe = path_enrollment_svc.create_path_enrollment(
                employee_id=emp["id"],
                learning_path_id=rule["learning_path_id"],
                due_date=due_date,
                assignment_rule_id=rule["id"],
            )
            created_path_enrollment_ids.append(pe["id"])

    result = {
        "created_enrollment_ids": created_enrollment_ids,
        "created_path_enrollment_ids": created_path_enrollment_ids,
        "created_count": len(created_enrollment_ids) + len(created_path_enrollment_ids),
    }
    return object_response(result)


def _matching_employees(rule):
    out = []
    for emp in db.employees.values():
        if emp["status"] != "ACTIVE":
            continue
        dep = rule["target_department"]
        role = rule["target_job_role"]
        if dep != "ANY" and emp["department"] != dep:
            continue
        if role != "ANY" and emp["job_role"] != role:
            continue
        out.append(emp)
    # deterministic order by created_at
    return sorted(out, key=lambda e: (e.get("created_at") or "", e.get("id") or ""))


def _has_open_course_cycle(employee_id, course_id):
    for e in db.enrollments.values():
        if (e["employee_id"] == employee_id and e["course_id"] == course_id
                and e["status"] in ("NOT_STARTED", "IN_PROGRESS", "FAILED", "EXPIRED")):
            return True
    return False


def _has_open_path_cycle(employee_id, learning_path_id):
    for pe in db.path_enrollments.values():
        if (pe["employee_id"] == employee_id and pe["learning_path_id"] == learning_path_id
                and pe["status"] in ("NOT_STARTED", "IN_PROGRESS", "FAILED")):
            return True
    return False


def _create_rule_enrollment(emp, rule, due_date):
    rec = {
        "employee_id": emp["id"],
        "course_id": rule["course_id"],
        "path_enrollment_id": None,
        "assignment_rule_id": rule["id"],
        "is_required": True,
        "due_date": due_date,
        "best_score": None,
        "latest_score": None,
        "final_grade": None,
        "attempts_used": 0,
        "cycle_index": 1,
        "escalation_tier": 0,
        "certificate_id": None,
        "status": "NOT_STARTED",
    }
    stamp_create(rec)
    db.enrollments[rec["id"]] = rec
    return rec
