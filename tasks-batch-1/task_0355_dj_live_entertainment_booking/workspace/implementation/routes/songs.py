"""Song request / do-not-play endpoints."""
from flask import Blueprint, request

import db
from errors import not_resource_owner
from middleware import authenticate, require_roles
from response import array_response, object_response
from services import get_or_404
from validate import (get_json_body, opt_int, opt_str, parse_pagination,
                      paginate, require_enum, require_nonempty_str)

bp = Blueprint("songs", __name__)

LIST_TYPES = {"REQUEST", "DO_NOT_PLAY"}


@bp.post("/bookings/<bid>/song-requests")
def create_song_request(bid):
    caller = authenticate()
    require_roles(caller, {"Client", "BookingAgent"})
    booking = get_or_404(db.bookings, bid)
    if caller.role == "Client" and caller.user_id != booking["client_id"]:
        raise not_resource_owner()

    body = get_json_body()
    title = require_nonempty_str(body, "title")
    artist = opt_str(body, "artist")
    list_type = require_enum(body, "list_type", LIST_TYPES)
    priority = opt_int(body, "priority", default=100, minimum=1)

    status = "ACCEPTED"
    if list_type == "REQUEST":
        # Conflict if an existing DO_NOT_PLAY on the same booking matches
        # (title, artist) case-insensitively.
        t_norm = title.strip().lower()
        a_norm = (artist or "").strip().lower()
        for s in db.song_requests.values():
            if s["booking_id"] != booking["id"]:
                continue
            if s["list_type"] != "DO_NOT_PLAY":
                continue
            s_title = (s["title"] or "").strip().lower()
            s_artist = (s["artist"] or "").strip().lower()
            if s_title == t_norm and s_artist == a_norm:
                status = "CONFLICTED"
                break

    rec = db.make_common()
    rec.update({
        "booking_id": booking["id"],
        "title": title,
        "artist": artist,
        "list_type": list_type,
        "priority": priority,
        "status": status,
    })
    db.song_requests[rec["id"]] = rec
    return object_response(rec, 201)


@bp.get("/bookings/<bid>/song-requests")
def list_song_requests(bid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer", "Client"})
    limit, offset = parse_pagination()
    booking = get_or_404(db.bookings, bid)
    if caller.role == "Client" and caller.user_id != booking["client_id"]:
        raise not_resource_owner()
    rows = [s for s in db.song_requests.values() if s["booking_id"] == bid]
    list_type = request.args.get("list_type")
    if list_type is not None:
        rows = [s for s in rows if s["list_type"] == list_type]
    page, total = paginate(rows, limit, offset)
    return array_response(page, limit, offset, total)


@bp.get("/song-requests/<sid>")
def get_song_request(sid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer", "Client"})
    rec = get_or_404(db.song_requests, sid)
    if caller.role == "Client":
        booking = db.bookings.get(rec["booking_id"])
        if booking is None or caller.user_id != booking["client_id"]:
            raise not_resource_owner()
    return object_response(rec)
