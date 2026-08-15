"""Product endpoints (scaffold §1.5)."""
from flask import Blueprint, request
import db
from middleware import get_auth, require_role
from response import success_object, success_list, parse_pagination
from util import get_json_body, req_string, req_int, req_array, req_enum, stamp_new, touch
from errors import (
    ApiError, ERR_PRODUCT_NOT_FOUND, ERR_DUPLICATE_SKU, ERR_INVALID_REQUEST,
    ERR_PRODUCT_DISCONTINUED, ERR_INVALID_QUANTITY,
)

bp = Blueprint("products", __name__)

CATEGORIES = {"BEVERAGE", "SNACK", "CANDY", "CHILLED", "FROZEN"}
LOCATION_TYPES = {"OFFICE", "SCHOOL", "HOSPITAL", "GYM"}
PERISHABILITY = {"AMBIENT", "CHILLED", "FROZEN"}


def view(p):
    return {k: v for k, v in p.items()}


@bp.post("/wholesale/products")
def create_product():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["WholesaleAdmin"])
    sku = req_string(body, "sku")
    name = req_string(body, "name")
    category = req_enum(body, "category", CATEGORIES)
    eligible = req_array(body, "eligible_location_types")
    for t in eligible:
        if not isinstance(t, str) or t not in LOCATION_TYPES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "eligible_location_types contains invalid location type")
    case_pack_qty = req_int(body, "case_pack_qty")
    if case_pack_qty <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "case_pack_qty must be > 0")
    base_price_cents = req_int(body, "base_price_cents")
    if base_price_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "base_price_cents must be >= 0")
    cost_cents = req_int(body, "cost_cents")
    if cost_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "cost_cents must be >= 0")
    shelf_life_days = req_int(body, "shelf_life_days")
    if shelf_life_days < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "shelf_life_days must be >= 0")
    perishability = body.get("perishability_class", "AMBIENT")
    if perishability is None:
        perishability = "AMBIENT"
    if not isinstance(perishability, str) or perishability not in PERISHABILITY:
        raise ApiError(ERR_INVALID_REQUEST, 400, "perishability_class must be AMBIENT | CHILLED | FROZEN")
    for p in db.products.values():
        if p["sku"] == sku:
            raise ApiError(ERR_DUPLICATE_SKU, 409, "Product sku already exists")
    p = stamp_new({
        "sku": sku,
        "name": name,
        "category": category,
        "eligible_location_types": eligible,
        "case_pack_qty": case_pack_qty,
        "base_price_cents": base_price_cents,
        "cost_cents": cost_cents,
        "shelf_life_days": shelf_life_days,
        "perishability_class": perishability,
        "status": "ACTIVE",
    })
    db.products[p["id"]] = p
    return success_object(view(p), 201)


@bp.get("/wholesale/products")
def list_products():
    get_auth()
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    category_f = request.args.get("category")
    items = list(db.products.values())
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    if category_f is not None:
        items = [p for p in items if p["category"] == category_f]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    return success_list([view(p) for p in items[offset:offset + limit]], limit, offset, total)


@bp.get("/wholesale/products/<productId>")
def get_product(productId):
    get_auth()
    p = db.products.get(productId)
    if p is None:
        raise ApiError(ERR_PRODUCT_NOT_FOUND, 404, "Product id does not exist")
    return success_object(view(p))


@bp.post("/wholesale/products/<productId>/discontinue")
def discontinue_product(productId):
    user_id, role = get_auth()
    require_role(role, ["WholesaleAdmin"])
    p = db.products.get(productId)
    if p is None:
        raise ApiError(ERR_PRODUCT_NOT_FOUND, 404, "Product id does not exist")
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCT_DISCONTINUED, 409, "Product must be ACTIVE to discontinue")
    p["status"] = "DISCONTINUED"
    touch(p)
    return success_object(view(p))
