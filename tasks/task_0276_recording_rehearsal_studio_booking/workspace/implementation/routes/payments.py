"""Payment routes: deposit / balance / refund (PRD §3.6)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_principal, require_roles
from helpers import (
    get_json_body, require_enum, require_int, optional_enum,
    get_pagination, paginate, get_or_404, stamp_common, touch,
)
from response import success_object, success_array
from serialize import public, public_list
from services import booking_logic as bl

bp = Blueprint("payments", __name__)


def _owns_booking(principal, booking):
    if principal.role == "Client" and booking["client_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN", "client may only act on their own bookings")


@bp.route("/studio/bookings/<bid>/payments", methods=["POST"])
def create_payment(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client"})
    booking = get_or_404(db.bookings, bid, "booking")
    if principal.role == "Client":
        _owns_booking(principal, booking)

    body = get_json_body()
    kind = require_enum(body, "kind", {"DEPOSIT", "BALANCE", "REFUND"})
    amount_cents = require_int(body, "amount_cents")
    refund_destination = optional_enum(body, "refund_destination", {"ORIGINAL", "WALLET"}, "ORIGINAL")

    if amount_cents < 1:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be >= 1")

    client = db.clients[booking["client_id"]]

    if kind == "DEPOSIT":
        # State: settlement must be AWAITING_DEPOSIT.
        if booking["settlement_status"] != "AWAITING_DEPOSIT":
            raise err("ERR_INVALID_STATE", "deposit not expected in current settlement state")
        # Deposit exactness.
        if amount_cents != booking["deposit_due_cents"]:
            raise err("ERR_DEPOSIT_MISMATCH", "deposit must equal deposit_due_cents")
        payment = _record_payment(booking, kind, amount_cents, refund_destination)
        bl.recompute_amount_paid(booking)
        booking["settlement_status"] = "DEPOSIT_PAID"
        touch(booking)
        return success_object(public(payment), status=201)

    if kind == "BALANCE":
        if booking["settlement_status"] != "BALANCE_DUE":
            raise err("ERR_INVALID_STATE", "balance not expected in current settlement state")
        remaining_balance = booking["total_charge_cents"] - booking["amount_paid_cents"]
        wallet_applied = min(client["wallet_credit_cents"], remaining_balance)
        external_required = remaining_balance - wallet_applied
        # Balance exactness (incl. wallet-fully-covers case where external==0).
        if amount_cents != external_required:
            raise err("ERR_BALANCE_MISMATCH", "balance must equal external residue")
        payment = _record_payment(booking, kind, amount_cents, refund_destination)
        # Drain wallet by the applied portion.
        if wallet_applied > 0:
            client["wallet_credit_cents"] -= wallet_applied
            touch(client)
        bl.recompute_amount_paid(booking)
        booking["settlement_status"] = "SETTLED"
        touch(booking)
        return success_object(public(payment), status=201)

    # kind == REFUND — a manually-posted refund payment.
    payment = _record_payment(booking, kind, amount_cents, refund_destination)
    if refund_destination == "WALLET":
        client["wallet_credit_cents"] += amount_cents
        touch(client)
    bl.recompute_amount_paid(booking)
    touch(booking)
    return success_object(public(payment), status=201)


def _record_payment(booking, kind, amount_cents, refund_destination):
    payment = {
        "booking_id": booking["id"],
        "client_id": booking["client_id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "refund_destination": refund_destination,
        "reversed": False,
    }
    stamp_common(payment)
    db.payments[payment["id"]] = payment
    return payment


@bp.route("/studio/bookings/<bid>/payments", methods=["GET"])
def list_booking_payments(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client"})
    booking = get_or_404(db.bookings, bid, "booking")
    if principal.role == "Client":
        _owns_booking(principal, booking)
    payments = [p for p in db.payments.values() if p["booking_id"] == bid]
    limit, offset = get_pagination()
    page, total = paginate(payments, limit, offset)
    return success_array(public_list(page), limit, offset, total)


@bp.route("/studio/payments/<pid>", methods=["GET"])
def get_payment(pid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client"})
    payment = get_or_404(db.payments, pid, "payment")
    if principal.role == "Client" and payment["client_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN", "client may only access their own payments")
    return success_object(public(payment))


@bp.route("/studio/payments", methods=["GET"])
def list_payments():
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client"})
    client_id = request.args.get("client_id")
    booking_id = request.args.get("booking_id")
    payments = list(db.payments.values())
    if client_id is not None:
        payments = [p for p in payments if p["client_id"] == client_id]
    if booking_id is not None:
        payments = [p for p in payments if p["booking_id"] == booking_id]
    if principal.role == "Client":
        payments = [p for p in payments if p["client_id"] == principal.user_id]
    limit, offset = get_pagination()
    page, total = paginate(payments, limit, offset)
    return success_array(public_list(page), limit, offset, total)
