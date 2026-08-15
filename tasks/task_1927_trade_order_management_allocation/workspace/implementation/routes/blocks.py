"""Blocks: assembly, routing, fills (PRD §3.5-3.6)."""
from flask import Blueprint, request

import audit
import db
import services as svc
from errors import raise_err
from middleware import (ALL_ROLES, body, paged, pagination, require_enum,
                        require_roles)
from response import no_content, ok_list, ok_object
from util import is_int, parse_dt, public

bp = Blueprint("blocks", __name__)

BLOCK_SIDES = ("BUY", "SELL")


@bp.post("/trading/blocks")
@require_roles("Trader")
def create_block():
    b = body()
    security_id = b.get("security_id")
    if not isinstance(security_id, str) or not security_id:
        raise_err("ERR_INVALID_REQUEST", "Field 'security_id' is required")
    side = require_enum(b, "side", BLOCK_SIDES)
    svc.fetch("securities", security_id, "ERR_SECURITY_NOT_FOUND")
    rec = svc.new_record()
    rec.update({"security_id": security_id, "side": side, "broker_id": None,
                "total_qty": 0, "filled_qty": 0, "avg_fill_price_cents": None,
                "routed_at": None, "allocated_through_seq": 0,
                "status": "OPEN", "allocation_status": "UNALLOCATED"})
    db.store["blocks"][rec["id"]] = rec
    audit.record_request("BlockOrder", rec["id"], "BLOCK_CREATED",
                         f"security_id: {security_id}; side: {side}")
    return ok_object(public(rec), 201)


@bp.get("/trading/blocks/<blockId>")
@require_roles(*ALL_ROLES)
def get_block(blockId):
    return ok_object(public(svc.fetch("blocks", blockId, "ERR_BLOCK_NOT_FOUND")))


