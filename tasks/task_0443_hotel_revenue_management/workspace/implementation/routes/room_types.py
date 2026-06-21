"""RoomType endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db, new_id
from middleware import authenticate, require_role
from response import success, list_success
from errors import (
    err, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND, ERR_DUPLICATE_ROOM_TYPE_CODE,
)
from services.common import (
    get_body, require_str, require_int, stamp_new,
    parse_pagination, sort_by_created, get_or_404,
)
from services.serialize import ser_room_type

bp = Blueprint("room_types", __name__)

ALL_ROLES = {"RevenueManager", "GroupSalesManager", "ChannelManager", "Analyst"}


@bp.route("/room-types", methods=["POST"])
def create_room_type():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = get_body()
    property_id = require_str(body, "property_id")
    code = require_str(body, "code")
    name = require_str(body, "name")
    physical_rooms = require_int(body, "physical_rooms")
    if physical_rooms < 1:
        raise err(ERR_INVALID_REQUEST, "physical_rooms must be >= 1")

    # FK resolution.
    if property_id not in db.properties:
        raise err(ERR_FK_NOT_FOUND, "property_id does not reference an existing property")

    # code unique within property.
    for rt in db.room_types.values():
        if rt["property_id"] == property_id and rt["code"] == code:
            raise err(ERR_DUPLICATE_ROOM_TYPE_CODE, "code already used within the property")

    rec = {
        "id": new_id(),
        "property_id": property_id,
        "code": code,
        "name": name,
        "physical_rooms": physical_rooms,
        "_seq": db.next_seq(),
    }
    stamp_new(rec)
    db.room_types[rec["id"]] = rec
    return success(ser_room_type(rec), status=201)


@bp.route("/room-types/<rid>", methods=["GET"])
def get_room_type(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.room_types, rid)
    return success(ser_room_type(rec), status=200)


@bp.route("/room-types", methods=["GET"])
def list_room_types():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    items = [r for r in db.room_types.values()
             if property_id is None or r["property_id"] == property_id]
    items = sort_by_created(items)
    total = len(items)
    page = [ser_room_type(r) for r in items[offset:offset + limit]]
    return list_success(page, limit, offset, total)
