"""Payment endpoints (authorize, capture, void) + deposit-threshold auto-confirm."""
from flask import Blueprint

import db
from errors import (ApiError, invalid_state, not_resource_owner,
                    ERR_OVERPAYMENT, ERR_PAYMENT_NOT_VOIDABLE)
from middleware import authenticate, require_roles
from response import array_response, object_response
from services import get_or_404, get_or_ref_404, refresh_ledger
from validate import (get_json_body, opt_enum, parse_pagination, paginate,
                      require_enum, require_int, require_str_field)

bp = Blueprint("payments", __name__)

KINDS = {"DEPOSIT", "BALANCE", "ADJUSTMENT"}
REFUND_DESTS = {"ORIGINAL", "STORE_CREDIT"}


@bp.post("/payments")
def create_payment():
    caller = authenticate()
    require_roles(caller, {"BookingAgent", "Client"})
    body = get_json_body()
    # FK existence (priority 5) before remaining well-formedness (priority 6).
    booking_id = require_str_field(body, "booking_id")
    booking = get_or_ref_404(db.bookings, booking_id)
    # Ownership: Client may only pay on own booking.
    if caller.role == "Client" and caller.user_id != booking["client_id"]:
        raise not_resource_owner()
    kind = require_enum(body, "kind", KINDS)
    amount = require_int(body, "amount_cents", minimum=1)
    refund_dest = opt_enum(body, "refund_destination", REFUND_DESTS,
                           default="ORIGINAL")

    rec = db.make_common()
    rec.update({
        "booking_id": booking["id"],
        "kind": kind,
        "amount_cents": amount,
        "capture_status": "AUTHORIZED",
        "settlement_status": "UNSETTLED",
        "refund_destination": refund_dest,
    })
    db.payments[rec["id"]] = rec
    return object_response(rec, 201)


@bp.get("/payments/<pid>")
def get_payment(pid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Client"})
    rec = get_or_404(db.payments, pid)
    if caller.role == "Client":
        booking = db.bookings.get(rec["booking_id"])
        if booking is None or caller.user_id != booking["client_id"]:
            raise not_resource_owner()
    return object_response(rec)


@bp.get("/bookings/<bid>/payments")
def list_payments(bid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Client"})
    limit, offset = parse_pagination()
    booking = get_or_404(db.bookings, bid)
    if caller.role == "Client" and caller.user_id != booking["client_id"]:
        raise not_resource_owner()
    rows = [p for p in db.payments.values() if p["booking_id"] == bid]
    page, total = paginate(rows, limit, offset)
    return array_response(page, limit, offset, total)


@bp.post("/payments/<pid>/capture")
def capture_payment(pid):
    caller = authenticate()
    require_roles(caller, {"BookingAgent", "Client"})
    payment = get_or_404(db.payments, pid)
    booking = db.bookings.get(payment["booking_id"])
    if caller.role == "Client":
        if booking is None or caller.user_id != booking["client_id"]:
            raise not_resource_owner()

    if payment["capture_status"] != "AUTHORIZED":
        raise invalid_state("payment is not in AUTHORIZED state")
    if booking["status"] in ("CANCELLED", "SETTLED"):
        raise invalid_state("owning booking is not capturable")

    # Overpayment: captured amount must not exceed outstanding balance.
    refresh_ledger(booking)
    if payment["amount_cents"] > booking["balance_due_cents"]:
        raise ApiError(ERR_OVERPAYMENT, 409,
                       "captured amount exceeds outstanding balance")

    payment["capture_status"] = "CAPTURED"
    db.touch(payment)
    refresh_ledger(booking)
    db.touch(booking)

    _maybe_confirm(booking)
    return object_response(payment)


def _maybe_confirm(booking):
    """Auto CONTRACT_SENT -> CONFIRMED when a captured DEPOSIT brings cumulative
    captured deposits >= deposit_required and the booking has a SIGNED contract."""
    if booking["status"] != "CONTRACT_SENT":
        return
    has_signed = any(c["booking_id"] == booking["id"] and c["status"] == "SIGNED"
                     for c in db.contracts.values())
    if not has_signed:
        return
    cumulative_deposits = sum(
        p["amount_cents"] for p in db.payments.values()
        if p["booking_id"] == booking["id"] and p["kind"] == "DEPOSIT"
        and p["capture_status"] == "CAPTURED")
    if cumulative_deposits < booking["deposit_required_cents"]:
        return
    # Confirm.
    performer = db.performers[booking["performer_id"]]
    booking["active_performer_id"] = performer["id"]
    booking["status"] = "CONFIRMED"
    db.touch(booking)
    performer["availability_status"] = "BOOKED"
    db.touch(performer)


@bp.post("/payments/<pid>/void")
def void_payment(pid):
    caller = authenticate()
    require_roles(caller, {"BookingAgent"})
    payment = get_or_404(db.payments, pid)
    if payment["capture_status"] != "AUTHORIZED":
        raise ApiError(ERR_PAYMENT_NOT_VOIDABLE, 409,
                       "only an AUTHORIZED payment may be voided")
    payment["capture_status"] = "VOID"
    db.touch(payment)
    return object_response(payment)
