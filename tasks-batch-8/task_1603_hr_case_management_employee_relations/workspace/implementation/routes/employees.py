"""Employee roster endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_DUPLICATE
from middleware import authorize
from response import success_object
from services.core import (
    new_record, touch, require_path, require_ref, list_response,
    serialize_employee,
)
from util import fmt_dt
from validate import Payload

bp = Blueprint("employees", __name__)

EMPLOYMENT_STATUSES = {"ACTIVE", "ON_LEAVE", "TERMINATED"}
READ_ROLES = {"ERManager", "Investigator", "LegalCounsel", "HRAnalyst"}


def _manager_chain_has(employee_id, target_id) -> bool:
    """True if walking employee_id's manager chain reaches target_id."""
    cur_id = employee_id
    seen = set()
    while cur_id:
        if cur_id == target_id:
            return True
        if cur_id in seen:
            return False
        seen.add(cur_id)
        cur = db["employees"].get(cur_id)
        cur_id = cur["manager_id"] if cur else None
    return False


@bp.post("/er/employees")
def create_employee():
    authorize({"ERManager"})
    p = Payload(request.get_json(silent=True))
    employee_number = p.get_str("employee_number", required=True)
    full_name = p.get_str("full_name", required=True)
    email = p.get_str("email", required=True)
    location_code = p.get_str("location_code", required=True)
    department = p.get_str("department", required=True)
    hire_dt = p.get_dt("hire_date", required=True)
    manager_id = p.get_str("manager_id", required=False)
    employment_status = p.get_enum("employment_status", EMPLOYMENT_STATUSES,
                                   required=False)

    # priority 5 — body FK resolution
    if manager_id is not None:
        require_ref("employees", manager_id, "manager_id")

    # priority 15 — uniqueness (employee_number, email) and acyclicity
    for e in db["employees"].values():
        if employee_number is not None and e["employee_number"] == employee_number:
            raise_error(ERR_DUPLICATE,
                        f"employee_number {employee_number} already exists")
        if email is not None and e["email"] == email:
            raise_error(ERR_DUPLICATE, f"email {email} already exists")

    # priority 24 — syntactic screen
    p.raise_if_errors()

    rec = new_record()
    rec.update({
        "employee_number": employee_number,
        "full_name": full_name,
        "email": email,
        "manager_id": manager_id,
        "location_code": location_code,
        "department": department,
        "employment_status": employment_status or "ACTIVE",
        "hire_date": fmt_dt(hire_dt),
        "_hire_date": hire_dt,
    })
    db["employees"][rec["id"]] = rec
    return success_object(serialize_employee(rec), status=201)


@bp.get("/er/employees/<eid>")
def get_employee(eid):
    authorize(READ_ROLES)
    rec = require_path("employees", eid)
    return success_object(serialize_employee(rec))


@bp.get("/er/employees")
def list_employees():
    authorize(READ_ROLES)
    items = list(db["employees"].values())
    for field in ("location_code", "department", "employment_status", "manager_id"):
        v = request.args.get(field)
        if v is not None:
            items = [e for e in items if e.get(field) == v]
    return list_response(items, serialize_employee)


@bp.patch("/er/employees/<eid>")
def patch_employee(eid):
    authorize({"ERManager"})
    rec = require_path("employees", eid)
    p = Payload(request.get_json(silent=True))
    full_name = p.get_str("full_name")
    manager_id = p.get_str("manager_id")
    location_code = p.get_str("location_code")
    department = p.get_str("department")
    employment_status = p.get_enum("employment_status", EMPLOYMENT_STATUSES)

    # priority 5 — body FK resolution
    if manager_id is not None:
        require_ref("employees", manager_id, "manager_id")

    # priority 15 — manager-chain acyclicity
    if manager_id is not None and _manager_chain_has(manager_id, eid):
        raise_error(ERR_DUPLICATE,
                    "manager assignment would create a cycle in the reporting chain")

    # priority 24
    p.raise_if_errors()

    changed = False
    if full_name is not None:
        rec["full_name"] = full_name
        changed = True
    if "manager_id" in p.raw:
        rec["manager_id"] = manager_id  # may be null to clear
        changed = True
    if location_code is not None:
        rec["location_code"] = location_code
        changed = True
    if department is not None:
        rec["department"] = department
        changed = True
    if employment_status is not None:
        rec["employment_status"] = employment_status
        changed = True
    if changed:
        touch(rec)
    return success_object(serialize_employee(rec))
