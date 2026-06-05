"""Employee + WaitingPeriod endpoints (PRD §3.1, §2.7)."""
from __future__ import annotations

from flask import Blueprint, request

import clock
import db
import errors as E
from middleware import (
    authenticate, authorize,
    BENEFITS_ADMIN, PAYROLL_OFFICER, COMPLIANCE_OFFICER, DEPENDENT_VERIFIER,
)
import response
from services import common as C
from services import domain as D
from routes._helpers import get_or_404

bp = Blueprint("employees", __name__)

ALL_ROLES = {BENEFITS_ADMIN, PAYROLL_OFFICER, COMPLIANCE_OFFICER, DEPENDENT_VERIFIER}

EMPLOYMENT_TYPES = {"FULL_TIME", "PART_TIME", "SEASONAL"}
PAYROLL_SCHEDULES = {"SEMI_MONTHLY", "BIWEEKLY"}


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------
@bp.route("/employees", methods=["POST"])
def create_employee():
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    body = C.get_body()
    C.require_fields(body, [
        "full_name", "hire_date", "employment_type",
        "payroll_schedule", "monthly_household_income_cents",
    ])
    full_name = C.require_str(body, "full_name")
    hire_date = body["hire_date"]
    C.parse_iso(hire_date)  # validate ISO 8601
    employment_type = C.require_enum(body, "employment_type", EMPLOYMENT_TYPES)
    payroll_schedule = C.require_enum(body, "payroll_schedule", PAYROLL_SCHEDULES)
    income = C.require_nonneg_int(body, "monthly_household_income_cents")

    eligibility = "INELIGIBLE" if employment_type == "SEASONAL" else "WAITING"

    emp = C.new_common_fields()
    emp.update({
        "full_name": full_name,
        "hire_date": hire_date,
        "employment_type": employment_type,
        "payroll_schedule": payroll_schedule,
        "monthly_household_income_cents": income,
        "eligibility_status": eligibility,
        "pay_periods_processed": 0,
    })
    db.employees[emp["id"]] = emp
    return response.ok_object(C.serialize(emp), 201)


@bp.route("/employees/<emp_id>", methods=["GET"])
def get_employee(emp_id):
    role = authenticate()
    authorize(role, ALL_ROLES)
    emp = get_or_404(db.employees, emp_id, "Employee")
    return response.ok_object(C.serialize(emp), 200)


@bp.route("/employees", methods=["GET"])
def list_employees():
    role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = C.parse_pagination()
    employment_type = request.args.get("employment_type")
    eligibility_status = request.args.get("eligibility_status")
    items = list(db.employees.values())
    if employment_type is not None:
        items = [e for e in items if e["employment_type"] == employment_type]
    if eligibility_status is not None:
        items = [e for e in items if e["eligibility_status"] == eligibility_status]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


@bp.route("/employees/<emp_id>/terminate", methods=["POST"])
def terminate_employee(emp_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    emp = get_or_404(db.employees, emp_id, "Employee")
    # State precondition (priority 5): only ELIGIBLE may terminate.
    if emp["eligibility_status"] != "ELIGIBLE":
        raise E.invalid_state("Employee must be ELIGIBLE to terminate")

    clock_date_str = C.date_of(clock.now()).isoformat()
    # Cascade: ACTIVE enrollments -> SUPERSEDED with coverage_end_date = clock date,
    # each emits a TERM carrier feed record.
    for enr in list(db.enrollments.values()):
        if enr["employee_id"] == emp_id and enr["status"] == "ACTIVE":
            D.supersede_enrollment(enr, clock_date_str, None)

    emp["eligibility_status"] = "TERMINATED"
    C.touch(emp)
    return response.ok_object(C.serialize(emp), 200)


# ---------------------------------------------------------------------------
# WaitingPeriod (sub-resource of Employee)
# ---------------------------------------------------------------------------
WINDOW_TYPES = {"INITIAL", "REINSTATEMENT"}


@bp.route("/employees/<emp_id>/waiting-periods", methods=["POST"])
def create_waiting_period(emp_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    emp = get_or_404(db.employees, emp_id, "Employee")
    body = C.get_body()
    C.require_fields(body, ["window_type", "start_date", "end_date"])
    window_type = C.require_enum(body, "window_type", WINDOW_TYPES)
    start_date = body["start_date"]
    end_date = body["end_date"]
    start_dt = C.parse_iso(start_date)
    end_dt = C.parse_iso(end_date)

    # Overlap check (priority 10): half-open [start, end); adjacency end==start ok.
    new_start = C.date_of(start_dt)
    new_end = C.date_of(end_dt)
    for wp in db.waiting_periods.values():
        if wp["employee_id"] != emp_id:
            continue
        ex_start = C.date_of(C.parse_iso(wp["start_date"]))
        ex_end = C.date_of(C.parse_iso(wp["end_date"]))
        # Half-open overlap: new_start < ex_end and ex_start < new_end
        if new_start < ex_end and ex_start < new_end:
            raise E.waiting_period_overlap()

    now = clock.now()
    status = "ELAPSED" if now >= end_dt else "PENDING"

    wp = C.new_common_fields()
    wp.update({
        "employee_id": emp_id,
        "window_type": window_type,
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
    })
    db.waiting_periods[wp["id"]] = wp

    # If the window is born already-elapsed (clock >= end_date), bubble eligibility
    # up to the owning employee just as a clock advance would (PRD §2.7, §3.1).
    if status == "ELAPSED" and emp["employment_type"] != "SEASONAL" \
            and emp["eligibility_status"] == "WAITING":
        emp["eligibility_status"] = "ELIGIBLE"
        C.touch(emp)

    return response.ok_object(C.serialize(wp), 201)


@bp.route("/employees/<emp_id>/waiting-periods", methods=["GET"])
def list_waiting_periods(emp_id):
    role = authenticate()
    authorize(role, ALL_ROLES)
    emp = get_or_404(db.employees, emp_id, "Employee")
    limit, offset = C.parse_pagination()
    items = [w for w in db.waiting_periods.values() if w["employee_id"] == emp_id]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)
