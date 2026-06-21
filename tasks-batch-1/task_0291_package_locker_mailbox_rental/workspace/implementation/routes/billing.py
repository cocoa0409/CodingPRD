"""Invoice, LedgerEntry, Payment endpoints."""
from flask import Blueprint, request, g

from db import db, new_id, now_iso
from errors import err
from response import success, list_response
from middleware import require_roles
from common import (get_json, require_fields, require_str, require_enum, require_int,
                    fk_or_404, get_or_404, touch, parse_pagination, paginate,
                    require_customer_owns)
import constants as C
import serializers as S
from services import billing as billing_svc

bp = Blueprint("billing", __name__)


def _invoice_customer(invoice):
    agreement = db.rental_agreements.get(invoice["rental_agreement_id"])
    return agreement["customer_id"] if agreement else None


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    invoice = get_or_404(db.invoices, iid)
    cust = _invoice_customer(invoice)
    if cust is not None:
        require_customer_owns(cust)
    return success(S.invoice_out(invoice))


@bp.get("/invoices")
def list_invoices():
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    limit, offset = parse_pagination()
    items = list(db.invoices.values())
    if g.role == "Customer":
        owned = {a["id"] for a in db.rental_agreements.values()
                 if a["customer_id"] == g.user_id}
        items = [x for x in items if x["rental_agreement_id"] in owned]
    for key in ("facility_id", "rental_agreement_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    page, total = paginate(items, limit, offset)
    return list_response([S.invoice_out(x) for x in page], limit, offset, total)


@bp.get("/invoices/<iid>/ledger-entries")
def list_ledger_entries(iid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    invoice = get_or_404(db.invoices, iid)
    cust = _invoice_customer(invoice)
    if cust is not None:
        require_customer_owns(cust)
    limit, offset = parse_pagination()
    items = [e for e in db.ledger_entries.values() if e["invoice_id"] == iid]
    page, total = paginate(items, limit, offset)
    return list_response([S.ledger_out(x) for x in page], limit, offset, total)


@bp.post("/payments")
def create_payment():
    require_roles("FacilityOperator", "Customer")
    body = get_json()
    require_fields(body, ["invoice_id", "amount_cents", "method"])
    invoice_id = require_str(body, "invoice_id")
    amount_cents = require_int(body, "amount_cents", minimum=1)
    method = require_enum(body, "method", C.PAYMENT_METHODS)
    invoice = fk_or_404(db.invoices, invoice_id)
    cust = _invoice_customer(invoice)
    if cust is not None:
        require_customer_owns(cust)
    # Manual payment exceeding positive outstanding balance is rejected.
    balance = billing_svc.invoice_balance(invoice)
    if balance > 0 and amount_cents > balance:
        raise err("ERR_PAYMENT_EXCEEDS_BALANCE", "Payment exceeds outstanding balance")
    if balance <= 0:
        # No positive balance to pay against.
        raise err("ERR_PAYMENT_EXCEEDS_BALANCE", "Payment exceeds outstanding balance")
    pid = new_id()
    payment = {
        "id": pid,
        "facility_id": invoice["facility_id"],
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "method": method,
        "status": "CAPTURED",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.payments[pid] = payment
    touch(invoice)
    billing_svc.settle_if_paid(invoice)
    return success(S.payment_out(payment), status=201)


@bp.get("/payments/<pid>")
def get_payment(pid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    payment = get_or_404(db.payments, pid)
    invoice = db.invoices.get(payment["invoice_id"])
    if invoice is not None:
        cust = _invoice_customer(invoice)
        if cust is not None:
            require_customer_owns(cust)
    return success(S.payment_out(payment))


@bp.get("/payments")
def list_payments():
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    limit, offset = parse_pagination()
    items = list(db.payments.values())
    if g.role == "Customer":
        owned = {a["id"] for a in db.rental_agreements.values()
                 if a["customer_id"] == g.user_id}
        owned_invoices = {i["id"] for i in db.invoices.values()
                          if i["rental_agreement_id"] in owned}
        items = [x for x in items if x["invoice_id"] in owned_invoices]
    invoice_id = request.args.get("invoice_id")
    if invoice_id is not None:
        items = [x for x in items if x["invoice_id"] == invoice_id]
    page, total = paginate(items, limit, offset)
    return list_response([S.payment_out(x) for x in page], limit, offset, total)
