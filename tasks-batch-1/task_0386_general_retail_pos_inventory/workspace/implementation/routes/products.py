"""Product endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import DB
from middleware import auth_context, require_role
from common import (
    stamp_create, touch, public_view, get_json_body,
    as_int, as_str, as_bool, parse_pagination, paginate,
)
from response import success, success_list
from errors import err, ERR_NOT_FOUND, ERR_DUPLICATE_RESOURCE, ERR_INVALID_STATE

bp = Blueprint("products", __name__)


@bp.route("/products", methods=["POST"])
def create_product():
    _, role = auth_context()
    require_role(role, {"StoreManager", "InventoryClerk"})
    body = get_json_body()
    sku = as_str(body, "sku")
    barcode = as_str(body, "barcode")
    name = as_str(body, "name")
    list_price_cents = as_int(body, "list_price_cents", minimum=0)
    tax_exempt = as_bool(body, "tax_exempt", default=False)
    loyalty_eligible = as_bool(body, "loyalty_eligible", default=True)

    with DB.lock:
        for p in DB.products.values():
            if p["sku"] == sku or p["barcode"] == barcode:
                raise err(ERR_DUPLICATE_RESOURCE, "SKU or barcode already exists")
        product = {
            "sku": sku,
            "barcode": barcode,
            "name": name,
            "list_price_cents": list_price_cents,
            "tax_exempt": tax_exempt,
            "loyalty_eligible": loyalty_eligible,
            "status": "ACTIVE",
        }
        stamp_create(product)
        DB.products[product["id"]] = product
        return success(public_view(product), status=201)


@bp.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier", "InventoryClerk", "Customer"})
    with DB.lock:
        product = DB.products.get(product_id)
        if product is None:
            raise err(ERR_NOT_FOUND, "Product not found")
        return success(public_view(product))


@bp.route("/products", methods=["GET"])
def list_products():
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier", "InventoryClerk", "Customer"})
    limit, offset = parse_pagination()
    sku = request.args.get("sku")
    barcode = request.args.get("barcode")
    status = request.args.get("status")
    with DB.lock:
        recs = list(DB.products.values())
        if sku is not None:
            recs = [r for r in recs if r["sku"] == sku]
        if barcode is not None:
            recs = [r for r in recs if r["barcode"] == barcode]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        items, total = paginate(recs, limit, offset)
        return success_list(items, limit, offset, total)


@bp.route("/products/<product_id>/discontinue", methods=["POST"])
def discontinue_product(product_id):
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    with DB.lock:
        product = DB.products.get(product_id)
        if product is None:
            raise err(ERR_NOT_FOUND, "Product not found")
        if product["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Product is not ACTIVE")
        product["status"] = "DISCONTINUED"
        touch(product)
        return success(public_view(product))
