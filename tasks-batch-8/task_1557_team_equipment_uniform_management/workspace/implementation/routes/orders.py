"""Kit orders (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, clock, stamp, touch, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_CONTRACT_NOT_FOUND,
    ERR_POOL_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_GARMENT_NOT_COVERED_BY_CONTRACT,
    ERR_ALLOCATION_CAP_EXCEEDED,
    ERR_ORDER_NOT_OPEN,
    ERR_RECEIVE_EXCEEDS_OUTSTANDING,
)
from middleware import endpoint
from response import success
from routes.common import ALL_ROLES, render_list
from routes.pools import GARMENT_TYPES
from services.orders import OPEN_STATUSES, price_order, units_committed_map
from services.pools import reconcile_pool
from util import is_int, is_pct

bp = Blueprint("orders", __name__)

ORDER_STATUSES = {"SUBMITTED", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED"}
ORDER_SOURCES = {"MANUAL", "AUTO_REORDER"}


def find_pool(season_label, garment_type, size_code):
    for p in db.pools.values():
        if (
            p["season_label"] == season_label
            and p["garment_type"] == garment_type
            and p["size_code"] == size_code
        ):
            return p
    return None


def _validate_lines(lines):
    if not isinstance(lines, list) or not lines:
        return None
    out = []
    for line in lines:
        if not isinstance(line, dict):
            return None
        gt = line.get("garment_type")
        size = line.get("size_code")
        qty = line.get("quantity")
        price = line.get("unit_price_cents")
        discount = line.get("line_discount_pct", 0)
        if gt not in GARMENT_TYPES:
            return None
        if not isinstance(size, str) or not size:
            return None
        if not is_int(qty) or qty <= 0:
            return None
        if not is_int(price) or price < 0:
            return None
        if not is_pct(discount):
            return None
        out.append(
            {
                "garment_type": gt,
                "size_code": size,
                "quantity": qty,
                "unit_price_cents": price,
                "line_discount_pct": discount,
            }
        )
    return out


@bp.post("/kit-orders")
@endpoint("EquipmentManager")
def create_order(ctx):
    b = ctx.body
    contract_id = b.get("supplier_contract_id")
    if not isinstance(contract_id, str) or not contract_id:
        raise_err(ERR_INVALID_REQUEST, "supplier_contract_id is required")
    lines = _validate_lines(b.get("lines"))
    if lines is None:
        raise_err(ERR_INVALID_REQUEST, "lines invalid")
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_CONTRACT_NOT_FOUND, "contract not found")
    # Existence (rung 4): each line resolves to a pool of the contract's season
    for line in lines:
        if find_pool(contract["season_label"], line["garment_type"], line["size_code"]) is None:
            raise_err(ERR_POOL_NOT_FOUND, "no pool matches an order line")
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "contract is not ACTIVE")
    capped = {cap["garment_type"] for cap in contract["allocation_caps"]}
    for line in lines:
        if line["garment_type"] not in capped:
            raise_err(
                ERR_GARMENT_NOT_COVERED_BY_CONTRACT,
                "garment_type absent from contract allocation_caps",
            )
    committed = units_committed_map(contract)
    totals = {}
    for line in lines:
        totals[line["garment_type"]] = totals.get(line["garment_type"], 0) + line["quantity"]
    for gt, qty in totals.items():
        cap = next(
            c["max_units"] for c in contract["allocation_caps"] if c["garment_type"] == gt
        )
        if qty > cap - committed.get(gt, 0):
            raise_err(ERR_ALLOCATION_CAP_EXCEEDED, "order exceeds remaining allocation")
    subtotal, total = price_order(lines, contract["contract_rebate_pct"])
    order = stamp(
        {
            "supplier_contract_id": contract_id,
            "source": "MANUAL",
            "status": "SUBMITTED",
            "lines": lines,
            "received_lines": [],
            "expected_delivery_on": (
                clock().date() + timedelta(days=contract["default_lead_time_days"])
            ).isoformat(),
            "subtotal_cents": subtotal,
            "total_cents": total,
        }
    )
    db.orders[order["id"]] = order
    return success(serialize(order), 201)


@bp.get("/kit-orders")
@endpoint(*ALL_ROLES)
def list_orders(ctx):
    contract_id = request.args.get("supplier_contract_id")
    status = request.args.get("status")
    source = request.args.get("source")
    if status is not None and status not in ORDER_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "status filter is not a declared value")
    if source is not None and source not in ORDER_SOURCES:
        raise_err(ERR_INVALID_REQUEST, "source filter is not a declared value")
    return render_list(
        db.orders,
        {"supplier_contract_id": contract_id, "status": status, "source": source},
    )


@bp.get("/kit-orders/<order_id>")
@endpoint(*ALL_ROLES)
def get_order(ctx, order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise_err(ERR_ORDER_NOT_FOUND, "order not found")
    return success(serialize(order))


@bp.post("/kit-orders/<order_id>/receive")
@endpoint("EquipmentManager")
def receive_order(ctx, order_id):
    b = ctx.body
    received = b.get("received_lines")
    if not isinstance(received, list):
        raise_err(ERR_INVALID_REQUEST, "received_lines must be an array")
    cleaned = []
    for rl in received:
        if not isinstance(rl, dict):
            raise_err(ERR_INVALID_REQUEST, "received_lines entries invalid")
        gt = rl.get("garment_type")
        size = rl.get("size_code")
        qty = rl.get("received_quantity")
        if gt not in GARMENT_TYPES or not isinstance(size, str) or not size:
            raise_err(ERR_INVALID_REQUEST, "received_lines entries invalid")
        if not is_int(qty) or qty <= 0:
            raise_err(ERR_INVALID_REQUEST, "received_quantity must be an integer > 0")
        cleaned.append({"garment_type": gt, "size_code": size, "received_quantity": qty})
    order = db.orders.get(order_id)
    if order is None:
        raise_err(ERR_ORDER_NOT_FOUND, "order not found")
    if order["status"] not in OPEN_STATUSES:
        raise_err(ERR_ORDER_NOT_OPEN, "order is not open")

    # Validate ALL lines against outstanding before committing any (atomicity).
    received_so_far = {
        (rl["garment_type"], rl["size_code"]): rl["received_quantity"]
        for rl in order["received_lines"]
    }
    additions = {}
    for rl in cleaned:
        key = (rl["garment_type"], rl["size_code"])
        ordered_qty = sum(
            l["quantity"]
            for l in order["lines"]
            if (l["garment_type"], l["size_code"]) == key
        )
        new_total = received_so_far.get(key, 0) + additions.get(key, 0) + rl["received_quantity"]
        if new_total > ordered_qty:
            raise_err(
                ERR_RECEIVE_EXCEEDS_OUTSTANDING,
                "received quantity exceeds outstanding for a line",
            )
        additions[key] = additions.get(key, 0) + rl["received_quantity"]

    contract = db.contracts.get(order["supplier_contract_id"])
    touched = {}
    for (gt, size), qty in additions.items():
        pool = find_pool(contract["season_label"], gt, size) if contract else None
        if pool is not None:
            touched.setdefault(pool["id"], (pool, 0))
            touched[pool["id"]] = (pool, touched[pool["id"]][1] + qty)
    for key, qty in additions.items():
        received_so_far[key] = received_so_far.get(key, 0) + qty
    order["received_lines"] = [
        {"garment_type": gt, "size_code": size, "received_quantity": qty}
        for (gt, size), qty in received_so_far.items()
    ]
    for pool, qty in touched.values():
        prev = pool["available_quantity"]
        pool["stock_on_hand"] += qty
        reconcile_pool(pool, "increase", prev)

    fully = True
    for line in order["lines"]:
        key = (line["garment_type"], line["size_code"])
        ordered_qty = sum(
            l["quantity"]
            for l in order["lines"]
            if (l["garment_type"], l["size_code"]) == key
        )
        if received_so_far.get(key, 0) < ordered_qty:
            fully = False
            break
    order["status"] = "RECEIVED" if fully else "PARTIALLY_RECEIVED"
    touch(order)
    return success(serialize(order))


@bp.post("/kit-orders/<order_id>/cancel")
@endpoint("EquipmentManager")
def cancel_order(ctx, order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise_err(ERR_ORDER_NOT_FOUND, "order not found")
    if order["status"] not in OPEN_STATUSES:
        raise_err(ERR_ORDER_NOT_OPEN, "order is not open")
    # Outstanding quantities are released from committed units; committed units
    # are derived on read, so no stored contract mutation occurs here.
    order["status"] = "CANCELLED"
    touch(order)
    return success(serialize(order))
