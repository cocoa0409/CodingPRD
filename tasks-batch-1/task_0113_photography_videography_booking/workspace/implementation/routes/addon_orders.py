"""Add-on orders: prints and albums (PRD §3.8, §2.6 OCC)."""
from __future__ import annotations

from flask import Blueprint, g

import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_STALE_BOOKING_VERSION,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import require_auth, ROLE_CLIENT, ROLE_STUDIO_ADMIN
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_enum, require_int, serialize, serialize_list,
    parse_pagination, paginate, order_by_created_at,
)
from services import calculations as calc
from services.common import (
    stamp_create, touch, addon_orders_for_booking,
    recompute_total_fee, recompute_amount_paid_and_balance,
)

bp = Blueprint("addon_orders", __name__)

LINE_KINDS = {"PRINT", "ALBUM"}


@bp.post("/studio/bookings/<id>/add-on-orders")
def create_addon(id):
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    booking = db.bookings.get(id)
    if booking is None:
        raise APIError(ERR_NOT_FOUND, 404, "Booking not found")

    # Ownership (priority 4): Client must own the booking.
    if g.user_role == ROLE_CLIENT and g.user_id != booking["client_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this booking")

    body = get_body()
    line_kind = require_enum(body, "line_kind", LINE_KINDS)
    quantity = require_int(body, "quantity", min_value=1)
    unit_price_cents = require_int(body, "unit_price_cents", gt=0)
    expected_version = require_int(body, "expected_booking_version", min_value=0)

    # OCC (priority 7).
    if expected_version != booking["version"]:
        raise APIError(ERR_STALE_BOOKING_VERSION, 412, "Booking version has advanced")

    line_total = calc.addon_line_total(line_kind, quantity, unit_price_cents)

    order = {
        "booking_id": booking["id"],
        "line_kind": line_kind,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "line_total_cents": line_total,
        "status": "ORDERED",
    }
    stamp_create(order)
    db.addon_orders[order["id"]] = order

    # ORDERED order joins the booking total.
    recompute_total_fee(booking)
    recompute_amount_paid_and_balance(booking)
    touch(booking)
    return ok_object(serialize(order), 201)


@bp.get("/studio/bookings/<id>/add-on-orders")
def list_addons_for_booking(id):
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    booking = db.bookings.get(id)
    if booking is None:
        raise APIError(ERR_NOT_FOUND, 404, "Booking not found")
    if g.user_role == ROLE_CLIENT and g.user_id != booking["client_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this booking")
    limit, offset = parse_pagination()
    items = order_by_created_at(addon_orders_for_booking(id))
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/studio/add-on-orders/<id>/cancel")
def cancel_addon(id):
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    order = db.addon_orders.get(id)
    if order is None:
        raise APIError(ERR_NOT_FOUND, 404, "Add-on order not found")

    booking = db.bookings.get(order["booking_id"])
    # Ownership (priority 4): Client must own the booking.
    if g.user_role == ROLE_CLIENT and (booking is None or g.user_id != booking["client_id"]):
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this booking")

    body = get_body()
    expected_version = require_int(body, "expected_booking_version", min_value=0)

    # State legality (priority 6) before OCC? PRD §2.7 puts state (6) before
    # OCC (7); but the OCC guard here protects the booking total. The booking
    # version is what is compared, and ORDERED->CANCELLED is the only legal
    # transition. Per the precedence table, state precedes OCC.
    if order["status"] != "ORDERED":
        raise APIError(ERR_INVALID_STATE, 409, "Order is not ORDERED")

    # OCC (priority 7).
    if expected_version != booking["version"]:
        raise APIError(ERR_STALE_BOOKING_VERSION, 412, "Booking version has advanced")

    order["status"] = "CANCELLED"
    touch(order)

    recompute_total_fee(booking)
    recompute_amount_paid_and_balance(booking)
    touch(booking)
    return ok_object(serialize(order), 200)
