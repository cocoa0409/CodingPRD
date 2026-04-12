"""Promotion routes: thin controllers delegating to promotion service."""

from flask import Blueprint, request, g
import middleware
import response
from services import shop as shop_service
from services import promotion as promotion_service

bp = Blueprint("promotions", __name__)


@bp.route("/shops/<shop_id>/promotions", methods=["POST"])
def create_promotion(shop_id):
    middleware.require_auth()
    middleware.require_role("Seller")
    shop = shop_service.get_shop(shop_id)
    middleware.require_shop_owner(shop)
    data = request.get_json()
    result = promotion_service.create_promotion(shop_id, data)
    return response.success(result, 201)


@bp.route("/shops/<shop_id>/promotions", methods=["GET"])
def list_promotions(shop_id):
    middleware.require_auth()
    limit, offset = response.parse_pagination(request.args)
    filters = {}
    status = request.args.get("status")
    if status:
        filters["status"] = status
    items, total = promotion_service.list_promotions(shop_id, filters, limit, offset)
    return response.success_list(items, total, limit, offset)


@bp.route("/shops/<shop_id>/promotions/<promotion_id>", methods=["GET"])
def get_promotion(shop_id, promotion_id):
    middleware.require_auth()
    result = promotion_service.get_promotion(shop_id, promotion_id)
    return response.success(result)


@bp.route("/shops/<shop_id>/promotions/<promotion_id>/activate", methods=["POST"])
def activate_promotion(shop_id, promotion_id):
    middleware.require_auth()
    middleware.require_role("Seller")
    shop = shop_service.get_shop(shop_id)
    middleware.require_shop_owner(shop)
    result = promotion_service.activate_promotion(shop_id, promotion_id)
    return response.success(result)


@bp.route("/shops/<shop_id>/promotions/<promotion_id>/pause", methods=["POST"])
def pause_promotion(shop_id, promotion_id):
    middleware.require_auth()
    middleware.require_role("Seller")
    shop = shop_service.get_shop(shop_id)
    middleware.require_shop_owner(shop)
    result = promotion_service.pause_promotion(shop_id, promotion_id)
    return response.success(result)


@bp.route("/shops/<shop_id>/promotions/<promotion_id>/cancel", methods=["POST"])
def cancel_promotion(shop_id, promotion_id):
    middleware.require_auth()
    middleware.require_role("Seller")
    shop = shop_service.get_shop(shop_id)
    middleware.require_shop_owner(shop)
    result = promotion_service.cancel_promotion(shop_id, promotion_id)
    return response.success(result)
