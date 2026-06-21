"""ReorderRequest endpoints + replenishment lifecycle."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    conflict,
    ERR_REORDER_NOT_SUGGESTED,
    ERR_PART_DISCONTINUED,
    ERR_REORDER_NOT_RECEIVABLE,
    ERR_INVALID_RECEIVE_QTY,
    ERR_REORDER_NOT_CANCELLABLE,
)
from middleware import require_role, get_body
from response import success, list_success
from services import common as c
from services.model import (
    stamp_common,
    touch,
    serialize,
    get_part,
    get_reorder_request,
)
from services.inventory import increment_on_hand

bp = Blueprint("reorder_requests", __name__)

ALL_ROLES = ("CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin")


@bp.post("/reorder-requests")
def create_reorder_request():
    require_role("InventoryManager")
    body = get_body()
    part_id = c.as_nonempty_string(body, "part_id", required=True)
    part = get_part(part_id)
    ro = {
        "part_id": part_id,
        "qty_ordered": part["reorder_qty"],
        "qty_received": 0,
        "status": "SUGGESTED",
    }
    stamp_common(ro)
    db.reorder_requests[ro["id"]] = ro
    return success(serialize(ro), 201)


@bp.get("/reorder-requests")
def list_reorder_requests():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    part_id = request.args.get("part_id")
    status = request.args.get("status")
    filters = []
    if part_id is not None:
        filters.append(lambda r: r["part_id"] == part_id)
    if status is not None:
        filters.append(lambda r: r["status"] == status)
    page, total = c.paginate(db.reorder_requests.values(), limit, offset, filters)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.get("/reorder-requests/<rid>")
def get_one_reorder_request(rid):
    require_role(*ALL_ROLES)
    return success(serialize(get_reorder_request(rid)))


@bp.post("/reorder-requests/<rid>/place")
def place_reorder(rid):
    require_role("InventoryManager")
    ro = get_reorder_request(rid)
    if ro["status"] != "SUGGESTED":
        raise conflict(ERR_REORDER_NOT_SUGGESTED)
    part = get_part(ro["part_id"])
    if part["status"] != "ACTIVE":
        raise conflict(ERR_PART_DISCONTINUED)
    ro["status"] = "ORDERED"
    touch(ro)
    return success(serialize(ro))


@bp.post("/reorder-requests/<rid>/receive")
def receive_reorder(rid):
    require_role("InventoryManager")
    ro = get_reorder_request(rid)
    body = get_body()
    receive_qty = c.as_int(body, "receive_qty", required=True)

    # state precondition: must be ORDERED or PARTIALLY_RECEIVED
    if ro["status"] not in ("ORDERED", "PARTIALLY_RECEIVED"):
        raise conflict(ERR_REORDER_NOT_RECEIVABLE)
    # qty precondition: receive_qty >= 1 and running total <= qty_ordered
    if receive_qty < 1 or (ro["qty_received"] + receive_qty) > ro["qty_ordered"]:
        raise conflict(ERR_INVALID_RECEIVE_QTY)

    part = get_part(ro["part_id"])
    increment_on_hand(part, receive_qty)
    ro["qty_received"] += receive_qty
    if ro["qty_received"] == ro["qty_ordered"]:
        ro["status"] = "RECEIVED"
    else:
        ro["status"] = "PARTIALLY_RECEIVED"
    touch(ro)
    return success(serialize(ro))


@bp.post("/reorder-requests/<rid>/cancel")
def cancel_reorder(rid):
    require_role("InventoryManager")
    ro = get_reorder_request(rid)
    if ro["status"] not in ("SUGGESTED", "ORDERED"):
        raise conflict(ERR_REORDER_NOT_CANCELLABLE)
    ro["status"] = "CANCELLED"
    touch(ro)
    return success(serialize(ro))
