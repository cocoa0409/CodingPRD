"""Employees, employment events, the audit packet and leave events
(PRD 3.2, 3.7, 3.9)."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import fail
from middleware import auth, body, opt_int, req_enum, req_int, req_str, req_ts
from response import object_response, paginated
from services import calc, effects, lookup, serialize

bp = Blueprint("employees", __name__)

LEAVE_TYPES = ("UNPAID", "PAID_FMLA", "MILITARY")
EVENT_TYPES = ("TERMINATE", "REHIRE")


@bp.post("/employees")
def create_employee():
    auth("BenefitsAdministrator")
    payload = body()
    external_id = req_str(payload, "external_id")
    hire_date, hire_dt = req_ts(payload, "hire_date")
    prior_comp = req_int(payload, "prior_year_compensation_cents", minimum=0)
    months = opt_int(payload, "vesting_service_months", 0, minimum=0)
    for existing in db.db.employees.values():
        if existing["external_id"] == external_id:
            fail("ERR_INVALID_REQUEST",
                 "external_id %s already exists" % external_id)
    row = {
        "external_id": external_id,
        "hire_date": hire_date,
        "prior_year_compensation_cents": prior_comp,
        "vesting_service_months": months,
        "employment_status": "ACTIVE",
        "termination_date": None,
        "rehire_date": None,
        "_hire_dt": hire_dt,
        "_termination_dt": None,
        "_rehire_dt": None,
    }
    db.stamp_new(row)
    db.db.employees[row["id"]] = row
    return object_response(serialize.employee(row), 201)


@bp.get("/employees")
def list_employees():
    _user_id, role = auth("BenefitsAdministrator", "PayrollOperator",
                          "ComplianceAuditor")
    rows = db.rows("employees")
    status = request.args.get("employment_status")
    external_id = request.args.get("external_id")
    hce = request.args.get("hce_flag")
    if external_id:
        rows = [r for r in rows if r["external_id"] == external_id]
    if status:
        rows = [r for r in rows if r["employment_status"] == status]
    if hce is not None and hce != "":
        wanted = str(hce).strip().lower()
        if wanted not in ("true", "false"):
            fail("ERR_INVALID_REQUEST", "hce_flag must be true or false")
        wanted_bool = wanted == "true"
        rows = [r for r in rows if calc.hce_flag(r) == wanted_bool]
    return paginated(rows, serialize.employee)


@bp.get("/employees/<employee_id>")
def get_employee(employee_id):
    user_id, role = auth("BenefitsAdministrator", "PayrollOperator",
                         "ComplianceAuditor", "Employee")
    row = lookup.employee(employee_id)
    lookup.require_owner(role, user_id, row["id"])
    return object_response(serialize.employee(row))


@bp.post("/employees/<employee_id>/employment-events")
def employment_event(employee_id):
    auth("BenefitsAdministrator")
    payload = body()
    event_type = req_enum(payload, "event_type", EVENT_TYPES)
    effective_date, effective_dt = req_ts(payload, "effective_date")
    employee = lookup.employee(employee_id)

    if event_type == "TERMINATE":
        if employee["employment_status"] not in ("ACTIVE", "LEAVE_UNPAID",
                                                 "LEAVE_PAID", "REHIRED"):
            fail("ERR_INVALID_REQUEST",
                 "employee cannot be terminated from %s"
                 % employee["employment_status"])
        employee["employment_status"] = "TERMINATED"
        employee["termination_date"] = effective_date
        employee["_termination_dt"] = effective_dt
        effects.run_vesting_and_forfeiture(employee)
    else:
        if employee["employment_status"] != "TERMINATED":
            fail("ERR_INVALID_REQUEST",
                 "only a TERMINATED employee may be rehired")
        if (employee["_termination_dt"] is None
                or effective_dt <= employee["_termination_dt"]):
            fail("ERR_INVALID_REQUEST",
                 "rehire effective_date must be strictly after "
                 "termination_date")
        employee["employment_status"] = "REHIRED"
        employee["rehire_date"] = effective_date
        employee["_rehire_dt"] = effective_dt

    db.touch(employee)
    return object_response(serialize.employee(employee))


@bp.get("/employees/<employee_id>/audit-packet")
def audit_packet(employee_id):
    auth("ComplianceAuditor", "BenefitsAdministrator")
    employee = lookup.employee(employee_id)

    plan_year = calc.open_plan_year()
    if plan_year is None:
        locked = [p for p in db.rows("plan_years") if p["status"] == "LOCKED"]
        if locked:
            locked.sort(key=lambda p: p["year"])
            plan_year = locked[-1]

    if plan_year is None:
        return object_response({
            "plan_year_id": None,
            "certification_count": 0,
            "accepted_certified_cents": 0,
            "deferral_match_cents": 0,
            "qslp_match_cents": 0,
            "forfeited_cents": 0,
            "correction_cents": 0,
            "remaining_space_cents": calc.remaining_qslp_space(employee["id"]),
        })

    py_id = plan_year["id"]
    certs = calc.certifications_of(employee["id"], py_id)
    visible = ("SUBMITTED", "RETURNED", "ACCEPTED", "AUDIT_HOLD", "VOIDED",
               "SUPERSEDED")
    data = {
        "plan_year_id": py_id,
        "certification_count": len([c for c in certs
                                    if c["status"] in visible]),
        "accepted_certified_cents": sum(
            c["eligible_total_cents"] for c in certs
            if c["status"] in calc.CLAIMED_CERT_STATUSES),
        "deferral_match_cents": calc.ytd_deferral_match(employee["id"], py_id),
        "qslp_match_cents": calc.ytd_qslp_match(employee["id"], py_id),
        "forfeited_cents": sum(
            f["amount_cents"] for f in calc.forfeitures_of_plan_year(py_id)
            if f["employee_id"] == employee["id"]),
        "correction_cents": sum(
            a["amount_cents"]
            for a in calc.adjustments_of(employee["id"], py_id)),
        "remaining_space_cents": calc.remaining_qslp_space(employee["id"]),
    }
    return object_response(data)


# --------------------------------------------------------------------------
# leave events
# --------------------------------------------------------------------------

def _leave_plan_year():
    py = calc.open_plan_year()
    if py is not None:
        return py
    years = db.rows("plan_years")
    if not years:
        return None
    return sorted(years, key=lambda p: p["year"])[-1]


@bp.post("/leave-events")
def create_leave_event():
    auth("BenefitsAdministrator", "PayrollOperator")
    payload = body()
    employee_id = req_str(payload, "employee_id")
    leave_type = req_enum(payload, "leave_type", LEAVE_TYPES)
    start_date, start_dt = req_ts(payload, "start_date")
    end_date, end_dt = req_ts(payload, "end_date")
    employee = lookup.employee(employee_id)

    reference = _leave_plan_year()
    buffer_days = (int(reference["leave_merge_buffer_days"])
                   if reference is not None else 14)
    buffer_delta = timedelta(days=buffer_days)

    for existing in db.rows("leave_events"):
        if existing["employee_id"] != employee_id:
            continue
        if (start_dt <= existing["_end_dt"] + buffer_delta
                and end_dt >= existing["_start_dt"] - buffer_delta):
            fail("ERR_LEAVE_WINDOW_CONFLICT",
                 "the leave interval collides with an existing leave")

    open_py = calc.open_plan_year()
    if leave_type == "UNPAID" and open_py is not None:
        projected = calc.unpaid_leave_days_ytd(employee_id, open_py,
                                               extra=(start_dt, end_dt))
        if projected > int(open_py["unpaid_leave_day_cap"]):
            fail("ERR_LEAVE_CAP_EXCEEDED",
                 "the merged unpaid-leave day count would exceed the cap")

    row = {
        "employee_id": employee_id,
        "leave_type": leave_type,
        "start_date": start_date,
        "end_date": end_date,
        "day_count": calc.whole_days_inclusive(start_dt, end_dt),
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    db.stamp_new(row, versioned=False)
    db.db.leave_events[row["id"]] = row

    if (leave_type == "UNPAID"
            and employee["employment_status"] != "TERMINATED"
            and start_dt <= db.now() <= end_dt):
        employee["employment_status"] = "LEAVE_UNPAID"
    db.touch(employee)

    return object_response(serialize.leave_event(row), 201)


@bp.get("/leave-events")
def list_leave_events():
    auth("BenefitsAdministrator", "PayrollOperator", "ComplianceAuditor")
    rows = db.rows("leave_events")
    employee_id = request.args.get("employee_id")
    if employee_id:
        rows = [r for r in rows if r["employee_id"] == employee_id]
    leave_type = request.args.get("leave_type")
    if leave_type:
        rows = [r for r in rows if r["leave_type"] == leave_type]
    return paginated(rows, serialize.leave_event)


@bp.get("/leave-events/<leave_event_id>")
def get_leave_event(leave_event_id):
    auth("BenefitsAdministrator", "PayrollOperator", "ComplianceAuditor")
    row = lookup.audit_row("leave_events", leave_event_id)
    return object_response(serialize.leave_event(row))
