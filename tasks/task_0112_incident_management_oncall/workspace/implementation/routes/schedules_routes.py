"""OnCallSchedule + ScheduleShift creation/read; shift overlap check."""
from flask import Blueprint, request

import response
from db import db
from errors import ApiError
from middleware import require_user_context, require_role, get_json_body, get_pagination
from services.common import (
    require_str, optional_int, stamp_create, parse_datetime,
)
from services.lookups import get_schedule, get_responder, get_service
from services.serializers import schedule_out, shift_out

bp = Blueprint("schedules", __name__)

ADMIN_IC = {"PlatformAdmin", "IncidentCommander"}


# ---------------- OnCallSchedule ----------------

@bp.route("/on-call-schedules", methods=["POST"])
def create_schedule():
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    name = require_str(body, "name")
    service_id = require_str(body, "service_id")
    with db.lock:
        get_service(service_id)  # FK existence (priority 3)
        handoff = optional_int(body, "handoff_interval_hours", 168, minimum=0)
        rec = stamp_create({
            "name": name,
            "service_id": service_id,
            "handoff_interval_hours": handoff,
        })
        db.schedules[rec["id"]] = rec
    return response.success(schedule_out(rec), 201)


@bp.route("/on-call-schedules/<sid>", methods=["GET"])
def get_one_schedule(sid):
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    with db.lock:
        s = get_schedule(sid)
        return response.success(schedule_out(s), 200)


# ---------------- ScheduleShift ----------------

@bp.route("/schedule-shifts", methods=["POST"])
def create_shift():
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    schedule_id = require_str(body, "schedule_id")
    responder_id = require_str(body, "responder_id")
    with db.lock:
        # FK existence (priority 3), left-to-right
        get_schedule(schedule_id)
        get_responder(responder_id)
        # request shape (priority 4)
        starts_at = parse_datetime(body, "starts_at")
        ends_at = parse_datetime(body, "ends_at")
        # interval well-formedness (priority 5)
        if not (ends_at > starts_at):
            raise ApiError("ERR_INVALID_INTERVAL", "ends_at must be strictly after starts_at.")
        # overlap check (priority 10): half-open intervals on the same schedule
        for sh in db.shifts.values():
            if sh["schedule_id"] != schedule_id:
                continue
            if starts_at < sh["ends_at"] and sh["starts_at"] < ends_at:
                raise ApiError("ERR_SHIFT_OVERLAP", "Shift overlaps an existing shift on the schedule.")
        rec = stamp_create({
            "schedule_id": schedule_id,
            "responder_id": responder_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
        })
        db.shifts[rec["id"]] = rec
    return response.success(shift_out(rec), 201)


@bp.route("/schedule-shifts", methods=["GET"])
def list_shifts():
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    limit, offset = get_pagination()
    schedule_id = request.args.get("schedule_id")
    responder_id = request.args.get("responder_id")
    with db.lock:
        rows = list(db.shifts.values())
        if schedule_id is not None:
            rows = [r for r in rows if r["schedule_id"] == schedule_id]
        if responder_id is not None:
            rows = [r for r in rows if r["responder_id"] == responder_id]
        return response.list_response(rows, limit, offset, shift_out)


@bp.route("/schedule-shifts/<shid>", methods=["GET"])
def get_one_shift(shid):
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    with db.lock:
        sh = db.shifts.get(shid)
        if sh is None:
            raise ApiError("ERR_SCHEDULE_NOT_FOUND", "Schedule shift not found.")
        return response.success(shift_out(sh), 200)
