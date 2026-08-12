"""People routes: employees, fit tests, manager overrides."""
from datetime import timedelta

from flask import Blueprint, g

import db
from auth import require_roles
from envelope import ok, ok_list
from errors import err
from helpers import (FIT_TEST_VALIDITY_DAYS, body, get_or_404, opt_bool,
                     opt_str, paged, pagination_params, qparam, req_date,
                     req_enum, req_int, req_str)
from util import new_id, new_record, now_iso, parse_date, touch

bp = Blueprint("people", __name__)

REASON_CODES = {"MEDICAL", "NEW_HIRE", "INCIDENT", "PROJECT", "OTHER"}
EMP_STATUSES = {"ACTIVE", "SUSPENDED", "TERMINATED"}


def override_out(o):
    """Serialize an override with the status-aware remaining_qty."""
    if o["status"] == "REVOKED":
        remaining = 0
    else:
        remaining = o["approved_qty"] - o["consumed_qty"]
    out = dict(o)
    out["remaining_qty"] = remaining
    return out


# --- Employee --------------------------------------------------------------

@bp.post("/employees")
def create_employee():
    require_roles("EHSAdministrator")
    b = body()
    code = req_str(b, "employee_code")
    full_name = req_str(b, "full_name")
    job_role_id = req_str(b, "job_role_id")
    home_cc = req_str(b, "home_cost_center_id")
    is_manager = opt_bool(b, "is_manager")
    get_or_404(db.job_roles, job_role_id, "ERR_JOB_ROLE_NOT_FOUND")
    get_or_404(db.cost_centers, home_cc, "ERR_COST_CENTER_NOT_FOUND")
    if any(e["employee_code"] == code for e in db.employees.values()):
        err("ERR_DUPLICATE_EMPLOYEE_CODE", "employee_code already exists")
    rec = new_record({
        "employee_code": code,
        "full_name": full_name,
        "job_role_id": job_role_id,
        "home_cost_center_id": home_cc,
        "is_manager": bool(is_manager) if is_manager is not None else False,
        "fit_tests": [],
        "status": "ACTIVE",
    })
    db.employees[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/employees")
def list_employees():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.employees.values())
    jr = qparam("job_role_id")
    cc = qparam("cost_center_id") or qparam("home_cost_center_id")
    st = qparam("status")
    if jr is not None:
        rows = [e for e in rows if e["job_role_id"] == jr]
    if cc is not None:
        rows = [e for e in rows if e["home_cost_center_id"] == cc]
    if st is not None:
        rows = [e for e in rows if e["status"] == st]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/employees/<employeeId>")
def get_employee(employeeId):
    require_roles("Any")
    return ok(get_or_404(db.employees, employeeId, "ERR_EMPLOYEE_NOT_FOUND"))


@bp.put("/employees/<employeeId>")
def update_employee(employeeId):
    require_roles("EHSAdministrator")
    b = body()
    status = opt_str(b, "status")
    if status is not None and status not in EMP_STATUSES:
        err("ERR_VALIDATION_FAILED", "invalid status")
    job_role_id = opt_str(b, "job_role_id")
    home_cc = opt_str(b, "home_cost_center_id")
    is_manager = opt_bool(b, "is_manager")
    emp = get_or_404(db.employees, employeeId, "ERR_EMPLOYEE_NOT_FOUND")
    if job_role_id is not None:
        get_or_404(db.job_roles, job_role_id, "ERR_JOB_ROLE_NOT_FOUND")
    if home_cc is not None:
        get_or_404(db.cost_centers, home_cc, "ERR_COST_CENTER_NOT_FOUND")
    if status is not None:
        cur = emp["status"]
        allowed = ((cur == "ACTIVE" and status in ("SUSPENDED", "TERMINATED"))
                   or (cur == "SUSPENDED" and status in ("ACTIVE", "TERMINATED")))
        if not allowed:
            err("ERR_INVALID_STATE", "employee status transition %s -> %s not allowed"
                % (cur, status))
        emp["status"] = status
        if status == "TERMINATED":
            # cascade: revoke this employee's ACTIVE overrides
            for o in db.overrides.values():
                if o["employee_id"] == employeeId and o["status"] == "ACTIVE":
                    o["status"] = "REVOKED"  # consumed_qty preserved
                    touch(o)
    if job_role_id is not None:
        emp["job_role_id"] = job_role_id
    if home_cc is not None:
        emp["home_cost_center_id"] = home_cc
    if is_manager is not None:
        emp["is_manager"] = is_manager
    touch(emp)
    return ok(emp)


