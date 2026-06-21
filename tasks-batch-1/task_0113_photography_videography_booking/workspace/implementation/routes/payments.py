"""Payments and settlement — the money track (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import require_auth, ROLE_CLIENT, ROLE_STUDIO_ADMIN
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_str, require_enum, require_int, serialize, serialize_list,
    parse_pagination, paginate, order_by_created_at,
)
from services.common import (
    stamp_create, touch, recompute_amount_paid_and_balance,
)

bp = Blueprint("payments", __name__)

PAYMENT_KINDS = {"DEPOSIT", "BALANCE", "REFUND"}


@bp.post("/studio/payments")
def create_payment():
    require_auth([ROLE_STUDIO_ADMIN])
    body = get_body()
    booking_id = require_str(body, "booking_id")
    kind = require_enum(body, "kind", PAYMENT_KINDS)
    amount_cents = require_int(body, "amount_cents", gt=0)

    if booking_id not in db.bookings:
        raise APIError(ERR_INVALID_REFERENCE, 422, "Booking does not exist")

    payment = {
        "booking_id": booking_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "status": "PENDING",
    }
    stamp_create(payment)
    db.payments[payment["id"]] = payment
    return ok_object(serialize(payment), 201)


@bp.get("/studio/payments/<id>")
def get_payment(id):
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    p = db.payments.get(id)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment not found")
    _assert_payment_read_owner(p)
    return ok_object(serialize(p), 200)


def _assert_payment_read_owner(payment):
    if g.user_role == ROLE_CLIENT:
        booking = db.bookings.get(payment["booking_id"])
        if booking is None or g.user_id != booking["client_id"]:
            raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this payment")


@bp.get("/studio/payments")
def list_payments():
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    limit, offset = parse_pagination()
    items = list(db.payments.values())
    for field in ("booking_id", "kind", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p[field] == val]
    # A Client only sees payments on its own bookings.
    if g.user_role == ROLE_CLIENT:
        owned = {b["id"] for b in db.bookings.values() if b["client_id"] == g.user_id}
        items = [p for p in items if p["booking_id"] in owned]
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/studio/payments/<id>/settle")
def settle_payment(id):
    require_auth([ROLE_STUDIO_ADMIN])
    p = db.payments.get(id)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment not found")

    booking = db.bookings[p["booking_id"]]
    kind = p["kind"]

    # State legality (priority 6): payment must be PENDING and the booking's
    # payment_status must be the legal source for this kind.
    if p["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Payment is not PENDING")

    if kind == "DEPOSIT":
        if booking["payment_status"] != "UNPAID":
            raise APIError(ERR_INVALID_STATE, 409, "Booking is not UNPAID")
        expected = booking["deposit_due_cents"]
        if p["amount_cents"] != expected:
            raise APIError(ERR_PAYMENT_AMOUNT_MISMATCH, 422,
                           "DEPOSIT amount must equal deposit_due_cents")
        p["status"] = "SETTLED"
        recompute_amount_paid_and_balance(booking)
        booking["payment_status"] = "DEPOSIT_PAID"
        touch(booking)
        touch(p)
        return ok_object(serialize(p), 200)

    if kind == "BALANCE":
        if booking["payment_status"] != "DEPOSIT_PAID":
            raise APIError(ERR_INVALID_STATE, 409, "Booking is not DEPOSIT_PAID")
        expected = booking["balance_due_cents"]
        if p["amount_cents"] != expected:
            raise APIError(ERR_PAYMENT_AMOUNT_MISMATCH, 422,
                           "BALANCE amount must equal balance_due_cents")
        p["status"] = "SETTLED"
        recompute_amount_paid_and_balance(booking)
        booking["payment_status"] = "PAID_IN_FULL"
        touch(booking)
        touch(p)
        return ok_object(serialize(p), 200)

    # REFUND
    if booking["payment_status"] != "REFUND_PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Booking is not REFUND_PENDING")
    expected = booking["amount_paid_cents"] - booking["cancellation_fee_cents"]
    if p["amount_cents"] != expected:
        raise APIError(ERR_PAYMENT_AMOUNT_MISMATCH, 422,
                       "REFUND amount must equal amount_paid_cents - cancellation_fee_cents")
    p["status"] = "SETTLED"
    recompute_amount_paid_and_balance(booking)
    booking["payment_status"] = "UNPAID"
    touch(booking)
    touch(p)
    return ok_object(serialize(p), 200)
