"""Invoices, adjustment lines and void cascades (PRD 3.7)."""

from flask import Blueprint, request

from db import store
from errors import invalid_state, not_found
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.calculations import job_downtime, recompute_invoice_totals
from util import get_body, list_paginated, req_field, touch

bp = Blueprint("invoices", __name__)

INVOICE_STATUSES = ["DRAFT", "ISSUED", "PAID", "VOID"]


def _get_invoice(invoice_id):
    invoice = store.invoices.get(invoice_id)
    if invoice is None:
        raise not_found("Invoice not found")
    return invoice


@bp.get("/v1/invoices")
def list_invoices():
    require_roles(ALL_ROLES)
    filters = {}
    for param in ("job_id", "status"):
        if request.args.get(param) is not None:
            filters[param] = request.args[param]
    page, limit, offset, total = list_paginated(store.invoices, filters,
                                                request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/invoices/<invoiceId>")
def get_invoice(invoiceId):
    require_roles(ALL_ROLES)
    return success_object(_get_invoice(invoiceId))


@bp.post("/v1/invoices/<invoiceId>/issue")
def issue_invoice(invoiceId):
    require_roles(["AccountManager"])
    invoice = _get_invoice(invoiceId)
    if invoice["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT invoice can be issued")
    invoice["status"] = "ISSUED"
    touch(invoice)
    return success_object(invoice)


@bp.post("/v1/invoices/<invoiceId>/mark-paid")
def mark_paid_invoice(invoiceId):
    require_roles(["AccountManager"])
    invoice = _get_invoice(invoiceId)
    if invoice["status"] != "ISSUED":
        raise invalid_state("Only an ISSUED invoice can be marked paid")
    invoice["status"] = "PAID"
    touch(invoice)
    return success_object(invoice)


@bp.post("/v1/invoices/<invoiceId>/void")
def void_invoice(invoiceId):
    require_roles(["AccountManager"])
    invoice = _get_invoice(invoiceId)
    if invoice["status"] not in ("DRAFT", "ISSUED"):
        raise invalid_state("Only a DRAFT or ISSUED invoice can be voided")
    invoice["status"] = "VOID"
    touch(invoice)
    # Cascade link 1: owning job INVOICED -> FIELD_COMPLETE.
    job = store.jobs.get(invoice["job_id"])
    if job is not None and job["execution_status"] == "INVOICED":
        job["execution_status"] = "FIELD_COMPLETE"
        touch(job)
    # Cascade link 2: downtime events billed via this invoice revert to CLOSED.
    for d in job_downtime(invoice["job_id"]):
        if d["status"] == "BILLED" and d["invoice_id"] == invoiceId:
            d["status"] = "CLOSED"
            d["invoice_id"] = None
            touch(d)
    return success_object(invoice)


@bp.post("/v1/invoices/<invoiceId>/lines")
def add_invoice_line(invoiceId):
    require_roles(["AccountManager"])
    body = get_body()
    description = req_field(body, "description")
    amount_cents = req_field(body, "amount_cents", kind="int")
    invoice = _get_invoice(invoiceId)
    if invoice["status"] != "DRAFT":
        raise invalid_state("Lines can only be added to a DRAFT invoice")
    line = {
        "line_id": "L%d" % (len(invoice["lines"]) + 1),
        "kind": "ADJUSTMENT",
        "description": description,
        "quantity": 1,
        "unit": "each",
        "rate_cents": amount_cents,
        "amount_cents": amount_cents,
        "discountable": False,
        "voided": False,
        "origin": "MANUAL",
    }
    invoice["lines"].append(line)
    recompute_invoice_totals(invoice)
    touch(invoice)
    return success_object(invoice, status=201)


@bp.post("/v1/invoices/<invoiceId>/lines/<lineId>/void")
def void_invoice_line(invoiceId, lineId):
    require_roles(["AccountManager"])
    invoice = _get_invoice(invoiceId)
    line = next((ln for ln in invoice["lines"] if ln["line_id"] == lineId), None)
    if line is None:
        raise not_found("Invoice line not found")
    if invoice["status"] != "DRAFT":
        raise invalid_state("Lines can only be voided on a DRAFT invoice")
    line["voided"] = True
    recompute_invoice_totals(invoice)
    touch(invoice)
    return success_object(invoice)
