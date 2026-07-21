"""Speaker profiles scoped to an event (PRD 3.6)."""

from flask import Blueprint

import db
from auth import authorize, own_event
from db import S
from errors import ApiError
from response import ok, ok_list
from validate import body, get_event, get_speaker, pagination, paginate, qs, req_str

bp = Blueprint("speakers", __name__)


@bp.route("/api/events/<event_id>/speakers", methods=["POST"])
def create_speaker(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")

    for sp in S.speakers.values():
        if sp.get("event_id") == event["id"] and sp.get("email") == email:
            raise ApiError("ERR_VALIDATION", "email is already used by a speaker of this event.")

    row = db.new_row({
        "event_id": event["id"],
        "full_name": full_name,
        "email": email,
        "accepted_session_count": 0,
        "engagement_status": "UNASSIGNED",
    })
    S.speakers[row["id"]] = row
    return ok(db.serialize(row), 201)


@bp.route("/api/events/<event_id>/speakers", methods=["GET"])
def list_event_speakers(event_id):
    authorize("Organizer", "PlatformAdmin", "SpeakerUser")
    event = get_event(event_id)
    limit, offset = pagination()
    rows = [s for s in S.speakers.values() if s.get("event_id") == event["id"]]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/speakers", methods=["GET"])
def list_speakers():
    authorize("Organizer", "PlatformAdmin", "SpeakerUser")
    limit, offset = pagination()
    event_id = qs("event_id")
    engagement_status = qs("engagement_status")
    rows = [
        s for s in S.speakers.values()
        if (event_id is None or s.get("event_id") == event_id)
        and (engagement_status is None or s.get("engagement_status") == engagement_status)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/speakers/<speaker_id>", methods=["GET"])
def read_speaker(speaker_id):
    authorize("Organizer", "PlatformAdmin", "SpeakerUser")
    return ok(db.serialize(get_speaker(speaker_id)))
