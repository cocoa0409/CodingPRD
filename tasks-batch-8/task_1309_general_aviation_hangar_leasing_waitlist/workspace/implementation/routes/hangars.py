"""Hangar endpoints: create/list/get/decommission."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_roles
from envelope import success_list, success_obj
from errors import ApiError, ERR_HANGAR_OCCUPIED, ERR_NOT_FOUND, ERR_OPEN_OFFER_EXISTS
from services.core import DOOR_TYPES, SIZE_CLASSES, occupying_lease, open_offer_on_hangar, serialize_hangar, touch
from validators import body, paginate, pagination, req_enum, req_str

bp = Blueprint("hangars", __name__)


def get_hangar_or_404(hangar_id):
    hangar = db.hangars.get(hangar_id)
    if hangar is None:
        raise ApiError(ERR_NOT_FOUND, "Hangar not found", 404)
    return hangar


@bp.post("/hangars")
def create_hangar():
    require_roles("AirportManager")
    data = body()
    airport_id = req_str(data, "airport_id")
    if db.airports.get(airport_id) is None:
        raise ApiError(ERR_NOT_FOUND, "Airport not found", 404)
    hangar_code = req_str(data, "hangar_code")
    size_class = req_enum(data, "size_class", SIZE_CLASSES)
    door_type = req_enum(data, "door_type", DOOR_TYPES)
    hangar = db.new_entity({
        "airport_id": airport_id,
        "hangar_code": hangar_code,
        "size_class": size_class,
        "door_type": door_type,
        "condition_rating": "GOOD",
        "status": "OPERATIONAL",
    })
    db.hangars[hangar["id"]] = hangar
    return success_obj(serialize_hangar(hangar), 201)


@bp.get("/hangars")
def list_hangars():
    require_roles(*ALL_ROLES)
    from services.core import hangar_posture
    items = list(db.hangars.values())
    airport_id = request.args.get("airport_id")
    size_class = request.args.get("size_class")
    posture = request.args.get("posture")
    if airport_id is not None:
        items = [h for h in items if h["airport_id"] == airport_id]
    if size_class is not None:
        items = [h for h in items if h["size_class"] == size_class]
    if posture is not None:
        items = [h for h in items if hangar_posture(h) == posture]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_hangar(h) for h in page], limit, offset, total)


@bp.get("/hangars/<hid>")
def get_hangar(hid):
    require_roles(*ALL_ROLES)
    return success_obj(serialize_hangar(get_hangar_or_404(hid)), 200)


@bp.post("/hangars/<hid>/decommission")
def decommission_hangar(hid):
    require_roles("AirportManager")
    hangar = get_hangar_or_404(hid)
    if occupying_lease(hangar["id"]) is not None:
        raise ApiError(ERR_HANGAR_OCCUPIED, "An active-phase lease occupies the hangar", 409)
    if open_offer_on_hangar(hangar["id"]) is not None:
        raise ApiError(ERR_OPEN_OFFER_EXISTS, "An OPEN offer exists on the hangar", 409)
    hangar["status"] = "DECOMMISSIONED"
    touch(hangar)
    return success_obj(serialize_hangar(hangar), 200)
