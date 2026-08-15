"""BoomTruck endpoints."""
from flask import Blueprint, request
from db import db
from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from middleware import require_roles
from response import success
from services.helpers import (
    parse_pagination, paginate, body, require_fields, require_int, require_str,
    new_common_fields, touch,
)

bp = Blueprint("trucks", __name__)


def _get_truck_or_404(tid):
    t = db.boom_trucks.get(tid)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, "BoomTruck not found", 404)
    return t


@bp.route("/supply/boom-trucks", methods=["POST"])
def create_truck():
    require_roles("DispatcherUser")
    b = body()
    require_fields(b, "truck_code", "max_bundle_capacity", "max_weight_lbs")
    truck_code = require_str(b, "truck_code")
    max_bundle_capacity = require_int(b, "max_bundle_capacity", min_val=1)
    max_weight_lbs = require_int(b, "max_weight_lbs", min_val=1)
    for t in db.boom_trucks.values():
        if t["truck_code"] == truck_code:
            raise ApiError(ERR_VALIDATION, f"truck_code {truck_code} already exists", 400)
    truck = new_common_fields()
    truck.update({
        "truck_code": truck_code,
        "max_bundle_capacity": max_bundle_capacity,
        "max_weight_lbs": max_weight_lbs,
        "active": True,
    })
    db.boom_trucks[truck["id"]] = truck
    return success(truck, status=201)


@bp.route("/supply/boom-trucks/<tid>", methods=["GET"])
def get_truck(tid):
    require_roles("DispatcherUser", "Foreman", "WarehouseManager")
    return success(_get_truck_or_404(tid))


@bp.route("/supply/boom-trucks", methods=["GET"])
def list_trucks():
    require_roles("DispatcherUser", "Foreman", "WarehouseManager")
    limit, offset = parse_pagination()
    active_arg = request.args.get("active")
    items = list(db.boom_trucks.values())
    if active_arg is not None:
        want = active_arg.lower() in ("true", "1", "yes")
        items = [t for t in items if t["active"] == want]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/boom-trucks/<tid>", methods=["PATCH"])
def update_truck(tid):
    require_roles("DispatcherUser")
    t = _get_truck_or_404(tid)
    b = body()
    if "max_bundle_capacity" in b:
        t["max_bundle_capacity"] = require_int(b, "max_bundle_capacity", min_val=1)
    if "max_weight_lbs" in b:
        t["max_weight_lbs"] = require_int(b, "max_weight_lbs", min_val=1)
    if "active" in b:
        v = b["active"]
        if not isinstance(v, bool):
            raise ApiError(ERR_VALIDATION, "active must be a boolean", 400)
        t["active"] = v
    touch(t)
    return success(t)
