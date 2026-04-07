"""Shop routes: thin controllers delegating to shop service."""

from flask import Blueprint, request, g
import middleware
import response
from services import shop as shop_service

bp = Blueprint("shops", __name__)


@bp.route("/shops", methods=["POST"])
def create_shop():
    middleware.require_auth()
    middleware.require_role("Seller")
    data = request.get_json()
    data["owner_id"] = g.user_id
    result = shop_service.create_shop(data)
    return response.success(result, 201)


@bp.route("/shops", methods=["GET"])
def list_shops():
    middleware.require_auth()
    limit, offset = response.parse_pagination(request.args)
    filters = {}
    status = request.args.get("status")
    if status:
        filters["status"] = status
    items, total = shop_service.list_shops(filters, limit, offset)
    return response.success_list(items, total, limit, offset)


@bp.route("/shops/<shop_id>", methods=["GET"])
def get_shop(shop_id):
    middleware.require_auth()
    result = shop_service.get_shop(shop_id)
    return response.success(result)


@bp.route("/shops/<shop_id>", methods=["PUT"])
def update_shop(shop_id):
    middleware.require_auth()
    middleware.require_role("Seller")
    shop = shop_service.get_shop(shop_id)
    middleware.require_shop_owner(shop)
    data = request.get_json()
    result = shop_service.update_shop(shop_id, data, g.user_id)
    return response.success(result)


@bp.route("/shops/<shop_id>/approve", methods=["POST"])
def approve_shop(shop_id):
    middleware.require_auth()
    middleware.require_role("PlatformAdmin")
    result = shop_service.approve_shop(shop_id)
    return response.success(result)


@bp.route("/shops/<shop_id>/suspend", methods=["POST"])
def suspend_shop(shop_id):
    middleware.require_auth()
    middleware.require_role("PlatformAdmin")
    result = shop_service.suspend_shop(shop_id)
    return response.success(result)


@bp.route("/shops/<shop_id>/reinstate", methods=["POST"])
def reinstate_shop(shop_id):
    middleware.require_auth()
    middleware.require_role("PlatformAdmin")
    result = shop_service.reinstate_shop(shop_id)
    return response.success(result)


@bp.route("/shops/<shop_id>/close", methods=["POST"])
def close_shop(shop_id):
    middleware.require_auth()
    middleware.require_role("PlatformAdmin")
    result = shop_service.close_shop(shop_id)
    return response.success(result)
