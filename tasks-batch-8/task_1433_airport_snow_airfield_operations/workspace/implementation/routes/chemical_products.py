"""Chemical product routes."""

from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (ERR_PRODUCT_NOT_FOUND, not_found, validation)
from middleware import require_roles
from response import success_list, success_object
from services.core import (get_pagination, is_int, is_number, new_id,
                           now_iso_ms, paginate, to_decimal)
from services.domain import serialize_chemical_product

bp = Blueprint("chemical_products", __name__)


@bp.route("/chemical-products", methods=["POST"])
def create_product():
    user_id, role = require_roles("SystemAdmin")
    body = request.get_json(silent=True) or {}
    for f in ("product_code", "base_rate_lbs_per_1000sqft",
              "unit_cost_cents_per_lb", "seasonal_limit_lbs"):
        if f not in body:
            raise validation(f"Missing required field: {f}")
    if not isinstance(body["product_code"], str) or not body["product_code"]:
        raise validation("product_code must be a non-empty string")
    if not is_number(body["base_rate_lbs_per_1000sqft"]):
        raise validation("base_rate_lbs_per_1000sqft must be a number")
    base_rate = to_decimal(body["base_rate_lbs_per_1000sqft"],
                            "base_rate_lbs_per_1000sqft")
    if base_rate <= 0:
        raise validation("base_rate_lbs_per_1000sqft must be > 0")
    if not is_int(body["unit_cost_cents_per_lb"]):
        raise validation("unit_cost_cents_per_lb must be an integer")
    if body["unit_cost_cents_per_lb"] < 0:
        raise validation("unit_cost_cents_per_lb must be >= 0")
    if not is_number(body["seasonal_limit_lbs"]):
        raise validation("seasonal_limit_lbs must be a number")
    seasonal_limit = to_decimal(body["seasonal_limit_lbs"], "seasonal_limit_lbs")
    if seasonal_limit <= 0:
        raise validation("seasonal_limit_lbs must be > 0")
    for p in db.chemical_products.values():
        if p["product_code"] == body["product_code"]:
            raise validation("product_code must be unique")
    now = now_iso_ms()
    p = {
        "id": new_id(),
        "product_code": body["product_code"],
        "base_rate_lbs_per_1000sqft": base_rate,
        "unit_cost_cents_per_lb": body["unit_cost_cents_per_lb"],
        "seasonal_limit_lbs": seasonal_limit,
        "seasonal_reserved_lbs": Decimal(0),
        "seasonal_dispensed_lbs": Decimal(0),
        "seasonal_available_lbs": seasonal_limit,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.chemical_products[p["id"]] = p
    return success_object(serialize_chemical_product(p), 201)


@bp.route("/chemical-products", methods=["GET"])
def list_products():
    user_id, role = require_roles("SystemAdmin", "MaintenanceLead", "OpsController")
    limit, offset = get_pagination(request.args)
    items = list(db.chemical_products.values())
    code_q = request.args.get("product_code")
    status_q = request.args.get("status")
    if code_q:
        items = [p for p in items if p["product_code"] == code_q]
    if status_q:
        items = [p for p in items if p["status"] == status_q]
    items.sort(key=lambda p: p["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_chemical_product(p) for p in page],
                        limit, offset, total)


@bp.route("/chemical-products/<product_id>", methods=["GET"])
def get_product(product_id):
    user_id, role = require_roles("SystemAdmin", "MaintenanceLead", "OpsController")
    p = db.chemical_products.get(product_id)
    if not p:
        raise not_found(ERR_PRODUCT_NOT_FOUND, "ChemicalProduct not found")
    return success_object(serialize_chemical_product(p))
