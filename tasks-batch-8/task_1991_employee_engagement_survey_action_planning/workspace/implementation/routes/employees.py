"""Employees (PRD §3.2)."""

from flask import Blueprint, request

from db import db, stamp_new, touch, public, parse_ts
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_DUPLICATE,
)
from middleware import (
    require_roles, parse_pagination, paginate, get_json_body,
    require_fields, optional_fields_present, as_non_empty_string, as_enum,
)
from response import success_object, success_list

bp = Blueprint("employees", __name__)

EMPLOYMENT_STATUSES = {"ACTIVE", "LEAVE", "TERMINATED"}


def _get_employee_or_404(emp_id):
    emp = db.employees.get(emp_id)
    if emp is None:
        raise err(ERR_NOT_FOUND, "employee not found", 404)
    return emp


@bp.post("/engagement/employees")
def create_employee():
    require_roles("HRAdmin")
    body = get_json_body()
    optional_fields_present(body, {"external_ref", "unit_id", "employment_status", "hired_at"})
    require_fields(body, ["external_ref", "unit_id", "employment_status", "hired_at"])
    external_ref = as_non_empty_string(body["external_ref"], "external_ref")
    unit_id = as_non_empty_string(body["unit_id"], "unit_id")
    employment_status = as_enum(body["employment_status"], "employment_status", EMPLOYMENT_STATUSES)
    hired_at_raw = body["hired_at"]
    try:
        hired_at = parse_ts(hired_at_raw)
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, "hired_at must be an ISO 8601 timestamp", 400)

    if unit_id not in db.org_units:
        raise err(ERR_REFERENCE_NOT_FOUND, "unit_id does not exist", 404)

    for emp in db.employees.values():
        if emp["external_ref"] == external_ref:
            raise err(ERR_DUPLICATE, "external_ref must be unique", 409)

    emp = stamp_new({
        "external_ref": external_ref,
        "unit_id": unit_id,
        "employment_status": employment_status,
        "hired_at": hired_at_raw,
        "_hired_at": hired_at,
        "exited_at": None,
    })
    db.employees[emp["id"]] = emp
    return success_object(public(emp), 201)


@bp.get("/engagement/employees")
def list_employees():
    require_roles("HRAdmin", "PeopleAnalyst")
    limit, offset = parse_pagination({"unit_id", "employment_status"})
    unit_id = request.args.get("unit_id")
    status = request.args.get("employment_status")
    items = list(db.employees.values())
    if unit_id is not None:
        items = [e for e in items if e["unit_id"] == unit_id]
    if status is not None:
        items = [e for e in items if e["employment_status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


@bp.get("/engagement/employees/<emp_id>")
def get_employee(emp_id):
    require_roles("HRAdmin", "PeopleAnalyst")
    emp = _get_employee_or_404(emp_id)
    return success_object(public(emp))


@bp.post("/engagement/employees/<emp_id>/terminate")
def terminate_employee(emp_id):
    require_roles("HRAdmin")
    emp = _get_employee_or_404(emp_id)
    body = get_json_body()
    optional_fields_present(body, {"exited_at"})
    require_fields(body, ["exited_at"])
    try:
        parse_ts(body["exited_at"])
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, "exited_at must be an ISO 8601 timestamp", 400)
    emp["employment_status"] = "TERMINATED"
    emp["exited_at"] = body["exited_at"]
    touch(emp)
    return success_object(public(emp))
