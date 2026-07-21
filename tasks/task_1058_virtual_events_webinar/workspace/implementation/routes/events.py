"""Event lifecycle endpoints (PRD 3.1, 3.10)."""

from flask import Blueprint, g

import calc
import cascades
import db
from auth import authorize, own_event
from db import S
from errors import ApiError
from response import ok, ok_list
from validate import (
    body, get_event, guard_state, opt_dt, opt_int, opt_str, pagination,
    paginate, qs, req_dt, req_int, req_str,
)

bp = Blueprint("events", __name__)

EVENT_TERMINAL = ("SETTLED", "CANCELLED")


@bp.route("/api/events", methods=["POST"])
def create_event():
    authorize("Organizer")
    b = body()
    name = req_str(b, "name")
    timezone_label = req_str(b, "timezone")
    starts_at = req_dt(b, "starts_at")
    ends_at = req_dt(b, "ends_at")
    early_bird_ends_at = req_dt(b, "early_bird_ends_at")
    capacity = req_int(b, "capacity", minimum=1)

    if ends_at <= starts_at:
        raise ApiError("ERR_TIME_RANGE_INVALID")

    row = db.new_row({
        "organizer_user_id": g.user_id,
        "name": name,
        "timezone": timezone_label,
        "starts_at": db.fmt_dt(starts_at),
        "ends_at": db.fmt_dt(ends_at),
        "early_bird_ends_at": db.fmt_dt(early_bird_ends_at),
        "capacity": capacity,
        "state": "DRAFT",
        "registered_count": 0,
        "gross_collected_cents": 0,
        "streamed_minutes_total": 0,
        "published_recording_count": 0,
        "settlement_adjustment_cents": 0,
    })
    S.events[row["id"]] = row
    return ok(db.serialize(row), 201)


@bp.route("/api/events", methods=["GET"])
def list_events():
    authorize("Organizer", "PlatformAdmin", "FinanceAdmin")
    limit, offset = pagination()
    state = qs("state")
    organizer_user_id = qs("organizer_user_id")
    rows = [
        r for r in S.events.values()
        if (state is None or r.get("state") == state)
        and (organizer_user_id is None or r.get("organizer_user_id") == organizer_user_id)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/events/<event_id>", methods=["GET"])
def read_event(event_id):
    authorize("Organizer", "PlatformAdmin", "FinanceAdmin", "Attendee",
              "SponsorUser", "SpeakerUser")
    event = get_event(event_id)
    return ok(db.serialize(event))


@bp.route("/api/events/<event_id>", methods=["PATCH"])
def patch_event(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)
    b = body()
    name = opt_str(b, "name")
    capacity = opt_int(b, "capacity", minimum=1)
    early_bird_ends_at = opt_dt(b, "early_bird_ends_at")

    guard_state(event, ("DRAFT", "PUBLISHED"), EVENT_TERMINAL)

    if name is not None:
        event["name"] = name
    if capacity is not None:
        event["capacity"] = capacity
    if early_bird_ends_at is not None:
        event["early_bird_ends_at"] = db.fmt_dt(early_bird_ends_at)
    db.touch(event)
    return ok(db.serialize(event))


@bp.route("/api/events/<event_id>/publish", methods=["POST"])
def publish_event(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)
    guard_state(event, ("DRAFT",), EVENT_TERMINAL)
    has_ticket_type = any(
        t.get("event_id") == event["id"] for t in S.ticket_types.values()
    )
    if not has_ticket_type:
        raise ApiError("ERR_INVALID_STATE", "The event has no ticket types.")
    event["state"] = "PUBLISHED"
    db.touch(event)
    return ok(db.serialize(event))


@bp.route("/api/events/<event_id>/start", methods=["POST"])
def start_event(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)
    guard_state(event, ("PUBLISHED",), EVENT_TERMINAL)
    event["state"] = "LIVE"
    for booth in db.sort_rows(list(S.booths.values())):
        if booth.get("event_id") == event["id"] and booth.get("state") == "APPROVED":
            booth["state"] = "LIVE"
            db.touch(booth)
    db.touch(event)
    return ok(db.serialize(event))


@bp.route("/api/events/<event_id>/end", methods=["POST"])
def end_event(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)
    guard_state(event, ("LIVE",), EVENT_TERMINAL)

    session_ids = {
        s["id"] for s in S.sessions.values() if s.get("event_id") == event["id"]
    }
    for bc in S.broadcasts.values():
        if bc.get("session_id") in session_ids and bc.get("state") in ("PREVIEW", "LIVE"):
            raise ApiError("ERR_INVALID_STATE", "A broadcast is still on air.")

    event["state"] = "ENDED"
    for reg in db.sort_rows(list(S.registrations.values())):
        if reg.get("event_id") != event["id"]:
            continue
        status = reg.get("attendance_status")
        if status == "REGISTERED":
            reg["attendance_status"] = "NO_SHOW"
            db.touch(reg)
        elif status == "CHECKED_IN":
            if int(reg.get("watched_minutes", 0)) >= calc.ATTENDANCE_MIN_MINUTES:
                reg["attendance_status"] = "ATTENDED"
            else:
                reg["attendance_status"] = "NO_SHOW"
            db.touch(reg)
    db.touch(event)
    return ok(db.serialize(event))


@bp.route("/api/events/<event_id>/cancel", methods=["POST"])
def cancel_event(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)
    b = body()
    req_str(b, "reason")
    guard_state(event, ("DRAFT", "PUBLISHED", "LIVE"), EVENT_TERMINAL)
    event["state"] = "CANCELLED"
    cascades.cancel_event_cascade(event)
    db.touch(event)
    return ok(db.serialize(event))


@bp.route("/api/events/<event_id>/analytics", methods=["GET"])
def event_analytics(event_id):
    authorize("Organizer", "PlatformAdmin")
    event = get_event(event_id)
    return ok(calc.event_analytics_snapshot(event))
