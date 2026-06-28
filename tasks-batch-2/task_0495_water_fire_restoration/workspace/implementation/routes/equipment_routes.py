from flask import Blueprint, request

from db import db, stamp_create
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from validate import get_body, req_str, req_enum, pagination_params

bp = Blueprint("equipment_units", __name__)

KINDS = {"AIR_MOVER", "DEHUMIDIFIER"}


@bp.route("/restoration/equipment-units", methods=["POST"])
def create_unit():
    auth(["PlatformAdmin", "Dispatcher"])
    body = get_body()
    asset_tag = req_str(body, "asset_tag")
    kind = req_enum(body, "kind", KINDS)

    entity = {
        "asset_tag": asset_tag,
        "kind": kind,
        "status": "AVAILABLE",
        "active_placement_id": None,
    }
    stamp_create(entity)
    db.units[entity["id"]] = entity
    return object_response(entity, status=201)


@bp.route("/restoration/equipment-units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    auth(["PlatformAdmin", "Dispatcher", "Technician"])
    return object_response(get_or_404(db.units, unit_id))


@bp.route("/restoration/equipment-units", methods=["GET"])
def list_units():
    auth(["PlatformAdmin", "Dispatcher", "Technician"])
    status = request.args.get("status")
    kind = request.args.get("kind")
    active_placement_id = request.args.get("active_placement_id")
    limit, offset = pagination_params()

    items = list(db.units.values())
    if status is not None:
        items = [u for u in items if u["status"] == status]
    if kind is not None:
        items = [u for u in items if u["kind"] == kind]
    if active_placement_id is not None:
        items = [u for u in items if u["active_placement_id"] == active_placement_id]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)
