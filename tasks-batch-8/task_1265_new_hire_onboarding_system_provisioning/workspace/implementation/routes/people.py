"""Employee and NewHire endpoints (PRD §3.2)."""

from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from db import store
from errors import (ApiError, ERR_EMPLOYEE_NOT_FOUND, ERR_NEW_HIRE_NOT_FOUND,
                    ERR_EMPLOYEE_NOT_ACTIVE)
from helpers import (new_record, touch, get_or_404, ser_employee,
                     ser_new_hire, ser_checkin, sort_created)
from sweep import refresh_health, TERMINAL_PHASES
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_date, bad)

bp = Blueprint("people", __name__)


@bp.post("/api/employees")
def create_employee():
    require_roles("HRAdmin")
    body = get_body()
    full_name = as_str(req_present(body, "full_name"), "full_name")
    email = as_str(req_present(body, "email"), "email")
    manager_id = body.get("manager_id")
    if manager_id is not None:
        if not isinstance(manager_id, str):
            bad("manager_id must be a string")
        get_or_404("employees", manager_id, ERR_EMPLOYEE_NOT_FOUND,
                   "Employee")
    rec = new_record("employees", {
        "full_name": full_name,
        "email": email,
        "employment_status": "ACTIVE",
        "manager_id": manager_id,
    })
    return success(ser_employee(rec), 201)


@bp.get("/api/employees")
def list_employees():
    require_roles(*ALL_ROLES)
    limit, offset = page_params()
    q = request.args
    records = list(store["employees"].values())
    if "manager_id" in q and q.get("manager_id") is not None:
        records = [e for e in records if e.get("manager_id") == q["manager_id"]]
    if "employment_status" in q and q.get("employment_status") is not None:
        st = q["employment_status"]
        if st not in ("ACTIVE", "INACTIVE"):
            bad("employment_status must be one of ACTIVE, INACTIVE")
        records = [e for e in records if e["employment_status"] == st]
    records = sort_created(records)
    return paged([ser_employee(e) for e in records], limit, offset)


@bp.get("/api/employees/<eid>")
def get_employee(eid):
    require_roles(*ALL_ROLES)
    rec = get_or_404("employees", eid, ERR_EMPLOYEE_NOT_FOUND, "Employee")
    return success(ser_employee(rec))


@bp.post("/api/employees/<eid>/deactivate")
def deactivate_employee(eid):
    require_roles("HRAdmin")
    emp = get_or_404("employees", eid, ERR_EMPLOYEE_NOT_FOUND, "Employee")
    if emp["employment_status"] != "ACTIVE":
        raise ApiError(ERR_EMPLOYEE_NOT_ACTIVE, 409,
                       "Employee is not ACTIVE")
    emp["employment_status"] = "INACTIVE"
    touch(emp)

    # Cascade link 1: every non-terminal case this employee manages gets
    # manager_reassignment_required = true (version += 1 each).
    managed = [c for c in store["cases"].values()
               if c["manager_id"] == eid and c["phase"] not in TERMINAL_PHASES]
    managed_ids = {c["id"] for c in managed}
    for case in managed:
        case["manager_reassignment_required"] = True
        touch(case)

    # Cascade link 2: check-ins owned by this employee on those cases; plus
    # every SCHEDULED/MISSED check-in where the employee is the case's buddy.
    affected = set()
    for ci in store["checkins"].values():
        if ci["owner_employee_id"] != eid or \
                ci["status"] not in ("SCHEDULED", "MISSED"):
            continue
        case = store["cases"].get(ci["case_id"])
        if case is None:
            continue
        if ci["case_id"] in managed_ids or case.get("buddy_id") == eid:
            ci["status"] = "CANCELLED"
            touch(ci)
            affected.add(ci["case_id"])
    for cid in affected:
        case = store["cases"].get(cid)
        if case is not None:
            refresh_health(case)
    return success(ser_employee(emp))


@bp.get("/api/employees/<eid>/check-ins")
def employee_checkins(eid):
    require_roles(*ALL_ROLES)
    get_or_404("employees", eid, ERR_EMPLOYEE_NOT_FOUND, "Employee")
    limit, offset = page_params()
    records = [c for c in store["checkins"].values()
               if c["owner_employee_id"] == eid]
    records = sort_created(records)
    return paged([ser_checkin(c) for c in records], limit, offset)


@bp.post("/api/new-hires")
def create_new_hire():
    require_roles("HRAdmin")
    body = get_body()
    full_name = as_str(req_present(body, "full_name"), "full_name")
    personal_email = as_str(req_present(body, "personal_email"),
                            "personal_email")
    start_d = as_date(req_present(body, "start_date"), "start_date")
    department = as_str(req_present(body, "department"), "department")
    rec = new_record("new_hires", {
        "full_name": full_name,
        "personal_email": personal_email,
        "start_date": start_d.isoformat(),
        "department": department,
        "status": "REGISTERED",
        "_start_d": start_d,
    })
    return success(ser_new_hire(rec), 201)


@bp.get("/api/new-hires/<nid>")
def get_new_hire(nid):
    require_roles(*ALL_ROLES)
    rec = get_or_404("new_hires", nid, ERR_NEW_HIRE_NOT_FOUND, "NewHire")
    return success(ser_new_hire(rec))
