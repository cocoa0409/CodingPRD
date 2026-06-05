"""PathEnrollment endpoints (PRD §3.7)."""

from flask import Blueprint, request

import errors
import serializers as ser
from db import db
from middleware import authenticate, require_roles, ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER
from response import object_response, array_response
from services.common import (
    require_body, req_field, opt_field, check_nonneg_int, fk_or_404, get_or_404,
    parse_pagination, paginate, report_set,
)
from services import calculations as calc
from services import path_enrollment_svc
from timeutil import add_days

bp = Blueprint("path_enrollments", __name__)


def _scope_filter(principal, items):
    if principal.is_admin:
        return items
    if principal.is_manager:
        scope = report_set(principal.user_id)
        return [pe for pe in items if pe["employee_id"] in scope]
    if principal.is_learner:
        return [pe for pe in items if pe["employee_id"] == principal.user_id]
    return []


@bp.route("/path-enrollments", methods=["POST"])
def create_path_enrollment():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_LEARNER])
    body = require_body()
    employee_id = req_field(body, "employee_id")
    learning_path_id = req_field(body, "learning_path_id")
    fk_or_404(db.employees, employee_id)
    fk_or_404(db.learning_paths, learning_path_id)
    due_in_days = opt_field(body, "due_in_days", 60)
    check_nonneg_int(due_in_days, "due_in_days")

    if p.is_learner and employee_id != p.user_id:
        raise errors.unauthorized("Learner may only self-enroll")

    due_date = add_days(db.now(), due_in_days)
    pe = path_enrollment_svc.create_path_enrollment(
        employee_id=employee_id,
        learning_path_id=learning_path_id,
        due_date=due_date,
        assignment_rule_id=None,
    )
    return object_response(ser.path_enrollment(pe), status=201)


@bp.route("/path-enrollments", methods=["GET"])
def list_path_enrollments():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    limit, offset = parse_pagination()
    items = list(db.path_enrollments.values())
    for field in ("employee_id", "learning_path_id", "assignment_rule_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [pe for pe in items if pe.get(field) == val]
    items = _scope_filter(p, items)
    page, total = paginate(items, limit, offset)
    return array_response([ser.path_enrollment(pe) for pe in page], limit, offset, total)


@bp.route("/path-enrollments/<rid>", methods=["GET"])
def get_path_enrollment(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.path_enrollments, rid)
    if p.is_learner and rec["employee_id"] != p.user_id:
        raise errors.unauthorized("Out of scope")
    if p.is_manager and rec["employee_id"] not in report_set(p.user_id):
        raise errors.unauthorized("Out of scope")
    # recompute progress on read
    rec["progress_pct"] = calc.compute_path_progress(rec)
    return object_response(ser.path_enrollment(rec))
