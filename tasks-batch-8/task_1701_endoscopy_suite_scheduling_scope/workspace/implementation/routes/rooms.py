"""Room endpoints (PRD 3.1)."""
from flask import Blueprint, request

from errors import ERR_ROOM_NOT_FOUND
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from validate import get_body, opt_enum, opt_str, req_bool, req_enum, req_str, require_path_resource

bp = Blueprint("rooms", __name__)

ROOM_CLASSES = {"STANDARD", "ERCP_CAPABLE"}
ROOM_STATUSES = {"ACTIVE", "OUT_OF_SERVICE"}


@bp.post("/endoscopy/rooms")
def create_room():
    authorized(["UnitAdmin"])
    body = get_body()
    name = req_str(body, "name")
    room_class = req_enum(body, "room_class", ROOM_CLASSES)
    supports_anesthesia = req_bool(body, "supports_anesthesia")
    rec = new_record("rooms", {
        "name": name,
        "room_class": room_class,
        "supports_anesthesia": supports_anesthesia,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/endoscopy/rooms")
def list_rooms():
    return list_response("rooms", {"status": request.args.get("status")})


@bp.get("/endoscopy/rooms/<rid>")
def get_room(rid):
    return get_one("rooms", rid, ERR_ROOM_NOT_FOUND)


@bp.patch("/endoscopy/rooms/<rid>")
def patch_room(rid):
    authorized(["UnitAdmin"])
    rec = require_path_resource("rooms", rid, ERR_ROOM_NOT_FOUND)
    body = get_body()
    name = opt_str(body, "name", None)
    status = opt_enum(body, "status", ROOM_STATUSES, None)
    if name is not None:
        rec["name"] = name
    if status is not None:
        rec["status"] = status
    touch(rec)
    return success_object(public(rec))
