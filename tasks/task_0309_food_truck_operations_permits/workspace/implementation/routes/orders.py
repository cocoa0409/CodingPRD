"""Order endpoints: open, authorize, capture, settle, void (PRD §3.6, §3.7)."""

from flask import request, Blueprint

import errors
import serializers
import services
from db import db
from errors import err
from helpers import (get_body, require_str, require_fk, optional_int,
                     optional_enum, get_pagination, paginate)
from lookups import get_order, get_booking
from middleware import require_user_context, require_role, require_truck_ownership
from response import ok_object, ok_array

bp = Blueprint("orders", __name__)

WRITE_ROLES = {"OperatorTruck", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}
DISCOUNT_CODES = {"NONE", "HAPPY_HOUR", "BULK10"}


@bp.post("/orders")
def open_order():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    # FK existence (priority 4).
    booking_id = require_fk(body, "booking_id")
    booking = get_booking(booking_id)
    # Ownership: the owning truck is the booking's truck.
    require_truck_ownership(user_id, role, booking["truck_id"])
    truck = db.trucks.get(booking["truck_id"])
    # Priority 7: owning truck OPERABLE.
    if truck is None or truck["operability"] != "OPERABLE":
        raise err(errors.ERR_TRUCK_NOT_OPERABLE, "Owning truck is not OPERABLE")
    # Priority 8: parent booking ARRIVED.
    if booking["status"] != "ARRIVED":
        raise err(errors.ERR_BOOKING_NOT_ARRIVED, "Parent booking is not ARRIVED")
    rec = db.new_record({
        "truck_id": booking["truck_id"],
        "booking_id": booking_id,
        "lifecycle_status": "OPEN",
        "payment_status": "UNPAID",
        "tip_cents": 0,
        "discount_code": "NONE",
        "live_total_cents": 0,
        "settled_total_cents": None,
    })
    db.orders[rec["id"]] = rec
    return ok_object(serializers.order(rec), 201)


@bp.get("/orders")
def list_orders():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    records = list(db.orders.values())
    for field in ("truck_id", "booking_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    window, total = paginate(records, limit, offset)
    return ok_array([serializers.order(r) for r in window], limit, offset, total)


@bp.get("/orders/<order_id>")
def get_order_route(order_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_order(order_id)
    return ok_object(serializers.order(rec))


@bp.post("/orders/<order_id>/authorize-payment")
def authorize_payment(order_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_order(order_id)
    require_truck_ownership(user_id, role, rec["truck_id"])
    # Priority 6: order OPEN.
    if rec["lifecycle_status"] != "OPEN":
        raise err(errors.ERR_ORDER_NOT_OPEN, "Order is not OPEN")
    # payment_status UNPAID.
    if rec["payment_status"] != "UNPAID":
        raise err(errors.ERR_PAYMENT_NOT_UNPAID, "Payment status is not UNPAID")
    # Order must have >= 1 line.
    if not _has_lines(rec["id"]):
        raise err(errors.ERR_EMPTY_ORDER, "Order has no lines")
    rec["payment_status"] = "AUTHORIZED"
    db.touch(rec)
    return ok_object(serializers.order(rec))


@bp.post("/orders/<order_id>/capture-payment")
def capture_payment(order_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_order(order_id)
    require_truck_ownership(user_id, role, rec["truck_id"])
    body = get_body()
    tip_cents = optional_int(body, "tip_cents", default=0, minimum=0)
    # payment_status AUTHORIZED.
    if rec["payment_status"] != "AUTHORIZED":
        raise err(errors.ERR_PAYMENT_NOT_AUTHORIZED, "Payment status is not AUTHORIZED")
    rec["tip_cents"] = tip_cents
    rec["payment_status"] = "CAPTURED"
    # Refresh live_total to include the tip.
    rec["live_total_cents"] = services.compute_live_total(rec)
    db.touch(rec)
    return ok_object(serializers.order(rec))


@bp.post("/orders/<order_id>/settle")
def settle_order(order_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_order(order_id)
    require_truck_ownership(user_id, role, rec["truck_id"])
    body = get_body()
    discount_code = optional_enum(body, "discount_code", DISCOUNT_CODES, default="NONE")
    # Priority 6: order OPEN.
    if rec["lifecycle_status"] != "OPEN":
        raise err(errors.ERR_ORDER_NOT_OPEN, "Order is not OPEN")
    # >= 1 line.
    lines = [ln for ln in db.order_lines.values() if ln["order_id"] == rec["id"]]
    if not lines:
        raise err(errors.ERR_EMPTY_ORDER, "Order has no lines")
    # payment CAPTURED.
    if rec["payment_status"] != "CAPTURED":
        raise err(errors.ERR_PAYMENT_NOT_CAPTURED, "Payment status is not CAPTURED")
    # Priority 15: settle must not drive any prepared_units below 0.
    needed = {}
    for ln in lines:
        needed[ln["menu_item_id"]] = needed.get(ln["menu_item_id"], 0) + ln["quantity"]
    for menu_item_id, qty in needed.items():
        if services.prepared_units(menu_item_id) - qty < 0:
            raise err(errors.ERR_INSUFFICIENT_PREPARED_UNITS,
                      "Insufficient prepared units to settle")
    # Pin the settled total and apply consumption (consumption is via the ledger
    # once lifecycle_status flips to SETTLED).
    rec["discount_code"] = discount_code
    rec["settled_total_cents"] = services.compute_settled_total(rec, discount_code)
    rec["lifecycle_status"] = "SETTLED"
    db.touch(rec)
    # Owning truck gross_sales_cents += settled_total_cents.
    truck = db.trucks.get(rec["truck_id"])
    if truck is not None:
        truck["gross_sales_cents"] += rec["settled_total_cents"]
        db.touch(truck)
    return ok_object(serializers.order(rec))


@bp.post("/orders/<order_id>/void")
def void_order_route(order_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_order(order_id)
    require_truck_ownership(user_id, role, rec["truck_id"])
    if rec["lifecycle_status"] != "OPEN":
        raise err(errors.ERR_ORDER_NOT_OPEN, "Order is not OPEN")
    services.void_order(rec)
    return ok_object(serializers.order(rec))


def _has_lines(order_id):
    return any(ln["order_id"] == order_id for ln in db.order_lines.values())
