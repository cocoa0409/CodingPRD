"""Payroll runs: open/include/finalize/cancel (PRD §3.9)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import object_response, array_response
from util import as_int, as_str, body, paginate, pagination, parse_date_str, public, public_list
from services.helpers import get_or_404

bp = Blueprint("payroll", __name__)


@bp.post("/payroll-runs")
def create_payroll_run():
    require_role("PayrollAdmin")
    data = body()
    employer_id = as_str(data, "employer_id", required=True)
    period_start = parse_date_str(data, "period_start", required=True)
    period_end = parse_date_str(data, "period_end", required=True)

    # period_end >= period_start.
    if period_end < period_start:
        raise err("ERR_INVALID_REQUEST", "period_end must be on or after period_start.")

    get_or_404(db.employers, employer_id)

    record = db.base_fields()
    record.update({
        "employer_id": employer_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "total_gross_cents": 0,
        "included_week_count": 0,
    })
    db.payroll_runs[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/payroll-runs")
def list_payroll_runs():
    require_role("PayrollAdmin", "Supervisor")
    limit, offset = pagination()
    employer_id = request.args.get("employer_id")
    status = request.args.get("status")
    matches = list(db.payroll_runs.values())
    if employer_id is not None:
        matches = [r for r in matches if r.get("employer_id") == employer_id]
    if status is not None:
        matches = [r for r in matches if r.get("status") == status]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/payroll-runs/<run_id>")
def get_payroll_run(run_id):
    require_role("PayrollAdmin", "Supervisor")
    record = get_or_404(db.payroll_runs, run_id)
    return object_response(public(record))


@bp.post("/payroll-runs/<run_id>/include")
def include_week(run_id):
    require_role("PayrollAdmin")
    run = get_or_404(db.payroll_runs, run_id)
    data = body()
    timesheet_week_id = as_str(data, "timesheet_week_id", required=True)

    # Existence of the week (priority 4), left-to-right after the run path id.
    week = get_or_404(db.timesheet_weeks, timesheet_week_id)

    # State: week must be APPROVED, and run must be OPEN (priority 7).
    if run.get("status") != "OPEN":
        raise err("ERR_INVALID_STATE", "Payroll run is not OPEN.")
    if week.get("status") != "APPROVED":
        raise err("ERR_INVALID_STATE", "Timesheet week is not APPROVED.")

    # Week must fall within the run's period (priority 19).
    if not (run["period_start"] <= week["workweek_start"] <= run["period_end"]):
        raise err("ERR_WEEK_OUTSIDE_PERIOD",
                  "Week's workweek_start is outside the run period.")

    # OCC: expected_timesheet_week_version matches current version (priority 21).
    expected = as_int(data, "expected_timesheet_week_version", required=True)
    if expected != week.get("version"):
        raise err("ERR_STALE_VERSION",
                  "expected_timesheet_week_version does not match current version.")

    # Lock the week into the run.
    week["payroll_run_id"] = run_id
    week["status"] = "LOCKED"
    db.touch(week)

    run["included_week_count"] = run.get("included_week_count", 0) + 1
    run["total_gross_cents"] = run.get("total_gross_cents", 0) + week.get("gross_wages_cents", 0)
    db.touch(run)
    return object_response(public(run))


@bp.post("/payroll-runs/<run_id>/finalize")
def finalize_run(run_id):
    require_role("PayrollAdmin")
    run = get_or_404(db.payroll_runs, run_id)

    # State: OPEN (priority 7).
    if run.get("status") != "OPEN":
        raise err("ERR_INVALID_STATE", "Payroll run is not OPEN.")

    # At least one LOCKED week (priority 18).
    locked = [
        w for w in db.timesheet_weeks.values()
        if w.get("payroll_run_id") == run_id and w.get("status") == "LOCKED"
    ]
    if not locked:
        raise err("ERR_EMPTY_PAYROLL_RUN", "Payroll run has no LOCKED week.")

    run["status"] = "FINALIZED"
    db.touch(run)
    return object_response(public(run))


@bp.post("/payroll-runs/<run_id>/cancel")
def cancel_run(run_id):
    require_role("PayrollAdmin")
    run = get_or_404(db.payroll_runs, run_id)

    # State: OPEN (priority 7).
    if run.get("status") != "OPEN":
        raise err("ERR_INVALID_STATE", "Payroll run is not OPEN.")

    # Revert each LOCKED week to APPROVED; clear payroll_run_id (cascade).
    for w in db.timesheet_weeks.values():
        if w.get("payroll_run_id") == run_id and w.get("status") == "LOCKED":
            w["status"] = "APPROVED"
            w["payroll_run_id"] = None
            db.touch(w)

    run["total_gross_cents"] = 0
    run["included_week_count"] = 0
    run["status"] = "CANCELLED"
    db.touch(run)
    return object_response(public(run))