@bp.get("/trading/blocks")
@require_roles(*ALL_ROLES)
def list_blocks():
    limit, offset = pagination()
    items = sorted(db.store["blocks"].values(), key=lambda r: r["_seq"])
    for param in ("security_id", "broker_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [x for x in items if x[param] == v]
    page, total = paged(items, limit, offset)
    return ok_list([public(x) for x in page], total, limit, offset)


@bp.post("/trading/blocks/<blockId>/orders")
@require_roles("Trader")
def attach_order(blockId):
    b = body()
    order_id = b.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise_err("ERR_INVALID_REQUEST", "Field 'order_id' is required")
    block = svc.fetch("blocks", blockId, "ERR_BLOCK_NOT_FOUND")
    order = svc.fetch("orders", order_id, "ERR_ORDER_NOT_FOUND")
    if block["status"] != "OPEN":
        raise_err("ERR_BLOCK_NOT_OPEN", "Block is not OPEN")
    if order["block_id"] is not None:
        raise_err("ERR_ORDER_ALREADY_BLOCKED", "Order is already attached to a block")
    if order["status"] != "APPROVED":
        raise_err("ERR_ORDER_NOT_APPROVED", f"Order is {order['status']}, not APPROVED")
    if order["security_id"] != block["security_id"]:
        raise_err("ERR_BLOCK_SECURITY_MISMATCH", "Order security differs from block security")
    if order["side"] != block["side"]:
        raise_err("ERR_BLOCK_SIDE_MISMATCH", "Order side differs from block side")
    order["block_id"] = block["id"]
    order["status"] = "BLOCKED"
    svc.touch(order)
    block["total_qty"] += order["order_qty"]
    svc.touch(block)
    audit.record_request("Order", order["id"], "ORDER_ATTACHED",
                         f"status: APPROVED -> BLOCKED; block_id: {block['id']}")
    return ok_object(public(order))


@bp.delete("/trading/blocks/<blockId>/orders/<orderId>")
@require_roles("Trader")
def detach_order(blockId, orderId):
    block = svc.fetch("blocks", blockId, "ERR_BLOCK_NOT_FOUND")
    order = svc.fetch("orders", orderId, "ERR_ORDER_NOT_FOUND")
    if block["status"] != "OPEN":
        raise_err("ERR_BLOCK_NOT_OPEN", "Block is not OPEN")
    if order["block_id"] != block["id"]:
        raise_err("ERR_ORDER_NOT_IN_BLOCK", "Order is not attached to this block")
    order["block_id"] = None
    order["status"] = "APPROVED"
    svc.touch(order)
    block["total_qty"] -= order["order_qty"]
    svc.touch(block)
    audit.record_request("Order", order["id"], "ORDER_DETACHED",
                         "status: BLOCKED -> APPROVED; block_id cleared")
    return no_content()


@bp.post("/trading/blocks/<blockId>/cancel")
@require_roles("Trader")
def cancel_block(blockId):
    block = svc.fetch("blocks", blockId, "ERR_BLOCK_NOT_FOUND")
    if block["status"] != "OPEN":
        raise_err("ERR_BLOCK_NOT_OPEN", "Block is not OPEN")
    for order in svc.block_members(block["id"]):
        order["block_id"] = None
        order["status"] = "APPROVED"
        svc.touch(order)
    block["status"] = "CANCELLED"
    svc.touch(block)
    audit.record_request("BlockOrder", block["id"], "BLOCK_CANCELLED",
                         "status: OPEN -> CANCELLED; member orders returned to APPROVED")
    return ok_object(public(block))


@bp.post("/trading/blocks/<blockId>/route")
@require_roles("Trader")
def route_block(blockId):
    b = body()
    broker_id = b.get("broker_id")
    if not isinstance(broker_id, str) or not broker_id:
        raise_err("ERR_INVALID_REQUEST", "Field 'broker_id' is required")
    block = svc.fetch("blocks", blockId, "ERR_BLOCK_NOT_FOUND")
    broker = svc.fetch("brokers", broker_id, "ERR_BROKER_NOT_FOUND")
    if block["status"] != "OPEN":
        raise_err("ERR_BLOCK_NOT_OPEN", "Block is not OPEN")
    security = db.store["securities"][block["security_id"]]
    if security["status"] != "ACTIVE":
        raise_err("ERR_SECURITY_HALTED", "Security is not ACTIVE")
    if broker["status"] != "ACTIVE":
        raise_err("ERR_BROKER_SUSPENDED", "Broker is not ACTIVE")
    if security["asset_class"] not in broker["supported_asset_classes"]:
        raise_err("ERR_BROKER_ASSET_CLASS_UNSUPPORTED",
                  "Broker does not support this asset class")
    if block["total_qty"] <= 0:
        raise_err("ERR_EMPTY_BLOCK", "Block has no member orders")
    block["broker_id"] = broker_id
    block["routed_at"] = db.clock_raw()
    block["status"] = "WORKING"
    svc.touch(block)
    audit.record_request("BlockOrder", block["id"], "BLOCK_ROUTED",
                         f"status: OPEN -> WORKING; broker_id: {broker_id}; "
                         f"routed_at: {block['routed_at']}")
    return ok_object(public(block))


@bp.post("/trading/blocks/<blockId>/fills")
@require_roles("ExecutionDesk")
def record_fill(blockId):
    b = body()
    qty = b.get("fill_qty")
    price = b.get("fill_price_cents")
    executed_raw = b.get("executed_at")
    if not is_int(qty) or qty <= 0:
        raise_err("ERR_INVALID_REQUEST", "Field 'fill_qty' must be a positive integer")
    if not is_int(price) or price <= 0:
        raise_err("ERR_INVALID_REQUEST", "Field 'fill_price_cents' must be a positive integer")
    executed_dt = parse_dt(executed_raw)
    if executed_dt is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'executed_at' must be an ISO 8601 datetime")
    block = svc.fetch("blocks", blockId, "ERR_BLOCK_NOT_FOUND")
    if block["status"] not in ("WORKING", "PARTIALLY_FILLED"):
        raise_err("ERR_INVALID_STATE", f"Cannot record fills on a block in {block['status']}")
    security = db.store["securities"][block["security_id"]]
    if security["status"] != "ACTIVE":
        raise_err("ERR_SECURITY_HALTED", "Security is not ACTIVE")
    if block["filled_qty"] + qty > block["total_qty"]:
        raise_err("ERR_OVERFILL", "fill_qty would exceed the block's remaining quantity")
    routed_dt = parse_dt(block["routed_at"])
    if executed_dt < routed_dt:
        raise_err("ERR_FILL_BEFORE_ROUTE", "Fill executed_at precedes block routed_at")
    fills = svc.block_fills(block["id"])
    fill = svc.new_record(common=False)  # fills carry only id + created_at
    fill.update({"block_id": block["id"], "fill_qty": qty, "fill_price_cents": price,
                 "executed_at": executed_raw,
                 "fill_seq": (fills[-1]["fill_seq"] + 1) if fills else 1,
                 "gross_amount_cents": qty * price})
    db.store["fills"][fill["id"]] = fill
    svc.recompute_block_fill_stats(block)
    completed = block["filled_qty"] == block["total_qty"]
    frm = block["status"]
    block["status"] = "FILLED" if completed else "PARTIALLY_FILLED"
    svc.touch(block)
    audit.record_request("Fill", fill["id"], "FILL_RECORDED",
                         f"block_id: {block['id']}; fill_seq: {fill['fill_seq']}; "
                         f"fill_qty: {qty}; fill_price_cents: {price}; "
                         f"block status: {frm} -> {block['status']}")
    if completed:
        audit.record_request("BlockOrder", block["id"], "BLOCK_FILLED",
                             f"status: {frm} -> FILLED; filled_qty: {block['filled_qty']}")
    if block["allocation_status"] == "FULL":
        block["allocation_status"] = "PARTIAL"
        svc.touch(block)
    return ok_object(public(fill), 201)


@bp.get("/trading/blocks/<blockId>/fills")
@require_roles(*ALL_ROLES)
def list_fills(blockId):
    svc.fetch("blocks", blockId, "ERR_BLOCK_NOT_FOUND")
    limit, offset = pagination()
    items = svc.block_fills(blockId)  # fill_seq ASC — the one non-default ordering
    page, total = paged(items, limit, offset)
    return ok_list([public(f) for f in page], total, limit, offset)
