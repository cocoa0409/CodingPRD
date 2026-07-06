"""Shop endpoints."""
from flask import Blueprint, request
from auth import get_auth, require_role, require_shop_owner
from db import store, stamp_common, touch
from envelope import success
from errors import raise_err, ERR_VALIDATION, ERR_SHOP_NOT_FOUND, ERR_INVALID_STATE
from helpers import get_json_body, require_field, opt_field, parse_pagination, paginate, sort_by_created
from serializers import shop_view
from services import cascade_shop_suspended, find_shop

bp = Blueprint("shops", __name__)

VALID_CURRENCIES = {"USD", "EUR", "GBP"}


def _require_shop(shop_id):
    s = find_shop(shop_id)
    if s is None:
        raise_err(ERR_SHOP_NOT_FOUND, f"shop {shop_id} not found")
    return s


@bp.route("/seller/shops", methods=["POST"])
def create_shop():
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    owner_seller_id = require_field(body, "owner_seller_id", str)
    name = require_field(body, "name", str)
    if not name or len(name) > 120:
        raise_err(ERR_VALIDATION, "name must be non-empty and <=120 chars")
    currency = opt_field(body, "currency", str, "USD")
    if currency not in VALID_CURRENCIES:
        raise_err(ERR_VALIDATION, "invalid currency")
    max_conc = opt_field(body, "max_concurrent_production", int, 3)
    if max_conc < 1:
        raise_err(ERR_VALIDATION, "max_concurrent_production must be >= 1")
    announcement = opt_field(body, "announcement", str, None)
    vac_reply = opt_field(body, "vacation_auto_reply", str, None)

    rec = {
        "owner_seller_id": owner_seller_id,
        "name": name,
        "currency": currency,
        "status": "ACTIVE",
        "max_concurrent_production": max_conc,
        "announcement": announcement,
        "vacation_auto_reply": vac_reply,
        "published_review_count": 0,
        "simple_avg_rating": None,
        "weighted_shop_rating": None,
        "available_balance_cents": 0,
        "pending_balance_cents": 0,
        "lifetime_gross_cents": 0,
        "lifetime_fees_cents": 0,
    }
    stamp_common(rec)
    store.shops[rec["id"]] = rec
    return success(shop_view(rec), status=201)


@bp.route("/seller/shops/<shop_id>", methods=["GET"])
def get_shop(shop_id):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    s = _require_shop(shop_id)
    require_shop_owner(user_id, role, shop_id)
    return success(shop_view(s))


@bp.route("/seller/shops", methods=["GET"])
def list_shops():
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    owner = request.args.get("owner_seller_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = list(store.shops.values())
    if owner is not None:
        items = [s for s in items if s["owner_seller_id"] == owner]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, pmeta = paginate(items, limit, offset)
    return success([shop_view(s) for s in page], response_type="array", pagination=pmeta)


@bp.route("/seller/shops/<shop_id>/enable-vacation", methods=["POST"])
def enable_vacation(shop_id):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    s = _require_shop(shop_id)
    require_shop_owner(user_id, role, shop_id)
    body = get_json_body()
    vac_reply = opt_field(body, "vacation_auto_reply", str, None)
    if s["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "shop not ACTIVE")
    s["status"] = "VACATION"
    if vac_reply is not None:
        s["vacation_auto_reply"] = vac_reply
    touch(s)
    return success(shop_view(s))


@bp.route("/seller/shops/<shop_id>/return-from-vacation", methods=["POST"])
def return_from_vacation(shop_id):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    s = _require_shop(shop_id)
    require_shop_owner(user_id, role, shop_id)
    if s["status"] != "VACATION":
        raise_err(ERR_INVALID_STATE, "shop not VACATION")
    s["status"] = "ACTIVE"
    touch(s)
    return success(shop_view(s))


@bp.route("/seller/shops/<shop_id>/suspend", methods=["POST"])
def suspend_shop(shop_id):
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    s = _require_shop(shop_id)
    body = get_json_body()
    close = opt_field(body, "close", bool, False)
    if close:
        # close permitted from {ACTIVE, VACATION, SUSPENDED}
        if s["status"] not in ("ACTIVE", "VACATION", "SUSPENDED"):
            raise_err(ERR_INVALID_STATE, "cannot close from this state")
        # If coming from ACTIVE/VACATION, we still cascade listings (parity w/ suspend).
        if s["status"] in ("ACTIVE", "VACATION"):
            cascade_shop_suspended(s)
        s["status"] = "CLOSED"
        touch(s)
    else:
        if s["status"] not in ("ACTIVE", "VACATION"):
            raise_err(ERR_INVALID_STATE, "cannot suspend from this state")
        cascade_shop_suspended(s)
        s["status"] = "SUSPENDED"
        touch(s)
    return success(shop_view(s))


@bp.route("/seller/shops/<shop_id>/reinstate", methods=["POST"])
def reinstate_shop(shop_id):
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    s = _require_shop(shop_id)
    if s["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "shop not SUSPENDED")
    s["status"] = "ACTIVE"
    touch(s)
    return success(shop_view(s))
