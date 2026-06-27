"""Product (catalog) endpoints (PRD §3.1)."""
from flask import Blueprint

import db
from db import stamp_create
from middleware import require_auth, require_role
from response import object_response, array_response
from errors import err
from services.common import (
    get_body, lookup, parse_pagination, paginate,
    require_present, as_str, as_int, as_bool, as_enum,
)
from services.serialize import product_out

bp = Blueprint("products", __name__)

READ_ROLES = ["InventoryManager", "LivestockKeeper", "ClinicVet", "StoreClerk", "Customer"]
CATEGORIES = {"FOOD", "HABITAT", "ACCESSORY", "MEDICATION"}


@bp.route("/products", methods=["POST"])
def create_product():
    _, role = require_auth()
    require_role(role, ["InventoryManager"])
    body = get_body()
    sku = as_str(require_present(body, "sku"), "sku")
    name = as_str(require_present(body, "name"), "name")
    category = as_enum(require_present(body, "category"), "category", CATEGORIES)
    unit_price = as_int(require_present(body, "unit_price_cents"), "unit_price_cents")
    if unit_price <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "unit_price_cents must be > 0.")
    is_rx = False
    if "is_prescription_diet" in body and body["is_prescription_diet"] is not None:
        is_rx = as_bool(body["is_prescription_diet"], "is_prescription_diet")
    points = 0
    if "loyalty_points_per_unit" in body and body["loyalty_points_per_unit"] is not None:
        points = as_int(body["loyalty_points_per_unit"], "loyalty_points_per_unit")
        if points < 0:
            raise err("ERR_INVALID_FIELD_VALUE", "loyalty_points_per_unit must be >= 0.")

    # Uniqueness: sku globally unique (PRD §2.7).
    for p in db.products.values():
        if p["sku"] == sku:
            raise err("ERR_DUPLICATE_RESOURCE", "Product sku must be globally unique.")

    record = {
        "sku": sku,
        "name": name,
        "category": category,
        "unit_price_cents": unit_price,
        "is_prescription_diet": is_rx,
        "loyalty_points_per_unit": points,
    }
    stamp_create(record)
    db.products[record["id"]] = record
    return object_response(product_out(record), 201)


@bp.route("/products", methods=["GET"])
def list_products():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    page, total = paginate(list(db.products.values()), limit, offset)
    return array_response([product_out(r) for r in page], limit, offset, total)


@bp.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    record = lookup("products", product_id)
    return object_response(product_out(record))
