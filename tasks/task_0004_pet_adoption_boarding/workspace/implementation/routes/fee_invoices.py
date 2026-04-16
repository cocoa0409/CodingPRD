from flask import Blueprint, request
from db import fee_invoices, now_iso
from errors import (
    raise_error,
    ERR_INVOICE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PAYMENT_AMOUNT_INVALID,
    ERR_INVOICE_HAS_PAYMENTS,
    ERR_INVOICE_ALREADY_SETTLED,
)
from middleware import require_roles, parse_pagination
from response import success_response, list_response
from services.fee_service import serialize_invoice

fee_invoices_bp = Blueprint("fee_invoices", __name__)


@fee_invoices_bp.route("/petcare/fee-invoices", methods=["GET"])
def list_invoices():
    require_roles("ShelterManager", "CaseWorker")
    limit, offset = parse_pagination()
    shelter_id = request.args.get("shelter_id")
    reference_type = request.args.get("reference_type")
    status = request.args.get("status")
    items = []
    for inv in fee_invoices.values():
        if shelter_id and inv["shelter_id"] != shelter_id:
            continue
        if reference_type and inv["reference_type"] != reference_type:
            continue
        if status and inv["status"] != status:
            continue
        items.append(inv)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_invoice(x) for x in page], total, limit, offset)


@fee_invoices_bp.route("/petcare/fee-invoices/<inv_id>", methods=["GET"])
def get_invoice(inv_id):
    require_roles("ShelterManager", "CaseWorker")
    inv = fee_invoices.get(inv_id)
    if not inv:
        raise_error(ERR_INVOICE_NOT_FOUND, "Invoice not found")
    return success_response(serialize_invoice(inv))


@fee_invoices_bp.route("/petcare/fee-invoices/<inv_id>/pay", methods=["POST"])
def pay_invoice(inv_id):
    require_roles("CaseWorker")
    inv = fee_invoices.get(inv_id)
    if not inv:
        raise_error(ERR_INVOICE_NOT_FOUND, "Invoice not found")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise_error(ERR_INVALID_STATE, "Invoice must be ISSUED or PARTIALLY_PAID")
    body = request.get_json(silent=True) or {}
    amount_cents = body.get("amount_cents")
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool):
        raise_error(ERR_PAYMENT_AMOUNT_INVALID, "amount_cents must be an integer")
    balance = max(0, inv["total_amount_cents"] - inv["paid_amount_cents"])
    if amount_cents <= 0 or amount_cents > balance:
        raise_error(ERR_PAYMENT_AMOUNT_INVALID, "amount_cents out of range")

    inv["paid_amount_cents"] += amount_cents
    if inv["paid_amount_cents"] >= inv["total_amount_cents"]:
        inv["status"] = "PAID"
        inv["paid_at"] = now_iso()
    else:
        inv["status"] = "PARTIALLY_PAID"
    inv["updated_at"] = now_iso()
    inv["version"] += 1
    return success_response(serialize_invoice(inv))


@fee_invoices_bp.route("/petcare/fee-invoices/<inv_id>/refund", methods=["POST"])
def refund_invoice(inv_id):
    require_roles("ShelterManager")
    inv = fee_invoices.get(inv_id)
    if not inv:
        raise_error(ERR_INVOICE_NOT_FOUND, "Invoice not found")
    if inv["status"] not in ("PAID", "PARTIALLY_PAID"):
        raise_error(ERR_INVALID_STATE, "Invoice must be PAID or PARTIALLY_PAID to refund")
    # Check settlement attachment
    batch_id = inv.get("settlement_batch_id")
    if batch_id:
        from db import settlement_batches
        batch = settlement_batches.get(batch_id)
        if batch and batch["status"] in ("APPROVED", "PAID"):
            raise_error(ERR_INVOICE_ALREADY_SETTLED,
                        "Invoice already settled")

    inv["refund_amount_cents"] = inv["paid_amount_cents"]
    inv["status"] = "REFUNDED"
    inv["refunded_at"] = now_iso()
    inv["updated_at"] = now_iso()
    inv["version"] += 1
    return success_response(serialize_invoice(inv))


@fee_invoices_bp.route("/petcare/fee-invoices/<inv_id>/void", methods=["POST"])
def void_invoice(inv_id):
    require_roles("ShelterManager")
    inv = fee_invoices.get(inv_id)
    if not inv:
        raise_error(ERR_INVOICE_NOT_FOUND, "Invoice not found")
    # A PARTIALLY_PAID invoice is "has payments" per the transition precondition
    # and the concurrency guarantee (POST /pay commits first -> void returns
    # ERR_INVOICE_HAS_PAYMENTS). PAID/REFUNDED/VOID are terminal-ish states
    # where no further void applies, so ERR_INVALID_STATE fires instead.
    if inv["status"] == "PARTIALLY_PAID":
        raise_error(ERR_INVOICE_HAS_PAYMENTS, "Invoice has payments")
    if inv["status"] not in ("DRAFT", "ISSUED"):
        raise_error(ERR_INVALID_STATE, "Invoice must be DRAFT or ISSUED to void")
    if inv.get("paid_amount_cents", 0) > 0:
        raise_error(ERR_INVOICE_HAS_PAYMENTS, "Invoice has payments")
    inv["status"] = "VOID"
    inv["updated_at"] = now_iso()
    inv["version"] += 1
    return success_response(serialize_invoice(inv))
