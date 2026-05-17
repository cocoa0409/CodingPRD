"""Employee routes."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import (
    ROLE_PAYROLL_MANAGER,
    ROLE_PAYROLL_SPECIALIST,
    ROLE_TREASURER,
    require_roles,
)
from ..clock import current_date, date_iso, now_iso
from ..errors import (
    err_employee_not_found,
    err_invalid_request,
    err_pending_paychecks,
)
from ..helpers import (
    assert_enum,
    assert_integer,
    assert_string,
    new_uuid,
    occ_check,
    paginate,
    parse_iso_date,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.lookups import employee_has_pending_paycheck
from ..services.serialize import serialize_employee
from ..store import store

bp = Blueprint("employees", __name__)


VALID_WORK_STATES = ["CA", "NY", "TX", "IL", "PA"]
VALID_WORK_LOCALITIES = ["NYC", "PHL", "NONE"]


def _get_employee_or_404(employee_id: str) -> dict:
    emp = store().employees.get(employee_id)
    if emp is None:
        raise err_employee_not_found()
    return emp


@bp.post("/employees")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER)
def create_employee(**_kw):
    body = require_json_object()
    full_name = assert_string(body.get("full_name"), "full_name")
    hire_date = parse_iso_date(body.get("hire_date"), "hire_date")
    work_state = assert_enum(body.get("work_state"), "work_state", VALID_WORK_STATES)
    work_locality = body.get("work_locality")
    if work_locality is None:
        work_locality = "NONE"
    work_locality = assert_enum(work_locality, "work_locality", VALID_WORK_LOCALITIES)
    hourly_rate_cents = assert_integer(body.get("hourly_rate_cents"), "hourly_rate_cents", minimum=0)

    s = store()
    with s.lock:
        ts = now_iso()
        emp_id = new_uuid()
        emp = {
            "id": emp_id,
            "full_name": full_name,
            "hire_date": hire_date.isoformat(),
            "work_state": work_state,
            "work_locality": work_locality,
            "hourly_rate_cents": hourly_rate_cents,
            "ytd_gross_wages_cents": 0,
            "ytd_social_security_wages_cents": 0,
            "ytd_medicare_wages_cents": 0,
            "status": "ACTIVE",
            "termination_date": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "created_seq": s.next_seq(),
        }
        s.employees[emp_id] = emp
    return created(serialize_employee(emp))


@bp.get("/employees")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def list_employees(**_kw):
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    with store().lock:
        items = list(store().employees.values())
        if status_filter is not None:
            items = [e for e in items if e["status"] == status_filter]
        items.sort(key=lambda e: (e["created_at"], e["created_seq"]))
        total = len(items)
        page = paginate(items, limit, offset)
        return listing([serialize_employee(e) for e in page], total, limit, offset)


@bp.get("/employees/<employee_id>")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def get_employee(employee_id: str, **_kw):
    with store().lock:
        emp = _get_employee_or_404(employee_id)
        return ok(serialize_employee(emp))


@bp.post("/employees/<employee_id>/terminate")
@require_roles(ROLE_PAYROLL_MANAGER)
def terminate_employee(employee_id: str, **_kw):
    body = require_json_object()
    version = body.get("version")
    with store().lock:
        emp = _get_employee_or_404(employee_id)
        occ_check(version, emp["version"])
        if employee_has_pending_paycheck(employee_id):
            raise err_pending_paychecks()
        emp["status"] = "TERMINATED"
        emp["termination_date"] = date_iso(current_date())
        emp["updated_at"] = now_iso()
        emp["version"] = emp["version"] + 1
        return ok(serialize_employee(emp))
