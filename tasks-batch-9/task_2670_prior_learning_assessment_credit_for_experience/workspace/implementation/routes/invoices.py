"""Fee invoices: reads, payments and waivers."""
from flask import Blueprint, request

from db import db, order_rows
from errors import ApiError
from middleware import (ROLE_COORDINATOR, ROLE_REGISTRAR, ROLE_STUDENT,
                        authenticate, scoped_invoice)
from response import ok, ok_list, read_pagination
from serializers import invoice_out
from services import invoice as invoice_service
from util import as_enum, as_int, as_str, json_body, require, touch

bp = Blueprint("invoices", __name__)

READ_ROLES = [ROLE_COORDINATOR, ROLE_REGISTRAR, ROLE_STUDENT]
PAY_ROLES = [ROLE_STUDENT, ROLE_COORDINATOR]
PAYABLE_STATUSES = ("INVOICED", "PARTIALLY_PAID")


def _sync(invoice):
    claim = db.claims.get(invoice["claim_id"])
    if claim is not None:
        invoice["fee_status"] = claim["fee_status"]
    return claim


@bp.get("/fee-invoices/<invoice_id>")
def read_invoice(invoice_id):
    ctx = authenticate(READ_ROLES)
    invoice = scoped_invoice(ctx, invoice_id)
    return ok(invoice_out(invoice))


@bp.get("/fee-invoices")
def list_invoices():
    authenticate(READ_ROLES)
    limit, offset = read_pagination()
    rows = list(db.invoices.values())
    for row in rows:
        _sync(row)
    for name in ("claim_id", "student_id", "fee_status"):
        wanted = request.args.get(name)
        if wanted is not None and wanted != "":
            rows = [r for r in rows if r.get(name) == wanted]
    rows = order_rows(rows, [(lambda r: r["created_at"], False)])
    return ok_list(rows, invoice_out, limit, offset)


@bp.post("/fee-invoices/<invoice_id>/payments")
def pay_invoice(invoice_id):
    ctx = authenticate(PAY_ROLES)
    invoice = scoped_invoice(ctx, invoice_id)
    body = json_body()
    amount = as_int(require(body, "amount_cents"), "amount_cents", 1)
    method = as_enum(require(body, "method"), "method", invoice_service.PAYMENT_METHODS)
    claim = _sync(invoice)
    # rung 19
    if claim is None or claim["fee_status"] not in PAYABLE_STATUSES:
        raise ApiError("ERR_INVOICE_NOT_PAYABLE")
    if invoice["balance_due_cents"] <= 0:
        raise ApiError("ERR_INVOICE_NOT_PAYABLE")
    # rung 40
    if method == "FINANCIAL_AID":
        raise ApiError("ERR_AID_NOT_APPLICABLE")
    # rung 41
    if amount > invoice["balance_due_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    student = db.students.get(invoice["student_id"])
    invoice_service.apply_payment(claim, invoice, student, amount)
    return ok(invoice_out(invoice))


@bp.post("/fee-invoices/<invoice_id>/waive")
def waive_invoice(invoice_id):
    ctx = authenticate([ROLE_COORDINATOR])
    invoice = scoped_invoice(ctx, invoice_id)
    body = json_body()
    as_str(require(body, "waive_reason"), "waive_reason", 1)
    claim = _sync(invoice)
    # rung 19
    if claim is None or claim["fee_status"] not in PAYABLE_STATUSES:
        raise ApiError("ERR_INVOICE_NOT_PAYABLE")

    student = db.students.get(invoice["student_id"])
    invoice_service.waive(claim, invoice, student)
    return ok(invoice_out(invoice))
