"""Shipment endpoints: create/ship/deliver/cancel + listings (PRD §3.5)."""
from flask import Blueprint

from db import db
from errors import (
    err, ERR_VALIDATION, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_RESERVATION_MISMATCH, ERR_PAYMENT_NOT_CAPTURED, ERR_NOT_FOUND,
)
from middleware import require_roles
from response import success
from services import serialize
from services.common import parse_body, require_str, paginate, lookup
from services.fulfillment import rederive_fulfillment

bp = Blueprint("shipments", __name__)


@bp.route("/orders/<oid>/shipments", methods=["POST"])
def create_shipment(oid):
    require_roles(["WarehouseOperator", "StoreAdmin"])
    order = lookup(db.orders, oid)
    body = parse_body()
    warehouse_id = require_str(body, "warehouse_id")
    lines = body.get("lines")
    if not isinstance(lines, list) or len(lines) < 1:
        raise err(ERR_INVALID_REQUEST, "lines must be a non-empty array")
    # existence of warehouse FK
    lookup(db.warehouses, warehouse_id)

    # validate each shipment line shape + existence first (existence before
    # business rules per §2.9)
    parsed = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise err(ERR_INVALID_REQUEST, "each line must be an object")
        reservation_id = ln.get("reservation_id")
        if not isinstance(reservation_id, str) or reservation_id == "":
            raise err(ERR_INVALID_REQUEST, "line.reservation_id is required")
        qty = ln.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise err(ERR_INVALID_REQUEST, "line.qty must be an integer")
        reservation = lookup(db.reservations, reservation_id)
        parsed.append((reservation, qty))

    # order-line ids of this order (to confirm reservation belongs to order)
    line_ids = {l["id"] for l in db.order_lines.values() if l["order_id"] == oid}

    # business validation: qty == reservation.qty, reservation HELD, belongs to
    # order, warehouse matches
    for reservation, qty in parsed:
        if reservation["order_line_id"] not in line_ids:
            raise err(ERR_RESERVATION_MISMATCH, "reservation does not belong to this order")
        if reservation["status"] != "HELD":
            raise err(ERR_RESERVATION_MISMATCH, "reservation is not HELD")
        if reservation["warehouse_id"] != warehouse_id:
            raise err(ERR_RESERVATION_MISMATCH, "reservation warehouse does not match shipment warehouse")
        if qty != reservation["qty"]:
            raise err(ERR_RESERVATION_MISMATCH, "shipment line qty must equal reservation qty")

    ship = {
        "order_id": oid,
        "warehouse_id": warehouse_id,
        "status": "PENDING",
        "shipped_at": None,
        "delivered_at": None,
    }
    db.stamp_create(ship)
    db.shipments[ship["id"]] = ship
    for reservation, qty in parsed:
        sl = {
            "shipment_id": ship["id"],
            "reservation_id": reservation["id"],
            "order_line_id": reservation["order_line_id"],
            "qty": qty,
        }
        db.stamp_create(sl)
        db.shipment_lines[sl["id"]] = sl
    return success(serialize.shipment(ship), status=201)


@bp.route("/orders/<oid>/shipments", methods=["GET"])
def list_order_shipments(oid):
    require_roles(["Customer", "StoreAdmin", "WarehouseOperator"])
    lookup(db.orders, oid)
    rows = [s for s in db.shipments.values() if s["order_id"] == oid]
    data, meta = paginate(rows, serialize.shipment)
    return success(data, pagination=meta)


@bp.route("/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    require_roles(["Customer", "StoreAdmin", "WarehouseOperator"])
    rec = lookup(db.shipments, sid)
    return success(serialize.shipment(rec))


@bp.route("/shipments/<sid>/lines", methods=["GET"])
def list_shipment_lines(sid):
    require_roles(["Customer", "StoreAdmin", "WarehouseOperator"])
    lookup(db.shipments, sid)
    rows = [sl for sl in db.shipment_lines.values() if sl["shipment_id"] == sid]
    data, meta = paginate(rows, serialize.shipment_line)
    return success(data, pagination=meta)


def _shipment_lines_of(shipment_id):
    return [sl for sl in db.shipment_lines.values() if sl["shipment_id"] == shipment_id]


@bp.route("/shipments/<sid>/ship", methods=["POST"])
def ship_shipment(sid):
    require_roles(["WarehouseOperator"])
    ship = lookup(db.shipments, sid)
    if ship["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Shipment must be PENDING to ship")
    order = db.orders.get(ship["order_id"])
    # cross-entity guard: order must be CAPTURED
    if order is None or order["payment_status"] != "CAPTURED":
        raise err(ERR_PAYMENT_NOT_CAPTURED, "Order payment must be CAPTURED before shipping")

    sls = _shipment_lines_of(sid)
    # every referenced reservation must be HELD and belong to the order
    line_ids = {l["id"] for l in db.order_lines.values() if l["order_id"] == order["id"]}
    for sl in sls:
        reservation = db.reservations.get(sl["reservation_id"])
        if reservation is None or reservation["status"] != "HELD" \
                or reservation["order_line_id"] not in line_ids:
            raise err(ERR_RESERVATION_MISMATCH, "shipment references an invalid reservation")

    # cascade: commit reservations, decrement on_hand, recompute available
    for sl in sls:
        reservation = db.reservations[sl["reservation_id"]]
        reservation["status"] = "COMMITTED"
        db.touch(reservation)
        # decrement matching inventory item on_hand
        for inv in db.inventory_items.values():
            if inv["product_id"] == reservation["product_id"] \
                    and inv["warehouse_id"] == reservation["warehouse_id"]:
                inv["on_hand_qty"] = inv["on_hand_qty"] - reservation["qty"]
                db.touch(inv)
                break

    ship["status"] = "SHIPPED"
    ship["shipped_at"] = db.current_clock_iso()
    db.touch(ship)
    # re-derive order fulfillment
    rederive_fulfillment(order)
    db.touch(order)
    # bump touched order lines (shipped_qty changed)
    for sl in sls:
        ol = db.order_lines.get(sl["order_line_id"])
        if ol:
            db.touch(ol)
    return success(serialize.shipment(ship))


@bp.route("/shipments/<sid>/deliver", methods=["POST"])
def deliver_shipment(sid):
    require_roles(["WarehouseOperator"])
    ship = lookup(db.shipments, sid)
    if ship["status"] != "SHIPPED":
        raise err(ERR_INVALID_STATE, "Shipment must be SHIPPED to deliver")
    ship["status"] = "DELIVERED"
    ship["delivered_at"] = db.current_clock_iso()
    db.touch(ship)
    order = db.orders.get(ship["order_id"])
    if order:
        rederive_fulfillment(order)
        db.touch(order)
    return success(serialize.shipment(ship))


@bp.route("/shipments/<sid>/cancel", methods=["POST"])
def cancel_shipment(sid):
    require_roles(["WarehouseOperator"])
    ship = lookup(db.shipments, sid)
    if ship["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Shipment must be PENDING to cancel")
    ship["status"] = "CANCELLED"
    # remove its shipment lines; reservations stay HELD
    to_remove = [sl["id"] for sl in db.shipment_lines.values() if sl["shipment_id"] == sid]
    for slid in to_remove:
        del db.shipment_lines[slid]
    db.touch(ship)
    return success(serialize.shipment(ship))
