"""InspectionItem endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (get_json_or_400, require_str, require_int, require_enum,
                    parse_pagination, paginate, sort_by_created, stamp_create, new_id)
from response import success_object, success_array
from services import lookup
from services.serialize import inspection_item_out

bp = Blueprint("inspection_items", __name__)

ALL_ROLES = ("ShopManager", "ServiceAdvisor", "Technician", "FleetManager")
ITEM_CODES = {"AIR_FILTER", "CABIN_FILTER", "WIPER_BLADES", "COOLANT_FLUSH",
              "TRANSMISSION_FLUSH"}


@bp.route("/inspection-items", methods=["POST"])
def create_item():
    require_role("ShopManager")
    body = get_json_or_400()
    shop_id = require_str(body, "shop_id")
    code = require_enum(body, "code", ITEM_CODES)
    name = require_str(body, "name")
    price = require_int(body, "price_cents", minimum=0)
    labor = require_int(body, "labor_minutes", minimum=0)
    lookup.get_shop(shop_id)
    item = {
        "id": new_id(),
        "shop_id": shop_id,
        "code": code,
        "name": name,
        "price_cents": price,
        "labor_minutes": labor,
        "active": True,
    }
    stamp_create(item)
    db.inspection_items[item["id"]] = item
    return success_object(inspection_item_out(item), 201)


@bp.route("/inspection-items", methods=["GET"])
def list_items():
    require_role(*ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.inspection_items.values())
    shop_id = request.args.get("shop_id")
    if shop_id is not None:
        rows = [i for i in rows if i["shop_id"] == shop_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([inspection_item_out(i) for i in page], limit, offset, total)


@bp.route("/inspection-items/<item_id>", methods=["GET"])
def get_item(item_id):
    require_role(*ALL_ROLES)
    item = lookup.get_inspection_item(item_id)
    return success_object(inspection_item_out(item), 200)
