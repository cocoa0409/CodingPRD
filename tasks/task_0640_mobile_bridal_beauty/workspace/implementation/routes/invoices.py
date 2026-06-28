"""Invoices and payments (PRD §3.8, §3.9)."""
from flask import Blueprint, request

import errors
from db import store, LOCK, new_id, now_iso
from middleware import get_identity, require_role, parse_pagination, get_json_body
from response import object_response, array_response
from services.common import touch, paginate
from services.domain import reconcile_balance, paid_deposit
from services.validate import require_enum, require_int_min
from routes.contracts import serialize_invoice

bp = Blueprint("invoices", __name__)

APPLIES_TO = {"DEPOSIT", "BALANCE"}


def serialize_payment(p):
    return {
        "id": p["id"],
        "invoice_id": p["invoice_id"],
        "applies_to": p["applies_to"],
        "amount_cents": p["amount_cents"],
        "outcome": p["outcome"],
        "created_at": p["created_at"],
    }


@bp.route("/bridal-beauty/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator"})
    inv = store.invoices.get(invoice_id)
    if inv is None:
        raise errors.not_found()
    return object_response(serialize_invoice(inv), 200)


@bp.route("/bridal-beauty/invoices", methods=["GET"])
def list_invoices():
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator"})
    limit, offset = parse_pagination()
    event_f = request.args.get("event_id")
    contract_f = request.args.get("contract_id")
    items = list(store.invoices.values())
    if event_f is not None:
        items = [i for i in items if i["event_id"] == event_f]
    if contract_f is not None:
        items = [i for i in items if i["contract_id"] == contract_f]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_invoice(i) for i in page], limit, offset, total)


@bp.route("/bridal-beauty/invoices/<invoice_id>/payments", methods=["POST"])
def create_payment(invoice_id):
    user_id, role = get_identity()
    require_role(role, {"Client"})
    body = get_json_body()
    with LOCK:
        inv = store.invoices.get(invoice_id)
        if inv is None:
            raise errors.not_found()

        # Ownership via the event's client_id (PRD §2.4, priority 4).
        event = store.events.get(inv["event_id"])
        if event is None or user_id != event["client_id"]:
            raise errors.not_event_owner()

        applies_to = require_enum(body, "applies_to", APPLIES_TO)
        amount = require_int_min(body, "amount_cents", 1)

        if applies_to == "DEPOSIT":
            # Exact deposit settlement (priority 14).
            remaining = inv["deposit_amount_cents"] - paid_deposit(invoice_id)
            if amount != remaining:
                raise errors.deposit_amount_mismatch()
            # Record payment.
            p = _record_payment(invoice_id, applies_to, amount)
            reconcile_balance(inv)
            # Advance deposit_status DUE -> PAID.
            inv["deposit_status"] = "PAID"
            touch(inv)
            return object_response(serialize_payment(p), 201)
        else:  # BALANCE
            # Deposit must be settled first (priority 16).
            if inv["deposit_status"] != "PAID":
                raise errors.deposit_not_settled()
            # May not exceed current balance (priority 15).
            if amount > inv["balance_amount_cents"]:
                raise errors.balance_overpay()
            p = _record_payment(invoice_id, applies_to, amount)
            reconcile_balance(inv)
            # If balance cleared to zero, advance balance_status DUE -> PAID.
            if inv["balance_amount_cents"] == 0:
                inv["balance_status"] = "PAID"
            touch(inv)
            return object_response(serialize_payment(p), 201)


def _record_payment(invoice_id, applies_to, amount):
    p = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
        "invoice_id": invoice_id,
        "applies_to": applies_to,
        "amount_cents": amount,
        "outcome": "SUCCEEDED",
    }
    store.payments[p["id"]] = p
    return p


@bp.route("/bridal-beauty/invoices/<invoice_id>/payments", methods=["GET"])
def list_payments(invoice_id):
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator"})
    limit, offset = parse_pagination()
    applies_f = request.args.get("applies_to")
    inv = store.invoices.get(invoice_id)
    if inv is None:
        raise errors.not_found()
    items = [p for p in store.payments.values() if p["invoice_id"] == invoice_id]
    if applies_f is not None:
        items = [p for p in items if p["applies_to"] == applies_f]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_payment(p) for p in page], limit, offset, total)
