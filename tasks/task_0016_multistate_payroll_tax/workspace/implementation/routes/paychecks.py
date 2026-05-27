"""Paycheck endpoints (create + reads + listings)."""
from flask import Blueprint, request

import db
import response
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_FK_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_EMPLOYEE_NOT_ACTIVE,
    ERR_NO_W4_ON_FILE,
    ERR_PAY_PERIOD_OVERLAP,
)
from middleware import require_roles
from services import serialize, pagination, lookups
from services import validation as V
from services import paycheck_pipeline


bp = Blueprint("paychecks", __name__)


@bp.post("/paychecks")
@require_roles("PayrollPreparer")
def create_paycheck():
    body = V.require_dict(request.get_json(silent=True) or {})
    run_id = V.require_str(body, "paycheck_run_id")
    employee_id = V.require_str(body, "employee_id")
    pay_type = V.require_enum(body, "pay_type", V.PAY_TYPES)

    # Priority 4 — FK existence
    run = db.paycheck_runs.get(run_id)
    if run is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "paycheck_run_id not found")
    employee = db.employees.get(employee_id)
    if employee is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "employee_id not found")

    # Priority 5 — state guard: parent run must be DRAFT
    if run["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "parent PaycheckRun is not in DRAFT")

    # Priority 6 — employee not TERMINATED
    if employee["status"] == "TERMINATED":
        raise APIError(ERR_EMPLOYEE_NOT_ACTIVE, 409, "employee is TERMINATED")

    # Priority 9 — must have a FILED W-4 for pay_date.tax_year
    pay_year = lookups.pay_date_year(run["pay_date"])
    if lookups.effective_w4(employee_id, pay_year) is None:
        raise APIError(ERR_NO_W4_ON_FILE, 422, "employee has no FILED W-4 for the pay year")

    # Priority 11 — pay-period overlap when adding a paycheck for this employee.
    # The new paycheck would bring this employee into the run's interval; check
    # any non-VOID OTHER run that already has a Paycheck for the same employee
    # whose interval overlaps this run's interval.
    for other in db.paycheck_runs.values():
        if other["id"] == run_id:
            continue
        if other["status"] == "VOID":
            continue
        if not _intervals_overlap(run, other):
            continue
        # Other run has any Paycheck for this employee?
        for p in db.paychecks.values():
            if p["paycheck_run_id"] == other["id"] and p["employee_id"] == employee_id:
                raise APIError(ERR_PAY_PERIOD_OVERLAP, 422,
                               "pay-period overlap with existing run")

    regular_h = V.opt_int(body, "regular_hours_e2", 0)
    overtime_h = V.opt_int(body, "overtime_hours_e2", 0)
    double_h = V.opt_int(body, "double_hours_e2", 0)
    retro_amt = V.opt_int(body, "retro_amount_cents", 0)
    hourly_rate = V.opt_int(body, "hourly_rate_cents", 0)

    p = {
        "id": db.new_id(),
        "paycheck_run_id": run_id,
        "employee_id": employee_id,
        "pay_type": pay_type,
        "regular_hours_e2": regular_h,
        "overtime_hours_e2": overtime_h,
        "double_hours_e2": double_h,
        "retro_amount_cents": retro_amt,
        "hourly_rate_cents": hourly_rate,
        "gross_wages_cents": 0,
        "fed_withheld_cents": 0,
        "state_withheld_cents": 0,
        "local_withheld_cents": 0,
        "ss_withheld_cents": 0,
        "medicare_withheld_cents": 0,
        "addl_medicare_cents": 0,
        "garnishment_total_cents": 0,
        "net_pay_cents": 0,
        "status": "PENDING",
        # Internal: track exact ss_taxable amount applied at PAID time for symmetric void.
        "_ss_taxable_applied": 0,
    }
    db.stamp_common(p)

    # Run the withholding pipeline.
    deductions = paycheck_pipeline.compute_paycheck_derived(p)

    # Persist paycheck and child deductions.
    db.paychecks[p["id"]] = p
    for d in deductions:
        ded = {
            "id": db.new_id(),
            "paycheck_id": p["id"],
            "garnishment_order_id": d["garnishment_order_id"],
            "amount_cents": d["amount_cents"],
            "applied_at": None,
        }
        ded["created_at"] = db.now_utc()
        db.garnishment_deductions[ded["id"]] = ded

    # Record exact ss_taxable_applied for void symmetry: this is the value of
    # min(gross, ss_remaining_capacity) at compute time. We can derive it from
    # the formula and pre-paycheck YTD; but the easier exact path is to record
    # what the ytd_ss_wages_cents WOULD increment by at PAID time.
    # At paycheck CREATE time, the employee's ytd_ss_wages_cents has not yet
    # advanced, so the increment that WILL apply at PAID is computed against
    # the same employee state we used for fica_ss. To make void exactly
    # reversible we precompute that increment NOW.
    from services.calculations import ytd_ss_increment
    p["_ss_taxable_applied"] = ytd_ss_increment(
        p["gross_wages_cents"],
        employee["ytd_ss_wages_cents"],
    )

    # Update parent run total_gross_cents
    run["total_gross_cents"] = sum(
        pp["gross_wages_cents"] for pp in db.paychecks.values()
        if pp["paycheck_run_id"] == run_id
    )
    db.bump(run)

    return response.success_object(serialize.paycheck(p), status=201)


def _intervals_overlap(run_a, run_b):
    """Closed-closed interval overlap on pay_period_start/end strings (ISO 8601 string compares)."""
    return (run_a["pay_period_start"] <= run_b["pay_period_end"]
            and run_b["pay_period_start"] <= run_a["pay_period_end"])


@bp.get("/paychecks/<pid>")
@require_roles("PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin", "HRClerk")
def get_paycheck(pid):
    p = db.paychecks.get(pid)
    if not p:
        raise APIError(ERR_NOT_FOUND, 404, "Paycheck not found")
    return response.success_object(serialize.paycheck(p))


@bp.get("/paychecks")
@require_roles("PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin", "HRClerk")
def list_paychecks():
    limit, offset = pagination.parse_limit_offset()
    employee_id = V.opt_str(request.args, "employee_id")
    run_id = V.opt_str(request.args, "paycheck_run_id")
    status = V.opt_enum(request.args, "status", V.PAYCHECK_STATUSES)
    pay_type = V.opt_enum(request.args, "pay_type", V.PAY_TYPES)

    items = list(db.paychecks.values())
    if employee_id:
        items = [p for p in items if p["employee_id"] == employee_id]
    if run_id:
        items = [p for p in items if p["paycheck_run_id"] == run_id]
    if status:
        items = [p for p in items if p["status"] == status]
    if pay_type:
        items = [p for p in items if p["pay_type"] == pay_type]

    page, total = pagination.slice_sorted(items, limit, offset)
    return response.success_array(
        [serialize.paycheck(x) for x in page],
        limit=limit, offset=offset, total_count=total,
    )


# Garnishment deductions under a paycheck (sub-resource listing)
@bp.get("/paychecks/<pid>/garnishment-deductions")
@require_roles("PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin", "HRClerk")
def list_paycheck_deductions(pid):
    if pid not in db.paychecks:
        raise APIError(ERR_NOT_FOUND, 404, "Paycheck not found")
    limit, offset = pagination.parse_limit_offset()
    items = [d for d in db.garnishment_deductions.values() if d["paycheck_id"] == pid]
    page, total = pagination.slice_sorted(items, limit, offset)
    return response.success_array(
        [serialize.garnishment_deduction(x) for x in page],
        limit=limit, offset=offset, total_count=total,
    )
