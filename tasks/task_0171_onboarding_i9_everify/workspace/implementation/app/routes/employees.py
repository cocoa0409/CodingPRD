"""Employee routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_roles
from ..errors import err_validation
from ..pagination import paginate, parse_pagination
from ..response import make_array_envelope, make_object_envelope
from ..serializers import view_employee
from ..services.employees import (
    create_employee,
    get_employee,
    list_employees,
    patch_employee,
)
from ..services.onboarding_status import derive_onboarding_status
from ._helpers import enforce_employee_ownership, parse_json_body


bp_employees = Blueprint("employees", __name__)


@bp_employees.route("/employees", methods=["POST"])
@require_roles("HRStaff")
def create_employee_route(user_id, role):
    body = parse_json_body()
    row = create_employee(body, actor_user_id=user_id, actor_role=role)
    status = derive_onboarding_status(row)
    return jsonify(make_object_envelope(view_employee(row, status))), 201


@bp_employees.route("/employees/<employee_id>", methods=["GET"])
@require_roles("HRStaff", "EmployerRep", "Employee")
def read_employee_route(user_id, role, employee_id):
    row = get_employee(employee_id)
    enforce_employee_ownership(role, user_id, employee_id)
    status = derive_onboarding_status(row)
    return jsonify(make_object_envelope(view_employee(row, status))), 200


@bp_employees.route("/employees/<employee_id>", methods=["PATCH"])
@require_roles("HRStaff")
def patch_employee_route(user_id, role, employee_id):
    body = parse_json_body()
    row = patch_employee(employee_id, body, actor_user_id=user_id, actor_role=role)
    status = derive_onboarding_status(row)
    return jsonify(make_object_envelope(view_employee(row, status))), 200


@bp_employees.route("/employees", methods=["GET"])
@require_roles("HRStaff", "EmployerRep")
def list_employees_route(user_id, role):
    limit, offset = parse_pagination()
    filters = {
        "onboarding_status": request.args.get("onboarding_status"),
        "is_terminated": request.args.get("is_terminated"),
    }
    items = list_employees(filters)
    total = len(items)
    page = paginate(items, limit, offset)
    views = [view_employee(e, derive_onboarding_status(e)) for e in page]
    return jsonify(make_array_envelope(views, limit=limit, offset=offset, total_count=total)), 200
