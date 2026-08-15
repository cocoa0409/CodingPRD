"""Payment endpoints (PRD §3.7) — single charge-and-refund ledger."""

from flask import Blueprint, request

import db
import domain
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PAYMENT_AMOUNT_INVALID,
    ERR_REFUND_EXCEEDS_PAID,
    ERR_SESSION_NOT_ACTIVE,
)
from helpers import (
    check_no_undeclared,
    get_body,
    ok_object,
    paginate,
    req_enum,
    req_int,
    req_str,
    require,
)

bp = Blueprint("payments", __name__)

COLLECTORS = ("GateStaff", "FieldStaff", "FarmManager")
READERS = ("FarmManager", "GateStaff", "FieldStaff")
FM = ("FarmManager",)
METHODS = ("CASH", "CARD", "OFFLINE_CARD")


def outstanding_obligation(session):
    """PRD §2.7 gate 14 / §3.7: admission + FINALIZED line charges + value of
    BOOKED/REDEEMED bookings - net collected. PROVISIONAL/VOIDED lines,
    RELEASED bookings, and bundle discounts are deliberately excluded."""
    total = session["admission_charge_cents"]
    total += sum(
        l["line_charge_cents"]
        for l in domain.session_lines(session)
        if l["status"] == "FINALIZED"
    )
    total += sum(
        b["booked_value_cents"]
        for b in domain.session_bookings(session)
        if b["status"] in ("BOOKED", "REDEEMED")
    )
    total -= domain.session_total_paid(session) - domain.session_total_refunded(session)
    return total


@bp.post("/farm/payments")
def create_payment():
    require(COLLECTORS)
    body = get_body()
    check_no_undeclared(
        body, {"session_id", "kind", "method", "amount_cents", "idempotency_key"}
    )
    session_id = req_str(body, "session_id")
    kind = req_enum(body, "kind", ("CHARGE",))
    method = req_enum(body, "method", METHODS)
    amount = req_int(body, "amount_cents", min_value=1)
    idempotency_key = req_str(body, "idempotency_key")
    session = db.visit_sessions.get(session_id)
    if session is None:
        raise_err(ERR_NOT_FOUND, "session_id does not resolve")
    # Idempotency: the key is unique per session; replay returns the original.
    for p in domain.session_payments(session):
        if p["idempotency_key"] == idempotency_key:
            return ok_object(domain.serialize_payment(p), 201)
    # Tier 12: session must be on-site.
    if session["visit_status"] not in ("CHECKED_IN", "FIELD_ACTIVE"):
        raise_err(ERR_SESSION_NOT_ACTIVE, "Session is not on-site")
    # Tier 14: amount sanity against the outstanding obligation.
    if amount > outstanding_obligation(session):
        raise_err(ERR_PAYMENT_AMOUNT_INVALID, "amount_cents exceeds the outstanding obligation")
    payment = domain.new_entity()
    payment.update(
        {
            "session_id": session_id,
            "kind": kind,
            "method": method,
            "amount_cents": amount,
            "idempotency_key": idempotency_key,
            "refunded_amount_cents": 0,
            "status": "PENDING",
        }
    )
    db.payments[payment["id"]] = payment
    # CASH and online CARD settle immediately; OFFLINE_CARD settles on batch apply.
    if method in ("CASH", "CARD"):
        payment["status"] = "SETTLED"
        domain.touch(session)
    return ok_object(domain.serialize_payment(payment), 201)


@bp.get("/farm/payments/<pid>")
def get_payment(pid):
    require(READERS)
    payment = db.payments.get(pid)
    if payment is None:
        raise_err(ERR_NOT_FOUND, "Payment not found")
    return ok_object(domain.serialize_payment(payment))


@bp.get("/farm/payments")
def list_payments():
    require(READERS)
    items = list(db.payments.values())
    session_id = request.args.get("session_id")
    if session_id is not None:
        items = [p for p in items if p["session_id"] == session_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items, domain.serialize_payment)


@bp.post("/farm/payments/<pid>/refund")
def refund_payment(pid):
    require(FM)
    payment = db.payments.get(pid)
    if payment is None:
        raise_err(ERR_NOT_FOUND, "Payment not found")
    body = get_body()
    check_no_undeclared(body, {"amount_cents"})
    amount = req_int(body, "amount_cents", min_value=1)
    if payment["status"] not in ("SETTLED", "PARTIALLY_REFUNDED"):
        raise_err(ERR_INVALID_STATE, "Payment cannot be refunded from its current state")
    if amount > payment["amount_cents"] - payment["refunded_amount_cents"]:
        raise_err(ERR_REFUND_EXCEEDS_PAID, "Refund exceeds the payment's unrefunded amount")
    payment["refunded_amount_cents"] += amount
    payment["status"] = (
        "REFUNDED"
        if payment["refunded_amount_cents"] == payment["amount_cents"]
        else "PARTIALLY_REFUNDED"
    )
    domain.touch(payment)
    session = db.visit_sessions.get(payment["session_id"])
    if session is not None:
        domain.touch(session)
    return ok_object(domain.serialize_payment(payment))
