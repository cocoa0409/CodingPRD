"""Timesheets, earnings statements, and payroll runs."""
import uuid
from decimal import Decimal

from app import app
from store import store
from common import (
    ApiError, ok, ok_list, authenticate, authorize, body, verr,
    req_str, opt_str, req_date, req_sunday, coerce_hours, new_common, touch,
    pagination, paginate, READ_ROLES, fine_authz, check_ownership, D,
    add_days, date_le,
)
from serializers import ser_timesheet, ser_statement, ser_payroll_run
from domain import (
    classify_hours, build_weekly_statement, ledger_rollup, apply_clinician_recompute,
    _contract_of,
)


def _uuid():
    return str(uuid.uuid4())


def _filter(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _parse_daily_hours(b):
    if "daily_hours" not in b:
        verr("Missing required field: daily_hours")
    dh = b["daily_hours"]
    if not isinstance(dh, list) or len(dh) != 7:
        verr("daily_hours must be an array of exactly 7 numbers")
    return [coerce_hours(x, "daily_hours") for x in dh]


def _check_hours_limit(daily_hours):
    if any(h > 24 for h in daily_hours):
        raise ApiError("ERR_HOURS_LIMIT_EXCEEDED", 422, "A daily hours entry exceeds 24")
    if sum(daily_hours, Decimal("0")) > 84:
        raise ApiError("ERR_HOURS_LIMIT_EXCEEDED", 422, "Weekly hours exceed 84")


# ===========================================================================
# POST /timesheets
# ===========================================================================
@app.route("/timesheets", methods=["POST"])
def create_timesheet():
    uid, role = authenticate()
    authorize(role, ["Clinician"])
    b = body()
    assignment_id = req_str(b, "assignment_id")
    a = store.assignments.get(assignment_id)
    if not a:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    check_ownership(role, uid, a)
    week_start_date = req_sunday(b, "week_start_date")
    daily_hours = _parse_daily_hours(b)
    callback = coerce_hours(b["callback_hours"], "callback_hours") if b.get("callback_hours") is not None else Decimal("0")

    # state (priority 7): assignment must be ACTIVE
    if a["staffing_status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE", 409, "Assignment is not active")
    # compliance suspended (priority 10)
    if a["compliance_status"] == "SUSPENDED":
        raise ApiError("ERR_COMPLIANCE_SUSPENDED", 409, "Assignment compliance suspended")
    # week window (priority 14)
    clock_date = store.clock_date().isoformat()
    week_last = add_days(week_start_date, 6)
    if (not date_le(a["start_date"], week_start_date)
            or not date_le(week_last, a["end_date"])
            or not date_le(week_start_date, clock_date)):
        raise ApiError("ERR_WEEK_OUTSIDE_TERM", 422, "Week outside the assignment term")
    # duplicate week (priority 16)
    for t in store.timesheets.values():
        if (t["assignment_id"] == assignment_id and t["status"] in ("SUBMITTED", "APPROVED", "DISPUTED")
                and t["week_start_date"] == week_start_date):
            raise ApiError("ERR_DUPLICATE_TIMESHEET_WEEK", 409, "Duplicate timesheet week")
    # hours limit (priority 18)
    _check_hours_limit(daily_hours)

    cls = classify_hours(daily_hours, callback)
    t = new_common(True)
    t["id"] = _uuid()
    t.update({
        "assignment_id": assignment_id, "week_start_date": week_start_date,
        "daily_hours": daily_hours, "callback_hours": callback,
        "status": "SUBMITTED",
        "total_raw_hours": cls["total_raw_hours"],
        "regular_hours": cls["regular_hours"],
        "overtime_hours": cls["overtime_hours"],
        "days_worked": cls["days_worked"],
        "dispute_reason": None, "approved_by_user_id": None,
    })
    store.timesheets[t["id"]] = t
    return ok(ser_timesheet(t), 201)


# ===========================================================================
# GET /assignments/{id}/timesheets
# ===========================================================================
@app.route("/assignments/<aid>/timesheets", methods=["GET"])
def list_assignment_timesheets(aid):
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    if aid not in store.assignments:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    limit, offset = pagination()
    rows = [t for t in store.timesheets.values() if t["assignment_id"] == aid]
    status_f = _filter("status")
    if status_f is not None:
        rows = [t for t in rows if t["status"] == status_f]
    window, total = paginate(rows, limit, offset)
    return ok_list([ser_timesheet(t) for t in window], limit, offset, total)


# ===========================================================================
# POST /timesheets/{id}/transition
# ===========================================================================
TIMESHEET_STATES = {"SUBMITTED", "APPROVED", "DISPUTED", "VOIDED"}


def _linked_statement(ts_id):
    for st in store.statements.values():
        if st["timesheet_id"] == ts_id:
            return st
    return None


@app.route("/timesheets/<tid>/transition", methods=["POST"])
def transition_timesheet(tid):
    uid, role = authenticate()
    authorize(role, ["FacilityManager", "Clinician", "PayrollAdmin"])
    b = body()
    fine_authz("timesheet", role, b.get("to"))
    t = store.timesheets.get(tid)
    if not t:
        raise ApiError("ERR_TIMESHEET_NOT_FOUND", 404, "Timesheet not found")
    a = store.assignments[t["assignment_id"]]
    check_ownership(role, uid, a)
    to = req_str(b, "to")
    if to not in TIMESHEET_STATES:
        verr("to must be one of %s" % sorted(TIMESHEET_STATES))
    status = t["status"]

    if to == "APPROVED":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal timesheet transition")
        if a["staffing_status"] != "ACTIVE":
            raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE", 409, "Assignment is not active")
        if a["compliance_status"] == "SUSPENDED":
            raise ApiError("ERR_COMPLIANCE_SUSPENDED", 409, "Assignment compliance suspended")
        t["status"] = "APPROVED"
        t["approved_by_user_id"] = uid
        touch(t)
        _approve_settlement(t, a)
    elif to == "DISPUTED":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal timesheet transition")
        t["status"] = "DISPUTED"
        t["dispute_reason"] = opt_str(b, "dispute_reason", None)
        touch(t)
    elif to == "SUBMITTED":
        if status != "DISPUTED":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal timesheet transition")
        if "daily_hours" in b and b["daily_hours"] is not None:
            daily_hours = _parse_daily_hours(b)
        else:
            daily_hours = t["daily_hours"]
        if b.get("callback_hours") is not None:
            callback = coerce_hours(b["callback_hours"], "callback_hours")
        else:
            callback = t["callback_hours"]
        _check_hours_limit(daily_hours)
        cls = classify_hours(daily_hours, callback)
        t["daily_hours"] = daily_hours
        t["callback_hours"] = callback
        t["total_raw_hours"] = cls["total_raw_hours"]
        t["regular_hours"] = cls["regular_hours"]
        t["overtime_hours"] = cls["overtime_hours"]
        t["days_worked"] = cls["days_worked"]
        t["status"] = "SUBMITTED"
        t["dispute_reason"] = None
        touch(t)
    elif to == "VOIDED":
        if status != "APPROVED":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal timesheet transition")
        st = _linked_statement(tid)
        if st is not None and st["status"] == "POSTED":
            raise ApiError("ERR_STATEMENT_ALREADY_POSTED", 409, "Linked statement already posted")
        t["status"] = "VOIDED"
        touch(t)
        _void_settlement(t, a, st)
    else:
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal timesheet transition")
    return ok(ser_timesheet(t), 200)


def _approve_settlement(t, a):
    build_weekly_statement(t, a)
    contract = _contract_of(a)
    worked = t["regular_hours"] + t["overtime_hours"]
    delta = min(worked, D(contract["weekly_guaranteed_hours"]))
    a["guaranteed_hours_consumed"] = a["guaranteed_hours_consumed"] + delta
    a["guaranteed_hours_remaining"] = a["guaranteed_hours_remaining"] - delta
    ledger_rollup(a)
    if a["staffing_status"] == "ACTIVE" and a["guaranteed_hours_remaining"] == 0:
        a["staffing_status"] = "COMPLETED"
    touch(a)
    apply_clinician_recompute(store.clinicians[a["clinician_id"]])


def _void_settlement(t, a, st):
    contract = _contract_of(a)
    if st is not None:
        st["status"] = "REVERSED"
        touch(st)
        worked = st["billable_hours"]
    else:
        worked = t["regular_hours"] + t["overtime_hours"]
    delta = min(worked, D(contract["weekly_guaranteed_hours"]))
    a["guaranteed_hours_consumed"] = a["guaranteed_hours_consumed"] - delta
    a["guaranteed_hours_remaining"] = a["guaranteed_hours_remaining"] + delta
    ledger_rollup(a)
    if a["staffing_status"] == "COMPLETED" and a["guaranteed_hours_remaining"] > 0:
        a["staffing_status"] = "ACTIVE"
    touch(a)
    apply_clinician_recompute(store.clinicians[a["clinician_id"]])


# ===========================================================================
# GET /earnings-statements/{id}  and  GET /earnings-statements
# ===========================================================================
@app.route("/earnings-statements/<sid>", methods=["GET"])
def get_statement(sid):
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    st = store.statements.get(sid)
    if not st:
        raise ApiError("ERR_EARNINGS_STATEMENT_NOT_FOUND", 404, "Earnings statement not found")
    return ok(ser_statement(st), 200)


@app.route("/earnings-statements", methods=["GET"])
def list_statements():
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    rows = list(store.statements.values())
    for f in ("assignment_id", "clinician_id", "timesheet_id", "payroll_run_id",
              "status", "kind"):
        v = _filter(f)
        if v is not None:
            rows = [s for s in rows if s[f] == v]
    window, total = paginate(rows, limit, offset)
    return ok_list([ser_statement(s) for s in window], limit, offset, total)


# ===========================================================================
# POST /payroll-runs
# ===========================================================================
@app.route("/payroll-runs", methods=["POST"])
def open_payroll_run():
    uid, role = authenticate()
    authorize(role, ["PayrollAdmin"])
    b = body()
    period_start = req_date(b, "period_start_date")
    period_end = req_date(b, "period_end_date")

    run = new_common(True)
    run["id"] = _uuid()
    run.update({
        "period_start_date": period_start, "period_end_date": period_end,
        "status": "OPEN", "statement_count": 0,
        "total_pay_cost_cents": 0, "total_gross_bill_cents": 0, "total_margin_cents": 0,
        "opened_by_user_id": uid, "posted_by_user_id": None,
    })
    store.payroll_runs[run["id"]] = run

    claimed = [st for st in store.statements.values()
               if st["status"] == "FINALIZED" and st["payroll_run_id"] is None
               and date_le(period_start, st["period_key_date"])
               and date_le(st["period_key_date"], period_end)]
    claimed.sort(key=lambda s: (s["created_at"], s["_seq"]))
    for st in claimed:
        st["payroll_run_id"] = run["id"]
        touch(st)
    run["statement_count"] = len(claimed)
    run["total_pay_cost_cents"] = sum(st["total_pay_cost_cents"] for st in claimed)
    run["total_gross_bill_cents"] = sum(st["gross_bill_cents"] for st in claimed)
    run["total_margin_cents"] = sum(st["gross_margin_cents"] for st in claimed)
    return ok(ser_payroll_run(run), 201)


# ===========================================================================
# POST /payroll-runs/{id}/transition
# ===========================================================================
PAYROLL_STATES = {"OPEN", "LOCKED", "POSTED"}


@app.route("/payroll-runs/<rid>/transition", methods=["POST"])
def transition_payroll_run(rid):
    uid, role = authenticate()
    authorize(role, ["PayrollAdmin"])
    run = store.payroll_runs.get(rid)
    if not run:
        raise ApiError("ERR_PAYROLL_RUN_NOT_FOUND", 404, "Payroll run not found")
    b = body()
    to = req_str(b, "to")
    if to not in PAYROLL_STATES:
        verr("to must be one of %s" % sorted(PAYROLL_STATES))

    if to == "LOCKED":
        if run["status"] != "OPEN":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal payroll transition")
        run["status"] = "LOCKED"
        touch(run)
    elif to == "POSTED":
        if run["status"] != "LOCKED":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal payroll transition")
        if uid == run["opened_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Poster must differ from opener")
        run["status"] = "POSTED"
        run["posted_by_user_id"] = uid
        touch(run)
        for st in store.statements.values():
            if st["payroll_run_id"] == rid and st["status"] == "FINALIZED":
                st["status"] = "POSTED"
                touch(st)
    else:
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal payroll transition")
    return ok(ser_payroll_run(run), 200)
