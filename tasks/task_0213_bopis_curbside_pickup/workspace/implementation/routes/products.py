"""Product (catalog) endpoints."""

from flask import Blueprint

from db import db, stamp_common
from errors import err
from middleware import require_auth, get_json_body
from response import object_response
from services.common import require_str, require_pos_int, get_or_404, ser_product

bp = Blueprint("products", __name__)


@bp.post("/products")
def create_product():
    require_auth({"PlatformAdmin"})
    body = get_json_body()
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    unit_price_cents = require_pos_int(body, "unit_price_cents")
    substitution_group = None
    if "substitution_group" in body and body["substitution_group"] is not None:
        substitution_group = require_str(body, "substitution_group")

    # sku unique among products
    for p in db.products.values():
        if p["sku"] == sku:
            raise err("ERR_INVALID_REQUEST", "sku already exists")

    rec = {
        "sku": sku,
        "name": name,
        "unit_price_cents": unit_price_cents,
        "substitution_group": substitution_group,
    }
    stamp_common(rec)
    db.products[rec["id"]] = rec
    return object_response(ser_product(rec), 201)


@bp.get("/products/<pid>")
def get_product(pid):
    require_auth({"Customer", "StorePicker", "StoreAssociate",
                  "StoreManager", "PlatformAdmin"})
    rec = get_or_404(db.products, pid)
    return object_response(ser_product(rec))
