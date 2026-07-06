"""Consignment + DisplaySlot endpoints."""
from datetime import timedelta
from flask import Blueprint, request

import db
from models import base_fields, touch
from middleware import authenticate
from validators import (
    get_body, require_string, require_int, require_grade, get_pagination,
    paginate, sorted_by_created, lookup,
)
from response import success, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SLOT_INACTIVE, ERR_SLOT_OVERLAP,
)
from services import public, public_list, compute_item_price, sweep_consignment
from routes.inventory import make_inventory_item
import calculations as calc

bp = Blueprint("consignments", __name__)

CONSIGNMENT_BUFFER_DAYS = 2


def _linked_item(cons):
    for it in db.db.inventory_items.values():
        if it.get("consignment_id") == cons["id"]:
            return it
    return None


# ---- Display slots ---------------------------------------------------------
@bp.route("/shop/display-slots", methods=["POST"])
def create_display_slot():
    authenticate({"Manager"})
    body = get_body()
    label = require_string(body, "slot_label")
    for s in db.db.display_slots.values():
        if s["slot_label"] == label:
            raise err(ERR_INVALID_REQUEST, "slot_label must be unique")
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        raise err(ERR_INVALID_REQUEST, "is_active must be boolean")
    slot = base_fields()
    slot.update({"slot_label": label, "is_active": is_active})
    db.db.display_slots[slot["id"]] = slot
    return success(public(slot), 201)


@bp.route("/shop/display-slots/<sid>", methods=["GET"])
def read_display_slot(sid):
    authenticate({"StoreClerk", "Manager"})
    slot = lookup(db.db.display_slots, sid)
    return success(public(slot), 200)


# ---- Consignments ----------------------------------------------------------
@bp.route("/shop/consignments", methods=["POST"])
def create_consignment():
    authenticate({"StoreClerk", "Manager"})
    body = get_body()
    consignor_id = body.get("consignor_id")
    if not isinstance(consignor_id, str) or not consignor_id:
        raise err(ERR_INVALID_REQUEST, "consignor_id required")
    list_price = require_int(body, "list_price_cents")
    if list_price <= 0:
        raise err(ERR_INVALID_REQUEST, "list_price_cents must be > 0")
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise err(ERR_INVALID_REQUEST, "product_id required")
    grade = require_grade(body, "condition_grade")
    display_slot_id = body.get("display_slot_id")
    display_start = body.get("display_start")
    display_end = body.get("display_end")
    # existence
    lookup(db.db.customers, consignor_id)
    lookup(db.db.products, product_id)
    if display_slot_id is not None:
        lookup(db.db.display_slots, display_slot_id)
    cons = base_fields()
    cons.update({
        "consignor_id": consignor_id,
        "display_slot_id": display_slot_id,
        "list_price_cents": list_price,
        "sale_price_cents": None,
        "status": "DRAFT",
        "display_start": display_start,
        "display_end": display_end,
        "estimated_payout_cents": 0,
        "actual_payout_cents": 0,
    })
    db.db.consignments[cons["id"]] = cons
    # create linked used InventoryItem (consignment_id set) AVAILABLE
    make_inventory_item(product_id, True, grade, cons["id"])
    return success(public(cons), 201)


@bp.route("/shop/consignments/<cid>", methods=["GET"])
def read_consignment(cid):
    authenticate({"Customer", "StoreClerk", "Manager"})
    cons = lookup(db.db.consignments, cid)
    sweep_consignment(cons)
    return success(public(cons), 200)


@bp.route("/shop/consignments", methods=["GET"])
def list_consignments():
    authenticate({"Customer", "StoreClerk", "Manager"})
    limit, offset = get_pagination()
    consignor_id = request.args.get("consignor_id")
    display_slot_id = request.args.get("display_slot_id")
    status = request.args.get("status")
    # sweep before filtering so expiry reflects on read
    for cons in list(db.db.consignments.values()):
        sweep_consignment(cons)
    items = list(db.db.consignments.values())
    if consignor_id is not None:
        items = [c for c in items if c["consignor_id"] == consignor_id]
    if display_slot_id is not None:
        items = [c for c in items if c.get("display_slot_id") == display_slot_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)


@bp.route("/shop/consignments/<cid>/activate", methods=["POST"])
def activate_consignment(cid):
    authenticate({"Manager"})
    cons = lookup(db.db.consignments, cid)
    if cons["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Consignment is not DRAFT")
    slot_id = cons.get("display_slot_id")
    if slot_id is not None:
        slot = db.db.display_slots.get(slot_id)
        if slot is None:
            raise err(ERR_INVALID_STATE, "Display slot missing")
        if not slot["is_active"]:
            raise err(ERR_SLOT_INACTIVE, "Display slot is retired")
    # overlap check: buffered closed-interval against ACTIVE consignments on same slot
    if slot_id is not None and cons.get("display_start") is not None and cons.get("display_end") is not None:
        ns = db.parse_iso(cons["display_start"])
        ne = db.parse_iso(cons["display_end"])
        buf = timedelta(days=CONSIGNMENT_BUFFER_DAYS)
        for other in db.db.consignments.values():
            if other["id"] == cid:
                continue
            if other["status"] != "ACTIVE":
                continue
            if other.get("display_slot_id") != slot_id:
                continue
            if other.get("display_start") is None or other.get("display_end") is None:
                continue
            os_ = db.parse_iso(other["display_start"]) - buf
            oe_ = db.parse_iso(other["display_end"]) + buf
            # closed intervals overlap iff ns <= oe_ and os_ <= ne
            if ns <= oe_ and os_ <= ne:
                raise err(ERR_SLOT_OVERLAP, "Display booking overlaps another active consignment")
    cons["status"] = "ACTIVE"
    cons["estimated_payout_cents"] = calc.consignment_payout(cons["list_price_cents"])
    item = _linked_item(cons)
    if item is not None and item["status"] == "AVAILABLE":
        item["status"] = "ON_DISPLAY"
        touch(item)
    touch(cons)
    return success(public(cons), 200)


@bp.route("/shop/consignments/<cid>/markdown", methods=["POST"])
def markdown_consignment(cid):
    authenticate({"Manager"})
    cons = lookup(db.db.consignments, cid)
    if cons["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Consignment is not ACTIVE")
    body = get_body()
    new_price = require_int(body, "new_list_price_cents")
    if new_price <= 0:
        raise err(ERR_INVALID_REQUEST, "new_list_price_cents must be > 0")
    cons["list_price_cents"] = new_price
    # estimated_payout NOT recomputed (pinned at ACTIVE)
    item = _linked_item(cons)
    if item is not None:
        item["list_price_cents"] = compute_item_price(item)
        touch(item)
    touch(cons)
    return success(public(cons), 200)


@bp.route("/shop/consignments/<cid>/withdraw", methods=["POST"])
def withdraw_consignment(cid):
    authenticate({"Manager"})
    cons = lookup(db.db.consignments, cid)
    if cons["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Consignment is not ACTIVE")
    item = _linked_item(cons)
    if item is not None and item["status"] == "SOLD":
        raise err(ERR_INVALID_STATE, "Linked copy is SOLD")
    cons["status"] = "WITHDRAWN"
    if item is not None:
        item["status"] = "AVAILABLE"
        item["hold_start_at"] = None
        item["hold_end_at"] = None
        touch(item)
    cons["display_slot_id"] = None
    touch(cons)
    return success(public(cons), 200)
