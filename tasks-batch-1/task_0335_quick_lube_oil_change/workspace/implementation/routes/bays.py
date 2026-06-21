"""Bay endpoints (PRD §2.9, §3.1, §3.11)."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (get_json_or_400, require_str, require_bool, parse_pagination,
                    paginate, sort_by_created, stamp_create, new_id, touch)
from errors import ApiError, ERR_INVALID_STATE, ERR_BAY_OCCUPIED
from response import success_object, success_array
from services import lookup
from services.workorder import _adjust_open_bay_count
from services.serialize import bay_out

bp = Blueprint("bays", __name__)

READ_ROLES = ("ShopManager", "ServiceAdvisor", "Technician")


@bp.route("/bays", methods=["POST"])
def create_bay():
    require_role("ShopManager")
    body = get_json_or_400()
    shop_id = require_str(body, "shop_id")
    label = require_str(body, "label")
    synthetic = require_bool(body, "synthetic_certified", default=False)
    lookup.get_shop(shop_id)
    bay = {
        "id": new_id(),
        "shop_id": shop_id,
        "label": label,
        "synthetic_certified": synthetic,
        "current_work_order_id": None,
        "status": "OPEN",
    }
    stamp_create(bay)
    db.bays[bay["id"]] = bay
    _adjust_open_bay_count(shop_id)  # creating a bay raises open_bay_count by one
    return success_object(bay_out(bay), 201)


@bp.route("/bays", methods=["GET"])
def list_bays():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.bays.values())
    shop_id = request.args.get("shop_id")
    if shop_id is not None:
        rows = [b for b in rows if b["shop_id"] == shop_id]
    status = request.args.get("status")
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([bay_out(b) for b in page], limit, offset, total)


@bp.route("/bays/<bay_id>", methods=["GET"])
def get_bay(bay_id):
    require_role(*READ_ROLES)
    bay = lookup.get_bay(bay_id)
    return success_object(bay_out(bay), 200)


@bp.route("/bays/<bay_id>/close", methods=["POST"])
def close_bay(bay_id):
    require_role("ShopManager")
    bay = lookup.get_bay(bay_id)
    if bay["status"] == "OCCUPIED":
        raise ApiError(ERR_BAY_OCCUPIED, 409, "cannot close an occupied bay")
    if bay["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "bay is not OPEN")
    bay["status"] = "CLOSED"
    touch(bay)
    _adjust_open_bay_count(bay["shop_id"])
    return success_object(bay_out(bay), 200)


@bp.route("/bays/<bay_id>/reopen", methods=["POST"])
def reopen_bay(bay_id):
    require_role("ShopManager")
    bay = lookup.get_bay(bay_id)
    if bay["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "bay is not CLOSED")
    bay["status"] = "OPEN"
    touch(bay)
    _adjust_open_bay_count(bay["shop_id"])
    return success_object(bay_out(bay), 200)
