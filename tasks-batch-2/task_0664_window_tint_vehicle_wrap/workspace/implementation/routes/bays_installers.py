"""Bays and installers."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from models import stamp_create, serialize
from response import success, success_list
from services import common

bp = Blueprint("bays_installers", __name__)

SERVICE_TYPES = {"TINT", "PPF", "WRAP", "CERAMIC"}


# ---- Bay --------------------------------------------------------------------
@bp.route("/bays", methods=["POST"])
def create_bay():
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    shop_location_id = common.require_string(body, "shop_location_id")
    label = common.require_string(body, "label")
    common.get_or_404(db.shop_locations, shop_location_id)

    rec = {
        "shop_location_id": shop_location_id,
        "label": label,
        "reserved_minutes": 0,
        "status": "OPEN",
    }
    stamp_create(rec)
    db.bays[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/bays/<rid>", methods=["GET"])
def get_bay(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "Installer"})
    rec = common.get_or_404(db.bays, rid)
    return success(serialize(rec), 200)


@bp.route("/bays", methods=["GET"])
def list_bays():
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "Installer"})
    limit, offset = parse_pagination()
    shop_filter = request.args.get("shop_location_id")
    items = list(db.bays.values())
    if shop_filter is not None:
        items = [b for b in items if b["shop_location_id"] == shop_filter]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(b) for b in page], limit, offset, total, 200)


# ---- Installer --------------------------------------------------------------
@bp.route("/installers", methods=["POST"])
def create_installer():
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    shop_location_id = common.require_string(body, "shop_location_id")
    installer_user_id = common.require_string(body, "installer_user_id")
    full_name = common.require_string(body, "full_name")
    certified_service_types = common.require_field(body, "certified_service_types")
    if not isinstance(certified_service_types, list) or any(
        st not in SERVICE_TYPES for st in certified_service_types
    ):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "certified_service_types must be a subset of {TINT, PPF, WRAP, CERAMIC}.")
    common.get_or_404(db.shop_locations, shop_location_id)

    rec = {
        "shop_location_id": shop_location_id,
        "installer_user_id": installer_user_id,
        "full_name": full_name,
        "certified_service_types": list(certified_service_types),
        "status": "AVAILABLE",
    }
    stamp_create(rec)
    db.installers[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/installers/<rid>", methods=["GET"])
def get_installer(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "Installer"})
    rec = common.get_or_404(db.installers, rid)
    return success(serialize(rec), 200)


@bp.route("/installers", methods=["GET"])
def list_installers():
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    limit, offset = parse_pagination()
    shop_filter = request.args.get("shop_location_id")
    items = list(db.installers.values())
    if shop_filter is not None:
        items = [i for i in items if i["shop_location_id"] == shop_filter]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(i) for i in page], limit, offset, total, 200)
