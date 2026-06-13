from datetime import timedelta
from flask import Blueprint, request

import errors
from errors import err
from db import db, new_id, now_iso
from middleware import require_roles, get_json
from response import created, ok, listing
from services import validate as V
from services.entities import get_room, get_slot, ser_slot, touch
from services.pricing import _parse_utc

bp = Blueprint("time_slots", __name__)


def _iso_utc(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.post("/time-slots")
def create_time_slot():
    require_roles({"VenueManager"})
    body = get_json()
    room_id = V.req_str(body, "room_id")
    start_utc = V.req_str(body, "start_utc")
    try:
        start_dt = _parse_utc(start_utc)
    except (ValueError, TypeError):
        raise err(errors.ERR_INVALID_REQUEST, "start_utc must be an ISO 8601 instant")

    room = get_room(room_id)
    if room["status"] == "RETIRED":
        raise err(errors.ERR_ROOM_RETIRED, "Room is retired")

    venue = db.venues.get(room["venue_id"])
    game_end_dt = start_dt + timedelta(minutes=room["game_minutes"])
    block_end_dt = start_dt + timedelta(
        minutes=room["game_minutes"] + room["reset_buffer_minutes"]
    )

    # Operating-hours check: game window fits within venue open/close minute-of-day (UTC).
    start_mod = start_dt.hour * 60 + start_dt.minute
    # Game-window length in minutes; end-of-game minute-of-day on the absolute timeline.
    game_end_mod = start_mod + room["game_minutes"]
    if start_mod < venue["open_minute_of_day"] or game_end_mod > venue["close_minute_of_day"]:
        raise err(errors.ERR_OUTSIDE_OPERATING_HOURS, "Slot outside venue operating hours")

    ts = now_iso()
    sid = new_id()
    slot = {
        "id": sid,
        "room_id": room_id,
        "venue_id": room["venue_id"],
        "start_utc": start_utc,
        "game_end_utc": _iso_utc(game_end_dt),
        "block_end_utc": _iso_utc(block_end_dt),
        "assigned_game_master_id": None,
        "booking_id": None,
        "status": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.time_slots[sid] = slot
    return created(ser_slot(slot))


@bp.get("/time-slots/<slot_id>")
def read_time_slot(slot_id):
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster", "Customer"})
    slot = get_slot(slot_id)
    return ok(ser_slot(slot))


@bp.get("/time-slots")
def list_time_slots():
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster", "Customer"})
    limit, offset = V.parse_pagination()
    room_id = request.args.get("room_id")
    venue_id = request.args.get("venue_id")
    assigned_gm = request.args.get("assigned_game_master_id")
    booking_id = request.args.get("booking_id")
    status = request.args.get("status")
    rows = list(db.time_slots.values())
    if room_id is not None:
        rows = [s for s in rows if s["room_id"] == room_id]
    if venue_id is not None:
        rows = [s for s in rows if s["venue_id"] == venue_id]
    if assigned_gm is not None:
        rows = [s for s in rows if s.get("assigned_game_master_id") == assigned_gm]
    if booking_id is not None:
        rows = [s for s in rows if s.get("booking_id") == booking_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return listing([ser_slot(s) for s in page], limit, offset, total)


def _slot_lifecycle(slot_id, allowed_from, target):
    slot = get_slot(slot_id)
    body = get_json()
    expected = V.req_int(body, "expected_time_slot_version")
    if slot["status"] not in allowed_from:
        raise err(errors.ERR_INVALID_STATE, "Slot not in a valid state for this action")
    if expected != slot["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale slot version")
    slot["status"] = target
    touch(slot)
    return ok(ser_slot(slot))


@bp.post("/time-slots/<slot_id>/block")
def block_slot(slot_id):
    require_roles({"VenueManager"})
    return _slot_lifecycle(slot_id, {"OPEN"}, "BLOCKED")


@bp.post("/time-slots/<slot_id>/unblock")
def unblock_slot(slot_id):
    require_roles({"VenueManager"})
    return _slot_lifecycle(slot_id, {"BLOCKED"}, "OPEN")


@bp.post("/time-slots/<slot_id>/close")
def close_slot(slot_id):
    require_roles({"VenueManager"})
    return _slot_lifecycle(slot_id, {"OPEN", "BLOCKED"}, "CLOSED")
