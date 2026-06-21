"""PMSchedule routes (PRD §3.3, §4) — create, fetch, list, generate-due."""
from flask import Blueprint

import db
import errors
import serialize
from middleware import authenticate, authorize, get_json_body
from helpers import (require_enum, opt_number, opt_int, require_number,
                     opt_enum, opt_bool, parse_pagination, paginate)
from response import object_response, array_response
from services import calc, workflow

bp = Blueprint("pm_schedules", __name__)

TRIGGER_TYPES = {"METER", "CALENDAR"}
SEVERITIES = {"ROUTINE", "MAJOR", "OVERHAUL"}


@bp.post("/assets/<aid>/pm-schedules")
def create_pm_schedule(aid):
    _, role = authenticate()
    authorize(role, ["Planner", "MaintenanceManager"])
    body = get_json_body()
    with db.LOCK:
        asset = db.assets.get(aid)
        if asset is None:
            raise errors.not_found()

        trigger_type = require_enum(body, "trigger_type", TRIGGER_TYPES)
        meter_interval = opt_number(body, "meter_interval", default=None, gt=0)
        calendar_interval_days = opt_int(body, "calendar_interval_days", default=None, minimum=1)
        estimated_labor_hours = require_number(body, "estimated_labor_hours", gt=0)
        severity = opt_enum(body, "severity", SEVERITIES, default="ROUTINE")
        active = opt_bool(body, "active", default=True)

        # Config validity (priority 9): METER needs meter_interval & null
        # calendar_interval_days; CALENDAR needs calendar_interval_days & null
        # meter_interval (PRD §3.3).
        if trigger_type == "METER":
            if meter_interval is None or calendar_interval_days is not None:
                raise errors.ApiError(errors.ERR_SCHEDULE_CONFIG_INVALID,
                                      "METER schedule requires meter_interval and null calendar_interval_days.", 422)
        else:  # CALENDAR
            if calendar_interval_days is None or meter_interval is not None:
                raise errors.ApiError(errors.ERR_SCHEDULE_CONFIG_INVALID,
                                      "CALENDAR schedule requires calendar_interval_days and null meter_interval.", 422)

        rec = db.new_record()
        rec.update({
            "asset_id": aid,
            "trigger_type": trigger_type,
            "meter_interval": meter_interval,
            "calendar_interval_days": calendar_interval_days,
            "estimated_labor_hours": estimated_labor_hours,
            "severity": severity,
            "anchor_meter": asset["meter_reading"],
            "anchor_date": db.logical_now_iso(),
            "next_due_meter": None,
            "next_due_date": None,
            "active": active,
        })
        calc.compute_next_due(rec)
        db.pm_schedules[rec["id"]] = rec
        return object_response(serialize.pm_schedule(rec), 201)


@bp.get("/assets/<aid>/pm-schedules")
def list_asset_pm_schedules(aid):
    _, role = authenticate()
    authorize(role, ["Planner", "MaintenanceManager", "Technician"])
    limit, offset = parse_pagination()
    with db.LOCK:
        if aid not in db.assets:
            raise errors.not_found()
        items = sorted(
            (s for s in db.pm_schedules.values() if s["asset_id"] == aid),
            key=lambda s: s["_seq"])
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.pm_schedule(s) for s in page],
                              limit, offset, total)


@bp.get("/pm-schedules/<sid>")
def get_pm_schedule(sid):
    _, role = authenticate()
    authorize(role, ["Planner", "MaintenanceManager", "Technician"])
    with db.LOCK:
        rec = db.pm_schedules.get(sid)
        if rec is None:
            raise errors.not_found()
        return object_response(serialize.pm_schedule(rec), 200)


@bp.post("/pm-schedules/<sid>/generate-due")
def generate_due(sid):
    _, role = authenticate()
    authorize(role, ["Planner", "MaintenanceManager"])
    with db.LOCK:
        sched = db.pm_schedules.get(sid)
        if sched is None:
            raise errors.not_found()
        asset = db.assets.get(sched["asset_id"])
        # is_due also honors the active flag (a soft-paused schedule is not due).
        if not calc.is_due(sched, asset):
            raise errors.ApiError(errors.ERR_PM_NOT_DUE,
                                  "This PM schedule is not yet due.", 409)
        wo = workflow.generate_due_for_schedule(sched, asset)
        return object_response(serialize.work_order(wo), 201)
