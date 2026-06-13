"""Order / cart / order-line endpoints, checkout, capture, void (PRD §3.2-3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_ORDER_VERSION,
)
from middleware import require_roles, get_auth
from response import success
from services import serialize
from services.common import (
    parse_body, require_str, require_int, optional_int, paginate, lookup,
)
from services.calc import compute_order_totals

bp = Blueprint("orders", __name__)


def _order_lines_of(order_id):
    return [l for l in db.order_lines.values() if l["order_id"] == order_id]


@bp.route("/orders", methods=["POST"])
def create_order():
    user_id, role = require_roles(["Customer", "StoreAdmin"])
    body = parse_body()
    customer_id = require_str(body, "customer_id")
    promo = optional_int(body, "promo_flat_cents", 0)
    if promo < 0:
        raise err(ERR_VALIDATION, "promo_flat_cents must be >= 0")
    # existence of body FK
    lookup(db.customers, customer_id)
    rec = {
        "customer_id": customer_id,
        "payment_status": "CART",
        "fulfillment_status": "UNFULFILLED",
        "promo_flat_cents": promo,
        "subtotal_cents": 0,
        "discounted_subtotal_cents": 0,
        "tax_total_cents": 0,
        "shipping_fee_cents": 0,
        "grand_total_cents": 0,
        "captured_total_cents": 0,
    }
    db.stamp_create(rec)
    db.orders[rec["id"]] = rec
    return success(serialize.order(rec), status=201)


@bp.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    require_roles(["Customer", "StoreAdmin", "WarehouseOperator"])
    rec = lookup(db.orders, oid)
    return success(serialize.order(rec))


@bp.route("/orders/<oid>/lines", methods=["POST"])
def add_order_line(oid):
    user_id, role = require_roles(["Customer", "StoreAdmin"])
    order = lookup(db.orders, oid)
    # ownership (Customer only)
    if role == "Customer" and order["customer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "You do not own this order")
    body = parse_body()
    product_id = require_str(body, "product_id")
    qty = require_int(body, "qty")
    product = lookup(db.products, product_id)
    if qty < 1:
        raise err(ERR_VALIDATION, "qty must be >= 1")
    if order["payment_status"] != "CART":
        raise err(ERR_INVALID_STATE, "Lines can only be added to a CART order")
    rec = {
        "order_id": oid,
        "product_id": product_id,
        "qty": qty,
        "unit_price_cents_snapshot": product["unit_price_cents"],
        "tax_rate_bps_snapshot": product["tax_rate_bps"],
        "line_tax_cents": 0,
        "backordered_qty": 0,
    }
    db.stamp_create(rec)
    db.order_lines[rec["id"]] = rec
    # adding a line bumps the parent Order.version
    db.touch(order)
    return success(serialize.order_line(rec), status=201)


@bp.route("/orders/<oid>/lines", methods=["GET"])
def list_order_lines(oid):
    require_roles(["Customer", "StoreAdmin", "WarehouseOperator"])
    lookup(db.orders, oid)
    rows = _order_lines_of(oid)
    data, meta = paginate(rows, serialize.order_line)
    return success(data, pagination=meta)


@bp.route("/order-lines/<lid>", methods=["GET"])
def get_order_line(lid):
    require_roles(["Customer", "StoreAdmin", "WarehouseOperator"])
    rec = lookup(db.order_lines, lid)
    return success(serialize.order_line(rec))


@bp.route("/order-lines/<lid>/reservations", methods=["GET"])
def list_order_line_reservations(lid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    lookup(db.order_lines, lid)
    rows = [r for r in db.reservations.values() if r["order_line_id"] == lid]
    wid = request.args.get("warehouse_id")
    if wid is not None:
        rows = [r for r in rows if r["warehouse_id"] == wid]
    data, meta = paginate(rows, serialize.reservation)
    return success(data, pagination=meta)


@bp.route("/order-lines/<lid>/shipment-lines", methods=["GET"])
def list_order_line_shipment_lines(lid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    lookup(db.order_lines, lid)
    rows = [sl for sl in db.shipment_lines.values() if sl["order_line_id"] == lid]
    data, meta = paginate(rows, serialize.shipment_line)
    return success(data, pagination=meta)


@bp.route("/order-lines/<lid>/return-lines", methods=["GET"])
def list_order_line_return_lines(lid):
    require_roles(["Customer", "StoreAdmin"])
    lookup(db.order_lines, lid)
    rows = [rl for rl in db.return_lines.values() if rl["order_line_id"] == lid]
    data, meta = paginate(rows, serialize.return_line)
    return success(data, pagination=meta)


@bp.route("/orders/<oid>/checkout", methods=["POST"])
def checkout_order(oid):
    user_id, role = require_roles(["Customer"])
    order = lookup(db.orders, oid)
    # ownership
    if order["customer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "You do not own this order")
    body = parse_body()
    expected_version = require_int(body, "expected_order_version")
    lines = _order_lines_of(oid)
    # state: must be CART with >= 1 line
    if order["payment_status"] != "CART":
        raise err(ERR_INVALID_STATE, "Order is not in CART status")
    if len(lines) < 1:
        raise err(ERR_INVALID_STATE, "Order has no lines to check out")
    # OCC (priority after state per §2.9)
    if expected_version != order["version"]:
        raise err(ERR_STALE_ORDER_VERSION, "Order version is stale")

    # recompute totals
    totals = compute_order_totals(lines, order["promo_flat_cents"])
    order["subtotal_cents"] = totals["subtotal_cents"]
    order["discounted_subtotal_cents"] = totals["discounted_subtotal_cents"]
    order["tax_total_cents"] = totals["tax_total_cents"]
    order["shipping_fee_cents"] = totals["shipping_fee_cents"]
    order["grand_total_cents"] = totals["grand_total_cents"]
    for L in lines:
        L["line_tax_cents"] = totals["line_tax"][L["id"]]
        db.touch(L)

    # reservation waterfall per line
    any_backorder = False
    for L in lines:
        remaining = L["qty"]
        # candidates: inventory items for this product with available_qty > 0
        candidates = []
        for inv in db.inventory_items.values():
            if inv["product_id"] != L["product_id"]:
                continue
            reserved = sum(
                r["qty"] for r in db.reservations.values()
                if r["product_id"] == inv["product_id"]
                and r["warehouse_id"] == inv["warehouse_id"]
                and r["status"] in ("HELD", "COMMITTED")
            )
            available = max(0, inv["on_hand_qty"] - reserved)
            if available > 0:
                candidates.append((inv, available))
        # order by (warehouse.fulfillment_priority ASC, inv.created_at ASC), never id
        def sort_key(entry):
            inv = entry[0]
            wh = db.warehouses[inv["warehouse_id"]]
            return (wh["fulfillment_priority"], inv["created_at"], inv["_seq"])
        candidates.sort(key=sort_key)

        for inv, available in candidates:
            if remaining <= 0:
                break
            take = min(remaining, available)
            if take > 0:
                res = {
                    "order_line_id": L["id"],
                    "warehouse_id": inv["warehouse_id"],
                    "product_id": L["product_id"],
                    "qty": take,
                    "status": "HELD",
                }
                db.stamp_create(res)
                db.reservations[res["id"]] = res
                remaining -= take

        L["backordered_qty"] = remaining
        if remaining > 0:
            any_backorder = True
        db.touch(L)

    order["payment_status"] = "AUTHORIZED"
    order["fulfillment_status"] = "BACKORDERED" if any_backorder else "UNFULFILLED"
    db.touch(order)
    return success(serialize.order(order))


@bp.route("/orders/<oid>/capture-payment", methods=["POST"])
def capture_payment(oid):
    require_roles(["StoreAdmin"])
    order = lookup(db.orders, oid)
    if order["payment_status"] != "AUTHORIZED":
        raise err(ERR_INVALID_STATE, "Order must be AUTHORIZED to capture")
    order["captured_total_cents"] = order["grand_total_cents"]
    order["payment_status"] = "CAPTURED"
    db.touch(order)
    # Customer lifetime_purchased & return_risk recomputed -> bump customer
    cust = db.customers.get(order["customer_id"])
    if cust:
        db.touch(cust)
    return success(serialize.order(order))


@bp.route("/orders/<oid>/void", methods=["POST"])
def void_order(oid):
    require_roles(["StoreAdmin"])
    order = lookup(db.orders, oid)
    if order["payment_status"] != "AUTHORIZED":
        raise err(ERR_INVALID_STATE, "Order must be AUTHORIZED to void")
    # precondition: no SHIPPED/DELIVERED shipment exists
    for s in db.shipments.values():
        if s["order_id"] == oid and s["status"] in ("SHIPPED", "DELIVERED"):
            raise err(ERR_INVALID_STATE, "Cannot void an order with shipped/delivered parcels")
    # release every HELD reservation belonging to the order
    line_ids = {L["id"] for L in _order_lines_of(oid)}
    for r in db.reservations.values():
        if r["order_line_id"] in line_ids and r["status"] == "HELD":
            r["status"] = "RELEASED"
            db.touch(r)
    order["payment_status"] = "VOIDED"
    order["fulfillment_status"] = "UNFULFILLED"
    db.touch(order)
    return success(serialize.order(order))


@bp.route("/orders/<oid>/refunds", methods=["GET"])
def list_order_refunds(oid):
    require_roles(["Customer", "StoreAdmin"])
    lookup(db.orders, oid)
    rows = [r for r in db.refunds.values() if r["order_id"] == oid]
    data, meta = paginate(rows, serialize.refund)
    return success(data, pagination=meta)
