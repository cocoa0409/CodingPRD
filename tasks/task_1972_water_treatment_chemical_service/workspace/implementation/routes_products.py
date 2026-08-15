"""ChemicalProduct catalog endpoints (PlatformAdmin-owned)."""

from flask import Blueprint, g

import errors
from db import db, create_entity, touch
from helpers import list_response, query_filter
from response import success_object
from serializers import product as ser
from validate import get_body, validate_shape, resolve

bp = Blueprint("products", __name__)


@bp.route("/wt/products", methods=["POST"])
def create_product():
    body = get_body()
    vals = validate_shape(body, [
        ("product_code", "str", True),
        ("active_pct", "num", True),
        ("container_size_gal", "num", True),
        ("unit_price_cents_per_gal", "int", True),
        ("contract_price_cents_per_gal", "int", True),
        ("density_g_per_ml", "num", False),
    ])
    if not (vals["active_pct"] > 0 and vals["active_pct"] <= 100):
        raise errors.field_constraint("active_pct must be > 0 and <= 100")
    if vals["container_size_gal"] <= 0:
        raise errors.field_constraint("container_size_gal must be > 0")
    if vals["unit_price_cents_per_gal"] < 0:
        raise errors.field_constraint("unit_price_cents_per_gal must be >= 0")
    if vals["contract_price_cents_per_gal"] < 0:
        raise errors.field_constraint("contract_price_cents_per_gal must be >= 0")
    if vals["contract_price_cents_per_gal"] > vals["unit_price_cents_per_gal"]:
        raise errors.field_constraint("contract_price_cents_per_gal must not exceed unit_price_cents_per_gal")
    for existing in db["products"].values():
        if existing["product_code"] == vals["product_code"]:
            raise errors.field_constraint("product_code must be unique across the catalog")
    ent = create_entity("products", {
        "product_code": vals["product_code"],
        "active_pct": vals["active_pct"],
        "container_size_gal": vals["container_size_gal"],
        "unit_price_cents_per_gal": vals["unit_price_cents_per_gal"],
        "contract_price_cents_per_gal": vals["contract_price_cents_per_gal"],
        "density_g_per_ml": vals["density_g_per_ml"] if vals["density_g_per_ml"] is not None else 1.0,
        "status": "LISTED",
    })
    return success_object(ser(ent), 201)


@bp.route("/wt/products", methods=["GET"])
def list_products():
    items = list(db["products"].values())
    status = query_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items, ser, None, (g.role, g.user_id))


@bp.route("/wt/products/<productId>", methods=["GET"])
def get_product(productId):
    ent = resolve("products", productId)
    return success_object(ser(ent), 200)


@bp.route("/wt/products/<productId>/delist", methods=["POST"])
def delist_product(productId):
    ent = resolve("products", productId)
    get_body()
    if ent["status"] != "LISTED":
        raise errors.invalid_state("Product must be LISTED to delist")
    ent["status"] = "DELISTED"
    touch(ent)
    return success_object(ser(ent), 200)
