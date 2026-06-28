"""Dues invoices and payments (PRD §3.3)."""
from datetime import datetime, timezone

from flask import Blueprint, request

from db import db
from errors import (
    err,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_OVERPAYMENT,
    ERR_INVALID_REQUEST,
)
from middleware import authenticate, require_roles, BOTH_ROLES
from response import object_response, array_response
from serializers import serialize_dues_invoice, serialize_payment
from util import new_id, iso_now
from routes import helpers as h
from services import recompute, calculations
from services.ledger import post_ledger_entry

bp = Blueprint("dues", __name__)


@bp.post("/members/<member_id>/dues-invoices")
def issue_invoice(member_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    member = h.get_or_404(db.members, member_id)
    body = h.get_json_body()
    issued_on = h.require_string(body, "issued_on")

    council = db.councils[db.troops[member["troop_id"]]["council_id"]]
    base = (
        council["youth_dues_cents"]
        if member["member_type"] == "YOUTH"
        else council["adult_dues_cents"]
    )
    amount = calculations.dues_proration(base, issued_on)

    now = iso_now(datetime.now(timezone.utc))
    invoice = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "member_id": member["id"],
        "troop_id": member["troop_id"],
        "amount_cents": amount,
        "issued_on": issued_on,
        "status": "OPEN",
        "_seq": db.next_seq(),
    }
    db.dues_invoices[invoice["id"]] = invoice
    return object_response(serialize_dues_invoice(invoice), status=201)


@bp.get("/dues-invoices/<invoice_id>")
def get_invoice(invoice_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    invoice = h.get_or_404(db.dues_invoices, invoice_id)
    return object_response(serialize_dues_invoice(invoice))


@bp.get("/dues-invoices")
def list_invoices():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    member_id = request.args.get("member_id")
    troop_id = request.args.get("troop_id")
    status = request.args.get("status")
    limit, offset = h.parse_pagination()
    rows = [
        d for d in db.dues_invoices.values()
        if (member_id is None or d["member_id"] == member_id)
        and (troop_id is None or d["troop_id"] == troop_id)
        and (status is None or d["status"] == status)
    ]
    rows = h.sort_by_creation(rows)
    page, total = h.paginate(rows, limit, offset)
    return array_response(
        [serialize_dues_invoice(d) for d in page], limit, offset, total
    )


payments_bp = Blueprint("payments", __name__)


@payments_bp.post("/payments")
def post_payment():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    body = h.get_json_body()

    invoice_id = h.require_string(body, "invoice_id")
    member_id = h.require_string(body, "member_id")
    amount_cents = h.require_int(body, "amount_cents")

    # Body-level referential integrity (PRD §2.7) -> ERR_INVALID_REFERENCE.
    invoice = db.dues_invoices.get(invoice_id)
    member = db.members.get(member_id)
    if invoice is None or member is None:
        raise err(ERR_INVALID_REFERENCE, "invoice_id or member_id does not exist")

    # amount_cents must be strictly > 0 (PRD §3.3) -> ERR_INVALID_REQUEST.
    if amount_cents <= 0:
        raise err(ERR_INVALID_REQUEST, "amount_cents must be > 0")

    # Payment posts against an OPEN invoice (PRD §3.3) -> ERR_INVALID_STATE.
    if invoice["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "invoice is not OPEN")

    # No overpayment: cumulative POSTED must not exceed invoice amount.
    existing = sum(
        p["amount_cents"]
        for p in db.payments.values()
        if p["invoice_id"] == invoice_id and p["status"] == "POSTED"
    )
    if existing + amount_cents > invoice["amount_cents"]:
        raise err(ERR_OVERPAYMENT, "payment would exceed invoice amount")

    # Append-only payment record: only id + created_at (PRD §2.4).
    now = iso_now(datetime.now(timezone.utc))
    payment = {
        "id": new_id(),
        "created_at": now,
        "invoice_id": invoice_id,
        "member_id": member_id,
        "amount_cents": amount_cents,
        "status": "POSTED",
        "_seq": db.next_seq(),
    }
    db.payments[payment["id"]] = payment

    # Credit TROOP_DUES (source_kind=PAYMENT), routed to the invoice's troop.
    troop = db.troops[invoice["troop_id"]]
    council = db.councils[troop["council_id"]]
    post_ledger_entry(
        council["id"], "TROOP_DUES", amount_cents, "PAYMENT", payment["id"],
        troop_id=troop["id"],
    )

    # If cumulative POSTED >= invoice amount: PAID + member REGISTERED.
    cumulative = existing + amount_cents
    troop_changed = False
    if cumulative >= invoice["amount_cents"]:
        invoice["status"] = "PAID"
        h.touch_and_bump(invoice)
        if member["registration_status"] == "PENDING":
            member["registration_status"] = "REGISTERED"
            h.touch_and_bump(member)
        troop_changed = True

    # Troop version always bumps because TROOP_DUES changed (PRD §2.5).
    recompute.recompute_troop_counts(troop, bump=True)
    return object_response(serialize_payment(payment), status=201)


@payments_bp.get("/payments/<payment_id>")
def get_payment(payment_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    payment = h.get_or_404(db.payments, payment_id)
    return object_response(serialize_payment(payment))


@payments_bp.get("/payments")
def list_payments():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    invoice_id = request.args.get("invoice_id")
    member_id = request.args.get("member_id")
    limit, offset = h.parse_pagination()
    rows = [
        p for p in db.payments.values()
        if (invoice_id is None or p["invoice_id"] == invoice_id)
        and (member_id is None or p["member_id"] == member_id)
    ]
    rows = h.sort_by_creation(rows)
    page, total = h.paginate(rows, limit, offset)
    return array_response([serialize_payment(p) for p in page], limit, offset, total)
