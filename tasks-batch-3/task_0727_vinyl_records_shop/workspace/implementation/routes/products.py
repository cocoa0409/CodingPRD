"""Product, catalog lifecycle, and allocation endpoints."""
from flask import Blueprint, request

import db
from models import base_fields, touch
from middleware import authenticate, get_identity_optional
from validators import (
    get_body, require_string, require_int, require_enum, get_pagination,
    paginate, sorted_by_created, lookup,
)
from response import success, success_list
from errors import err, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from services import public, public_list

bp = Blueprint("products", __name__)

FORMATS = {"VINYL", "CD", "CASSETTE"}


@bp.route("/shop/products", methods=["POST"])
def create_product():
    authenticate({"Manager"})
    body = get_body()
    artist = require_string(body, "artist")
    title = require_string(body, "title")
    fmt = require_enum(body, "format", FORMATS)
    base_price = require_int(body, "base_price_cents")
    if base_price <= 0:
        raise err(ERR_INVALID_REQUEST, "base_price_cents must be > 0")
    is_rsd = body.get("is_rsd_exclusive", False)
    if not isinstance(is_rsd, bool):
        raise err(ERR_INVALID_REQUEST, "is_rsd_exclusive must be boolean")
    prod = base_fields()
    prod.update({
        "artist": artist,
        "title": title,
        "format": fmt,
        "base_price_cents": base_price,
        "is_rsd_exclusive": is_rsd,
        "catalog_status": "DRAFT",
    })
    db.db.products[prod["id"]] = prod
    return success(public(prod), 201)


@bp.route("/shop/products/<pid>", methods=["GET"])
def read_product(pid):
    get_identity_optional()
    prod = lookup(db.db.products, pid)
    return success(public(prod), 200)


@bp.route("/shop/products", methods=["GET"])
def list_products():
    get_identity_optional()
    limit, offset = get_pagination()
    fmt = request.args.get("format")
    status = request.args.get("catalog_status")
    rsd = request.args.get("is_rsd_exclusive")
    items = list(db.db.products.values())
    if fmt is not None:
        items = [p for p in items if p["format"] == fmt]
    if status is not None:
        items = [p for p in items if p["catalog_status"] == status]
    if rsd is not None:
        want = rsd.lower() == "true"
        items = [p for p in items if p["is_rsd_exclusive"] == want]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)


@bp.route("/shop/products/<pid>/list", methods=["POST"])
def list_product(pid):
    authenticate({"Manager"})
    prod = lookup(db.db.products, pid)
    if prod["catalog_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Product is not in DRAFT")
    has_inventory = any(
        i["product_id"] == pid for i in db.db.inventory_items.values()
    )
    if not (has_inventory or prod["is_rsd_exclusive"]):
        raise err(ERR_INVALID_STATE, "Product not stockable")
    prod["catalog_status"] = "LISTED"
    touch(prod)
    return success(public(prod), 200)


@bp.route("/shop/products/<pid>/open-preorders", methods=["POST"])
def open_preorders(pid):
    authenticate({"Manager"})
    prod = lookup(db.db.products, pid)
    if prod["catalog_status"] != "LISTED":
        raise err(ERR_INVALID_STATE, "Product is not LISTED")
    if not prod["is_rsd_exclusive"]:
        raise err(ERR_INVALID_STATE, "Product is not RSD exclusive")
    allocs = [a for a in db.db.allocations.values() if a["product_id"] == pid]
    if not allocs:
        raise err(ERR_INVALID_STATE, "No allocation exists for this product")
    # current_utc < window_close_at for some allocation
    ok = any(db.db.now < db.parse_iso(a["window_close_at"]) for a in allocs)
    if not ok:
        raise err(ERR_INVALID_STATE, "Allocation window already closed")
    prod["catalog_status"] = "PRE_ORDER_OPEN"
    touch(prod)
    return success(public(prod), 200)


@bp.route("/shop/products/<pid>/discontinue", methods=["POST"])
def discontinue(pid):
    authenticate({"Manager"})
    prod = lookup(db.db.products, pid)
    if prod["catalog_status"] != "LISTED":
        raise err(ERR_INVALID_STATE, "Product is not LISTED")
    reserved = any(
        i["product_id"] == pid and i["status"] == "RESERVED"
        for i in db.db.inventory_items.values()
    )
    if reserved:
        raise err(ERR_INVALID_STATE, "A copy is currently RESERVED")
    prod["catalog_status"] = "DISCONTINUED"
    touch(prod)
    return success(public(prod), 200)


# ---- Allocations -----------------------------------------------------------
@bp.route("/shop/products/<pid>/allocations", methods=["POST"])
def create_allocation(pid):
    authenticate({"Manager"})
    prod = lookup(db.db.products, pid)
    body = get_body()
    total = require_int(body, "allocation_total")
    if total <= 0:
        raise err(ERR_INVALID_REQUEST, "allocation_total must be > 0")
    window_open = require_string(body, "window_open_at")
    window_close = require_string(body, "window_close_at")
    pickup_conc = body.get("pickup_concurrency", 1)
    if not isinstance(pickup_conc, int) or isinstance(pickup_conc, bool) or pickup_conc < 1:
        raise err(ERR_INVALID_REQUEST, "pickup_concurrency must be >= 1")
    alloc = base_fields()
    alloc.update({
        "product_id": pid,
        "allocation_total": total,
        "pickup_concurrency": pickup_conc,
        "available_count": total,
        "reserved_count": 0,
        "committed_count": 0,
        "window_open_at": window_open,
        "window_close_at": window_close,
    })
    db.db.allocations[alloc["id"]] = alloc
    return success(public(alloc), 201)


@bp.route("/shop/allocations/<aid>", methods=["GET"])
def read_allocation(aid):
    authenticate({"Customer", "StoreClerk", "Manager"})
    alloc = lookup(db.db.allocations, aid)
    return success(public(alloc), 200)


@bp.route("/shop/products/<pid>/allocations", methods=["GET"])
def list_allocations(pid):
    authenticate({"Customer", "StoreClerk", "Manager"})
    lookup(db.db.products, pid)
    limit, offset = get_pagination()
    items = [a for a in db.db.allocations.values() if a["product_id"] == pid]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)
