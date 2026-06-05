"""Weekly timesheet lifecycle: open/submit/approve/reject (PRD §3.6, §3.8)."""
from datetime import date, datetime, timezone

from flask import Blueprint, g, request

import db
from errors import err
from middleware import require_role
from response import object_response, array_response
from util import as_int, as_str, body, paginate, pagination, parse_date_str, public, public_list
from services.helpers import get_or_404, week_dates
from services.wages import has_governing_ruleset, recompute_timesheet

bp = Blueprint("timesheets", __name__)

DOW_INDEX = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


def _is_workweek_boundary(employer, workweek_start):
    """workweek_start must align with an employer workweek boundary (its
    day-of-week must equal employer.workweek_start_dow) (PRD §3.6)."""
    try:
        d = date.fromisoformat(workweek_start)
    except ValueError:
        return False
    dow = employer.get("workweek_start_dow", "MON")
    return d.weekday() == DOW_INDEX.get(dow, 0)


def _editors_of_week(week):
    """The set of editor_user_ids of TimeEdits on any punch in this week."""
    dates = set(week_dates(week["workweek_start"]))
    employee_id = week.get("employee_id")
    punch_ids = {
        p["id"] for p in db.punches.values()
        if p.get("employee_id") == employee_id and p.get("workday_date") in dates
    }
    return {
        e.get("editor_user_id") for e in db.time_edits.values()
        if e.get("punch_id") in punch_ids
    }


def _open_punch_in_week(week):
    """True when an OPEN punch exists for the employee inside the workweek."""
    dates = set(week_dates(week["workweek_start"]))
    employee_id = week.get("employee_id")
    for p in db.punches.values():
        if p.get("employee_id") != employee_id:
            continue
        if p.get("status") != "OPEN":
            continue
        d = _date_of(p.get("clock_in"))
        if d in dates:
            return True
    return False


def _date_of(iso_dt):
    if iso_dt is None:
        return None
    s = iso_dt
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


@bp.post("/timesheet-weeks")
def create_timesheet_week():
    require_role("Supervisor")
    data = body()
    employee_id = as_str(data, "employee_id", required=True)
    workweek_start = parse_date_str(data, "workweek_start", required=True)

    employee = get_or_404(db.employees, employee_id)
    employer = db.employers.get(employee.get("employer_id"))

    # workweek_start must align with an employer workweek boundary.
    if employer is None or not _is_workweek_boundary(employer, workweek_start):
        raise err("ERR_INVALID_REQUEST",
                  "workweek_start must align with an employer workweek boundary.")

    record = db.base_fields()
    record.update({
        "employee_id": employee_id,
        "workweek_start": workweek_start,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "regular_minutes": 0,
        "ot_minutes": 0,
        "dt_minutes": 0,
        "break_premium_hours": 0,
        "gross_wages_cents": 0,
        "tip_true_up_cents": 0,
        "payroll_run_id": None,
    })
    db.timesheet_weeks[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/timesheet-weeks")
def list_timesheet_weeks():
    require_role("PayrollAdmin", "Supervisor", "Employee")
    limit, offset = pagination()
    employee_id = request.args.get("employee_id")
    payroll_run_id = request.args.get("payroll_run_id")
    status = request.args.get("status")
    matches = list(db.timesheet_weeks.values())
    if employee_id is not None:
        matches = [w for w in matches if w.get("employee_id") == employee_id]
    if payroll_run_id is not None:
        matches = [w for w in matches if w.get("payroll_run_id") == payroll_run_id]
    if status is not None:
        matches = [w for w in matches if w.get("status") == status]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/timesheet-weeks/<week_id>")
def get_timesheet_week(week_id):
    require_role("PayrollAdmin", "Supervisor", "Employee")
    record = get_or_404(db.timesheet_weeks, week_id)
    return object_response(public(record))


@bp.post("/timesheet-weeks/<week_id>/submit")
def submit_timesheet_week(week_id):
    require_role("Supervisor")
    week = get_or_404(db.timesheet_weeks, week_id)

    # State: DRAFT or REJECTED (priority 7).
    if week.get("status") not in ("DRAFT", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Timesheet week is not DRAFT or REJECTED.")

    # No governing wage rule set -> ERR_NO_WAGE_RULESET (priority 5).
    employee = db.employees.get(week.get("employee_id"))
    if employee is None or not has_governing_ruleset(employee):
        raise err("ERR_NO_WAGE_RULESET",
                  "No wage rule set governs this employer and state.")

    # No OPEN punch inside the workweek (priority 9).
    if _open_punch_in_week(week):
        raise err("ERR_OPEN_PUNCH_IN_WEEK",
                  "An OPEN punch exists inside the workweek.")

    recompute_timesheet(week)
    week["submitted_by_user_id"] = g.user_id
    week["status"] = "SUBMITTED"
    db.touch(week)
    return object_response(public(week))


@bp.post("/timesheet-weeks/<week_id>/approve")
def approve_timesheet_week(week_id):
    require_role("Supervisor")
    week = get_or_404(db.timesheet_weeks, week_id)
    data = body()

    # State: SUBMITTED (priority 7).
    if week.get("status") != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Timesheet week is not SUBMITTED.")

    # Segregation of duties (priority 20) is checked before OCC per §1.4
    # ordering (priority 20 < 21): approver differs from submitter and from any
    # punch editor in the week.
    if g.user_id == week.get("submitted_by_user_id"):
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Approver must differ from the submitter.")
    if g.user_id in _editors_of_week(week):
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Approver must not have edited any punch in the week.")

    # OCC: expected_timesheet_week_version must equal current version
    # (priority 21 / ERR_STALE_VERSION).
    expected = as_int(data, "expected_timesheet_week_version", required=True)
    if expected != week.get("version"):
        raise err("ERR_STALE_VERSION",
                  "expected_timesheet_week_version does not match current version.")

    week["approved_by_user_id"] = g.user_id
    week["status"] = "APPROVED"
    db.touch(week)
    return object_response(public(week))


@bp.post("/timesheet-weeks/<week_id>/reject")
def reject_timesheet_week(week_id):
    require_role("Supervisor")
    week = get_or_404(db.timesheet_weeks, week_id)

    # State: SUBMITTED (priority 7).
    if week.get("status") != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Timesheet week is not SUBMITTED.")

    # Segregation of duties (priority 20): rejecter differs from submitter.
    if g.user_id == week.get("submitted_by_user_id"):
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Rejecter must differ from the submitter.")

    week["status"] = "REJECTED"
    week["submitted_by_user_id"] = None
    db.touch(week)
    return object_response(public(week))
