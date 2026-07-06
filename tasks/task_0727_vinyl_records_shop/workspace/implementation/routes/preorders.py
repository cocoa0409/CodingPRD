"""PreOrder endpoints (allocation reservations, OCC, waitlist, pickup)."""
from flask import Blueprint, request

import db
from models import base_fields, touch
from middleware import authenticate
from validators import (
    get_body, require_int, get_pagination, paginate, sorted_by_created, lookup,
)
from response import success, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
    ERR_DEPENDENCY_NOT_READY, ERR_PREORDER_WINDOW_CLOSED,
    ERR_PICKUP_CAPACITY_EXCEEDED, ERR_ALLOCATION_EXHAUSTED, ERR_STALE_VERSION,
)
from services import public, public_list, promote_waitlist

bp = Blueprint("preorders", __name__)


def _owner_check(role, user_id, customer_id):
    if role == "Customer" and user_id != customer_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Customer does not own this resource")


def _intervals_overlap(s1, e1, s2, e2):
    # half-open [s, e): overlap iff s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


@bp.route("/shop/pre-orders", methods=["POST"])
def create_preorder():
    user_id, role = authenticate({"Customer"})
    body = get_body()
    customer_id = body.get("customer_id")
    product_id = body.get("product_id")
    allocation_id = body.get("allocation_id")
    for f in ("customer_id", "product_id", "allocation_id",
              "pickup_window_start", "pickup_window_end", "expected_allocation_version"):
        if body.get(f) is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)
    expected_version = require_int(body, "expected_allocation_version")
    # existence (left-to-right: customer, product, allocation)
    lookup(db.db.customers, customer_id)
    lookup(db.db.products, product_id)
    alloc = lookup(db.db.allocations, allocation_id)
    _owner_check(role, user_id, customer_id)
    pstart = body["pickup_window_start"]
    pend = body["pickup_window_end"]

    # PRE_ORDER_OPEN -> PRE_ORDER_CLOSED system transition when clock past close.
    product = db.db.products[product_id]
    close_at = db.parse_iso(alloc["window_close_at"])
    open_at = db.parse_iso(alloc["window_open_at"])
    now = db.db.now
    if now >= close_at and product["catalog_status"] == "PRE_ORDER_OPEN":
        product["catalog_status"] = "PRE_ORDER_CLOSED"
        touch(product)

    # business_temporal: window half-open [open, close)
    within_window = open_at <= now < close_at

    # OCC version check (priority 13, evaluated after window/exhaustion per scaffold
    # ordering; but scaffold lists window(7), exhaustion(11), version(13)).
    if not within_window:
        raise err(ERR_PREORDER_WINDOW_CLOSED, "Pre-order window is closed")

    # exhaustion check: available_count < 1 => waitlist (window open) else exhausted
    exhausted = alloc["available_count"] < 1

    # OCC (priority 13) after the above business gates
    if expected_version != alloc["version"]:
        raise err(ERR_STALE_VERSION, "expected_allocation_version is stale")

    po = base_fields()
    po.update({
        "customer_id": customer_id,
        "product_id": product_id,
        "allocation_id": allocation_id,
        "status": "RESERVED",
        "pickup_window_start": pstart,
        "pickup_window_end": pend,
        "fulfilled_item_id": None,
    })
    if exhausted:
        po["status"] = "WAITLISTED"
    else:
        alloc["available_count"] -= 1
        alloc["reserved_count"] += 1
    db.db.pre_orders[po["id"]] = po
    # every create increments allocation version by one
    touch(alloc)
    return success(public(po), 201)


@bp.route("/shop/pre-orders/<pid>", methods=["GET"])
def read_preorder(pid):
    authenticate({"Customer", "StoreClerk", "Manager"})
    po = lookup(db.db.pre_orders, pid)
    return success(public(po), 200)


