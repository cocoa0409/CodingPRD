"""Product endpoints."""

from flask import Blueprint

from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int, opt_number,
    opt_bool, base_fields, err, apply_changes,
)
from response import success_object
from errors import (
    ERR_INVALID_REQUEST, ERR_PRODUCT_NOT_FOUND, ERR_PRODUCT_DISCONTINUED,
)
from serializers import serialize_product

bp = Blueprint("products", __name__)


@bp.post("/dairy/products")
def create_product():
    require_role("TerritoryManager")
    body = get_json_body()
    check_unknown_fields(body, {
        "sku", "name", "units_per_case", "shelf_life_days", "regulated",
        "weight_lbs_per_unit", "list_price_cents", "margin_cents_per_unit",
    })
    require_fields(body, ["sku", "name", "units_per_case", "shelf_life_days", "regulated"])
    sku = body["sku"]
    if not isinstance(sku, str):
        raise err(ERR_INVALID_REQUEST, "sku must be a string")
    name = body["name"]
    if not isinstance(name, str):
        raise err(ERR_INVALID_REQUEST, "name must be a string")
    units_per_case = opt_int(body, "units_per_case", gt=0)
    shelf_life_days = opt_int(body, "shelf_life_days", ge=0)
    regulated = opt_bool(body, "regulated")
    weight = opt_number(body, "weight_lbs_per_unit", gt=0)
    list_price = opt_number(body, "list_price_cents", ge=0)
    margin = opt_number(body, "margin_cents_per_unit", ge=0)
    for p in DB.products.values():
        if p["sku"] == sku:
            raise err(ERR_INVALID_REQUEST, "sku must be unique")
    p = base_fields()
    p.update({
        "sku": sku,
        "name": name,
        "units_per_case": units_per_case,
        "weight_lbs_per_unit": weight if weight is not None else 8.6,
        "shelf_life_days": shelf_life_days,
        "regulated": regulated,
        "list_price_cents": list_price if list_price is not None else 0,
        "margin_cents_per_unit": margin if margin is not None else 0,
        "status": "ACTIVE",
    })
    DB.products[p["id"]] = p
    return success_object(serialize_product(p), status=201)


@bp.get("/dairy/products/<productId>")
def get_product(productId):
    require_any()
    p = DB.products.get(productId)
    if p is None:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product id not found")
    return success_object(serialize_product(p))


@bp.post("/dairy/products/<productId>/discontinue")
def discontinue_product(productId):
    require_role("TerritoryManager")
    p = DB.products.get(productId)
    if p is None:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product id not found")
    if p["status"] != "ACTIVE":
        raise err(ERR_PRODUCT_DISCONTINUED, "Product is already DISCONTINUED")
    apply_changes(p, {"status": "DISCONTINUED"})
    return success_object(serialize_product(p))
