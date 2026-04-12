"""Product routes: thin controllers delegating to product service."""

from flask import Blueprint, request, g
import middleware
import response
from services import shop as shop_service
from services import product as product_service

bp = Blueprint("products", __name__)


@bp.route("/shops/<shop_id>/products", methods=["POST"])
def create_product(shop_id):
    middleware.require_auth()
    middleware.require_role("Seller")
    shop = shop_service.get_shop(shop_id)
    middleware.require_shop_owner(shop)
    data = request.get_json()
    result = product_service.create_product(shop_id, data)
    return response.success(result, 201)


@bp.route("/shops/<shop_id>/products", methods=["GET"])
def list_products(shop_id):
    middleware.require_auth()
    limit, offset = response.parse_pagination(request.args)
    filters = {}
    status = request.args.get("status")
    if status:
        filters["status"] = status
    items, total = product_service.list_products(shop_id, filters, limit, offset)
    return response.success_list(items, total, limit, offset)


@bp.route("/shops/<shop_id>/products/<product_id>", methods=["GET"])
def get_product(shop_id, product_id):
    middleware.require_auth()
    result = product_service.get_product(shop_id, product_id)
    return response.success(result)


@bp.route("/shops/<shop_id>/products/<product_id>", methods=["PUT"])
def update_product(shop_id, product_id):
    middleware.require_auth()
    middleware.require_role("Seller")
    shop = shop_service.get_shop(shop_id)
    middleware.require_shop_owner(shop)
    data = request.get_json()
    result = product_service.update_product(shop_id, product_id, data)
    return response.success(result)


@bp.route("/shops/<shop_id>/products/<product_id>/list", methods=["POST"])
def list_product(shop_id, product_id):
    middleware.require_auth()
    middleware.require_role("Seller")
    shop = shop_service.get_shop(shop_id)
    middleware.require_shop_owner(shop)
    result = product_service.list_product(shop_id, product_id)
    return response.success(result)


@bp.route("/shops/<shop_id>/products/<product_id>/delist", methods=["POST"])
def delist_product(shop_id, product_id):
    middleware.require_auth()
    middleware.require_role("Seller")
    shop = shop_service.get_shop(shop_id)
    middleware.require_shop_owner(shop)
    result = product_service.delist_product(shop_id, product_id)
    return response.success(result)


@bp.route("/shops/<shop_id>/products/<product_id>/archive", methods=["POST"])
def archive_product(shop_id, product_id):
    middleware.require_auth()
    middleware.require_role("Seller")
    shop = shop_service.get_shop(shop_id)
    middleware.require_shop_owner(shop)
    result = product_service.archive_product(shop_id, product_id)
    return response.success(result)
