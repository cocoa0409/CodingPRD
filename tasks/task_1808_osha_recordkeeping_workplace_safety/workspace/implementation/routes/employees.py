"""Employee endpoints (PRD §3.1)."""
from flask import Blueprint

from db import STORE
from middleware import get_auth, require_roles, ALL_ROLES, RATES_READ_ROLES
from response import success_object, success_list
from services.core import (get_body, req_str, opt_str, opt_enum, req_date,
                           base_fields, serialize, serialize_case, lookup,
                           paginated, query_int, bump)

bp = Blueprint("employees", __name__)

EMPLOYMENT_STATUSES = ("ACTIVE", "SEPARATED")
EMPLOYEE_WRITE_ROLES = ("PlatformAdmin", "RecordkeepingCoordinator")


@bp.post("/safety/employees")
def create_employee():
    auth = get_auth()
    require_roles(auth, EMPLOYEE_WRITE_ROLES)
    data = get_body()
    company_id = req_str(data, "company_id")
    full_name = req_str(data, "full_name", non_empty=True)
    job_title = req_str(data, "job_title", non_empty=True)
    hire = req_date(data, "hire_date")
    status = opt_enum(data, "employment_status", EMPLOYMENT_STATUSES, "ACTIVE")
    lookup(STORE.companies, company_id)
    emp = base_fields()
    emp.update({
        "company_id": company_id,
        "full_name": full_name,
        "job_title": job_title,
        "hire_date": hire.isoformat(),
        "employment_status": status,
    })
    STORE.employees[emp["id"]] = emp
    return success_object(serialize(emp), status=201)


@bp.get("/safety/employees/<employeeId>")
def get_employee(employeeId):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    emp = lookup(STORE.employees, employeeId)
    return success_object(serialize(emp))


@bp.patch("/safety/employees/<employeeId>")
def update_employee(employeeId):
    auth = get_auth()
    require_roles(auth, EMPLOYEE_WRITE_ROLES)
    emp = lookup(STORE.employees, employeeId)
    data = get_body()
    full_name = opt_str(data, "full_name", non_empty=True)
    job_title = opt_str(data, "job_title", non_empty=True)
    status = opt_enum(data, "employment_status", EMPLOYMENT_STATUSES)
    if full_name is not None:
        emp["full_name"] = full_name
    if job_title is not None:
        emp["job_title"] = job_title
    if status is not None:
        emp["employment_status"] = status
    # Marking SEPARATED closes day counting on the employee's non-FINALIZED
    # cases; day_count_closed is derived from employment status at read time.
    bump(emp)
    return success_object(serialize(emp))


@bp.get("/safety/employees/<employeeId>/cases")
def list_employee_cases(employeeId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.employees, employeeId)
    log_year = query_int("log_year")
    items = [c for c in STORE.cases.values()
             if c["employee_id"] == employeeId
             and (log_year is None or c["log_year"] == log_year)]
    page, limit, offset, total = paginated(items)
    return success_list([serialize_case(c) for c in page], limit, offset, total)
