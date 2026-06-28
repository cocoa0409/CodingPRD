"""ArtistAssignment endpoints (PRD §3.2).

Artist double-booking: 30-minute travel buffer on each side. The comparison
window for the NEW event is [start-30m, end+30m). An existing ASSIGNED
assignment conflicts when its event's [start, end) overlaps that buffered
window. A clear gap of exactly 30 minutes is allowed (half-open adjacency).
"""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import models
from errors import err
from response import object_response, array_response

bp = Blueprint("assignments", __name__)

BUFFER = timedelta(minutes=30)


@bp.post("/studio-ops/assignments")
def create_assignment():
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    body = helpers.get_json_body()
    event_id = helpers.as_str(body, "event_id")
    artist_id = helpers.as_str(body, "artist_id")

    # Priority 5: body FK existence.
    event = db.events.get(event_id)
    if not event:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "event_id does not exist")
    artist = db.artists.get(artist_id)
    if not artist:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "artist_id does not exist")

    # Priority 10: artist must be ACTIVE.
    if artist["status"] != "ACTIVE":
        raise err(errors.ERR_ARTIST_INACTIVE, "Artist is INACTIVE")

    # Priority 11: artist double-booking within 30m buffer.
    new_lo = event["_start_dt"] - BUFFER
    new_hi = event["_end_dt"] + BUFFER
    for a in db.assignments.values():
        if a["artist_id"] != artist_id or a["status"] != "ASSIGNED":
            continue
        other = db.events.get(a["event_id"])
        if not other:
            continue
        # buffered window [new_lo, new_hi) overlaps other's [start, end)
        if new_lo < other["_end_dt"] and new_hi > other["_start_dt"]:
            raise err(errors.ERR_ARTIST_DOUBLE_BOOKED,
                      "Artist is double-booked within the 30-minute buffer")

    rec = models.make_assignment(event_id, artist_id)
    db.assignments[rec["id"]] = rec
    return object_response(models.serialize_assignment(rec), 201)


@bp.get("/studio-ops/assignments/<aid>")
def get_assignment(aid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "FrontDesk", "PlatformAdmin")
    rec = db.assignments.get(aid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Assignment not found")
    return object_response(models.serialize_assignment(rec), 200)


@bp.get("/studio-ops/assignments")
def list_assignments():
    middleware.authenticate()
    middleware.require_roles("StudioManager", "FrontDesk", "PlatformAdmin")
    limit, offset = helpers.parse_pagination()
    event_id = request.args.get("event_id")
    artist_id = request.args.get("artist_id")
    status = request.args.get("status")
    rows = list(db.assignments.values())
    if event_id:
        rows = [r for r in rows if r["event_id"] == event_id]
    if artist_id:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = helpers.sort_and_page(rows, limit, offset)
    return array_response([models.serialize_assignment(r) for r in page],
                          limit, offset, total, 200)


@bp.post("/studio-ops/assignments/<aid>/release")
def release_assignment(aid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    rec = db.assignments.get(aid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Assignment not found")
    if rec["status"] != "ASSIGNED":
        raise err(errors.ERR_INVALID_STATE, "Assignment is not ASSIGNED")
    rec["status"] = "RELEASED"
    models.touch(rec)
    return object_response(models.serialize_assignment(rec), 200)
