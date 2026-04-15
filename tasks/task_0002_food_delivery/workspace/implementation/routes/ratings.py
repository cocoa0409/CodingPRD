"""Rating routes."""

from flask import Blueprint, request as req
import db
from errors import raise_error, ERR_ORDER_NOT_FOUND, ERR_RATING_NOT_FOUND, \
    ERR_ORDER_NOT_DELIVERED, ERR_INVALID_RATING, ERR_DUPLICATE_RATING, ERR_INVALID_STATE
from middleware import require_roles
from response import success_response, list_response
from services.calculations import recalculate_rating

bp = Blueprint("ratings", __name__)


def _get_order_or_404(oid):
    o = db.orders.get(oid)
    if not o:
        raise_error(ERR_ORDER_NOT_FOUND, "The referenced order does not exist.")
    return o


def _paginate(request):
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    return limit, offset


@bp.route("/platform/orders/<order_id>/ratings", methods=["POST"])
def create_rating(order_id):
    require_roles("customer", "restaurant")
    order = _get_order_or_404(order_id)
    if order["status"] != "DELIVERED":
        raise_error(ERR_ORDER_NOT_DELIVERED, "Order must be DELIVERED to rate.")
    body = req.get_json(force=True, silent=True) or {}
    score = body.get("score")
    if not isinstance(score, int) or score < 1 or score > 5:
        raise_error(ERR_INVALID_RATING, "Rating score must be 1-5.")
    rater_type = body.get("rater_type")
    rater_id = body.get("rater_id")
    # Duplicate check
    for r in db.ratings.values():
        if r["order_id"] == order_id and r["rater_type"] == rater_type and r["rater_id"] == rater_id:
            raise_error(ERR_DUPLICATE_RATING, "Duplicate rating.")

    now = db.now_iso()
    rating = {
        "id": db.new_id(),
        "order_id": order_id,
        "rater_type": rater_type,
        "rater_id": rater_id,
        "ratee_id": body.get("ratee_id"),
        "score": score,
        "comment": body.get("comment"),
        "status": "PENDING",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.ratings[rating["id"]] = rating
    return success_response(rating, 201)


@bp.route("/platform/orders/<order_id>/ratings", methods=["GET"])
def list_ratings(order_id):
    require_roles("customer", "restaurant", "rider", "platform_admin")
    _get_order_or_404(order_id)
    limit, offset = _paginate(req)
    items = sorted(
        [r for r in db.ratings.values() if r["order_id"] == order_id],
        key=lambda x: x["created_at"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.route("/platform/orders/<order_id>/ratings/<rating_id>/publish", methods=["POST"])
def publish_rating(order_id, rating_id):
    require_roles("platform_admin")
    _get_order_or_404(order_id)
    r = db.ratings.get(rating_id)
    if not r or r["order_id"] != order_id:
        raise_error(ERR_RATING_NOT_FOUND, "Rating not found.")
    if r["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "Rating must be PENDING to publish.")
    r["status"] = "PUBLISHED"
    r["updated_at"] = db.now_iso()
    r["version"] += 1

    # Determine entity type from rater_type
    if r["rater_type"] == "CUSTOMER_TO_RESTAURANT":
        recalculate_rating("restaurant", r["ratee_id"])
    elif r["rater_type"] in ("CUSTOMER_TO_RIDER", "RESTAURANT_TO_RIDER"):
        recalculate_rating("rider", r["ratee_id"])

    return success_response(r)


@bp.route("/platform/orders/<order_id>/ratings/<rating_id>/hide", methods=["POST"])
def hide_rating(order_id, rating_id):
    require_roles("platform_admin")
    _get_order_or_404(order_id)
    r = db.ratings.get(rating_id)
    if not r or r["order_id"] != order_id:
        raise_error(ERR_RATING_NOT_FOUND, "Rating not found.")
    if r["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "Rating must be PUBLISHED to hide.")
    r["status"] = "HIDDEN"
    r["updated_at"] = db.now_iso()
    r["version"] += 1

    if r["rater_type"] == "CUSTOMER_TO_RESTAURANT":
        recalculate_rating("restaurant", r["ratee_id"])
    elif r["rater_type"] in ("CUSTOMER_TO_RIDER", "RESTAURANT_TO_RIDER"):
        recalculate_rating("rider", r["ratee_id"])

    return success_response(r)
