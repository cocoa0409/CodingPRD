"""ShippingProfile endpoints."""
from flask import Blueprint, request
from auth import get_auth, require_role, require_shop_owner
from db import store, stamp_common
from envelope import success
from errors import raise_err, ERR_VALIDATION, ERR_SHIPPING_PROFILE_NOT_FOUND, ERR_SHOP_NOT_FOUND
from helpers import get_json_body, require_field, opt_field, parse_pagination, paginate, sort_by_created
from serializers import shipping_profile_view
from services import find_shop

bp = Blueprint("shipping_profiles", __name__)


@bp.route("/seller/shipping-profiles", methods=["POST"])
def create():
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    body = get_json_body()
    shop_id = require_field(body, "shop_id", str)
    name = require_field(body, "name", str)
    base = require_field(body, "base_cost_cents", int)
    per = require_field(body, "per_item_cost_cents", int)

    # Ownership before existence (auth precedes existence per PRD 2.1)
    require_shop_owner(user_id, role, shop_id)
    if find_shop(shop_id) is None:
        raise_err(ERR_SHOP_NOT_FOUND, "shop not found")

    origin = opt_field(body, "origin_country", str, "US")
    thr = opt_field(body, "free_shipping_threshold_cents", int, 0)
    ptd = opt_field(body, "processing_time_days", int, 1)

    if base < 0 or per < 0 or thr < 0 or ptd < 0:
        raise_err(ERR_VALIDATION, "numeric field out of range")

    rec = {
        "shop_id": shop_id,
        "name": name,
        "origin_country": origin,
        "base_cost_cents": base,
        "per_item_cost_cents": per,
        "free_shipping_threshold_cents": thr,
        "processing_time_days": ptd,
    }
    stamp_common(rec)
    store.shipping_profiles[rec["id"]] = rec
    return success(shipping_profile_view(rec), status=201)


@bp.route("/seller/shipping-profiles/<sp_id>", methods=["GET"])
def fetch(sp_id):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    sp = store.shipping_profiles.get(sp_id)
    if sp is None:
        raise_err(ERR_SHIPPING_PROFILE_NOT_FOUND, "not found")
    require_shop_owner(user_id, role, sp["shop_id"])
    return success(shipping_profile_view(sp))


@bp.route("/seller/shipping-profiles", methods=["GET"])
def list_():
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    items = list(store.shipping_profiles.values())
    if shop_id is not None:
        items = [x for x in items if x["shop_id"] == shop_id]
    if role == "Seller":
        items = [x for x in items if x["shop_id"] == user_id]
    items = sort_by_created(items)
    page, pmeta = paginate(items, limit, offset)
    return success([shipping_profile_view(x) for x in page], response_type="array", pagination=pmeta)
