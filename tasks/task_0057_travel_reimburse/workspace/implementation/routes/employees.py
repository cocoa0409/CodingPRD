"""Employee endpoints."""

from __future__ import annotations

from flask import Blueprint, request

from db import STORE
from errors import APIError, ERR_NOT_FOUND
from middleware import require_auth
from response import success
from serializers import employee as ser_employee
from services.validate import require_body, get_str, get_enum
from utils import CLOCK, new_uuid


bp = Blueprint("employees", __name__)


EMPLOYEE_LEVELS = {"STAFF", "MANAGER", "DIRECTOR", "EXECUTIVE"}


@bp.route("/employees", methods=["POST"])
@require_auth(["Admin"])
def create_employee():
    body = require_body(request.get_json(silent=True))
    full_name = get_str(body, "full_name")
    level = get_enum(body, "employee_level", EMPLOYEE_LEVELS)
    department_id = get_str(body, "department_id")
    # supervisor_id may legitimately be null (top of org)
    supervisor_id = body.get("supervisor_id")
    if supervisor_id is not None and not isinstance(supervisor_id, str):
        raise APIError("ERR_VALIDATION", "supervisor_id must be a string or null", 422)

    now = CLOCK.now_iso()
    eid = new_uuid()
    row = {
        "id": eid,
        "full_name": full_name,
        "employee_level": level,
        "department_id": department_id,
        "supervisor_id": supervisor_id,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.employees[eid] = row
    return success(ser_employee(row), status=201)


@bp.route("/employees/<eid>", methods=["GET"])
@require_auth(["Admin", "Applicant", "Supervisor", "DeptHead", "Finance", "GeneralManager"])
def get_employee(eid):
    row = STORE.employees.get(eid)
    if not row:
        raise APIError(ERR_NOT_FOUND, f"Employee {eid} not found", 404)
    return success(ser_employee(row))