@bp.route("/shop/pre-orders", methods=["GET"])
def list_preorders():
    authenticate({"Customer", "StoreClerk", "Manager"})
    limit, offset = get_pagination()
    items = list(db.db.pre_orders.values())
    for key in ("customer_id", "product_id", "allocation_id", "fulfilled_item_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)


@bp.route("/shop/pre-orders/<pid>/ready", methods=["POST"])
def ready_preorder(pid):
    authenticate({"StoreClerk"})
    po = lookup(db.db.pre_orders, pid)
    if po["status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Pre-order is not RESERVED")
    product = db.db.products[po["product_id"]]
    # cross-entity guard: product catalog_status must permit (PRE_ORDER_OPEN/CLOSED)
    if product["catalog_status"] not in ("PRE_ORDER_OPEN", "PRE_ORDER_CLOSED"):
        raise err(ERR_DEPENDENCY_NOT_READY, "Product does not permit readying")
    # an AVAILABLE InventoryItem must exist for the product
    avail = [
        i for i in db.db.inventory_items.values()
        if i["product_id"] == po["product_id"] and i["status"] == "AVAILABLE"
    ]
    if not avail:
        raise err(ERR_DEPENDENCY_NOT_READY, "No available copy for the product")
    # pickup capacity: count READY_FOR_PICKUP pre-orders on same allocation whose
    # half-open pickup interval overlaps this one.
    ns = db.parse_iso(po["pickup_window_start"])
    ne = db.parse_iso(po["pickup_window_end"])
    overlap = 0
    for other in db.db.pre_orders.values():
        if other["id"] == po["id"]:
            continue
        if other["allocation_id"] != po["allocation_id"]:
            continue
        if other["status"] != "READY_FOR_PICKUP":
            continue
        os = db.parse_iso(other["pickup_window_start"])
        oe = db.parse_iso(other["pickup_window_end"])
        if _intervals_overlap(ns, ne, os, oe):
            overlap += 1
    alloc = db.db.allocations[po["allocation_id"]]
    if overlap >= alloc["pickup_concurrency"]:
        raise err(ERR_PICKUP_CAPACITY_EXCEEDED, "Pickup capacity exceeded")
    # select earliest-created AVAILABLE item
    avail.sort(key=lambda x: (x["created_at"], x["id"]))
    item = avail[0]
    po["fulfilled_item_id"] = item["id"]
    po["status"] = "READY_FOR_PICKUP"
    item["status"] = "RESERVED"
    item["hold_start_at"] = po["pickup_window_start"]
    item["hold_end_at"] = po["pickup_window_end"]
    touch(item)
    touch(po)
    return success(public(po), 200)


@bp.route("/shop/pre-orders/<pid>/fulfill", methods=["POST"])
def fulfill_preorder(pid):
    authenticate({"StoreClerk"})
    po = lookup(db.db.pre_orders, pid)
    ready = po["status"] == "READY_FOR_PICKUP"
    reserved_held = po["status"] == "RESERVED" and po["fulfilled_item_id"] is not None
    if not (ready or reserved_held):
        raise err(ERR_INVALID_STATE, "Pre-order is not ready to fulfill")
    item = db.db.inventory_items.get(po["fulfilled_item_id"])
    if item is not None:
        item["status"] = "SOLD"
        touch(item)
    alloc = db.db.allocations[po["allocation_id"]]
    alloc["reserved_count"] -= 1
    alloc["committed_count"] += 1
    touch(alloc)
    po["status"] = "FULFILLED"
    touch(po)
    return success(public(po), 200)


@bp.route("/shop/pre-orders/<pid>/cancel", methods=["POST"])
def cancel_preorder(pid):
    user_id, role = authenticate({"Customer"})
    po = lookup(db.db.pre_orders, pid)
    _owner_check(role, user_id, po["customer_id"])
    if po["status"] == "FULFILLED":
        raise err(ERR_INVALID_STATE, "Pre-order is FULFILLED")
    if po["status"] == "CANCELLED":
        raise err(ERR_INVALID_STATE, "Pre-order already cancelled")
    alloc = db.db.allocations[po["allocation_id"]]
    if po["status"] == "WAITLISTED":
        po["status"] = "CANCELLED"
        touch(po)
        return success(public(po), 200)
    # RESERVED or READY_FOR_PICKUP: release the held unit
    if po["status"] == "READY_FOR_PICKUP" and po["fulfilled_item_id"]:
        item = db.db.inventory_items.get(po["fulfilled_item_id"])
        if item is not None and item["status"] == "RESERVED":
            item["status"] = "AVAILABLE"
            item["hold_start_at"] = None
            item["hold_end_at"] = None
            touch(item)
    alloc["available_count"] += 1
    alloc["reserved_count"] -= 1
    po["status"] = "CANCELLED"
    touch(po)
    touch(alloc)
    promote_waitlist(alloc)
    return success(public(po), 200)
