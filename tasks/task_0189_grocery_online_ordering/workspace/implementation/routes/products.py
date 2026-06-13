"""Product endpoints (PRD §3.1, SCAFFOLD §1.5)."""
from flask import Blueprint, request

import db
from errors import err, ERR_PRODUCT_NOT_FOUND, ERR_STORE_NOT_FOUND, ERR_INVALID_ORDER_STATE
from middleware import get_user_context, require_role
import validate as V
from response import object_response, array_response
from serialize import public, public_list
from pagination import get_pagination, paginate

bp = Blueprint("products", __name__)


@bp.route("/v1/products", methods=["POST"])
def create_product():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps"})  # PRD §4
    body = V.get_body()
    store_id = V.require_str(body, "store_id")
    sku = V.require_str(body, "sku")
    name = V.require_str(body, "name")
    pricing_mode = V.require_enum(body, "pricing_mode", {"UNIT", "WEIGHT"})
    unit_price = V.require_int(body, "unit_price_cents", minimum=0)  # must be >= 0
    ebt_eligible = V.require_bool(body, "ebt_eligible", False)   # default false
    age_restricted = V.require_bool(body, "age_restricted", False)  # default false
    cold_chain = V.require_bool(body, "cold_chain", False)      # default false
    on_hand = V.opt_number(body, "on_hand_qty", 0, minimum=0)   # default 0
    with db.lock:
        if store_id not in db.stores:
            err(ERR_STORE_NOT_FOUND, "Store not found")
        product = {
            "store_id": store_id,
            "sku": sku,
            "name": name,
            "pricing_mode": pricing_mode,
            "unit_price_cents": unit_price,
            "ebt_eligible": ebt_eligible,
            "age_restricted": age_restricted,
            "cold_chain": cold_chain,
            "on_hand_qty": on_hand,
            "status": "ACTIVE",  # PRD §3.1: begins ACTIVE
        }
        db.stamp_create(product)
        db.products[product["id"]] = product
        return object_response(public(product), 201)


@bp.route("/v1/products", methods=["GET"])
def list_products():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer", "Picker"})  # PRD §4
    limit, offset = get_pagination()
    store_id = request.args.get("store_id")
    sku = request.args.get("sku")
    with db.lock:
        records = list(db.products.values())
        if store_id is not None:
            records = [p for p in records if p["store_id"] == store_id]
        if sku is not None:
            records = [p for p in records if p["sku"] == sku]
        page, total = paginate(records, limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/products/<product_id>", methods=["GET"])
def get_product(product_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer", "Picker"})  # PRD §4
    with db.lock:
        product = db.products.get(product_id)
        if product is None:
            err(ERR_PRODUCT_NOT_FOUND, "Product not found")
        return object_response(public(product))


@bp.route("/v1/products/<product_id>/discontinue", methods=["POST"])
def discontinue_product(product_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps"})  # PRD §4
    with db.lock:
        product = db.products.get(product_id)
        if product is None:
            err(ERR_PRODUCT_NOT_FOUND, "Product not found")
        if product["status"] != "ACTIVE":
            err(ERR_INVALID_ORDER_STATE, "Product is not ACTIVE")
        product["status"] = "DISCONTINUED"
        db.touch(product)
        return object_response(public(product))
