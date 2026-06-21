from flask import Blueprint, request

import errors
from errors import err
from db import db, new_id, now_iso
from middleware import require_roles, get_json
from response import created, ok, listing
from services import validate as V
from services.entities import get_venue, get_game_master, ser_game_master, touch

bp = Blueprint("game_masters", __name__)


@bp.post("/game-masters")
def create_game_master():
    require_roles({"VenueManager"})
    body = get_json()
    venue_id = V.req_str(body, "venue_id")
    full_name = V.req_str(body, "full_name")
    get_venue(venue_id)

    ts = now_iso()
    gid = new_id()
    gm = {
        "id": gid,
        "venue_id": venue_id,
        "full_name": full_name,
        "status": "AVAILABLE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.game_masters[gid] = gm
    return created(ser_game_master(gm))


@bp.get("/game-masters/<game_master_id>")
def read_game_master(game_master_id):
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster"})
    gm = get_game_master(game_master_id)
    return ok(ser_game_master(gm))


@bp.get("/game-masters")
def list_game_masters():
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster"})
    limit, offset = V.parse_pagination()
    venue_id = request.args.get("venue_id")
    rows = list(db.game_masters.values())
    if venue_id is not None:
        rows = [g for g in rows if g["venue_id"] == venue_id]
    page, total = V.paginate(rows, limit, offset)
    return listing([ser_game_master(g) for g in page], limit, offset, total)


@bp.post("/game-masters/<game_master_id>/set-status")
def set_status(game_master_id):
    require_roles({"VenueManager"})
    gm = get_game_master(game_master_id)
    body = get_json()
    status = V.req_enum(body, "status", {"AVAILABLE", "OFF_DUTY"})
    expected = V.req_int(body, "expected_game_master_version")
    if expected != gm["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale game master version")
    gm["status"] = status
    touch(gm)
    return ok(ser_game_master(gm))
