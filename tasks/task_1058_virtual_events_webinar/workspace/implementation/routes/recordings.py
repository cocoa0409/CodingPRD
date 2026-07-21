"""Recordings: the cyclic media lifecycle and on-demand gating (PRD 3.7)."""

from flask import Blueprint

import db
from auth import authorize, own_entity, own_event
from db import S
from errors import ApiError
from response import ok, ok_list
from validate import (
    body, get_recording, get_registration, guard_state, pagination, paginate,
    qs, req_enum, req_int, req_str,
)
from routes.registrations import fk

bp = Blueprint("recordings", __name__)

RECORDING_TERMINAL = ("DELETED",)
PUBLISH_GATING = ("ON_DEMAND", "BOTH")


def _event_of(recording):
    return S.events.get(recording.get("event_id"))


@bp.route("/api/recordings", methods=["GET"])
def list_recordings():
    authorize("Organizer", "PlatformAdmin", "Attendee")
    limit, offset = pagination()
    event_id = qs("event_id")
    session_id = qs("session_id")
    broadcast_id = qs("broadcast_id")
    state = qs("state")
    rows = []
    for r in S.recordings.values():
        if r.get("state") == "DELETED" and state != "DELETED":
            continue
        if event_id is not None and r.get("event_id") != event_id:
            continue
        if session_id is not None and r.get("session_id") != session_id:
            continue
        if broadcast_id is not None and r.get("broadcast_id") != broadcast_id:
            continue
        if state is not None and r.get("state") != state:
            continue
        rows.append(r)
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/recordings/<recording_id>", methods=["GET"])
def read_recording(recording_id):
    authorize("Organizer", "PlatformAdmin", "Attendee")
    return ok(db.serialize(get_recording(recording_id)))


@bp.route("/api/recordings/<recording_id>/complete", methods=["POST"])
def complete_recording(recording_id):
    authorize("PlatformAdmin")
    rec = get_recording(recording_id)
    b = body()
    duration_seconds = req_int(b, "duration_seconds", minimum=0)
    guard_state(rec, ("PROCESSING",), RECORDING_TERMINAL)
    rec["state"] = "READY"
    rec["duration_seconds"] = duration_seconds
    db.touch(rec)
    return ok(db.serialize(rec))


@bp.route("/api/recordings/<recording_id>/publish", methods=["POST"])
def publish_recording(recording_id):
    authorize("Organizer")
    rec = get_recording(recording_id)
    event = _event_of(rec)
    if event is not None:
        own_event(event)
    b = body()
    gating_level = req_enum(b, "gating_level", PUBLISH_GATING)

    guard_state(rec, ("READY",), RECORDING_TERMINAL)
    if int(rec.get("duration_seconds", 0)) <= 0:
        raise ApiError("ERR_INVALID_STATE", "A zero-length asset cannot be published.")

    rec["state"] = "PUBLISHED"
    rec["gating_level"] = gating_level
    db.touch(rec)
    if event is not None:
        event["published_recording_count"] = int(event.get("published_recording_count", 0)) + 1
    return ok(db.serialize(rec))


@bp.route("/api/recordings/<recording_id>/retract", methods=["POST"])
def retract_recording(recording_id):
    authorize("Organizer")
    rec = get_recording(recording_id)
    event = _event_of(rec)
    if event is not None:
        own_event(event)
    b = body()
    req_str(b, "reason")

    guard_state(rec, ("PUBLISHED",), RECORDING_TERMINAL)
    rec["state"] = "RETRACTED"
    db.touch(rec)
    if event is not None:
        event["published_recording_count"] = max(
            0, int(event.get("published_recording_count", 0)) - 1
        )
    return ok(db.serialize(rec))


@bp.route("/api/recordings/<recording_id>/reprocess", methods=["POST"])
def reprocess_recording(recording_id):
    authorize("PlatformAdmin")
    rec = get_recording(recording_id)
    guard_state(rec, ("RETRACTED",), RECORDING_TERMINAL)
    rec["state"] = "PROCESSING"
    rec["duration_seconds"] = 0
    db.touch(rec)
    return ok(db.serialize(rec))


@bp.route("/api/recordings/<recording_id>/views", methods=["POST"])
def record_view(recording_id):
    authorize("Attendee")
    rec = get_recording(recording_id)
    b = body()

    registration = fk(b, "registration_id", get_registration)
    if registration is not None:
        own_entity(registration["id"])

    req_str(b, "registration_id")

    if rec.get("state") != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", "The asset is not available for viewing.")

    ticket_type = S.ticket_types.get(registration.get("ticket_type_id"))
    gating = ticket_type.get("gating_level") if ticket_type is not None else None
    if gating not in ("ON_DEMAND", "BOTH"):
        raise ApiError("ERR_GATING_NOT_PERMITTED")
    if registration.get("payment_status") != "PAID":
        raise ApiError("ERR_GATING_NOT_PERMITTED")

    if registration.get("event_id") != rec.get("event_id"):
        raise ApiError("ERR_REGISTRATION_EVENT_MISMATCH")

    rec["view_count"] = int(rec.get("view_count", 0)) + 1
    db.touch(rec)
    return ok(db.serialize(rec))


@bp.route("/api/recordings/<recording_id>", methods=["DELETE"])
def delete_recording(recording_id):
    authorize("Organizer")
    rec = get_recording(recording_id)
    event = _event_of(rec)
    if event is not None:
        own_event(event)
    guard_state(rec, ("RETRACTED", "READY"), RECORDING_TERMINAL)
    rec["state"] = "DELETED"
    db.touch(rec)
    return "", 204
