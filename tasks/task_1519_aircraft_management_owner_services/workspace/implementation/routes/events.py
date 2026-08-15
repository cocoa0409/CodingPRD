"""MaintenanceEvent endpoints, including successor forecast spawning."""
from decimal import Decimal

from flask import Blueprint, request

import clock
from db import db
from errors import validation, ApiError, ERR_EVENT_INVALID_STATE
from middleware import require_roles, require_read
from response import success_object, success_list
from serializers import event_view
from services.core import (
    make_record, touch, require_exists, filter_value_exists,
    get_pagination, paginate,
)
from util import fmt_ts, parse_date

bp = Blueprint("events", __name__)

STATUSES = {"FORECAST", "SCHEDULED", "COMPLETED"}


def _positive_hours(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise validation(f"{field} must be a number > 0")


@bp.route("/events", methods=["POST"])
def create_event():
    require_roles("MaintenancePlanner")
    body = request.get_json(silent=True) or {}

    aircraft_id = body.get("aircraft_id")
    if aircraft_id is not None:
        require_exists(db.aircraft, aircraft_id, "aircraft_id does not resolve")
    if not isinstance(aircraft_id, str) or not aircraft_id:
        raise validation("aircraft_id is required")

    event_code = body.get("event_code")
    if not isinstance(event_code, str) or not event_code:
        raise validation("event_code is required")

    interval_hours = body.get("interval_hours")
    _positive_hours(interval_hours, "interval_hours")

    due_at = body.get("due_at_aircraft_hours")
    if isinstance(due_at, bool) or not isinstance(due_at, (int, float)) or due_at < 0:
        raise validation("due_at_aircraft_hours must be a non-negative number")

    rec = make_record({
        "aircraft_id": aircraft_id,
        "previous_event_id": None,
        "event_code": event_code,
        "interval_hours": interval_hours,
        "due_at_aircraft_hours": due_at,
        "scheduled_date": None,
        "completed_at": None,
        "actual_aircraft_hours": None,
        "handed_over_at": None,
        "status": "FORECAST",
    })
    db.events[rec["id"]] = rec
    return success_object(event_view(rec), 201)


@bp.route("/events/<event_id>", methods=["GET"])
def get_event(event_id):
    require_read()
    rec = require_exists(db.events, event_id)
    return success_object(event_view(rec))


@bp.route("/events", methods=["GET"])
def list_events():
    require_read()
    aircraft_id = request.args.get("aircraft_id")
    previous_event_id = request.args.get("previous_event_id")
    status = request.args.get("status")
    filter_value_exists(db.aircraft, aircraft_id)
    filter_value_exists(db.events, previous_event_id)
    if status is not None and status not in STATUSES:
        raise validation("status is not a valid enum value")

    limit, offset = get_pagination(request.args)
    records = list(db.events.values())
    if aircraft_id is not None:
        records = [r for r in records if r["aircraft_id"] == aircraft_id]
    if previous_event_id is not None:
        records = [r for r in records if r["previous_event_id"] == previous_event_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return success_list([event_view(r) for r in page], limit, offset, total)


@bp.route("/events/<event_id>/schedule", methods=["POST"])
def schedule_event(event_id):
    require_roles("MaintenancePlanner")
    rec = require_exists(db.events, event_id)
    body = request.get_json(silent=True) or {}
    scheduled_date = body.get("scheduled_date")
    parse_date(scheduled_date, "scheduled_date")

    if rec["status"] != "FORECAST":
        raise ApiError(ERR_EVENT_INVALID_STATE, "Event must be in FORECAST", 409)

    rec["scheduled_date"] = scheduled_date
    rec["status"] = "SCHEDULED"
    touch(rec, bump_version=True)
    return success_object(event_view(rec))


@bp.route("/events/<event_id>/complete", methods=["POST"])
def complete_event(event_id):
    require_roles("MaintenancePlanner")
    rec = require_exists(db.events, event_id)
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_EVENT_INVALID_STATE, "Event must be in SCHEDULED", 409)

    aircraft = db.aircraft[rec["aircraft_id"]]
    now_str = fmt_ts(clock.now())
    actual_hours = aircraft["total_time_hours"]

    rec["completed_at"] = now_str
    rec["actual_aircraft_hours"] = actual_hours
    rec["status"] = "COMPLETED"
    touch(rec, bump_version=True)

    # auto-spawn the successor forecast
    successor_due = float(
        Decimal(str(actual_hours)) + Decimal(str(rec["interval_hours"]))
    )
    successor = make_record({
        "aircraft_id": rec["aircraft_id"],
        "previous_event_id": rec["id"],
        "event_code": rec["event_code"],
        "interval_hours": rec["interval_hours"],
        "due_at_aircraft_hours": successor_due,
        "scheduled_date": None,
        "completed_at": None,
        "actual_aircraft_hours": None,
        "handed_over_at": None,
        "status": "FORECAST",
    })
    db.events[successor["id"]] = successor

    return success_object(event_view(rec))