@bp.post("/employees/<employeeId>/fit-tests")
def create_fit_test(employeeId):
    require_roles("SafetyOfficer")
    b = body()
    item_id = req_str(b, "item_id")
    tested_on = req_date(b, "tested_on")
    result = req_enum(b, "result", {"PASS", "FAIL"})
    emp = get_or_404(db.employees, employeeId, "ERR_EMPLOYEE_NOT_FOUND")
    get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    tested_date = parse_date(tested_on)
    if result == "PASS":
        expires = tested_date + timedelta(days=FIT_TEST_VALIDITY_DAYS)
    else:
        expires = tested_date
    entry = {
        "fit_test_id": new_id(),
        "item_id": item_id,
        "tested_on": tested_on,
        "result": result,
        "expires_on": expires.isoformat(),
        "status": "VALID",
        "_seq": db.next_seq(),
        "_created_at": now_iso(),
    }
    emp["fit_tests"].append(entry)
    touch(emp)
    return ok(emp, 201)


# --- ManagerOverride -------------------------------------------------------

@bp.post("/manager-overrides")
def create_override():
    require_roles("Manager")
    b = body()
    employee_id = req_str(b, "employee_id")
    item_id = req_str(b, "item_id")
    approved = req_int(b, "approved_qty", minimum=1)
    valid_from = req_date(b, "valid_from")
    valid_until = req_date(b, "valid_until")
    reason = req_enum(b, "reason_code", REASON_CODES)
    if parse_date(valid_until) < parse_date(valid_from):
        err("ERR_VALIDATION_FAILED", "valid_until must be >= valid_from")
    get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    get_or_404(db.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
    # window separation: >= 1 full calendar day between closed intervals
    nf, nu = parse_date(valid_from), parse_date(valid_until)
    for o in db.overrides.values():
        if (o["employee_id"] == employee_id and o["item_id"] == item_id
                and o["status"] == "ACTIVE"):
            of, ou = parse_date(o["valid_from"]), parse_date(o["valid_until"])
            if not (nf >= ou + timedelta(days=2) or nu <= of - timedelta(days=2)):
                err("ERR_OVERRIDE_WINDOW_OVERLAP",
                    "override window too close to an existing ACTIVE override")
    # segregation of duties: grantor != grantee
    if g.user_id == employee_id:
        err("ERR_SELF_OVERRIDE_FORBIDDEN", "manager cannot grant an override to self")
    rec = new_record({
        "employee_id": employee_id,
        "item_id": item_id,
        "approved_qty": approved,
        "consumed_qty": 0,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "reason_code": reason,
        "granted_by_user_id": g.user_id,
        "status": "ACTIVE",
    })
    db.overrides[rec["id"]] = rec
    return ok(override_out(rec), 201)


@bp.get("/manager-overrides")
def list_overrides():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.overrides.values())
    emp = qparam("employee_id")
    it = qparam("item_id")
    st = qparam("status")
    if emp is not None:
        rows = [o for o in rows if o["employee_id"] == emp]
    if it is not None:
        rows = [o for o in rows if o["item_id"] == it]
    if st is not None:
        rows = [o for o in rows if o["status"] == st]
    page, total = paged(rows, limit, offset)
    return ok_list([override_out(o) for o in page], limit, offset, total)


@bp.get("/manager-overrides/<overrideId>")
def get_override(overrideId):
    require_roles("Any")
    o = get_or_404(db.overrides, overrideId, "ERR_MANAGER_OVERRIDE_NOT_FOUND")
    return ok(override_out(o))


@bp.post("/manager-overrides/<overrideId>/revoke")
def revoke_override(overrideId):
    require_roles("Manager")
    body()
    o = get_or_404(db.overrides, overrideId, "ERR_MANAGER_OVERRIDE_NOT_FOUND")
    if o["status"] != "ACTIVE":
        err("ERR_OVERRIDE_NOT_ACTIVE", "override is not ACTIVE")
    o["status"] = "REVOKED"  # consumed_qty preserved; remaining reads 0
    touch(o)
    return ok(override_out(o))
