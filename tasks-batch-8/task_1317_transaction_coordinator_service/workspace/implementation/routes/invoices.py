"""Invoices."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, touch, pub, pub_list, fmt_dt
from response import ok_object, ok_list

bp = Blueprint("invoices", __name__)


@bp.get("/tc/invoices/<invoiceId>")
def get_invoice(invoiceId):
    mw.auth()
    rec = mw.get_or_404("invoice", invoiceId)
    return ok_object(pub("invoice", rec))


@bp.get("/tc/invoices")
def list_invoices():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.invoices.values())
    recs = mw.filter_eq(recs, "file_id", request.args.get("file_id"))
    recs = mw.filter_eq(recs, "subscription_id", request.args.get("subscription_id"))
    recs = mw.filter_eq(recs, "status", request.args.get("status"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("invoice", page), limit, offset, total)


@bp.post("/tc/invoices/<invoiceId>/issue")
def issue_invoice(invoiceId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("invoice", invoiceId)
    file_rec = mw.own_file_chain(uid, rec, "invoice")
    if rec["status"] != "DRAFT":
        E.raise_err(E.ERR_INVOICE_INVALID_STATE, "Only a DRAFT invoice can be issued")
    if file_rec is None or file_rec["status"] not in ("ACTIVE", "CLOSED"):
        E.raise_err(E.ERR_FILE_NOT_ACTIVE, "Owning file must be ACTIVE or CLOSED")
    rec["status"] = "ISSUED"
    rec["issued_at"] = fmt_dt(store.now)
    touch(rec)
    return ok_object(pub("invoice", rec))


@bp.post("/tc/invoices/<invoiceId>/mark-paid")
def mark_paid(invoiceId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("invoice", invoiceId)
    mw.own_file_chain(uid, rec, "invoice")
    if rec["status"] != "ISSUED":
        E.raise_err(E.ERR_INVOICE_INVALID_STATE, "Only an ISSUED invoice can be marked paid")
    rec["status"] = "PAID"
    touch(rec)
    return ok_object(pub("invoice", rec))
