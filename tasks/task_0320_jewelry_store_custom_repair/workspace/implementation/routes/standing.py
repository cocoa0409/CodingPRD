"""Customers, InventoryItems, Workbenches — the standing records (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_caller, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.common import (
    get_body, require_str, require_int, require_enum, require_own_version, resolve_path,
)

bp = Blueprint("standing", __name__)


# ---------------------------------------------------------------- Customers
@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    phone = require_str(body, "phone")
    # Uniqueness: email unique across customers (PRD §2.8).
    for c in db.customers.values():
        if c["email"] == email:
            raise ApiError("ERR_DUPLICATE", "email already exists")
    rec = db.new_record()
    rec.update({
        "full_name": full_name, "email": email, "phone": phone,
        "store_credit_balance_cents": 0, "status": "ACTIVE",
    })
    db.customers[rec["id"]] = rec
    return success(serialize.customer(rec), status=201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Goldsmith"})
    limit, offset = parse_pagination()
    email = request.args.get("email")
    records = [c for c in db.customers.values() if email is None or c["email"] == email]
    page, meta = paginate(records, limit, offset)
    return success([serialize.customer(r) for r in page], status=200, pagination=meta)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Goldsmith", "Customer"})
    rec = resolve_path(db.customers, cid)
    return success(serialize.customer(rec), status=200)


@bp.route("/customers/<cid>/suspend", methods=["POST"])
def suspend_customer(cid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.customers, cid)
    body = get_body()
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Customer is not ACTIVE")
    require_own_version(rec, body)
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return success(serialize.customer(rec), status=200)


# ---------------------------------------------------------------- Inventory items
@bp.route("/inventory-items", methods=["POST"])
def create_inventory_item():
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    body = get_body()
    sku = require_str(body, "sku")
    title = require_str(body, "title")
    metal_karat = require_enum(body, "metal_karat", {"K14", "K18", "K24"})
    list_price = require_int(body, "list_price_cents", gt=0)
    for it in db.inventory_items.values():
        if it["sku"] == sku:
            raise ApiError("ERR_DUPLICATE", "sku already exists")
    rec = db.new_record()
    rec.update({
        "sku": sku, "title": title, "metal_karat": metal_karat,
        "list_price_cents": list_price, "latest_appraised_value_cents": None,
        "status": "IN_STOCK",
    })
    db.inventory_items[rec["id"]] = rec
    return success(serialize.inventory_item(rec), status=201)


@bp.route("/inventory-items", methods=["GET"])
def list_inventory_items():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Goldsmith", "Customer"})
    limit, offset = parse_pagination()
    sku = request.args.get("sku")
    status = request.args.get("status")
    records = []
    for it in db.inventory_items.values():
        if sku is not None and it["sku"] != sku:
            continue
        if status is not None and it["status"] != status:
            continue
        records.append(it)
    page, meta = paginate(records, limit, offset)
    return success([serialize.inventory_item(r) for r in page], status=200, pagination=meta)


@bp.route("/inventory-items/<iid>", methods=["GET"])
def get_inventory_item(iid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Goldsmith", "Customer"})
    rec = resolve_path(db.inventory_items, iid)
    return success(serialize.inventory_item(rec), status=200)


# ---------------------------------------------------------------- Workbenches
@bp.route("/workbenches", methods=["POST"])
def create_workbench():
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    body = get_body()
    label = require_str(body, "label")
    # PRD §2.8 enumerates exactly two ERR_DUPLICATE constraints (Customer.email,
    # InventoryItem.sku); workbench label carries no duplicate-rejection error.
    rec = db.new_record()
    rec.update({"label": label, "status": "ACTIVE"})
    db.workbenches[rec["id"]] = rec
    return success(serialize.workbench(rec), status=201)


@bp.route("/workbenches", methods=["GET"])
def list_workbenches():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Goldsmith"})
    limit, offset = parse_pagination()
    page, meta = paginate(list(db.workbenches.values()), limit, offset)
    return success([serialize.workbench(r) for r in page], status=200, pagination=meta)


@bp.route("/workbenches/<wid>", methods=["GET"])
def get_workbench(wid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Goldsmith"})
    rec = resolve_path(db.workbenches, wid)
    return success(serialize.workbench(rec), status=200)
