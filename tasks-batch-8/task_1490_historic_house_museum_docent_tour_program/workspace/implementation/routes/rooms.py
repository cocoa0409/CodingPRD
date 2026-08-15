"""Room endpoints."""
from flask import Blueprint

from db import DB, new_id
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import lookup, ser_incident, ser_room, ser_route, sort_items, stamp
from util import body, pagination_args, req_enum, req_int, req_str

bp = Blueprint("rooms", __name__)

COLLECTION_TIERS = ("STANDARD", "LIGHT_SENSITIVE", "HIGH_VALUE")


def _paginate(items, serializer):
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(x) for x in page], total, limit, offset)


@bp.post("/rooms")
def create_room():
    auth(["MuseumAdmin"])
    data = body()
    name = req_str(data, "name")
    floor = req_int(data, "floor")
    capacity_max = req_int(data, "capacity_max", minimum=1)
    safety_max_party = req_int(data, "safety_max_party", minimum=1)
    tier = req_enum(data, "collection_tier", COLLECTION_TIERS)
    rec = {
        "id": new_id(),
        "name": name,
        "floor": floor,
        "capacity_max": capacity_max,
        "safety_max_party": safety_max_party,
        "collection_tier": tier,
        "status": "OPEN",
    }
    stamp(rec)
    DB["rooms"][rec["id"]] = rec
    return ok(ser_room(rec), 201)


@bp.get("/rooms/<rid>")
def get_room(rid):
    auth(ALL_ROLES)
    return ok(ser_room(lookup("rooms", rid)))


@bp.get("/rooms/<rid>/routes")
def list_room_routes(rid):
    auth(ALL_ROLES)
    room = lookup("rooms", rid)
    items = sort_items(
        [r for r in DB["routes"].values() if room["id"] in r["room_ids"]]
    )
    return _paginate(items, ser_route)


@bp.get("/rooms/<rid>/incidents")
def list_room_incidents(rid):
    auth(["MuseumAdmin", "Curator"])
    room = lookup("rooms", rid)
    items = sort_items(
        [i for i in DB["incidents"].values() if i["room_id"] == room["id"]]
    )
    return _paginate(items, ser_incident)
