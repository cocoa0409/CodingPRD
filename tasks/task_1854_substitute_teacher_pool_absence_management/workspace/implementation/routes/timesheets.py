"""Timesheet endpoints: submit, get, list per assignment/payroll period,
review (streak machinery), resubmit."""

from flask import Blueprint

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_ASSIGNMENT_NOT_FOUND, ERR_TIMESHEET_NOT_FOUND,
    ERR_ASSIGNMENT_INVALID_STATE, ERR_TIMESHEET_INVALID_STATE,
    ERR_INVALID_DATE_RANGE, ERR_DUPLICATE_TIMESHEET, ERR_TIMESHEET_OUT_OF_RANGE,
    ERR_PAYROLL_PERIOD_NOT_FOUND,
)
from middleware import (
    auth_context, require_role, require_coordinator_school,
    require_substitute_self, ALL_ROLES,
)
from response import ok, paginated
from util import parse_date, is_weekday
from validate import body, req_str, req_enum, req_date, req_hours

bp = Blueprint("timesheets", __name__)


def _get_timesheet_or_404(tid):
    t = STORE.timesheets.get(tid)
    if t is None:
        raise_err(ERR_TIMESHEET_NOT_FOUND, "timesheet id does not exist")
    return t


@bp.route("/timesheets", methods=["POST"])
def create_timesheet():
    user_id, role = auth_context()
    data = body()
    assignment_id = req_str(data, "assignment_id")
    work_date = req_date(data, "work_date")
    hours = req_hours(data, "hours_worked")
    require_role(role, ["Substitute"])
    asg = STORE.assignments.get(assignment_id)
    if asg is not None:
        require_substitute_self(user_id, asg["substitute_id"])
    if asg is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "assignment id does not exist")
    if asg["status"] != "WORKED":
        raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                  "timesheets may be submitted only while the assignment is WORKED")
    d = parse_date(work_date)
    if not is_weekday(d):
        raise_err(ERR_INVALID_DATE_RANGE, "work_date must be a weekday")
    for t in STORE.timesheets.values():
        if t["assignment_id"] == assignment_id and t["work_date"] == work_date:
            raise_err(ERR_DUPLICATE_TIMESHEET,
                      "a timesheet already exists for this assignment and work_date")
    if d < parse_date(asg["start_date"]) or d > parse_date(asg["end_date"]):
        raise_err(ERR_TIMESHEET_OUT_OF_RANGE,
                  "work_date is outside the assignment date range")
    t = new_entity(STORE.timesheets, {
        "assignment_id": assignment_id,
        "substitute_id": asg["substitute_id"],
        "payroll_period_id": None,
        "work_date": work_date,
        "hours_worked": hours,
        "status": "SUBMITTED",
        "streak_index": None,
        "day_pay_cents": None,
    })
    return ok(public(t), status=201)


@bp.route("/timesheets/<tid>", methods=["GET"])
def get_timesheet(tid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return ok(public(_get_timesheet_or_404(tid)))


@bp.route("/assignments/<aid>/timesheets", methods=["GET"])
def list_assignment_timesheets(aid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if aid not in STORE.assignments:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "assignment id does not exist")
    items = sorted((t for t in STORE.timesheets.values() if t["assignment_id"] == aid),
                   key=lambda t: (t["created_at"], t["_seq"]))
    page, meta = paginated(items)
    return ok([public(t) for t in page], pagination=meta)


@bp.route("/payroll-periods/<pid>/timesheets", methods=["GET"])
def list_period_timesheets(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if pid not in STORE.payroll_periods:
        raise_err(ERR_PAYROLL_PERIOD_NOT_FOUND, "payroll period id does not exist")
    items = sorted((t for t in STORE.timesheets.values() if t["payroll_period_id"] == pid),
                   key=lambda t: (t["created_at"], t["_seq"]))
    page, meta = paginated(items)
    return ok([public(t) for t in page], pagination=meta)


@bp.route("/timesheets/<tid>/review", methods=["POST"])
def review_timesheet(tid):
    user_id, role = auth_context()
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "REJECT"))
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    t = STORE.timesheets.get(tid)
    if role == "SchoolCoordinator":
        asg = STORE.assignments.get(t["assignment_id"]) if t else None
        require_coordinator_school(user_id, asg["school_id"] if asg else None)
    if t is None:
        raise_err(ERR_TIMESHEET_NOT_FOUND, "timesheet id does not exist")
    if t["status"] != "SUBMITTED":
        raise_err(ERR_TIMESHEET_INVALID_STATE, "review requires status SUBMITTED")
    asg = STORE.assignments[t["assignment_id"]]
    if asg["status"] != "WORKED":
        raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                  "the assignment must still be WORKED to review its timesheets")
    if decision == "REJECT":
        t["status"] = "REJECTED"
        touch(t)
        return ok(public(t))
    t["status"] = "APPROVED"
    touch(t)
    domain.recompute_streaks(asg)  # chronological streak + per-day pay pass
    t = STORE.timesheets[tid]
    return ok(public(t))


@bp.route("/timesheets/<tid>", methods=["PUT"])
def resubmit_timesheet(tid):
    user_id, role = auth_context()
    data = body()
    hours = req_hours(data, "hours_worked")
    require_role(role, ["Substitute"])
    t = STORE.timesheets.get(tid)
    if t is not None:
        require_substitute_self(user_id, t["substitute_id"])
    if t is None:
        raise_err(ERR_TIMESHEET_NOT_FOUND, "timesheet id does not exist")
    if t["status"] != "REJECTED":
        raise_err(ERR_TIMESHEET_INVALID_STATE, "resubmission requires status REJECTED")
    t["hours_worked"] = hours
    t["status"] = "SUBMITTED"
    touch(t)
    return ok(public(t))
