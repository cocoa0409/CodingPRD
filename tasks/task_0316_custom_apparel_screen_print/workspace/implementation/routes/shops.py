"""Shop endpoints (PRD §3.1, §2.7)."""
from flask import Blueprint

from db import store, new_common_fields
from clock import EPOCH_ISO
from errors import err
from middleware import endpoint
from response import success
from serialize import view
from validation import get_body, require_str, require_number, require_int
from services.lookups import get_shop

bp = Blueprint("shops", __name__)


@bp.route("/shops", methods=["POST"])
@endpoint("ShopManager")
def create_shop():
    body = get_body()
    name = require_str(body, "name")
    spoilage_pct = require_number(body, "spoilage_pct", default=0.05)
    rush_threshold_days = require_int(body, "rush_threshold_days", default=7)
    rush_surcharge_pct = require_number(body, "rush_surcharge_pct", default=0.25)
    if spoilage_pct < 0 or rush_surcharge_pct < 0 or rush_threshold_days < 0:
        raise err("ERR_INVALID_REQUEST", "Shop knobs must be non-negative")

    shop = new_common_fields()
    shop.update({
        "name": name,
        "current_utc": EPOCH_ISO,
        "spoilage_pct": spoilage_pct,
        "rush_threshold_days": rush_threshold_days,
        "rush_surcharge_pct": rush_surcharge_pct,
    })
    store.shops[shop["id"]] = shop
    return success(view(shop), status=201)


@bp.route("/shops/<shop_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def get_shop_route(shop_id):
    shop = get_shop(shop_id)
    return success(view(shop), status=200)
