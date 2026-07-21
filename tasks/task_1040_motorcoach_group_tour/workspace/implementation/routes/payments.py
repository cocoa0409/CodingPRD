"""Payment endpoints."""
from flask import Blueprint, request

import services
from errors import ApiError
from store import db
from web import (
    authenticate,
    get_body,
    created,
    ok,
    ok_list,
    parse_pagination,
    req_str,
    req_int,
    opt_str,
)

bp = Blueprint("payments", __name__)


@bp.post("/api/payments")
def create_payment():
    authenticate({"SalesAgent"})
    body = get_body()
    booking_id = req_str(body, "booking_id")
    kind = req_str(body, "kind")
    # Clients may record only DEPOSIT or BALANCE; REFUND is system-only (PRD §3.6).
    if kind not in ("DEPOSIT", "BALANCE"):
        raise ApiError("ERR_VALIDATION", "kind must be DEPOSIT or BALANCE")
    amount_cents = req_int(body, "amount_cents", min_val=1)
    method = opt_str(body, "method")
    booking = services.get_or_404(db.bookings, booking_id)
    pay = services.record_payment(booking, kind, amount_cents, method)
    return created(services.serialize(pay))


@bp.get("/api/payments/<payment_id>")
def get_payment(payment_id):
    authenticate("ALL")
    p = services.get_or_404(db.payments, payment_id)
    return ok(services.serialize(p))


@bp.get("/api/payments")
def list_payments():
    authenticate("ALL")
    limit, offset = parse_pagination()
    items = list(db.payments.values())
    booking_id = request.args.get("booking_id")
    if booking_id is not None:
        items = [p for p in items if p["booking_id"] == booking_id]
    page, total = services.paginate(items, limit, offset)
    return ok_list([services.serialize(p) for p in page], total, limit, offset)
