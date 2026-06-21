"""Product catalog endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_roles
from response import ok_array, ok_object
from services import common
from services.registration_svc import mint_common, public

bp = Blueprint("products", __name__)

CATEGORIES = {"ELECTRONICS", "APPLIANCE", "POWER_TOOL", "FURNITURE"}


@bp.post("/products")
def create_product():
    require_roles(["WarrantyAdmin"])
    body = common.get_json_body()
    common.require_fields(body, ["model_number", "category", "msrp_cents",
                                 "base_warranty_months", "serviceable_lifespan_months"])
    model_number = common.require_str(body, "model_number")
    category = common.require_enum(body, "category", CATEGORIES)
    msrp_cents = common.require_int(body, "msrp_cents", minimum=1)
    base_warranty_months = common.require_int(body, "base_warranty_months", minimum=0)
    serviceable_lifespan_months = common.require_int(body, "serviceable_lifespan_months", minimum=1)

    # model_number unique across catalog
    for p in db.products.values():
        if p["model_number"] == model_number:
            raise APIError(ERR_INVALID_REQUEST, 400, "model_number already exists")

    product = {
        "model_number": model_number,
        "category": category,
        "msrp_cents": msrp_cents,
        "base_warranty_months": base_warranty_months,
        "serviceable_lifespan_months": serviceable_lifespan_months,
        "status": "ACTIVE",
    }
    mint_common(product)
    db.products[product["id"]] = product
    return ok_object(public(product), 201)


@bp.get("/products/<pid>")
def get_product(pid):
    require_roles(["WarrantyAdmin", "Owner", "ClaimsProcessor"])
    product = db.products.get(pid)
    if product is None:
        raise APIError(ERR_NOT_FOUND, 404, "Product not found")
    return ok_object(public(product))


@bp.get("/products")
def list_products():
    require_roles(["WarrantyAdmin", "Owner", "ClaimsProcessor"])
    limit, offset = common.parse_pagination()
    category = request.args.get("category")
    rows = list(db.products.values())
    if category is not None:
        rows = [p for p in rows if p["category"] == category]
    page, total = common.paginate(rows, limit, offset)
    return ok_array([public(p) for p in page], limit, offset, total)
