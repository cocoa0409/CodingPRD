"""Invoice endpoints (PRD §3.8). Only ANNUAL_CERTIFICATION and REINSTATEMENT
are creatable here; PRODUCT_ADDITION and RENEWAL are auto-created by the
certificate add-products and renew flows."""
from datetime import timedelta

from flask import Blueprint, g

from db import logical_now, new_common, store, touch
from errors import err
from middleware import get_or_404, require_roles
from response import Paginator, created, ok
from services.domain import recompute_client_billed
from services.fees import REINSTATEMENT_FEE_CENTS
from validation import body_json, opt_str, req_enum, req_str

bp = Blueprint("invoices", __name__)

INVOICE_TYPES = ("ANNUAL_CERTIFICATION", "PRODUCT_ADDITION", "RENEWAL", "REINSTATEMENT")
INVOICE_DUE_DAYS = 30


def create_invoice(client_id, agreement_id, related_certificate_id,
                   invoice_type, subtotal_cents, discount_cents=0):
    """Shared invoice factory. due_date = creation instant + 30 days; a
    zero-total invoice is created directly PAID with paid_recorded_by
    'system'."""
    inv = new_common({
        "client_id": client_id,
        "agreement_id": agreement_id,
        "related_certificate_id": related_certificate_id,
        "invoice_type": invoice_type,
        "subtotal_cents": subtotal_cents,
        "discount_cents": discount_cents,
        "total_cents": subtotal_cents - discount_cents,
        "due_date": logical_now() + timedelta(days=INVOICE_DUE_DAYS),
        "paid_recorded_by": None,
        "status": "ISSUED",
    })
    if inv["total_cents"] == 0:
        inv["status"] = "PAID"
        inv["paid_recorded_by"] = "system"
    store.invoices[inv["id"]] = inv
    return inv


@bp.post("/invoices")
def create_invoice_endpoint():
    data = body_json()
    client_id = req_str(data, "client_id")
    invoice_type = req_enum(data, "invoice_type", INVOICE_TYPES)
    if invoice_type in ("PRODUCT_ADDITION", "RENEWAL"):
        err("ERR_INVALID_REQUEST",
            "PRODUCT_ADDITION and RENEWAL invoices are auto-created by the "
            "certificate add-products and renew flows")
    agreement_id = opt_str(data, "agreement_id")
    if invoice_type == "ANNUAL_CERTIFICATION" and agreement_id is None:
        err("ERR_INVALID_REQUEST",
            "ANNUAL_CERTIFICATION invoices require agreement_id")
    require_roles("AccountManager")
    client = get_or_404(store.clients, client_id, "Client")
    if invoice_type == "ANNUAL_CERTIFICATION":
        agreement = get_or_404(store.agreements, agreement_id, "Agreement")
        if agreement["client_id"] != client_id:
            err("ERR_CROSS_CLIENT_REFERENCE",
                "The named agreement belongs to a different client")
        if agreement["status"] != "ACTIVE":
            err("ERR_NO_ACTIVE_AGREEMENT",
                "ANNUAL_CERTIFICATION invoices require an ACTIVE agreement")
        if any(i for i in store.invoices.values()
               if i.get("agreement_id") == agreement_id
               and i["invoice_type"] == "ANNUAL_CERTIFICATION"
               and i["status"] != "VOID"):
            err("ERR_DUPLICATE_ANNUAL_INVOICE",
                "A non-VOID ANNUAL_CERTIFICATION invoice already exists for "
                "this agreement")
        amount = agreement["annual_fee_snapshot_cents"] or 0
        invoice = create_invoice(client_id, agreement_id, None,
                                 "ANNUAL_CERTIFICATION", amount)
    else:  # REINSTATEMENT
        if client["status"] != "SUSPENDED":
            err("ERR_CLIENT_INVALID_STATE",
                "REINSTATEMENT invoices are allowed only while the client is "
                "SUSPENDED")
        invoice = create_invoice(client_id, None, None, "REINSTATEMENT",
                                 REINSTATEMENT_FEE_CENTS)
    recompute_client_billed(client)
    return created(invoice)


@bp.get("/invoices")
def list_invoices():
    p = Paginator()
    rows = list(store.invoices.values())
    rows = p.filter(rows, "client_id")
    rows = p.filter(rows, "agreement_id")
    rows = p.filter(rows, "related_certificate_id")
    rows = p.filter(rows, "status")
    rows = p.filter(rows, "invoice_type")
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/invoices/<invoice_id>")
def get_invoice(invoice_id):
    return ok(get_or_404(store.invoices, invoice_id, "Invoice"))


@bp.post("/invoices/<invoice_id>/record-payment")
def record_payment(invoice_id):
    require_roles("AccountManager")
    invoice = get_or_404(store.invoices, invoice_id, "Invoice")
    if invoice["status"] not in ("ISSUED", "OVERDUE"):
        err("ERR_INVOICE_INVALID_STATE",
            "record-payment requires invoice status ISSUED or OVERDUE")
    invoice["status"] = "PAID"
    invoice["paid_recorded_by"] = g.user_id
    touch(invoice)
    return ok(invoice)


@bp.post("/invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    require_roles("AccountManager")
    invoice = get_or_404(store.invoices, invoice_id, "Invoice")
    if invoice["status"] not in ("ISSUED", "OVERDUE"):
        err("ERR_INVOICE_INVALID_STATE",
            "void requires invoice status ISSUED or OVERDUE")
    invoice["status"] = "VOID"
    touch(invoice)
    # The invoice leaves the billed set; compensate the ledger.
    client = store.clients.get(invoice["client_id"])
    if client is not None:
        recompute_client_billed(client)
    return ok(invoice)
