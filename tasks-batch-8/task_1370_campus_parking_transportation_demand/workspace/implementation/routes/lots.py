"""Parking lot endpoints."""
from flask import Blueprint, request

import db
from errors import bad_request, not_found, ERR_LOT_NOT_FOUND
from middleware import get_caller, require_roles, ALL_ROLES
from response import success, success_list, parse_pagination
from services.core import new_record, serialize, recompute_lot_reserved_and_availability

bp = Blueprint("lots", __name__)

ZONES = ("CORE", "PERIMETER", "REMOTE")


@bp.post("/parking/lots")
def create_lot():
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    body = request.get_json(silent=True) or {}

    lot_code = body.get("lot_code")
    name = body.get("name")
    zone = body.get("zone")
    capacity_total = body.get("capacity_total")

    if not isinstance(lot_code, str) or not lot_code:
        raise bad_request("lot_code is required")
    if not isinstance(name, str) or not name:
        raise bad_request("name is required")
    if zone not in ZONES:
        raise bad_request("zone must be CORE, PERIMETER, or REMOTE")
    if not isinstance(capacity_total, int) or isinstance(capacity_total, bool) or capacity_total < 1:
        raise bad_request("capacity_total must be an integer >= 1")

    record = new_record()
    record.update(
        lot_code=lot_code,
        name=name,
        zone=zone,
        capacity_total=capacity_total,
        posture="OPEN",
        reserved_spaces_total=0,
        available_capacity=capacity_total,
    )
    db.lots[record["id"]] = record
    return success(serialize(record), 201)


@bp.get("/parking/lots")
def list_lots():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)

    posture_filter = request.args.get("posture")
    zone_filter = request.args.get("zone")

    items = list(db.lots.values())
    if posture_filter is not None:
        items = [l for l in items if l["posture"] == posture_filter]
    if zone_filter is not None:
        items = [l for l in items if l["zone"] == zone_filter]
    # Refresh computed fields before returning
    for lot in items:
        recompute_lot_reserved_and_availability(lot)
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serialize(l) for l in page], limit, offset, total)


@bp.get("/parking/lots/<lotId>")
def get_lot(lotId):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    record = db.lots.get(lotId)
    if record is None:
        raise not_found(ERR_LOT_NOT_FOUND, "No parking lot with the given id")
    recompute_lot_reserved_and_availability(record)
    return success(serialize(record), 200)
