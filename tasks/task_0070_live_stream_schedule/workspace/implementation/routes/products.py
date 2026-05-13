"""Product endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION_FAILED, raise_err)
from middleware import require_auth, require_role, occ_check
from response import success


bp = Blueprint("products", __name__, url_prefix="/live-schedule/products")


_PRODUCT_STATUSES = {"ON_SHELF", "OFF_SHELF"}
_PRODUCT_CATEGORIES = {"FOOD", "COSMETICS", "ELECTRONICS",
                       "FASHION", "KIDS", "FINANCIAL"}


@bp.post("")
def create_product():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = request.get_json(silent=True) or {}
    for key in ("name", "category", "requires_professional_cert",
                "unit_price_cents", "available_stock"):
        if key not in body:
            raise_err(ERR_VALIDATION_FAILED, f"Missing field: {key}")
    if body["category"] not in _PRODUCT_CATEGORIES:
        raise_err(ERR_VALIDATION_FAILED, "Invalid category")
    if not isinstance(body["unit_price_cents"], int) or body["unit_price_cents"] < 0:
        raise_err(ERR_VALIDATION_FAILED, "unit_price_cents must be >=0")
    if not isinstance(body["available_stock"], int) or body["available_stock"] < 0:
        raise_err(ERR_VALIDATION_FAILED, "available_stock must be >=0")
    payload = {
        "name": body["name"],
        "category": body["category"],
        "requires_professional_cert": bool(body["requires_professional_cert"]),
        "unit_price_cents": int(body["unit_price_cents"]),
        "available_stock": int(body["available_stock"]),
        "reserved_stock": 0,
        "status": "ON_SHELF",
    }
    product = db.create_entity("products", payload)
    return success(product, http_status=201)


@bp.patch("/<pid>")
def update_product(pid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    entity = db.raw_get("products", pid)
    if entity is None:
        raise_err(ERR_NOT_FOUND, "Product not found")
    body = request.get_json(silent=True) or {}
    occ_check(entity, body)
    updates = {}
    if "status" in body:
        if body["status"] not in _PRODUCT_STATUSES:
            raise_err(ERR_VALIDATION_FAILED, "Invalid status")
        updates["status"] = body["status"]
    if "available_stock" in body:
        if not isinstance(body["available_stock"], int) or body["available_stock"] < 0:
            raise_err(ERR_VALIDATION_FAILED, "available_stock must be >=0")
        updates["available_stock"] = body["available_stock"]

    def mutate(p):
        p.update(updates)
    updated = db.update_entity("products", pid, mutate)
    return success(updated)
