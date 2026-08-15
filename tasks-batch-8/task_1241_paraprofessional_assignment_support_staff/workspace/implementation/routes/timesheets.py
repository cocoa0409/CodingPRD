"""TimesheetEntry endpoints (PRD §3.7)."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_INVALID_DATE_RANGE, ERR_PLAN_NOT_ACTIVE, ERR_TIMESHEET_INVALID_STATE,
    ERR_TIMESHEET_NOT_OWN, ERR_TIMESHEET_OVERLAP, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import as_date_str, as_int, as_str, body_json, need, parse_date

bp = Blueprint("timesheets", __name__)

PARA = {"Paraprofessional"}
ADMIN_BLDG = {"BuildingAdministrator"}
ANY = {"Any"}
MINUTE_MAX = 1439


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


@bp.post("/sped-staffing/timesheets")
def create_timesheet():
    user_id, role = auth_context()
    require_role(role, PARA)
    body = body_json(request)
    assignment_id = need(body, "assignment_id")
    assignment = svc.get_assignment(as_str(assignment_id, "assignment_id"))
    work_date = as_date_str(need(body, "work_date"), "work_date")
    start_minute = as_int(need(body, "start_minute"), "start_minute")
    end_minute = as_int(need(body, "end_minute"), "end_minute")
    # The entry's para_id is always the caller's identity; logging against
    # another para's assignment is rejected.
    if assignment["para_id"] != user_id:
        raise ApiError(ERR_TIMESHEET_NOT_OWN, 403,
                       "paras may only log timesheets against their own assignments")
    plan = db.STORE["plans"][assignment["plan_id"]]
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "timesheet logging requires plan ACTIVE")
    # Closed-interval double-log check vs SUBMITTED/APPROVED entries.
    if svc.timesheet_overlap(user_id, work_date, start_minute, end_minute):
        raise ApiError(ERR_TIMESHEET_OVERLAP, 409,
                       "interval conflicts with an existing submitted/approved entry")
    # Date coherence.
    if start_minute < 0 or start_minute > MINUTE_MAX:
        raise ApiError(ERR_INVALID_DATE_RANGE, 400,
                       "start_minute must be a minute-of-day 0..1439")
    if end_minute <= start_minute or end_minute > MINUTE_MAX + 1:
        raise ApiError(ERR_INVALID_DATE_RANGE, 400,
                       "end_minute must be strictly later than start_minute")
    wd = parse_date(work_date)
    if wd < parse_date(assignment["start_date"]) or wd > parse_date(assignment["end_date"]):
        raise ApiError(ERR_INVALID_DATE_RANGE, 400,
                       "work_date must fall within the assignment window")
    entry = {
        "plan_id": assignment["plan_id"],
        "para_id": user_id,
        "assignment_id": assignment["id"],
        "work_date": work_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "minutes_worked": end_minute - start_minute,
        "status": "DRAFT",
    }
    svc.stamp_new(entry)
    db.STORE["timesheets"][entry["id"]] = entry
    return success(svc.ser_timesheet(entry), "object", 201)


@bp.get("/sped-staffing/timesheets")
def list_timesheets():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    para_id = request.args.get("para_id")
    assignment_id = request.args.get("assignment_id")
    status = request.args.get("status")
    items = []
    for t in svc.sorted_records("timesheets"):
        if plan_id is not None and t["plan_id"] != plan_id:
            continue
        if para_id is not None and t["para_id"] != para_id:
            continue
        if assignment_id is not None and t["assignment_id"] != assignment_id:
            continue
        if status is not None and t["status"] != status:
            continue
        items.append(svc.ser_timesheet(t))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/timesheets/<timesheetId>")
def get_timesheet(timesheetId):
    _auth(ANY)
    t = svc.get_timesheet(timesheetId)
    return success(svc.ser_timesheet(t), "object", 200)


@bp.post("/sped-staffing/timesheets/<timesheetId>/submit")
def submit_timesheet(timesheetId):
    user_id, role = auth_context()
    require_role(role, PARA)
    t = svc.get_timesheet(timesheetId)
    if t["para_id"] != user_id:
        raise ApiError(ERR_TIMESHEET_NOT_OWN, 403,
                       "only the owning para may submit this timesheet")
    if t["status"] != "DRAFT":
        raise ApiError(ERR_TIMESHEET_INVALID_STATE, 409,
                       "submit requires timesheet DRAFT")
    if svc.timesheet_overlap(t["para_id"], t["work_date"], t["start_minute"],
                             t["end_minute"], exclude_id=t["id"]):
        raise ApiError(ERR_TIMESHEET_OVERLAP, 409,
                       "interval conflicts with an existing submitted/approved entry")
    t["status"] = "SUBMITTED"
    svc.touch(t)
    return success(svc.ser_timesheet(t), "object", 200)


@bp.post("/sped-staffing/timesheets/<timesheetId>/approve")
def approve_timesheet(timesheetId):
    _auth(ADMIN_BLDG)
    t = svc.get_timesheet(timesheetId)
    plan = db.STORE["plans"][t["plan_id"]]
    if plan["status"] not in ("ACTIVE", "RECONCILING"):
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "timesheet approval requires plan ACTIVE or RECONCILING")
    if t["status"] != "SUBMITTED":
        raise ApiError(ERR_TIMESHEET_INVALID_STATE, 409,
                       "approve requires timesheet SUBMITTED")
    t["status"] = "APPROVED"
    svc.touch(t)
    return success(svc.ser_timesheet(t), "object", 200)


@bp.post("/sped-staffing/timesheets/<timesheetId>/reject")
def reject_timesheet(timesheetId):
    _auth(ADMIN_BLDG)
    t = svc.get_timesheet(timesheetId)
    plan = db.STORE["plans"][t["plan_id"]]
    if plan["status"] not in ("ACTIVE", "RECONCILING"):
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "timesheet rejection requires plan ACTIVE or RECONCILING")
    if t["status"] != "SUBMITTED":
        raise ApiError(ERR_TIMESHEET_INVALID_STATE, 409,
                       "reject requires timesheet SUBMITTED")
    t["status"] = "DRAFT"
    svc.touch(t)
    return success(svc.ser_timesheet(t), "object", 200)
