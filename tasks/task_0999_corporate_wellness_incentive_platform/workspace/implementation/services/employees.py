"""Employee endpoints (PRD §3.1)."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import current_identity, require_roles
from response import success
from services import serializers
from services.common import (
    get_employee_or_404, get_employer_or_404, list_response, parse_body,
    require_fields, stamp_new,
)

bp = Blueprint("employees", __name__)


@bp.post("/wellness/employees")
@require_roles("BenefitsAdmin")
def create_employee():
    body = parse_body()
    vals = require_fields(body, [
        ("employer_id", "string", True),
        ("email", "string", True),
        ("full_name", "string", True),
        ("department", "string", True),
        ("hire_date", "date", True),
        ("tobacco_attested", "bool", False),
    ])
    get_employer_or_404(vals["employer_id"])
    # email unique per employer (PRD §3.1)
    for e in DB.employees.values():
        if e["employer_id"] == vals["employer_id"] and e["email"] == vals["email"]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "email must be unique per employer",
            )
    vals["hire_date"] = vals["hire_date"].isoformat()
    vals.setdefault("tobacco_attested", False)
    rec = stamp_new(dict(vals))
    DB.employees[rec["id"]] = rec
    return success(serializers.employee(rec), status=201)


def _check_employee_self(employee):
    """Employee callers may only read their own record (PRD §2.1, §2.6 stage 5)."""
    user_id, role = current_identity()
    if role == "Employee" and employee["id"] != user_id:
        raise ApiError(
            "ERR_OWNERSHIP_MISMATCH",
            "Employee may only access their own record",
        )


@bp.get("/wellness/employees/<eid>")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def get_employee(eid):
    emp = get_employee_or_404(eid)
    _check_employee_self(emp)
    return success(serializers.employee(emp))


@bp.get("/wellness/employees/<eid>/enrollments")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def list_employee_enrollments(eid):
    emp = get_employee_or_404(eid)
    _check_employee_self(emp)
    items = [en for en in DB.enrollments.values() if en["employee_id"] == eid]
    return list_response(items, serializers.enrollment)
