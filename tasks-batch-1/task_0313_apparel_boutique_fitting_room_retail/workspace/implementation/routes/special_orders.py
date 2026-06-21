"""Special orders: ship-from-store fulfillment (PRD §3.8)."""
from flask import Blueprint, request

import errors
from db import db, stamp_new, touch
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import success, list_success
from services.common import (
    get_or_404, require_str, require_int, parse_pagination, paginate,
    serialize, serialize_list, recompute_variant,
)

bp = Blueprint("special_orders", __name__)


@bp.post("/special-orders")
def create_special_order():
    user_id, role = authenticate()
    require_role(role, {"StoreAssociate", "Customer"})
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    source_sku_variant_id = require_str(body, "source_sku_variant_id")
    customer = get_or_404("customer", customer_id)
    get_or_404("sku_variant", source_sku_variant_id)
    if role == "Customer" and user_id != customer["id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    qty = require_int(body, "qty")
    if qty < 1:
        raise err(errors.ERR_INVALID_REQUEST, "qty must be >= 1")
    ship_to_state_code = require_str(body, "ship_to_state_code")
    if len(ship_to_state_code) != 2 or not ship_to_state_code.isupper():
        raise err(errors.ERR_INVALID_REQUEST, "ship_to_state_code must be 2-letter uppercase")

    rec = stamp_new({
        "customer_id": customer_id,
        "source_sku_variant_id": source_sku_variant_id,
        "qty": qty,
        "ship_to_state_code": ship_to_state_code,
        "status": "PLACED",
        "reserved_units": 0,
    })
    db.special_orders[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/special-orders/<rid>")
def get_special_order(rid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    rec = get_or_404("special_order", rid)
    if role == "Customer" and user_id != rec["customer_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    return success(serialize(rec))


@bp.get("/special-orders")
def list_special_orders():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.special_orders.values())
    customer_id = request.args.get("customer_id")
    source_sku_variant_id = request.args.get("source_sku_variant_id")
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    if source_sku_variant_id is not None:
        items = [s for s in items if s["source_sku_variant_id"] == source_sku_variant_id]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.post("/special-orders/<rid>/source")
def source_special_order(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    so = get_or_404("special_order", rid)
    if so["status"] != "PLACED":
        raise err(errors.ERR_INVALID_STATE, "source requires PLACED")
    variant = db.sku_variants[so["source_sku_variant_id"]]
    if variant["available"] < so["qty"]:
        raise err(errors.ERR_INSUFFICIENT_INVENTORY, "insufficient inventory to source")
    variant["reserved"] += so["qty"]
    so["reserved_units"] = so["qty"]
    so["status"] = "SOURCED"
    touch(so)
    recompute_variant(variant)
    return success(serialize(so))


@bp.post("/special-orders/<rid>/ship")
def ship_special_order(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    so = get_or_404("special_order", rid)
    if so["status"] != "SOURCED":
        raise err(errors.ERR_INVALID_STATE, "ship requires SOURCED")
    variant = db.sku_variants[so["source_sku_variant_id"]]
    variant["on_hand"] -= so["qty"]
    variant["reserved"] = max(0, variant["reserved"] - so["qty"])
    so["reserved_units"] = 0
    so["status"] = "SHIPPED"
    touch(so)
    recompute_variant(variant)
    return success(serialize(so))


@bp.post("/special-orders/<rid>/deliver")
def deliver_special_order(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    so = get_or_404("special_order", rid)
    if so["status"] != "SHIPPED":
        raise err(errors.ERR_INVALID_STATE, "deliver requires SHIPPED")
    so["status"] = "DELIVERED"
    touch(so)
    return success(serialize(so))


@bp.post("/special-orders/<rid>/cancel")
def cancel_special_order(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    so = get_or_404("special_order", rid)
    if so["status"] not in ("PLACED", "SOURCED"):
        raise err(errors.ERR_INVALID_STATE, "cancel requires PLACED or SOURCED")
    variant = db.sku_variants[so["source_sku_variant_id"]]
    if so["reserved_units"] > 0:
        variant["reserved"] = max(0, variant["reserved"] - so["reserved_units"])
        so["reserved_units"] = 0
        so["status"] = "CANCELLED"
        touch(so)
        recompute_variant(variant)
    else:
        so["status"] = "CANCELLED"
        touch(so)
    return success(serialize(so))
