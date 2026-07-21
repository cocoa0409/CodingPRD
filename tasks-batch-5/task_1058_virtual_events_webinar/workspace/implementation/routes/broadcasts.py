"""Broadcasts: the streaming apparatus attached to a session (PRD 3.7)."""

from flask import Blueprint

import cascades
import db
from auth import authorize, own_event
from db import S, dt_of
from errors import ApiError
from response import ok, ok_list
from validate import (
    body, get_broadcast, get_session, guard_state, pagination, paginate, qs,
    req_enum, req_str,
)
from routes.registrations import fk

bp = Blueprint("broadcasts", __name__)

INGEST_REGIONS = ("US_EAST", "US_WEST", "EU_WEST", "AP_SOUTH")
BROADCAST_TERMINAL = ("ENDED", "ABORTED")


def _event_of_broadcast(broadcast):
    session = S.sessions.get(broadcast.get("session_id"))
    if session is None:
        return None, None
    return session, S.events.get(session.get("event_id"))


@bp.route("/api/broadcasts", methods=["POST"])
def create_broadcast():
    authorize("Organizer")
    b = body()

    session = fk(b, "session_id", get_session)

    if session is not None:
        event = S.events.get(session.get("event_id"))
        if event is not None:
            own_event(event)

    req_str(b, "session_id")
    ingest_region = req_enum(b, "ingest_region", INGEST_REGIONS)

    row = db.new_row({
        "session_id": session["id"],
        "ingest_region": ingest_region,
        "state": "SCHEDULED",
        "started_at": None,
        "ended_at": None,
        "streamed_minutes": 0,
    })
    S.broadcasts[row["id"]] = row
    return ok(db.serialize(row), 201)


@bp.route("/api/broadcasts", methods=["GET"])
def list_broadcasts():
    authorize("Organizer", "PlatformAdmin")
    limit, offset = pagination()
    session_id = qs("session_id")
    state = qs("state")
    rows = [
        r for r in S.broadcasts.values()
        if (session_id is None or r.get("session_id") == session_id)
        and (state is None or r.get("state") == state)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/broadcasts/<broadcast_id>", methods=["GET"])
def read_broadcast(broadcast_id):
    authorize("Organizer", "PlatformAdmin")
    return ok(db.serialize(get_broadcast(broadcast_id)))


@bp.route("/api/broadcasts/<broadcast_id>/preview", methods=["POST"])
def preview_broadcast(broadcast_id):
    authorize("Organizer")
    broadcast = get_broadcast(broadcast_id)
    session, event = _event_of_broadcast(broadcast)
    if event is not None:
        own_event(event)

    guard_state(broadcast, ("SCHEDULED",), BROADCAST_TERMINAL)
    if session is None or session.get("state") != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    broadcast["state"] = "PREVIEW"
    db.touch(broadcast)
    return ok(db.serialize(broadcast))


@bp.route("/api/broadcasts/<broadcast_id>/go-live", methods=["POST"])
def go_live_broadcast(broadcast_id):
    authorize("Organizer")
    broadcast = get_broadcast(broadcast_id)
    session, event = _event_of_broadcast(broadcast)
    if event is not None:
        own_event(event)

    guard_state(broadcast, ("PREVIEW",), BROADCAST_TERMINAL)
    if session is None or session.get("state") != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    if event is None or event.get("state") != "LIVE":
        raise ApiError("ERR_INVALID_STATE")
    if int(session.get("accepted_speaker_count", 0)) < 1:
        raise ApiError("ERR_INVALID_STATE")

    broadcast["state"] = "LIVE"
    broadcast["started_at"] = S.now_iso()
    db.touch(broadcast)

    session["state"] = "LIVE"
    db.touch(session)

    recording = db.new_row({
        "broadcast_id": broadcast["id"],
        "session_id": session["id"],
        "event_id": event["id"],
        "state": "PENDING",
        "duration_seconds": 0,
        "gating_level": "ON_DEMAND",
        "view_count": 0,
    })
    S.recordings[recording["id"]] = recording

    return ok(db.serialize(broadcast))


@bp.route("/api/broadcasts/<broadcast_id>/end", methods=["POST"])
def end_broadcast(broadcast_id):
    authorize("Organizer")
    broadcast = get_broadcast(broadcast_id)
    session, event = _event_of_broadcast(broadcast)
    if event is not None:
        own_event(event)

    guard_state(broadcast, ("LIVE",), BROADCAST_TERMINAL)

    broadcast["state"] = "ENDED"
    broadcast["ended_at"] = S.now_iso()
    started = dt_of(broadcast, "started_at")
    ended = dt_of(broadcast, "ended_at")
    if started is not None and ended is not None and ended > started:
        broadcast["streamed_minutes"] = int((ended - started).total_seconds() // 60)
    else:
        broadcast["streamed_minutes"] = 0
    db.touch(broadcast)

    if event is not None:
        event["streamed_minutes_total"] = (
            int(event.get("streamed_minutes_total", 0)) + int(broadcast["streamed_minutes"])
        )

    if session is not None and session.get("state") == "LIVE":
        session["state"] = "COMPLETED"
        db.touch(session)

    for rec in db.sort_rows(list(S.recordings.values())):
        if rec.get("broadcast_id") == broadcast["id"] and rec.get("state") == "PENDING":
            rec["state"] = "PROCESSING"
            db.touch(rec)

    if event is not None:
        db.touch(event)
    return ok(db.serialize(broadcast))


@bp.route("/api/broadcasts/<broadcast_id>/abort", methods=["POST"])
def abort_broadcast_route(broadcast_id):
    authorize("Organizer")
    broadcast = get_broadcast(broadcast_id)
    session, event = _event_of_broadcast(broadcast)
    if event is not None:
        own_event(event)
    b = body()
    req_str(b, "reason")

    guard_state(broadcast, ("SCHEDULED", "PREVIEW", "LIVE"), BROADCAST_TERMINAL)
    cascades.abort_broadcast(broadcast, event)
    return ok(db.serialize(broadcast))
