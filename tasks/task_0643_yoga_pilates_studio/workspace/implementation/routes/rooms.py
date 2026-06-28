"""Room endpoints, including OCC-guarded update with demotion cascade (PRD §3.1, §3.5)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import authenticate, require_roles
from models import make_room, serialize, touch
from response import success, list_success
from helpers import (get_json_body, parse_pagination, paginate,
                     require_str, require_int, find_or_404)
from services import (recompute_session_counts, effective_capacity,
                      recompute_session_posture, repack_waitlist)

bp = Blueprint("rooms", __name__)

CATALOG_READERS = {"StudioManager", "Member", "Instructor"}


@bp.post("/rooms")
def create_room():
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()
    name = require_str(body, "name")
    room_type = body.get("room_type")
    if room_type not in ("REFORMER", "MAT"):
        raise err("ERR_INVALID_REQUEST", "room_type must be REFORMER or MAT")
    station_capacity = require_int(body, "station_capacity", minimum=1)
    room = make_room(name, room_type, station_capacity)
    store.rooms[room["id"]] = room
    return success(serialize(room), status=201)


@bp.get("/rooms/<rid>")
def get_room(rid):
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    room = find_or_404(store.rooms, rid, "Room")
    return success(serialize(room))


@bp.patch("/rooms/<rid>")
def update_room(rid):
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    room = find_or_404(store.rooms, rid, "Room")
    body = get_json_body()

    # OCC guard: expected_room_version mandatory.
    if "expected_room_version" not in body or body["expected_room_version"] is None:
        raise err("ERR_VERSION_REQUIRED", "expected_room_version is required")
    expected = body["expected_room_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_room_version must be an integer")
    if expected != room["version"]:
        raise err("ERR_STALE_VERSION", "Room version mismatch")

    # Apply updates.
    if "name" in body and body["name"] is not None:
        if not isinstance(body["name"], str) or not body["name"].strip():
            raise err("ERR_INVALID_REQUEST", "name must be a non-empty string")
        room["name"] = body["name"]
    if "status" in body and body["status"] is not None:
        if body["status"] not in ("OPEN", "CLOSED"):
            raise err("ERR_INVALID_REQUEST", "status must be OPEN or CLOSED")
        room["status"] = body["status"]
    capacity_changed = False
    if "station_capacity" in body and body["station_capacity"] is not None:
        cap = body["station_capacity"]
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
            raise err("ERR_INVALID_REQUEST", "station_capacity must be an integer >= 1")
        room["station_capacity"] = cap
        capacity_changed = True

    touch(room)

    if capacity_changed:
        _cascade_demotions(room)

    return success(serialize(room))


def _cascade_demotions(room):
    """If a published session's booked_count exceeds the new effective capacity,
    demote the most-recently-booked over-capacity BOOKED holders to WAITLISTED.

    Demotion order: latest booked_at_utc first; tie-break earliest created_at.
    Each demoted reservation goes to waitlist_position 1 (head), shifting the
    existing waitlist down behind it.
    """
    for session in store.class_sessions.values():
        if session["room_id"] != room["id"]:
            continue
        if session["status"] not in ("OPEN", "FULL"):
            continue
        recompute_session_counts(session)
        cap = effective_capacity(session)
        # Demote one-by-one until booked fits.
        while True:
            recompute_session_counts(session)
            if session["booked_count"] <= cap:
                break
            booked = [r for r in store.reservations.values()
                      if r["class_session_id"] == session["id"]
                      and r["status"] == "BOOKED"]
            if not booked:
                break
            target = _pick_demotion_target(booked)
            # Shift existing waitlist down, place target at position 1.
            for r in store.reservations.values():
                if (r["class_session_id"] == session["id"]
                        and r["status"] == "WAITLISTED"
                        and r["waitlist_position"] is not None):
                    r["waitlist_position"] += 1
                    touch(r)
            target["status"] = "WAITLISTED"
            target["waitlist_position"] = 1
            touch(target)
            recompute_session_counts(session)
        repack_waitlist(session["id"])
        recompute_session_counts(session)
        recompute_session_posture(session)


def _pick_demotion_target(booked):
    """Most-recently-booked (latest booked_at_utc); tie-break earliest created_at."""
    latest_ts = max(r["booked_at_utc"] for r in booked)
    candidates = [r for r in booked if r["booked_at_utc"] == latest_ts]
    candidates.sort(key=lambda r: r["_seq"])  # earliest created_at first
    return candidates[0]


@bp.get("/rooms/<rid>/class-sessions")
def room_sessions(rid):
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    find_or_404(store.rooms, rid, "Room")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [s for s in store.class_sessions.values() if s["room_id"] == rid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(s) for s in window], 200, limit, offset, total)


@bp.get("/rooms/<rid>/workshops")
def room_workshops(rid):
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    find_or_404(store.rooms, rid, "Room")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [w for w in store.workshops.values() if w["room_id"] == rid]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(w) for w in window], 200, limit, offset, total)
