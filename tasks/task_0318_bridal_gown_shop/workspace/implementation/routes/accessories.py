"""AccessoryAddOn endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
import common
import errors
import services
from middleware import require_roles
from response import success

ALL_ROLES = ("ShopManager", "BridalConsultant", "Seamstress", "FinanceClerk")
ACCESSORY_TYPES = {"VEIL", "TIARA", "SASH", "SHOES"}

bp = Blueprint("accessories", __name__)


@bp.route("/accessory-addons", methods=["POST"])
@require_roles("BridalConsultant", "ShopManager")
def create_accessory():
    body = common.get_body()
    gown_order_id = common.as_str(body, "gown_order_id")
    services.get_order(gown_order_id)  # FK existence (ERR_ORDER_NOT_FOUND)
    accessory_type = common.as_enum(body, "accessory_type", ACCESSORY_TYPES)
    price_cents = common.as_int(body, "price_cents", minimum=0)
    obj = {
        "id": db.new_id(),
        "gown_order_id": gown_order_id,
        "accessory_type": accessory_type,
        "price_cents": price_cents,
        "status": "ACTIVE",
    }
    db.stamp_create(obj)
    db.accessory_addons[obj["id"]] = obj
    return success(common.serialize(obj), status=201)


@bp.route("/accessory-addons", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_accessories():
    limit, offset = common.paginate(request.args)
    rows = list(db.accessory_addons.values())
    gown_order_id = request.args.get("gown_order_id")
    if gown_order_id is not None:
        rows = [a for a in rows if a["gown_order_id"] == gown_order_id]
    window, meta = common.page_slice(rows, limit, offset)
    return success([common.serialize(o) for o in window], pagination=meta)


@bp.route("/accessory-addons/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_accessory(aid):
    obj = services.get_accessory(aid)
    return success(common.serialize(obj))


@bp.route("/accessory-addons/<aid>/remove", methods=["POST"])
@require_roles("BridalConsultant", "ShopManager")
def remove_accessory(aid):
    obj = services.get_accessory(aid)
    obj["status"] = "REMOVED"
    db.touch(obj)
    return success(common.serialize(obj))
