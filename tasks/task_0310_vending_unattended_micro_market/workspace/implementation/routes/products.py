"""Product endpoints (PRD 3.1)."""
from flask import Blueprint

from common import (get_json_body, get_or_404, list_response, require_enum,
                    require_int, require_str)
from db import db, stamp_create, touch
from errors import ApiError
from middleware import require_roles
from response import object_response
from services import serialize

bp = Blueprint("products", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")


@bp.route("/operations/products", methods=["POST"])
@require_roles("FieldOps")
def create_product():
    body = get_json_body()
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    category = require_enum(body, "category", {"BEVERAGE", "SNACK", "FRESH_FOOD"})
    unit_cost = require_int(body, "unit_cost_cents")
    if unit_cost <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_cost_cents must be > 0")
    shelf_life = require_int(body, "shelf_life_days", allow_missing=True, default=0)
    if shelf_life < 0:
        raise ApiError("ERR_INVALID_REQUEST", "shelf_life_days must be >= 0")

    # sku unique across all products
    for p in db.products.values():
        if p["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU", "Product sku already exists")

    obj = {
        "sku": sku,
        "name": name,
        "category": category,
        "unit_cost_cents": unit_cost,
        "shelf_life_days": shelf_life,
        "status": "ACTIVE",
    }
    stamp_create(obj)
    db.products[obj["id"]] = obj
    return object_response(serialize.product(obj), 201)


@bp.route("/operations/products", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_products():
    return list_response(list(db.products.values()), serialize.product)


@bp.route("/operations/products/<product_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_product(product_id):
    obj = get_or_404("products", product_id)
    return object_response(serialize.product(obj))


@bp.route("/operations/products/<product_id>/cost", methods=["PATCH"])
@require_roles("FieldOps")
def update_cost(product_id):
    obj = get_or_404("products", product_id)
    body = get_json_body()
    unit_cost = require_int(body, "unit_cost_cents")
    if unit_cost <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_cost_cents must be > 0")
    obj["unit_cost_cents"] = unit_cost
    touch(obj)
    return object_response(serialize.product(obj))


@bp.route("/operations/products/<product_id>/discontinue", methods=["POST"])
@require_roles("FieldOps")
def discontinue(product_id):
    obj = get_or_404("products", product_id)
    obj["status"] = "DISCONTINUED"
    touch(obj)
    return object_response(serialize.product(obj))
