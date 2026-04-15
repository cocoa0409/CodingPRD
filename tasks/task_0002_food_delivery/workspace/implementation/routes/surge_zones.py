"""Surge zone routes."""

from flask import Blueprint, request as req
import db
from errors import raise_error, ERR_SURGE_ZONE_NOT_FOUND, ERR_INVALID_SURGE_MULTIPLIER, \
    ERR_VERSION_CONFLICT
from middleware import require_roles
from response import success_response, list_response

bp = Blueprint("surge_zones", __name__)


def _paginate(request):
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    return limit, offset


@bp.route("/platform/surge-zones", methods=["POST"])
def create_surge_zone():
    require_roles("platform_admin")
    body = req.get_json(force=True, silent=True) or {}
    mult = body.get("surge_multiplier", 1.0)
    if mult < 1.0 or mult > 3.0:
        raise_error(ERR_INVALID_SURGE_MULTIPLIER, "Surge multiplier must be between 1.0 and 3.0.")
    now = db.now_iso()
    sz = {
        "id": db.new_id(),
        "zone_name": body.get("zone_name"),
        "center_latitude": body.get("center_latitude"),
        "center_longitude": body.get("center_longitude"),
        "radius_km": body.get("radius_km"),
        "surge_multiplier": mult,
        "active_rider_count": 0,
        "pending_order_count": 0,
        "status": "ACTIVE",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.surge_zones[sz["id"]] = sz
    return success_response(sz, 201)


@bp.route("/platform/surge-zones", methods=["GET"])
def list_surge_zones():
    require_roles("platform_admin")
    limit, offset = _paginate(req)
    items = sorted(db.surge_zones.values(), key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.route("/platform/surge-zones/<surge_zone_id>", methods=["PATCH"])
def update_surge_zone(surge_zone_id):
    require_roles("platform_admin")
    sz = db.surge_zones.get(surge_zone_id)
    if not sz:
        raise_error(ERR_SURGE_ZONE_NOT_FOUND, "Surge zone not found.")
    body = req.get_json(force=True, silent=True) or {}
    if "version" in body and body["version"] is not None:
        if body["version"] != sz["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch.")
    if "surge_multiplier" in body:
        m = body["surge_multiplier"]
        if m < 1.0 or m > 3.0:
            raise_error(ERR_INVALID_SURGE_MULTIPLIER, "Surge multiplier must be between 1.0 and 3.0.")
        sz["surge_multiplier"] = m
    for key in ("radius_km", "status", "zone_name", "center_latitude", "center_longitude"):
        if key in body:
            sz[key] = body[key]
    sz["updated_at"] = db.now_iso()
    sz["version"] += 1
    return success_response(sz)
