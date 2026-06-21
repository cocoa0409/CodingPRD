"""Special orders — sourcing from a vendor (PRD §3.7)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_caller, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.calc import special_order_deposit_required_cents
from services.common import (
    get_body, require_str, require_int, require_enum, resolve_fk, resolve_path,
    require_own_version, post_ledger_entry,
)

bp = Blueprint("special_orders", __name__)

KARATS = {"K14", "K18", "K24"}


def recompute_deposit_paid(order):
    total = 0
    for p in db.payments.values():
        if p["target_type"] == "SPECIAL_ORDER" and p.get("special_order_id") == order["id"] \
                and p["outcome"] == "SUCCEEDED":
            total += p["amount_cents"]
    order["deposit_paid_cents"] = total
    return total


@bp.route("/special-orders", methods=["POST"])
def create_special_order():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = get_body()
    customer_id = require_str(body, "customer_id")
    resolve_fk(db.customers, customer_id)
    vendor_name = require_str(body, "vendor_name")
    catalog_ref = require_str(body, "catalog_ref")
    quoted_price = require_int(body, "quoted_price_cents", gt=0)
    rec = db.new_record()
    rec.update({
        "customer_id": customer_id, "vendor_name": vendor_name, "catalog_ref": catalog_ref,
        "quoted_price_cents": quoted_price,
        "deposit_required_cents": special_order_deposit_required_cents(quoted_price),
        "deposit_paid_cents": 0, "received_inventory_item_id": None, "status": "REQUESTED",
    })
    db.special_orders[rec["id"]] = rec
    return success(serialize.special_order(rec), status=201)


@bp.route("/special-orders", methods=["GET"])
def list_special_orders():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    f_customer = request.args.get("customer_id")
    f_item = request.args.get("received_inventory_item_id")
    records = []
    for o in db.special_orders.values():
        if f_customer is not None and o["customer_id"] != f_customer:
            continue
        if f_item is not None and o.get("received_inventory_item_id") != f_item:
            continue
        records.append(o)
    page, meta = paginate(records, limit, offset)
    return success([serialize.special_order(r) for r in page], status=200, pagination=meta)


@bp.route("/special-orders/<oid>", methods=["GET"])
def get_special_order(oid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    rec = resolve_path(db.special_orders, oid)
    return success(serialize.special_order(rec), status=200)


@bp.route("/special-orders/<oid>/place", methods=["POST"])
def place_special_order(oid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate"})
    rec = resolve_path(db.special_orders, oid)
    body = get_body()
    if rec["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Order is not REQUESTED")
    if rec["deposit_paid_cents"] < rec["deposit_required_cents"]:
        raise ApiError("ERR_DEPOSIT_REQUIRED", "Deposit not satisfied")
    require_own_version(rec, body)
    rec["status"] = "PLACED"
    db.touch(rec)
    return success(serialize.special_order(rec), status=200)


@bp.route("/special-orders/<oid>/receive", methods=["POST"])
def receive_special_order(oid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate"})
    rec = resolve_path(db.special_orders, oid)
    body = get_body()
    if rec["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", "Order is not PLACED")
    sku = require_str(body, "sku")
    metal_karat = require_enum(body, "metal_karat", KARATS)
    require_own_version(rec, body)
    # Create the arriving InventoryItem (RESERVED).
    item = db.new_record()
    item.update({
        "sku": sku, "title": rec["catalog_ref"], "metal_karat": metal_karat,
        "list_price_cents": rec["quoted_price_cents"],
        "latest_appraised_value_cents": None, "status": "RESERVED",
    })
    db.inventory_items[item["id"]] = item
    rec["received_inventory_item_id"] = item["id"]
    rec["status"] = "ARRIVED"
    db.touch(rec)
    return success(serialize.special_order(rec), status=200)


@bp.route("/special-orders/<oid>/deliver", methods=["POST"])
def deliver_special_order(oid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate"})
    rec = resolve_path(db.special_orders, oid)
    body = get_body()
    if rec["status"] != "ARRIVED":
        raise ApiError("ERR_INVALID_STATE", "Order is not ARRIVED")
    require_own_version(rec, body)
    rec["status"] = "DELIVERED"
    db.touch(rec)
    item = db.inventory_items.get(rec["received_inventory_item_id"])
    if item is not None:
        item["status"] = "SOLD"
        db.touch(item)
    return success(serialize.special_order(rec), status=200)


@bp.route("/special-orders/<oid>/cancel", methods=["POST"])
def cancel_special_order(oid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.special_orders, oid)
    body = get_body()
    if rec["status"] not in ("REQUESTED", "PLACED"):
        raise ApiError("ERR_INVALID_STATE", "Order cannot be cancelled from its current state")
    require_own_version(rec, body)
    rec["status"] = "CANCELLED"
    db.touch(rec)
    if rec["deposit_paid_cents"] > 0:
        post_ledger_entry(rec["customer_id"], "CREDIT", rec["deposit_paid_cents"], "LAYAWAY_REFUND")
    return success(serialize.special_order(rec), status=200)
