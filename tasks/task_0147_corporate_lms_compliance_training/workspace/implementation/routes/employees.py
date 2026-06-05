"""Employee endpoints (PRD §3.1, §3.9 dashboard)."""

from flask import Blueprint

import errors
import serializers as ser
from db import db
from middleware import authenticate, require_roles, ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER
from response import object_response, array_response
from services import calculations as calc
from services.common import (
    require_body, req_field, opt_field, check_str, check_enum, stamp_create,
    fk_or_404, get_or_404, parse_pagination, paginate, manager_can_see_employee,
    report_set,
)

bp = Blueprint("employees", __name__)

DEPARTMENTS = {"ENGINEERING", "SALES", "FINANCE", "HR", "OPERATIONS"}
JOB_ROLES = {"IC", "MANAGER", "DIRECTOR"}


@bp.route("/employees", methods=["POST"])
def create_employee():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    body = require_body()

    email = check_str(req_field(body, "email"), "email")
    full_name = check_str(req_field(body, "full_name"), "full_name")
    department = check_enum(req_field(body, "department"), DEPARTMENTS, "department")
    job_role = check_enum(req_field(body, "job_role"), JOB_ROLES, "job_role")
    manager_id = opt_field(body, "manager_id", None)

    if manager_id is not None:
        fk_or_404(db.employees, manager_id)

    # case-insensitive email uniqueness
    low = email.lower()
    for e in db.employees.values():
        if e["email"].lower() == low:
            raise errors.duplicate("Employee email already exists")

    rec = {
        "email": email,
        "full_name": full_name,
        "department": department,
        "job_role": job_role,
        "manager_id": manager_id,
        "total_ceu_earned": 0,
        "compliant_required_count": 0,
        "compliance_score": 100,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.employees[rec["id"]] = rec
    return object_response(ser.employee(rec), status=201)


@bp.route("/employees/<rid>", methods=["GET"])
def get_employee(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.employees, rid)
    if not manager_can_see_employee(p, rid):
        raise errors.unauthorized("Out of scope")
    return object_response(ser.employee(rec))


@bp.route("/employees", methods=["GET"])
def list_employees():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER])
    from flask import request
    limit, offset = parse_pagination()
    manager_id = request.args.get("manager_id")
    department = request.args.get("department")

    items = list(db.employees.values())
    if manager_id is not None:
        items = [e for e in items if e.get("manager_id") == manager_id]
    if department is not None:
        items = [e for e in items if e.get("department") == department]
    if p.is_manager:
        scope = report_set(p.user_id)
        items = [e for e in items if e["id"] in scope]

    page, total = paginate(items, limit, offset)
    return array_response([ser.employee(e) for e in page], limit, offset, total)


@bp.route("/employees/<rid>/dashboard", methods=["GET"])
def employee_dashboard(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.employees, rid)
    if not manager_can_see_employee(p, rid):
        raise errors.unauthorized("Out of scope")
    # recompute on read
    calc.recompute_employee_invariants(rec)
    calc.recompute_employee_compliance_score(rec)
    return object_response(ser.employee(rec))
