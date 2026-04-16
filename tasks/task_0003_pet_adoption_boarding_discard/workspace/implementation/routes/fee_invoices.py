"""Fee invoice endpoints."""

from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request
import db
from db import now_iso
from middleware import require_role, get_pagination
from response import success_object, success_list
from errors import (raise_error, ERR_INVOICE_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_PAYMENT_AMOUNT_INVALID, ERR_INVOICE_HAS_PAYMENTS, ERR_INVALID_REQUEST)
from services.fees import recompute_shelter_revenue, _dec, _round2

bp = Blueprint("fee_invoices", __name__)


def serialize_invoice(inv):
    return {k: v for k, v in inv.items()}


@bp.route("/fee-invoices", methods=["GET"])
def list_invoices():
    require_role("ShelterManager", "CaseWorker")
    limit, offset = get_pagination()

    items = list(db.fee_invoices.values())
    shelter_id = request.args.get("shelter_id")
    reference_type = request.args.get("reference_type")
    status = request.args.get("status")
    if shelter_id:
        items = [i for i in items if i["shelter_id"] == shelter_id]
    if reference_type:
        items = [i for i in items if i["reference_type"] == reference_type]
    if status:
        items = [i for i in items if i["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_invoice(i) for i in page], total, limit, offset)


@bp.route("/fee-invoices/<invoiceId>", methods=["GET"])
def get_invoice(invoiceId):
    require_role("ShelterManager", "CaseWorker")
    invoice = db.fee_invoices.get(invoiceId)
    if not invoice:
        raise_error(ERR_INVOICE_NOT_FOUND, "Invoice not found")
    return success_object(serialize_invoice(invoice))


@bp.route("/fee-invoices/<invoiceId>/pay", methods=["POST"])
def pay_invoice(invoiceId):
    user_id, role = require_role("CaseWorker")
    invoice = db.fee_invoices.get(invoiceId)
    if not invoice:
        raise_error(ERR_INVOICE_NOT_FOUND, "Invoice not found")
    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise_error(ERR_INVALID_STATE, "Invoice must be ISSUED or PARTIALLY_PAID to accept payment")

    body = request.get_json(force=True, silent=True) or {}
    amount = body.get("amount")
    if amount is None:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: amount")

    amount_dec = _dec(amount)
    if amount_dec <= 0:
        raise_error(ERR_PAYMENT_AMOUNT_INVALID, "Payment amount must be positive")

    balance = _dec(invoice["total_amount"]) - _dec(invoice["paid_amount"]) + _dec(invoice.get("refund_amount", 0))
    if amount_dec > balance:
        raise_error(ERR_PAYMENT_AMOUNT_INVALID, "Payment amount exceeds balance due")

    new_paid = _round2(_dec(invoice["paid_amount"]) + amount_dec)
    invoice["paid_amount"] = float(new_paid)
    invoice["balance_due"] = float(_round2(_dec(invoice["total_amount"]) - new_paid + _dec(invoice.get("refund_amount", 0))))

    if new_paid >= _dec(invoice["total_amount"]):
        invoice["status"] = "PAID"
    else:
        invoice["status"] = "PARTIALLY_PAID"

    invoice["updated_at"] = now_iso()
    invoice["version"] += 1

    recompute_shelter_revenue(invoice["shelter_id"])
    return success_object(serialize_invoice(invoice))


@bp.route("/fee-invoices/<invoiceId>/refund", methods=["POST"])
def refund_invoice(invoiceId):
    user_id, role = require_role("ShelterManager")
    invoice = db.fee_invoices.get(invoiceId)
    if not invoice:
        raise_error(ERR_INVOICE_NOT_FOUND, "Invoice not found")
    if invoice["status"] not in ("PAID", "PARTIALLY_PAID"):
        raise_error(ERR_INVALID_STATE, "Invoice must be PAID or PARTIALLY_PAID to refund")

    invoice["refund_amount"] = invoice["paid_amount"]
    invoice["status"] = "REFUNDED"
    invoice["balance_due"] = float(_round2(_dec(invoice["total_amount"]) - _dec(invoice["paid_amount"]) + _dec(invoice["refund_amount"])))
    invoice["updated_at"] = now_iso()
    invoice["version"] += 1

    recompute_shelter_revenue(invoice["shelter_id"])
    return success_object(serialize_invoice(invoice))


@bp.route("/fee-invoices/<invoiceId>/void", methods=["POST"])
def void_invoice(invoiceId):
    user_id, role = require_role("ShelterManager")
    invoice = db.fee_invoices.get(invoiceId)
    if not invoice:
        raise_error(ERR_INVOICE_NOT_FOUND, "Invoice not found")
    if _dec(invoice.get("paid_amount", 0)) > 0:
        raise_error(ERR_INVOICE_HAS_PAYMENTS, "Cannot void invoice with payments")

    if invoice["status"] not in ("DRAFT", "ISSUED"):
        raise_error(ERR_INVALID_STATE, "Invoice must be DRAFT or ISSUED to void")

    invoice["status"] = "VOID"
    invoice["updated_at"] = now_iso()
    invoice["version"] += 1
    return success_object(serialize_invoice(invoice))
