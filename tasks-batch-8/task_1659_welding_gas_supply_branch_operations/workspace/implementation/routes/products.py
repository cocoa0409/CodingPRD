"""Product catalog and branch inventory."""
from flask import Blueprint

import db
from db import store, new_common, new_id, touch, is_int
from errors import ApiError
from middleware import require_roles, body
from response import ok, created

bp = Blueprint("products", __name__)

_ALL = ("CounterRep", "BranchManager", "RouteDriver", "Trainer", "ServiceTech")
_CATEGORIES = ("HARDGOOD", "GAS", "SPECIALTY_GAS")


def product_view(product):
    product["needs_reorder"] = product["stock_on_hand"] <= product["reorder_point"]
    return product


def get_product(pid):
    product = store.products.get(pid)
    if product is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Product not found")
    return product


@bp.route("/products", methods=["POST"])
@require_roles("BranchManager")
def create_product():
    b = body()
    # Priority 4: shape.
    sku = b.get("sku")
    name = b.get("name")
    category = b.get("category")
    gas_grade = b.get("gas_grade")
    price = b.get("retail_price_cents")
    hazmat = b.get("hazmat", False)
    reorder_point = b.get("reorder_point", 0)
    lead_time = b.get("lead_time_days", 0)
    if not isinstance(sku, str) or not sku:
        raise ApiError("ERR_VALIDATION", 400, "sku is required")
    if not isinstance(name, str) or not name:
        raise ApiError("ERR_VALIDATION", 400, "name is required")
    if category not in _CATEGORIES:
        raise ApiError("ERR_VALIDATION", 400,
                       "category must be HARDGOOD, GAS or SPECIALTY_GAS")
    if category in ("GAS", "SPECIALTY_GAS"):
        if gas_grade not in db.GAS_GRADES:
            raise ApiError("ERR_VALIDATION", 400,
                           "gas_grade is required for gas products")
    elif gas_grade is not None:
        raise ApiError("ERR_VALIDATION", 400, "gas_grade must be null for HARDGOOD")
    if not is_int(price) or price < 0:
        raise ApiError("ERR_VALIDATION", 400, "retail_price_cents must be an integer >= 0")
    if not isinstance(hazmat, bool):
        raise ApiError("ERR_VALIDATION", 400, "hazmat must be a boolean")
    if not is_int(reorder_point) or reorder_point < 0:
        raise ApiError("ERR_VALIDATION", 400, "reorder_point must be an integer >= 0")
    if not is_int(lead_time) or lead_time < 0:
        raise ApiError("ERR_VALIDATION", 400, "lead_time_days must be an integer >= 0")
    # Priority 10: sku uniqueness.
    if any(p["sku"] == sku for p in store.products.values()):
        raise ApiError("ERR_DUPLICATE_SKU", 409, "sku already exists")
    product = {
        "id": new_id(),
        "sku": sku,
        "name": name,
        "category": category,
        "gas_grade": gas_grade,
        "retail_price_cents": price,
        "hazmat": hazmat,
        "stock_on_hand": 0,
        "reorder_point": reorder_point,
        "lead_time_days": lead_time,
    }
    new_common(product)
    store.products[product["id"]] = product
    return created(product_view(product))


@bp.route("/products/<pid>", methods=["GET"])
@require_roles(*_ALL)
def get_one_product(pid):
    return ok(product_view(get_product(pid)))


@bp.route("/products/<pid>/receive", methods=["POST"])
@require_roles("BranchManager")
def receive_stock(pid):
    product = get_product(pid)
    b = body()
    qty = b.get("qty")
    if not is_int(qty) or qty <= 0:
        raise ApiError("ERR_VALIDATION", 400, "qty must be a positive integer")
    product["stock_on_hand"] += qty
    touch(product)
    return ok(product_view(product))
