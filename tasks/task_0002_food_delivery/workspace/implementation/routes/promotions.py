"""Promotion routes."""

from flask import Blueprint, request as req
import db
from errors import raise_error, ERR_PROMOTION_NOT_FOUND, ERR_DUPLICATE_PROMOTION_CODE, \
    ERR_INVALID_STATE
from middleware import require_roles
from response import success_response, list_response

bp = Blueprint("promotions", __name__)


def _get_promotion_or_404(pid):
    p = db.promotions.get(pid)
    if not p:
        raise_error(ERR_PROMOTION_NOT_FOUND, "Promotion does not exist.")
    return p


def _paginate(request):
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    return limit, offset


@bp.route("/platform/promotions", methods=["POST"])
def create_promotion():
    require_roles("platform_admin")
    body = req.get_json(force=True, silent=True) or {}
    code = body.get("code")
    for p in db.promotions.values():
        if p["code"] == code:
            raise_error(ERR_DUPLICATE_PROMOTION_CODE, "Promotion code already exists.")
    now = db.now_iso()
    promo = {
        "id": db.new_id(),
        "code": code,
        "discount_type": body.get("discount_type"),
        "discount_value": body.get("discount_value"),
        "minimum_order_cents": body.get("minimum_order_cents"),
        "max_discount_cents": body.get("max_discount_cents"),
        "max_uses": body.get("max_uses"),
        "current_uses": 0,
        "max_uses_per_customer": body.get("max_uses_per_customer", 1),
        "valid_from": body.get("valid_from"),
        "valid_until": body.get("valid_until"),
        "restaurant_id": body.get("restaurant_id"),
        "status": "ACTIVE",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.promotions[promo["id"]] = promo
    return success_response(promo, 201)


@bp.route("/platform/promotions", methods=["GET"])
def list_promotions():
    require_roles("platform_admin")
    limit, offset = _paginate(req)
    items = sorted(db.promotions.values(), key=lambda x: x["created_at"])
    status_f = req.args.get("status")
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.route("/platform/promotions/<promotion_id>", methods=["GET"])
def get_promotion(promotion_id):
    require_roles("platform_admin", "customer")
    p = _get_promotion_or_404(promotion_id)
    return success_response(p)


@bp.route("/platform/promotions/<promotion_id>/disable", methods=["POST"])
def disable_promotion(promotion_id):
    require_roles("platform_admin")
    p = _get_promotion_or_404(promotion_id)
    if p["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Promotion must be ACTIVE to disable.")
    p["status"] = "DISABLED"
    p["updated_at"] = db.now_iso()
    p["version"] += 1
    return success_response(p)
