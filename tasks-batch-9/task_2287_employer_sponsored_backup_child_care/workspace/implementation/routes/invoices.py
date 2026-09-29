"""Employer invoice reads and the issue / pay / void lifecycle."""

from flask import Blueprint

from db import db
from errors import ApiError
from middleware import auth, json_body
from response import ok, paginate
from util import req_int_field, req_str

from services.core import s_invoice, s_invoice_line
from services.invoice import invoice_lines, issue_invoice, pay_invoice, void_invoice
from routes._common import LINE_TYPES, keep, need, qs_enum, qs_str

bp = Blueprint("invoices", __name__)

INVOICE_TERMINAL = ("PAID", "VOID")


@bp.get("/employer-invoices/<row_id>")
def get_invoice(row_id):
    auth("network_admin", "benefits_admin")
    invoice = need(db.employer_invoices, row_id, "ERR_EMPLOYERINVOICE_NOT_FOUND")
    return ok(s_invoice(invoice))


@bp.get("/employer-invoices/<row_id>/lines")
def get_invoice_lines(row_id):
    auth("network_admin", "benefits_admin")
    invoice = need(db.employer_invoices, row_id, "ERR_EMPLOYERINVOICE_NOT_FOUND")
    line_type = qs_enum("line_type", LINE_TYPES)
    employee_id = qs_str("employee_id")
    rows = invoice_lines(invoice["id"])
    rows = keep(rows, "line_type", line_type)
    rows = keep(rows, "employee_id", employee_id)
    return paginate(rows, s_invoice_line)


@bp.post("/employer-invoices/<row_id>/issue")
def issue(row_id):
    json_body()
    auth("network_admin")
    invoice = need(db.employer_invoices, row_id, "ERR_EMPLOYERINVOICE_NOT_FOUND")

    if invoice["invoice_status"] in INVOICE_TERMINAL:
        raise ApiError("ERR_EMPLOYERINVOICE_TERMINAL")
    if invoice["invoice_status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_STATE_INVALID")
    if invoice["line_count"] == 0 or invoice["total_cents"] == 0:
        raise ApiError("ERR_INVOICE_EMPTY")

    issue_invoice(invoice)
    return ok(s_invoice(invoice))


@bp.post("/employer-invoices/<row_id>/payment")
def payment(row_id):
    body = json_body()
    paid_amount_cents = req_int_field(body, "paid_amount_cents")

    auth("network_admin", "benefits_admin")
    invoice = need(db.employer_invoices, row_id, "ERR_EMPLOYERINVOICE_NOT_FOUND")

    if invoice["invoice_status"] in INVOICE_TERMINAL:
        raise ApiError("ERR_EMPLOYERINVOICE_TERMINAL")
    if invoice["invoice_status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_STATE_INVALID")
    if paid_amount_cents != invoice["total_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")

    pay_invoice(invoice, paid_amount_cents)
    return ok(s_invoice(invoice))


@bp.post("/employer-invoices/<row_id>/void")
def void(row_id):
    body = json_body()
    reason_code = req_str(body, "void_reason_code", 80)

    auth("network_admin")
    invoice = need(db.employer_invoices, row_id, "ERR_EMPLOYERINVOICE_NOT_FOUND")

    if invoice["invoice_status"] == "VOID":
        raise ApiError("ERR_EMPLOYERINVOICE_TERMINAL")
    if invoice["invoice_status"] == "PAID":
        raise ApiError("ERR_INVOICE_NOT_VOIDABLE")

    void_invoice(invoice, reason_code)
    return ok(s_invoice(invoice))
