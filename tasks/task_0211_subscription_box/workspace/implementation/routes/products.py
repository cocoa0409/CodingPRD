"""Product endpoints (PRD §3.1, §2.5)."""
from flask import Blueprint, request

from db import db
from common import (new_record, touch, serialize, get_body, require_str,
                    require_int, must_exist, paginate)
from middleware import authenticate, require_roles
from response import success, list_success
from errors import err, ERR_DUPLICATE_SKU

bp = Blueprint("products", __name__)


@bp.post("/products")
def create_product():
    authenticate()
    require_roles("CurationAdmin")
    body = get_body()
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    on_hand_qty = require_int(body, "on_hand_qty", minimum=0)

    # Uniqueness check (priority 7, after well-formedness).
    for p in db.products.values():
        if p["sku"] == sku:
            raise err(ERR_DUPLICATE_SKU, "Product sku already exists.")

    product = new_record({
        "sku": sku,
        "name": name,
        "on_hand_qty": on_hand_qty,
        "allocated_qty": 0,
        "status": "SELLABLE",
    })
    db.products[product["id"]] = product
    return success(serialize(product), status=201)


@bp.get("/products/<pid>")
def get_product(pid):
    authenticate()
    require_roles("CurationAdmin", "Subscriber", "BillingOperator")
    product = must_exist(db.products, pid, "Product")
    return success(serialize(product))


@bp.get("/products")
def list_products():
    authenticate()
    require_roles("CurationAdmin", "Subscriber", "BillingOperator")
    records = list(db.products.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.post("/products/<pid>/restock")
def restock_product(pid):
    authenticate()
    require_roles("CurationAdmin")
    product = must_exist(db.products, pid, "Product")
    body = get_body()
    add_qty = require_int(body, "add_qty", minimum=0)
    product["on_hand_qty"] += add_qty
    touch(product)
    return success(serialize(product))


@bp.post("/products/<pid>/discontinue")
def discontinue_product(pid):
    authenticate()
    require_roles("CurationAdmin")
    product = must_exist(db.products, pid, "Product")
    product["status"] = "DISCONTINUED"
    touch(product)
    return success(serialize(product))
