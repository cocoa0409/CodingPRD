"""Shop endpoints (PRD §3.1)."""
from flask import Blueprint

import db
from auth import require_role
from common import (get_json_or_400, require_str, require_number, require_int,
                    optional_number, parse_pagination, paginate, sort_by_created,
                    stamp_create, new_id)
from response import success_object, success_array
from services import lookup
from services.serialize import shop_out

bp = Blueprint("shops", __name__)

ALL_ROLES = ("ShopManager", "ServiceAdvisor", "Technician", "FleetManager")


@bp.route("/shops", methods=["POST"])
def create_shop():
    require_role("ShopManager")
    body = get_json_or_400()
    name = require_str(body, "name")
    tax_rate = require_number(body, "tax_rate", minimum=0, maximum=1,
                              min_inclusive=True, max_inclusive=False)
    target = require_int(body, "target_throughput_seconds", minimum=1)
    max_disc = optional_number(body, "max_discount_pct", 0.50, minimum=0, maximum=1,
                               min_inclusive=False, max_inclusive=True)
    shop = {
        "id": new_id(),
        "name": name,
        "tax_rate": tax_rate,
        "target_throughput_seconds": target,
        "max_discount_pct": max_disc,
        "open_bay_count": 0,
        "status": "OPEN",
    }
    stamp_create(shop)
    db.shops[shop["id"]] = shop
    return success_object(shop_out(shop), 201)


@bp.route("/shops", methods=["GET"])
def list_shops():
    require_role(*ALL_ROLES)
    limit, offset = parse_pagination()
    rows = sort_by_created(list(db.shops.values()))
    page, total = paginate(rows, limit, offset)
    return success_array([shop_out(s) for s in page], limit, offset, total)


@bp.route("/shops/<shop_id>", methods=["GET"])
def get_shop(shop_id):
    require_role(*ALL_ROLES)
    shop = lookup.get_shop(shop_id)
    return success_object(shop_out(shop), 200)
