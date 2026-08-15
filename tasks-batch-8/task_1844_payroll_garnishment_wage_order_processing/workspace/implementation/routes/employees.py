"""Employee roster and separation (PRD §3.2)."""

from flask import Blueprint

from db import logical_now, next_seq, store
from errors import (
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    fail,
)
from middleware import (
    ALL_ROLES,
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_SPECIALIST,
    authorize,
    get_body,
    pagination,
    public,
    req_date,
    req_enum,
    req_int,
    req_str,
    sort_created,
)
from response import list_response, object_response
from routes.employers import get_employer_or_404
from services import audit
from util import new_uuid, render_instant

bp = Blueprint("employees", __name__)

PAY_FREQUENCIES = ("WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY")


def get_employee_or_404(employee_id):
    employee = store.employees.get(employee_id)
    if employee is None:
        fail(ERR_NOT_FOUND, 404, "Employee '%s' does not exist." % employee_id)
    return employee


@bp.post("/employees")
def create_employee():
    authorize(ROLE_ADMIN, ROLE_SPECIALIST)
    body = get_body()
    employer_id = req_str(body, "employer_id")
    full_name = req_str(body, "full_name")
    work_state_code = req_str(body, "work_state_code")
    pay_frequency = req_enum(body, "pay_frequency", PAY_FREQUENCIES)
    hourly_rate_cents = req_int(body, "hourly_rate_cents")
    expected_employer_version = req_int(body, "expected_employer_version")
    if hourly_rate_cents < 0:
        from errors import ERR_INVALID_REQUEST
        fail(ERR_INVALID_REQUEST, 400, "hourly_rate_cents must be >= 0.")

    employer = store.employers.get(employer_id)
    if employer is None:
        fail(ERR_NOT_FOUND, 404, "Employer '%s' does not exist." % employer_id)

    # OCC (§2.7): expected_employer_version must match the current version.
    if expected_employer_version != employer["version"]:
        fail(ERR_STALE_VERSION, 412,
             "expected_employer_version %s does not match current employer version %s."
             % (expected_employer_version, employer["version"]))

    now = render_instant(logical_now())
    employee = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "employer_id": employer_id,
        "full_name": full_name,
        "work_state_code": work_state_code,
        "pay_frequency": pay_frequency,
        "hourly_rate_cents": hourly_rate_cents,
        "termination_date": None,
        "_seq": next_seq(),
    }
    store.employees[employee["id"]] = employee

    # Cascade: Employer.version += 1.
    employer["version"] += 1
    employer["updated_at"] = now
    audit.append_audit(employer_id, "Employee", employee["id"], "employee.create",
                       details={"employer_id": employer_id, "full_name": full_name})
    return object_response(public(employee), 201)


@bp.get("/employees/<employeeId>")
def get_employee(employeeId):
    authorize(*ALL_ROLES)
    return object_response(public(get_employee_or_404(employeeId)))


@bp.post("/employees/<employeeId>/terminate")
def terminate_employee(employeeId):
    authorize(ROLE_MANAGER)
    employee = get_employee_or_404(employeeId)
    body = get_body()
    termination_date = req_date(body, "termination_date")
    if employee["termination_date"] is not None:
        fail(ERR_INVALID_STATE, 409,
             "Employee '%s' already has termination_date set; it is immutable."
             % employeeId)

    employee["termination_date"] = termination_date
    employee["version"] += 1
    employee["updated_at"] = render_instant(logical_now())
    # Does NOT auto-terminate orders; that requires explicit per-order acts.
    audit.append_audit(employee["employer_id"], "Employee", employee["id"],
                       "employee.terminate",
                       details={"termination_date": termination_date})
    return object_response(public(employee))


@bp.get("/employees/<employeeId>/orders")
def list_employee_orders(employeeId):
    authorize(*ALL_ROLES)
    get_employee_or_404(employeeId)
    limit, offset = pagination()
    items = sort_created(
        [o for o in store.orders.values() if o["employee_id"] == employeeId]
    )
    page = items[offset:offset + limit]
    return list_response([public(o) for o in page], len(items), limit, offset)
