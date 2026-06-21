from flask import Blueprint, request

import errors
from errors import err
from db import db, new_id, now_iso
from middleware import require_roles, get_json
from response import created, ok, listing
from services import validate as V
from services.entities import get_venue, get_room, ser_room, touch

bp = Blueprint("rooms", __name__)


@bp.post("/rooms")
def create_room():
    require_roles({"VenueManager"})
    body = get_json()
    venue_id = V.req_str(body, "venue_id")
    name = V.req_str(body, "name")
    min_group = V.req_int(body, "min_group_size", min_v=1)
    max_group = V.req_int(body, "max_group_size", min_v=1)
    base_price = V.req_int(body, "base_price_cents", min_v=0)
    game_minutes = V.req_int(body, "game_minutes", min_v=1)
    min_age = V.opt_int(body, "min_age", default=0, min_v=0)
    waiver_required = V.opt_bool(body, "waiver_required", default=True)
    private_surcharge = V.opt_int(body, "private_surcharge_cents", default=0, min_v=0)
    reset_buffer = V.opt_int(body, "reset_buffer_minutes", default=0, min_v=0)
    if not (min_group <= max_group):
        raise err(errors.ERR_INVALID_REQUEST, "min_group_size must be <= max_group_size")

    # Existence of venue (body reference).
    get_venue(venue_id)

    ts = now_iso()
    rid = new_id()
    room = {
        "id": rid,
        "venue_id": venue_id,
        "name": name,
        "min_group_size": min_group,
        "max_group_size": max_group,
        "min_age": min_age,
        "waiver_required": waiver_required,
        "base_price_cents": base_price,
        "private_surcharge_cents": private_surcharge,
        "game_minutes": game_minutes,
        "reset_buffer_minutes": reset_buffer,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.rooms[rid] = room
    return created(ser_room(room))


@bp.get("/rooms/<room_id>")
def read_room(room_id):
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster", "Customer"})
    room = get_room(room_id)
    return ok(ser_room(room))


@bp.get("/rooms")
def list_rooms():
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster", "Customer"})
    limit, offset = V.parse_pagination()
    venue_id = request.args.get("venue_id")
    rows = list(db.rooms.values())
    if venue_id is not None:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    page, total = V.paginate(rows, limit, offset)
    return listing([ser_room(r) for r in page], limit, offset, total)


@bp.post("/rooms/<room_id>/retire")
def retire_room(room_id):
    require_roles({"VenueManager"})
    room = get_room(room_id)
    body = get_json()
    # Priority 5: required field present & well-typed.
    expected = V.req_int(body, "expected_room_version")
    # Priority 6: state.
    if room["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Room is not ACTIVE")
    # Priority 7: OCC.
    if expected != room["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale room version")
    room["status"] = "RETIRED"
    touch(room)
    return ok(ser_room(room))
