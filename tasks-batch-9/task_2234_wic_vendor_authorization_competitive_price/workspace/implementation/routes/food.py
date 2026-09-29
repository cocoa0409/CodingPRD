"""Authorized food list endpoints (PRD §3.1)."""

from flask import Blueprint

import calc
import config as C
import envelope
import models
import services
import validators
from auth import authenticate
from errors import ApiError
from routes.common import body_fk, listing, need
from store import db, ordered

bp = Blueprint("food", __name__)

READ_ROLES = (
    C.ROLE_ANALYST,
    C.ROLE_SUPERVISOR,
    C.ROLE_INVESTIGATOR,
    C.ROLE_VENDOR_OPERATOR,
)


@bp.post("/food-categories")
def create_category():
    authenticate(C.ROLE_SUPERVISOR)
    payload = validators.body()
    code = validators.req_string(payload, "code")
    name = validators.req_string(payload, "name")
    is_formula = validators.req_bool(payload, "is_formula")
    level = validators.req_enum(
        payload, "formula_restriction_level", C.FORMULA_RESTRICTION_LEVELS
    )
    min_stock_units = validators.req_int(payload, "min_stock_units", minimum=0)
    min_variety_count = validators.req_int(payload, "min_variety_count", minimum=0)
    max_units = validators.req_int(payload, "max_units_per_transaction", minimum=1)
    stock_required = validators.req_bool(payload, "stock_required")

    for existing in db.food_categories.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_FOOD_CATEGORY_CODE")

    record = models.food_category(
        code=code,
        name=name,
        is_formula=is_formula,
        formula_restriction_level=level,
        min_stock_units=min_stock_units,
        min_variety_count=min_variety_count,
        max_units_per_transaction=max_units,
        stock_required=stock_required,
    )
    db.food_categories[record["id"]] = record
    return envelope.success(record, 201)


@bp.get("/food-categories/<entity_id>")
def read_category(entity_id):
    authenticate(*READ_ROLES)
    return envelope.success(
        need(db.food_categories, entity_id, "ERR_FOOD_CATEGORY_NOT_FOUND")
    )


@bp.post("/authorized-food-items")
def create_item():
    authenticate(C.ROLE_SUPERVISOR)
    payload = validators.body()
    body_fk(payload, "food_category_id", db.food_categories, "ERR_FOOD_CATEGORY_NOT_FOUND")

    category_id = validators.req_string(payload, "food_category_id")
    upc = validators.req_upc(payload, "upc")
    brand = validators.req_string(payload, "brand")
    size = calc.dec(validators.req_number(payload, "container_size_oz", exclusive_min=0))
    contract_brand = validators.req_bool(payload, "contract_brand")
    required = validators.opt_bool(payload, "required_for_authorization", default=False)

    for existing in db.food_items.values():
        if existing["upc"] == upc and existing["status"] == "ACTIVE":
            raise ApiError("ERR_DUPLICATE_UPC")

    record = models.food_item(
        food_category_id=category_id,
        upc=upc,
        brand=brand,
        container_size_oz=size,
        contract_brand=contract_brand,
        required_for_authorization=required,
    )
    db.food_items[record["id"]] = record
    return envelope.success(record, 201)


@bp.get("/authorized-food-items/<entity_id>")
def read_item(entity_id):
    authenticate(*READ_ROLES)
    return envelope.success(need(db.food_items, entity_id, "ERR_FOOD_ITEM_NOT_FOUND"))


@bp.get("/authorized-food-items")
def list_items():
    authenticate(*READ_ROLES)
    return listing(
        ordered(db.food_items),
        {"food_category_id": "food_category_id", "upc": "upc", "status": "status"},
    )


@bp.post("/authorized-food-items/<entity_id>/delist")
def delist_item(entity_id):
    authenticate(C.ROLE_SUPERVISOR)
    item = need(db.food_items, entity_id, "ERR_FOOD_ITEM_NOT_FOUND")
    payload = validators.body()
    reason = validators.req_string(payload, "delist_reason")
    if item["status"] == "ACTIVE":
        services.delist_item(item, reason)
    return envelope.success(item)
