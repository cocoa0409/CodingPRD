"""Review endpoints."""
from flask import Blueprint, request
from auth import get_auth, require_role, require_shop_owner, require_buyer_owner
from db import store, stamp_common, touch
from envelope import success
from errors import (
    raise_err, ERR_VALIDATION, ERR_REVIEW_NOT_FOUND, ERR_ORDER_NOT_FOUND,
    ERR_INVALID_RATING, ERR_REVIEW_NOT_ALLOWED, ERR_DUPLICATE_REVIEW,
    ERR_INVALID_STATE,
)
from helpers import get_json_body, require_field, opt_field, parse_pagination, paginate, sort_by_created
from serializers import review_view
from services import recompute_shop_rating

bp = Blueprint("reviews", __name__)


@bp.route("/seller/reviews", methods=["POST"])
def create():
    user_id, role = get_auth()
    require_role(role, {"Buyer"})
    body = get_json_body()

    order_id = require_field(body, "order_id", str)
    order = store.orders.get(order_id)
    if order is None:
        raise_err(ERR_ORDER_NOT_FOUND, "order not found")

    # Structural validation (rating present + integer)
    if "rating" not in body or body["rating"] is None:
        raise_err(ERR_VALIDATION, "rating required")
    rating = body["rating"]

    # ERR_INVALID_RATING: not integer 1..5
    if not isinstance(rating, int) or isinstance(rating, bool) or rating < 1 or rating > 5:
        raise_err(ERR_INVALID_RATING, "rating must be integer 1..5")

    body_txt = opt_field(body, "body", str, None)

    # ERR_REVIEW_NOT_ALLOWED: order must be COMPLETED and belong to acting buyer
    if order["fulfillment_status"] != "COMPLETED" or order["buyer_id"] != user_id:
        raise_err(ERR_REVIEW_NOT_ALLOWED, "review not allowed")

    # ERR_DUPLICATE_REVIEW: at most one per order
    for r in store.reviews.values():
        if r["order_id"] == order_id:
            raise_err(ERR_DUPLICATE_REVIEW, "review already exists")

    rec = {
        "order_id": order_id,
        "listing_id": order["listing_id"],
        "shop_id": order["shop_id"],
        "buyer_id": user_id,
        "rating": rating,
        "body": body_txt,
        "seller_response": None,
        "status": "PUBLISHED",
    }
    stamp_common(rec)
    store.reviews[rec["id"]] = rec

    shop = store.shops.get(order["shop_id"])
    if shop is not None:
        recompute_shop_rating(shop)

    return success(review_view(rec), status=201)


@bp.route("/seller/reviews/<rid>", methods=["GET"])
def fetch(rid):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin", "Buyer"})
    r = store.reviews.get(rid)
    if r is None:
        raise_err(ERR_REVIEW_NOT_FOUND, "not found")
    return success(review_view(r))


@bp.route("/seller/reviews", methods=["GET"])
def list_():
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin", "Buyer"})
    limit, offset = parse_pagination()
    args = request.args
    order_id = args.get("order_id")
    listing_id = args.get("listing_id")
    shop_id = args.get("shop_id")
    status = args.get("status")

    items = list(store.reviews.values())
    if order_id is not None:
        items = [x for x in items if x["order_id"] == order_id]
    if listing_id is not None:
        items = [x for x in items if x["listing_id"] == listing_id]
    if shop_id is not None:
        items = [x for x in items if x["shop_id"] == shop_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if role == "Seller":
        items = [x for x in items if x["shop_id"] == user_id]
    elif role == "Buyer":
        items = [x for x in items if x["buyer_id"] == user_id]
    items = sort_by_created(items)
    page, pmeta = paginate(items, limit, offset)
    return success([review_view(x) for x in page], response_type="array", pagination=pmeta)


@bp.route("/seller/reviews/<rid>/respond", methods=["POST"])
def respond(rid):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    r = store.reviews.get(rid)
    if r is None:
        raise_err(ERR_REVIEW_NOT_FOUND, "not found")
    require_shop_owner(user_id, role, r["shop_id"])
    body = get_json_body()
    resp = require_field(body, "seller_response", str)
    r["seller_response"] = resp
    touch(r)
    return success(review_view(r))


@bp.route("/seller/reviews/<rid>/hide", methods=["POST"])
def hide(rid):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    r = store.reviews.get(rid)
    if r is None:
        raise_err(ERR_REVIEW_NOT_FOUND, "not found")
    require_shop_owner(user_id, role, r["shop_id"])
    if r["status"] != "PUBLISHED":
        raise_err(ERR_INVALID_STATE, "review not PUBLISHED")
    r["status"] = "HIDDEN"
    touch(r)
    shop = store.shops.get(r["shop_id"])
    if shop is not None:
        recompute_shop_rating(shop)
    return success(review_view(r))
