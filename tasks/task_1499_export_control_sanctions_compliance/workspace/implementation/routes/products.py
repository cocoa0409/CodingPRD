"""Product endpoints."""

from flask import Blueprint

import db
from errors import ApiError, ERR_VALIDATION
from middleware import auth, get_body, no_unknown, need, v_str, v_int, v_num, find
from response import ok

bp = Blueprint("products", __name__)


@bp.post("/compliance/products")
def create_product():
    auth("ComplianceAnalyst")
    body = get_body()
    no_unknown(body, {"sku", "name", "controlled_content_pct", "unit_value_cents"})
    sku = v_str(need(body, "sku"), "sku")
    name = v_str(need(body, "name"), "name")
    pct = v_num(need(body, "controlled_content_pct"), "controlled_content_pct")
    if pct < 0 or pct > 100:
        raise ApiError(ERR_VALIDATION, "controlled_content_pct must be between 0 and 100", 400)
    unit_value = v_int(need(body, "unit_value_cents"), "unit_value_cents")
    if unit_value <= 0:
        raise ApiError(ERR_VALIDATION, "unit_value_cents must be > 0", 400)
    product = {
        "sku": sku,
        "name": name,
        "controlled_content_pct": pct,
        "unit_value_cents": unit_value,
        "active_classification_id": None,
        "classification_count": 0,
        "status": "UNCLASSIFIED",
    }
    db.stamp_new(product)
    db.PRODUCTS[product["id"]] = product
    return ok(db.pub(product), "object", 201)


@bp.get("/compliance/products/<pid>")
def get_product(pid):
    auth()
    product = find(db.PRODUCTS, pid, "Product")
    return ok(db.pub(product), "object", 200)
