from flask import Blueprint, request
from db import db
from middleware import require_user_context, require_role
from response import object_response, array_response
from services.common import (stamp_new, bump, public, get_json_body, require_int,
                             require_enum, paginate, sorted_by_creation)
from services.lookup import get_or_404
from errors import err
from clock import clock

bp = Blueprint("reminders", __name__)

CHANNELS = {"SMS", "EMAIL"}


@bp.route("/reminders", methods=["POST"])
def create_reminder():
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    body = get_json_body()
    appointment_id = body.get("appointment_id")
    if not isinstance(appointment_id, str) or not appointment_id:
        raise err("ERR_INVALID_REQUEST", "appointment_id required")
    send_at_min = require_int(body, "send_at_min", minimum=0)
    if send_at_min > 1439:
        raise err("ERR_INVALID_REQUEST", "send_at_min out of range")
    channel = require_enum(body, "channel", CHANNELS)
    get_or_404("appointments", appointment_id)  # FK existence
    reminder = stamp_new({
        "appointment_id": appointment_id, "send_at_min": send_at_min,
        "channel": channel, "status": "PENDING",
    })
    db.reminders[reminder["id"]] = reminder
    return object_response(public(reminder), 201)


@bp.route("/reminders", methods=["GET"])
def list_reminders():
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "ClinicalStaff"})
    items = list(db.reminders.values())
    for f in ("appointment_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [r for r in items if r[f] == val]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.route("/reminders/<rid>", methods=["GET"])
def get_reminder(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "ClinicalStaff"})
    return object_response(public(get_or_404("reminders", rid)), 200)


@bp.route("/reminders/<rid>/send", methods=["POST"])
def send(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    reminder = get_or_404("reminders", rid)
    if reminder["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Reminder not PENDING")
    appt = db.appointments.get(reminder["appointment_id"])
    if not appt or appt["status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise err("ERR_APPOINTMENT_NOT_ACTIVE", "Appointment not active")
    if not _is_due(reminder, appt):
        raise err("ERR_REMINDER_NOT_DUE", "Reminder not yet due")
    reminder["status"] = "SENT"
    bump(reminder)
    return object_response(public(reminder), 200)


def _is_due(reminder, appt):
    now = clock.now()
    now_date = now.strftime("%Y-%m-%d")
    now_minutes = now.hour * 60 + now.minute
    event = db.events.get(appt["event_id"])
    event_date = event["event_date"] if event else None
    if event_date is not None and now_date > event_date:
        return True
    return now_minutes >= reminder["send_at_min"]


@bp.route("/reminders/<rid>/cancel", methods=["POST"])
def cancel(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    reminder = get_or_404("reminders", rid)
    if reminder["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Reminder not PENDING")
    reminder["status"] = "CANCELLED"
    bump(reminder)
    return object_response(public(reminder), 200)
