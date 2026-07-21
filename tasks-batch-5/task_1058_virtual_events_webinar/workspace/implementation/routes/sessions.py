"""Sessions: half-open track geometry, scheduling, cancellation (PRD 3.6)."""

from flask import Blueprint

import cascades
import db
from auth import authorize, own_event
from db import S, dt_of
from errors import ApiError
from response import ok, ok_list
from validate import (
    body, get_event, get_registration, get_session, get_track, guard_state,
    pagination, paginate, qs, req_dt, req_enum, req_int, req_str,
)
from routes.registrations import fk

bp = Blueprint("sessions", __name__)

SESSION_TYPES = ("LIVE", "SIMULIVE", "ON_DEMAND")
SESSION_TERMINAL = ("COMPLETED", "CANCELLED")


@bp.route("/api/sessions", methods=["POST"])
def create_session():
    authorize("Organizer")
    b = body()

    event = fk(b, "event_id", get_event)
    track = fk(b, "track_id", get_track)

    if event is not None:
        own_event(event)

    req_str(b, "event_id")
    req_str(b, "track_id")
    title = req_str(b, "title")
    starts_at = req_dt(b, "starts_at")
    ends_at = req_dt(b, "ends_at")
    session_type = req_enum(b, "session_type", SESSION_TYPES)
    capacity = req_int(b, "capacity", minimum=1)

    if ends_at <= starts_at:
        raise ApiError("ERR_TIME_RANGE_INVALID")

    row = db.new_row({
        "event_id": event["id"],
        "track_id": track["id"],
        "title": title,
        "starts_at": db.fmt_dt(starts_at),
        "ends_at": db.fmt_dt(ends_at),
        "session_type": session_type,
        "capacity": capacity,
        "state": "DRAFT",
        "accepted_speaker_count": 0,
    })
    S.sessions[row["id"]] = row
    return ok(db.serialize(row), 201)


@bp.route("/api/sessions", methods=["GET"])
def list_sessions():
    authorize("Organizer", "PlatformAdmin", "Attendee", "SpeakerUser")
    limit, offset = pagination()
    event_id = qs("event_id")
    track_id = qs("track_id")
    state = qs("state")
    rows = [
        s for s in S.sessions.values()
        if (event_id is None or s.get("event_id") == event_id)
        and (track_id is None or s.get("track_id") == track_id)
        and (state is None or s.get("state") == state)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/sessions/<session_id>", methods=["GET"])
def read_session(session_id):
    authorize("Organizer", "PlatformAdmin", "Attendee", "SpeakerUser")
    return ok(db.serialize(get_session(session_id)))


@bp.route("/api/sessions/<session_id>/schedule", methods=["POST"])
def schedule_session(session_id):
    authorize("Organizer")
    session = get_session(session_id)
    event = S.events.get(session.get("event_id"))
    if event is not None:
        own_event(event)

    guard_state(session, ("DRAFT",), SESSION_TERMINAL)
    if event is None or event.get("state") not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_INVALID_STATE")

    new_start = dt_of(session, "starts_at")
    new_end = dt_of(session, "ends_at")
    for other in S.sessions.values():
        if other["id"] == session["id"]:
            continue
        if other.get("track_id") != session.get("track_id"):
            continue
        if other.get("state") not in ("SCHEDULED", "LIVE", "COMPLETED"):
            continue
        other_start = dt_of(other, "starts_at")
        other_end = dt_of(other, "ends_at")
        # half-open geometry: zero-gap adjacency is permitted
        if new_start < other_end and other_start < new_end:
            raise ApiError("ERR_TRACK_SLOT_CONFLICT")

    session["state"] = "SCHEDULED"
    track = S.tracks.get(session.get("track_id"))
    if track is not None:
        track["scheduled_session_count"] = int(track.get("scheduled_session_count", 0)) + 1
        db.touch(track)
    db.touch(session)
    return ok(db.serialize(session))


@bp.route("/api/sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    authorize("Organizer")
    session = get_session(session_id)
    event = S.events.get(session.get("event_id"))
    if event is not None:
        own_event(event)
    b = body()
    req_str(b, "reason")
    guard_state(session, ("DRAFT", "SCHEDULED", "LIVE"), SESSION_TERMINAL)
    cascades.cancel_session(session, event)
    return ok(db.serialize(session))


@bp.route("/api/sessions/<session_id>/attendance", methods=["POST"])
def record_attendance(session_id):
    authorize("Organizer")
    session = get_session(session_id)
    b = body()

    registration = fk(b, "registration_id", get_registration)

    event = S.events.get(session.get("event_id"))
    if event is not None:
        own_event(event)

    req_str(b, "registration_id")
    watched_minutes = req_int(b, "watched_minutes", minimum=0)

    registration["watched_minutes"] = int(registration.get("watched_minutes", 0)) + watched_minutes
    db.touch(registration)
    return ok(db.serialize(registration))
