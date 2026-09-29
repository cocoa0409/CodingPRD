"""Payroll periods and contribution records (PRD 3.3)."""

from flask import Blueprint, request

import db
from errors import fail
from middleware import auth, body, req_enum, req_int, req_str, req_ts
from response import object_response, paginated
from services import calc, lookup, serialize

bp = Blueprint("payroll", __name__)

PERIOD_STATUSES = ("OPEN", "CLOSED", "FUNDED")


@bp.post("/payroll-periods")
def create_payroll_period():
    auth("PayrollOperator")
    payload = body()
    plan_year_id = req_str(payload, "plan_year_id")
    period_number = req_int(payload, "period_number", minimum=1)
    start_date, start_dt = req_ts(payload, "start_date")
    end_date, end_dt = req_ts(payload, "end_date")
    pay_date, pay_dt = req_ts(payload, "pay_date")
    plan_year = lookup.plan_year(plan_year_id)

    for existing in calc.periods_of_plan_year(plan_year["id"]):
        if existing["period_number"] == period_number:
            fail("ERR_DUPLICATE_PERIOD_RESOURCE",
                 "period_number %d already exists in this plan year"
                 % period_number)

    row = {
        "plan_year_id": plan_year["id"],
        "period_number": period_number,
        "start_date": start_date,
        "end_date": end_date,
        "pay_date": pay_date,
        "status": "OPEN",
        "reopen_count": 0,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "_pay_dt": pay_dt,
    }
    db.stamp_new(row)
    db.db.payroll_periods[row["id"]] = row
    return object_response(serialize.payroll_period(row), 201)


@bp.get("/payroll-periods")
def list_payroll_periods():
    auth("PayrollOperator", "BenefitsAdministrator", "ComplianceAuditor",
         "Recordkeeper")
    rows = db.rows("payroll_periods")
    plan_year_id = request.args.get("plan_year_id")
    if plan_year_id:
        rows = [r for r in rows if r["plan_year_id"] == plan_year_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, serialize.payroll_period)


@bp.get("/payroll-periods/<payroll_period_id>")
def get_payroll_period(payroll_period_id):
    auth("PayrollOperator", "BenefitsAdministrator", "ComplianceAuditor",
         "Recordkeeper")
    return object_response(serialize.payroll_period(
        lookup.payroll_period(payroll_period_id)))


@bp.post("/payroll-periods/<payroll_period_id>/status")
def set_payroll_period_status(payroll_period_id):
    auth("PayrollOperator")
    payload = body()
    to_status = req_enum(payload, "to_status", PERIOD_STATUSES)
    period = lookup.payroll_period(payroll_period_id)
    current = period["status"]
    transition = (current, to_status)

    if transition not in (("OPEN", "CLOSED"), ("CLOSED", "OPEN")):
        fail("ERR_PERIOD_ALREADY_FUNDED",
             "payroll period cannot move from %s to %s" % (current, to_status))

    plan_year = db.db.plan_years.get(period["plan_year_id"])
    if plan_year is None or plan_year["status"] not in ("OPEN", "LOCKED"):
        fail("ERR_PLAN_YEAR_LOCKED",
             "the owning plan year does not accept payroll period changes")

    if transition == ("CLOSED", "OPEN"):
        for batch in db.rows("funding_batches"):
            if (batch["payroll_period_id"] == period["id"]
                    and batch["status"] in ("TRANSMITTED", "SETTLED")):
                fail("ERR_PERIOD_HAS_SETTLED_FUNDING",
                     "funding of this period is already in flight")
        period["reopen_count"] += 1

    period["status"] = to_status
    db.touch(period)
    return object_response(serialize.payroll_period(period))


# --------------------------------------------------------------------------
# contribution records
# --------------------------------------------------------------------------

@bp.post("/contribution-records")
def create_contribution_record():
    auth("PayrollOperator")
    payload = body()
    employee_id = req_str(payload, "employee_id")
    payroll_period_id = req_str(payload, "payroll_period_id")
    eligible = req_int(payload, "eligible_compensation_cents", minimum=0)
    deferral = req_int(payload, "elective_deferral_cents", minimum=0)
    employee = lookup.employee(employee_id)
    period = lookup.payroll_period(payroll_period_id)

    plan_year = db.db.plan_years.get(period["plan_year_id"])
    if plan_year is None or plan_year["status"] != "OPEN":
        fail("ERR_PLAN_YEAR_LOCKED",
             "the payroll line's plan year is not OPEN")
    if period["status"] != "OPEN":
        fail("ERR_PERIOD_ALREADY_FUNDED",
             "the payroll period no longer accepts payroll lines")

    for existing in db.rows("contribution_records"):
        if (existing["employee_id"] == employee["id"]
                and existing["payroll_period_id"] == period["id"]):
            fail("ERR_DUPLICATE_CONTRIBUTION_RECORD",
                 "a payroll line already exists for this employee and period")

    computed = calc.deferral_match_per_period(
        plan_year=plan_year,
        employee_id=employee["id"],
        period_number=period["period_number"],
        eligible_cents=eligible,
        deferral_cents=deferral,
    )
    row = {
        "employee_id": employee["id"],
        "payroll_period_id": period["id"],
        "eligible_compensation_cents": eligible,
        "elective_deferral_cents": deferral,
        "counted_compensation_cents": computed["counted_compensation_cents"],
        "deferral_match_cents": computed["deferral_match_cents"],
        "qslp_space_tier1_cents": computed["qslp_space_tier1_cents"],
        "qslp_space_tier2_cents": computed["qslp_space_tier2_cents"],
        "_plan_year_id": plan_year["id"],
        "_period_number": period["period_number"],
    }
    db.stamp_new(row)
    db.db.contribution_records[row["id"]] = row

    db.touch(period)
    db.touch(plan_year)
    db.touch(employee)
    # PRD 3.3 -- posting a line for a period that starts on or after the
    # rehire date closes the rehire loop.
    if (employee["employment_status"] == "REHIRED"
            and employee["_rehire_dt"] is not None
            and period["_start_dt"] >= employee["_rehire_dt"]):
        employee["employment_status"] = "ACTIVE"
        db.touch(employee)

    return object_response(serialize.contribution_record(row), 201)


@bp.get("/contribution-records")
def list_contribution_records():
    auth("PayrollOperator", "BenefitsAdministrator", "ComplianceAuditor")
    rows = db.rows("contribution_records")
    employee_id = request.args.get("employee_id")
    if employee_id:
        rows = [r for r in rows if r["employee_id"] == employee_id]
    payroll_period_id = request.args.get("payroll_period_id")
    if payroll_period_id:
        rows = [r for r in rows
                if r["payroll_period_id"] == payroll_period_id]
    return paginated(rows, serialize.contribution_record)


@bp.get("/contribution-records/<contribution_record_id>")
def get_contribution_record(contribution_record_id):
    auth("PayrollOperator", "BenefitsAdministrator", "ComplianceAuditor")
    row = lookup.audit_row("contribution_records", contribution_record_id)
    return object_response(serialize.contribution_record(row))
