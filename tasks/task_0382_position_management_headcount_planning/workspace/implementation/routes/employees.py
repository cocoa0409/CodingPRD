"""Employee endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from response import success, list_success
from services import serialize
from services.common import (
    get_body, require_string, require_int, base_common_fields, fetch, paginate,
)

bp = Blueprint("employees", __name__)

ALL_ROLES = ["HRBP", "HRDirector", "FinanceController", "CompensationAnalyst"]


@bp.post("/employees")
def create_employee():
    require_auth(["HRBP", "HRDirector"])
    body = get_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    salary = require_int(body, "annual_salary_cents", min_value=0)

    # email unique among employees (PRD §3.1). Treated as a business constraint.
    for e in db.employees.values():
        if e["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique among employees")

    rec = base_common_fields()
    rec.update({
        "full_name": full_name,
        "email": email,
        "annual_salary_cents": salary,
        "status": "AVAILABLE",
    })
    db.employees[rec["id"]] = rec
    return success(serialize.employee_out(rec), status=201)


@bp.get("/employees/<employee_id>")
def get_employee(employee_id):
    require_auth(ALL_ROLES)
    rec = fetch(db.employees, employee_id)
    return success(serialize.employee_out(rec))


@bp.get("/employees")
def list_employees():
    require_auth(ALL_ROLES)
    status = request.args.get("status")
    records = list(db.employees.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.employee_out(r) for r in page], limit, offset, total)
