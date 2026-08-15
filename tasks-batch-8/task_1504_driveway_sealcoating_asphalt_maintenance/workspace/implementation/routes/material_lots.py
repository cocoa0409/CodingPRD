"""MaterialLot endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import (
    require_role, get_json_body, require_fields, check_unknown_fields,
    require_number, base_fields, paginate, err, valid_date_str,
)
from response import success_object, success_list
from errors import (
    ERR_MATERIAL_LOT_NOT_FOUND, ERR_MATERIAL_NOT_FOUND,
    ERR_MATERIAL_LOT_UNAVAILABLE, ERR_MATERIAL_LOT_IN_USE, ERR_INVALID_REQUEST,
)
from services import refresh_material_lot

bp = Blueprint("material_lots", __name__)


def serialize_lot(l):
    return {
        "id": l["id"],
        "material_id": l["material_id"],
        "delivered_gallons": l["delivered_gallons"],
        "reserved_gallons": l["reserved_gallons"],
        "consumed_gallons": l["consumed_gallons"],
        "wasted_gallons": l["wasted_gallons"],
        "on_hand_gallons": l["on_hand_gallons"],
        "unit_cost_cents": l["unit_cost_cents"],
        "received_on": l["received_on"],
        "reorder_threshold_gallons": l["reorder_threshold_gallons"],
        "reorder_flag": l["reorder_flag"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


@bp.post("/api/material-lots")
def create_material_lot():
    require_role("OfficeAdmin")
    body = get_json_body()
    check_unknown_fields(body, {"material_id", "delivered_gallons", "unit_cost_cents",
                                 "received_on", "reorder_threshold_gallons"})
    require_fields(body, ["material_id", "delivered_gallons", "unit_cost_cents",
                          "received_on", "reorder_threshold_gallons"])
    mat = DB.materials.get(body["material_id"])
    if mat is None:
        raise err(ERR_MATERIAL_NOT_FOUND, 404, "Material id does not exist")
    delivered = require_number(body, "delivered_gallons", gt=0)
    unit_cost = require_number(body, "unit_cost_cents", integer=True)
    received_on = body["received_on"]
    if not valid_date_str(received_on):
        raise err(ERR_INVALID_REQUEST, 400, "received_on must be YYYY-MM-DD")
    threshold = require_number(body, "reorder_threshold_gallons", ge=0)
    l = base_fields()
    l.update({
        "material_id": body["material_id"],
        "delivered_gallons": delivered,
        "reserved_gallons": 0,
        "consumed_gallons": 0,
        "wasted_gallons": 0,
        "on_hand_gallons": delivered,
        "unit_cost_cents": unit_cost,
        "received_on": received_on,
        "reorder_threshold_gallons": threshold,
        "reorder_flag": delivered <= threshold,
        "status": "RECEIVED",
    })
    DB.material_lots[l["id"]] = l
    return success_object(serialize_lot(l), status=201)


@bp.get("/api/material-lots")
def list_material_lots():
    require_role("OfficeAdmin", "Dispatcher")
    material_filter = request.args.get("material_id")
    status_filter = request.args.get("status")
    items = list(DB.material_lots.values())
    if material_filter:
        items = [l for l in items if l["material_id"] == material_filter]
    if status_filter:
        items = [l for l in items if l["status"] == status_filter]
    items.sort(key=lambda l: l["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_lot(l) for l in page], limit, offset, total)


@bp.get("/api/material-lots/<lotId>")
def get_material_lot(lotId):
    require_role("OfficeAdmin", "Dispatcher")
    l = DB.material_lots.get(lotId)
    if l is None:
        raise err(ERR_MATERIAL_LOT_NOT_FOUND, 404, "Material lot id does not exist")
    return success_object(serialize_lot(l))


@bp.post("/api/material-lots/<lotId>/quarantine")
def quarantine_lot(lotId):
    require_role("OfficeAdmin")
    l = DB.material_lots.get(lotId)
    if l is None:
        raise err(ERR_MATERIAL_LOT_NOT_FOUND, 404, "Material lot id does not exist")
    if l["status"] not in ("RECEIVED", "IN_USE"):
        raise err(ERR_MATERIAL_LOT_UNAVAILABLE, 409, "Lot QUARANTINED or DEPLETED when referenced")
    if l["status"] == "IN_USE" and l["reserved_gallons"] > 0:
        raise err(ERR_MATERIAL_LOT_IN_USE, 409, "Quarantine attempted with reserved_gallons > 0")
    l["status"] = "QUARANTINED"
    from middleware import touch
    touch(l)
    return success_object(serialize_lot(l))


@bp.post("/api/material-lots/<lotId>/record-waste")
def record_waste(lotId):
    require_role("OfficeAdmin")
    l = DB.material_lots.get(lotId)
    if l is None:
        raise err(ERR_MATERIAL_LOT_NOT_FOUND, 404, "Material lot id does not exist")
    body = get_json_body()
    check_unknown_fields(body, {"wasted_gallons"})
    require_fields(body, ["wasted_gallons"])
    wasted = require_number(body, "wasted_gallons", gt=0)
    l["wasted_gallons"] = l["wasted_gallons"] + wasted
    refresh_material_lot(l)
    return success_object(serialize_lot(l))
