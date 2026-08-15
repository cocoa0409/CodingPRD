"""Product master data (PRD §3.1) and its reverse lookups."""
from flask import Blueprint, request

from db import new_id, stamp_new, store
from errors import ApiError
from middleware import ALL_ROLES, auth, body, is_int, is_num, paginate, require_fields
from response import success_list, success_object
from serializers import gift_component_json, product_json, recipe_json

products_bp = Blueprint("products", __name__)

PRODUCT_TYPES = ("STANDARD", "SEASONAL", "GIFT_SET")
BRANDS = ("OWN", "PRIVATE_LABEL")


def get_product_or_404(pid):
    p = store.products.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Product not found: %s" % pid)
    return p


@products_bp.route("/products", methods=["POST"])
def create_product():
    auth(("ProductionPlanner",))
    b = body()
    # Existence: body FK references must resolve (ERR_NOT_FOUND).
    pc_id = b.get("packaging_component_id")
    if pc_id is not None and pc_id not in store.packaging_components:
        raise ApiError("ERR_NOT_FOUND", "packaging_component_id references a non-existent resource.")
    # Request shape (ERR_INVALID_REQUEST).
    require_fields(b, ["sku_code", "name", "product_type", "brand", "base_price_cents",
                       "unit_weight_grams", "shelf_life_days", "packaging_component_id"])
    if not isinstance(b["sku_code"], str) or not b["sku_code"]:
        raise ApiError("ERR_INVALID_REQUEST", "sku_code is required and must be a non-empty string.")
    if not isinstance(b["name"], str) or not b["name"]:
        raise ApiError("ERR_INVALID_REQUEST", "name is required and must be a non-empty string.")
    if b["product_type"] not in PRODUCT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "product_type must be one of STANDARD, SEASONAL, GIFT_SET.")
    if b["brand"] not in BRANDS:
        raise ApiError("ERR_INVALID_REQUEST", "brand must be one of OWN, PRIVATE_LABEL.")
    customer_name = b.get("customer_name")
    if b["brand"] == "PRIVATE_LABEL":
        if not isinstance(customer_name, str) or not customer_name:
            raise ApiError("ERR_INVALID_REQUEST",
                           "customer_name is required when brand is PRIVATE_LABEL.")
    if not is_int(b["base_price_cents"]) or b["base_price_cents"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "base_price_cents must be an integer > 0.")
    if not is_num(b["unit_weight_grams"]) or b["unit_weight_grams"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_weight_grams must be a number > 0.")
    if not is_int(b["shelf_life_days"]) or b["shelf_life_days"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "shelf_life_days must be an integer > 0.")
    for p in store.products.values():
        if p["sku_code"] == b["sku_code"]:
            raise ApiError("ERR_INVALID_REQUEST", "sku_code must be unique across all products.")
    p = {
        "id": new_id(),
        "sku_code": b["sku_code"],
        "name": b["name"],
        "product_type": b["product_type"],
        "brand": b["brand"],
        # customer_name is required for PRIVATE_LABEL and ignored otherwise.
        "customer_name": customer_name if b["brand"] == "PRIVATE_LABEL" else None,
        "base_price_cents": b["base_price_cents"],
        "unit_weight_grams": b["unit_weight_grams"],
        "shelf_life_days": b["shelf_life_days"],
        "packaging_component_id": b["packaging_component_id"],
    }
    stamp_new(p)
    store.products[p["id"]] = p
    return success_object(product_json(p), 201)


@products_bp.route("/products", methods=["GET"])
def list_products():
    auth(ALL_ROLES)
    items = list(store.products.values())
    f = request.args.get("product_type")
    if f is not None:
        items = [p for p in items if p["product_type"] == f]
    f = request.args.get("brand")
    if f is not None:
        items = [p for p in items if p["brand"] == f]
    f = request.args.get("packaging_component_id")
    if f is not None:
        items = [p for p in items if p["packaging_component_id"] == f]
    items.sort(key=lambda p: p["created_at"])
    page, meta = paginate(items)
    return success_list([product_json(p) for p in page], meta)


@products_bp.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    auth(ALL_ROLES)
    return success_object(product_json(get_product_or_404(pid)))


@products_bp.route("/products/<pid>/recipes", methods=["GET"])
def list_product_recipes(pid):
    auth(ALL_ROLES)
    get_product_or_404(pid)
    items = [r for r in store.recipes.values() if r["product_id"] == pid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items)
    return success_list([recipe_json(r) for r in page], meta)


@products_bp.route("/products/<pid>/gift-components", methods=["GET"])
def list_product_gift_components(pid):
    auth(ALL_ROLES)
    get_product_or_404(pid)
    # Rows where the product participates, as gift set or as component.
    items = [g for g in store.gift_components.values()
             if g["gift_product_id"] == pid or g["component_product_id"] == pid]
    items.sort(key=lambda g: g["created_at"])
    page, meta = paginate(items)
    return success_list([gift_component_json(g) for g in page], meta)
