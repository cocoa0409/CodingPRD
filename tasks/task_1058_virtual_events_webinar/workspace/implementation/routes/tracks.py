"""Tracks: the scheduling resource sessions compete for (PRD 3.6)."""

from flask import Blueprint

import db
from auth import authorize, own_event
from db import S
from response import ok, ok_list
from validate import body, get_event, get_track, pagination, paginate, qs, req_str

bp = Blueprint("tracks", __name__)


@bp.route("/api/events/<event_id>/tracks", methods=["POST"])
def create_track(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)
    b = body()
    name = req_str(b, "name")
    row = db.new_row({
        "event_id": event["id"],
        "name": name,
        "scheduled_session_count": 0,
    })
    S.tracks[row["id"]] = row
    return ok(db.serialize(row), 201)


@bp.route("/api/events/<event_id>/tracks", methods=["GET"])
def list_event_tracks(event_id):
    authorize("Organizer", "PlatformAdmin")
    event = get_event(event_id)
    limit, offset = pagination()
    rows = [t for t in S.tracks.values() if t.get("event_id") == event["id"]]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/tracks", methods=["GET"])
def list_tracks():
    authorize("Organizer", "PlatformAdmin")
    limit, offset = pagination()
    event_id = qs("event_id")
    rows = [
        t for t in S.tracks.values()
        if event_id is None or t.get("event_id") == event_id
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/tracks/<track_id>", methods=["GET"])
def read_track(track_id):
    authorize("Organizer", "PlatformAdmin")
    return ok(db.serialize(get_track(track_id)))
