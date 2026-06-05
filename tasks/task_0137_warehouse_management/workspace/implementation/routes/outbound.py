"""Outbound orders, order lines, manual allocations (PRD §3.6, §3.9)."""
from flask import Blueprint, request

from common import (
    new_record, touch, serialize, get_json_body, require_str, require_int,
    optional_int, paginate, lookup, lookup_fk,
)
from db import store
from errors import err
from middleware import get_identity, require_roles
from response import success, list_success
import calc
import services

bp = Blueprint("outbound", __name__)


# ---------------------------------------------------------------------------
# OutboundOrder
# ---------------------------------------------------------------------------
@bp.route("/warehouse/outbound-orders", methods=["POST"])
def create_order():
    _, role = get_identity()
    require_roles(role, ["WavePlanner"])
    body = get_json_body()
    order_number = require_str(body, "order_number")
    priority = optional_int(body, "priority", 5, minimum=1)
    if any(o["order_number"] == order_number for o in store.outbound_orders.values()):
        raise err("ERR_DUPLICATE_CODE", "order_number already exists.")
    rec = new_record()
    rec.update({
        "order_number": order_number,
        "priority": priority,
        "wave_id": None,
        "status": "OPEN",
    })
    store.outbound_orders[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.route("/warehouse/outbound-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    get_identity()
    rec = lookup(store.outbound_orders, order_id)
    return success(serialize(rec))


@bp.route("/warehouse/outbound-orders", methods=["GET"])
def list_orders():
    get_identity()
    items = list(store.outbound_orders.values())
    wave_id = request.args.get("wave_id")
    status = request.args.get("status")
    if wave_id:
        items = [o for o in items if o["wave_id"] == wave_id]
    if status:
        items = [o for o in items if o["status"] == status]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/outbound-orders/<order_id>/lines", methods=["POST"])
def add_order_line(order_id):
    _, role = get_identity()
    require_roles(role, ["WavePlanner"])
    order = lookup(store.outbound_orders, order_id)
    body = get_json_body()
    sku_id = require_str(body, "sku_id")
    sku = lookup_fk(store.skus, sku_id, "sku_id")
    ordered_qty = require_int(body, "ordered_qty", exclusive_min=0)
    if order["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Lines may only be added while the order is OPEN.")
    rec = new_record()
    rec.update({
        "order_id": order_id,
        "sku_id": sku["id"],
        "ordered_qty": ordered_qty,
        "allocated_qty": 0,
        "picked_qty": 0,
    })
    store.order_lines[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.route("/warehouse/outbound-orders/<order_id>/lines", methods=["GET"])
def list_order_lines_of_order(order_id):
    get_identity()
    lookup(store.outbound_orders, order_id)
    items = [l for l in store.order_lines.values() if l["order_id"] == order_id]
    for l in items:
        calc.refresh_order_line(l)
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/order-lines/<line_id>", methods=["GET"])
def get_order_line(line_id):
    get_identity()
    rec = lookup(store.order_lines, line_id)
    calc.refresh_order_line(rec)
    return success(serialize(rec))


@bp.route("/warehouse/order-lines", methods=["GET"])
def list_order_lines():
    get_identity()
    items = list(store.order_lines.values())
    order_id = request.args.get("order_id")
    sku_id = request.args.get("sku_id")
    if order_id:
        items = [l for l in items if l["order_id"] == order_id]
    if sku_id:
        items = [l for l in items if l["sku_id"] == sku_id]
    for l in items:
        calc.refresh_order_line(l)
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/outbound-orders/<order_id>/ship", methods=["POST"])
def ship_order(order_id):
    _, role = get_identity()
    require_roles(role, ["Picker"])
    order = lookup(store.outbound_orders, order_id)
    if order["status"] != "PICKED":
        raise err("ERR_INVALID_STATE", "Order is not PICKED.")
    affected_skus = set()
    # drive each PICKED_STAGED LPN behind COMMITTED allocations -> SHIPPED
    committed = [
        a for a in store.allocations.values()
        if a["order_line_id"] in {l["id"] for l in store.order_lines.values()
                                  if l["order_id"] == order_id}
        and a["status"] == "COMMITTED"
    ]
    for a in committed:
        lpn = store.license_plates.get(a["lpn_id"])
        if lpn is not None and lpn["disposition"] == "PICKED_STAGED":
            lpn["qty"] = 0
            lpn["disposition"] = "SHIPPED"
            touch(lpn)
            affected_skus.add(lpn["sku_id"])
    for sku_id in affected_skus:
        calc.refresh_sku(store.skus[sku_id])
    order["status"] = "SHIPPED"
    touch(order)
    return success(serialize(order))


@bp.route("/warehouse/outbound-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    _, role = get_identity()
    require_roles(role, ["WavePlanner"])
    order = lookup(store.outbound_orders, order_id)
    if order["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only an OPEN (not yet waved) order may be cancelled.")
    order["status"] = "CANCELLED"
    touch(order)
    return success(serialize(order))


# ---------------------------------------------------------------------------
# InventoryAllocation (manual reservation)
# ---------------------------------------------------------------------------
@bp.route("/warehouse/allocations", methods=["POST"])
def create_allocation():
    _, role = get_identity()
    require_roles(role, ["WavePlanner"])
    body = get_json_body()
    order_line_id = require_str(body, "order_line_id")
    line = lookup_fk(store.order_lines, order_line_id, "order_line_id")
    lpn_id = require_str(body, "lpn_id")
    lpn = lookup_fk(store.license_plates, lpn_id, "lpn_id")
    allocated_qty = require_int(body, "allocated_qty", exclusive_min=0)
    expected_lpn_version = require_int(body, "expected_lpn_version")
    # OCC (priority 6) — after existence + body validity, before business safety
    if expected_lpn_version != lpn["version"]:
        raise err("ERR_STALE_LPN_VERSION", "expected_lpn_version does not match the LPN version.")
    # availability (priority 13): not more than LPN free qty, not more than SKU available
    free = calc.lpn_free(lpn)
    if allocated_qty > free:
        raise err("ERR_INSUFFICIENT_AVAILABLE", "Allocation exceeds the LPN's free quantity.")
    sku = store.skus.get(lpn["sku_id"])
    if allocated_qty > calc.sku_available(sku["id"]):
        raise err("ERR_INSUFFICIENT_AVAILABLE", "Allocation exceeds the SKU's available quantity.")
    rec = new_record()
    rec.update({
        "order_line_id": order_line_id,
        "lpn_id": lpn_id,
        "allocated_qty": allocated_qty,
        "status": "RESERVED",
    })
    store.allocations[rec["id"]] = rec
    calc.refresh_order_line(line)
    # On a successful create the plate's version is incremented (PRD §3.6, and the
    # global rule that version bumps on every mutation that changes the resource).
    # If the reservation now fully reserves the plate, the STORED -> ALLOCATED flip
    # is that single mutating change; otherwise the create still bumps the version
    # exactly once.
    disposition_before = lpn["disposition"]
    services.maybe_flip_lpn_on_reserve(lpn)
    if lpn["disposition"] == disposition_before:
        touch(lpn)
    calc.refresh_sku(sku)
    return success(serialize(rec), status=201)


@bp.route("/warehouse/allocations/<alloc_id>", methods=["GET"])
def get_allocation(alloc_id):
    get_identity()
    rec = lookup(store.allocations, alloc_id)
    return success(serialize(rec))


@bp.route("/warehouse/allocations", methods=["GET"])
def list_allocations():
    get_identity()
    items = list(store.allocations.values())
    order_line_id = request.args.get("order_line_id")
    lpn_id = request.args.get("lpn_id")
    status = request.args.get("status")
    if order_line_id:
        items = [a for a in items if a["order_line_id"] == order_line_id]
    if lpn_id:
        items = [a for a in items if a["lpn_id"] == lpn_id]
    if status:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/allocations/<alloc_id>/cancel", methods=["POST"])
def cancel_allocation(alloc_id):
    _, role = get_identity()
    require_roles(role, ["WavePlanner"])
    alloc = lookup(store.allocations, alloc_id)
    if alloc["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Only a RESERVED allocation may be released.")
    services.release_allocation(alloc)
    lpn = store.license_plates.get(alloc["lpn_id"])
    if lpn is not None:
        sku = store.skus.get(lpn["sku_id"])
        if sku is not None:
            calc.refresh_sku(sku)
    return success(serialize(alloc))
