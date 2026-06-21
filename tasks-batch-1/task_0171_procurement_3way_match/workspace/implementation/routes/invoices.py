"""Invoice + MatchException endpoints (PRD §3.6, §3.7)."""
from flask import Blueprint, request, g

import errors
from errors import ApiError
from db import db
from middleware import require_roles
from response import object_response, list_response
from services.common import (
    init_common, touch, public, get_body, require_fields, require_positive_int,
    invalid, parse_pagination, paginate, resolve,
)
from services.calculations import invoice_total
from services.matching import (
    evaluate_match, recompute_vendor_status, open_exception_count,
)

bp = Blueprint("invoices", __name__)

INVOICE_READ_ROLES = ("ProcurementAdmin", "Buyer", "Matcher", "PayablesClerk")
EXCEPTION_READ_ROLES = ("ProcurementAdmin", "Buyer", "Matcher", "PayablesClerk")


def _validate_invoice_lines(lines):
    if not isinstance(lines, list) or len(lines) == 0:
        invalid("lines must be a non-empty array")
    for l in lines:
        if not isinstance(l, dict):
            invalid("each line must be an object")
        if "sku" not in l or not isinstance(l["sku"], str) or l["sku"] == "":
            invalid("each line requires a sku")
        if "billed_qty" not in l:
            invalid("each line requires billed_qty")
        require_positive_int(l["billed_qty"], "billed_qty")
        if "billed_unit_price_cents" not in l:
            invalid("each line requires billed_unit_price_cents")
        require_positive_int(l["billed_unit_price_cents"], "billed_unit_price_cents")


@bp.route("/procurement/invoices", methods=["POST"])
@require_roles("PayablesClerk")
def create_invoice():
    body = get_body()
    require_fields(body, ["vendor_id", "purchase_order_id", "goods_receipt_id",
                          "invoice_number", "lines"])
    vendor = resolve(db.vendors, body["vendor_id"])
    resolve(db.purchase_orders, body["purchase_order_id"])
    resolve(db.goods_receipts, body["goods_receipt_id"])

    invoice_number = body["invoice_number"]
    if not isinstance(invoice_number, str) or invoice_number == "":
        invalid("invoice_number must be a non-empty string")
    _validate_invoice_lines(body["lines"])

    # invoice_number unique per vendor across all non-void invoices.
    for inv in db.invoices.values():
        if (inv["vendor_id"] == vendor["id"]
                and inv["invoice_number"] == invoice_number
                and inv["payment_status"] != "VOID"):
            invalid("invoice_number already used for this vendor")

    lines = [
        {"sku": l["sku"], "billed_qty": l["billed_qty"],
         "billed_unit_price_cents": l["billed_unit_price_cents"]}
        for l in body["lines"]
    ]
    rec = {
        "vendor_id": vendor["id"],
        "purchase_order_id": body["purchase_order_id"],
        "goods_receipt_id": body["goods_receipt_id"],
        "invoice_number": invoice_number,
        "lines": lines,
        "invoice_total_cents": invoice_total(lines),
        "match_status": "UNMATCHED",
        "payment_status": "PENDING",
    }
    init_common(rec)
    db.invoices[rec["id"]] = rec
    return object_response(public(rec), status=201)


@bp.route("/procurement/invoices/<iid>", methods=["GET"])
@require_roles(*INVOICE_READ_ROLES)
def get_invoice(iid):
    rec = resolve(db.invoices, iid)
    return object_response(public(rec))


@bp.route("/procurement/invoices", methods=["GET"])
@require_roles(*INVOICE_READ_ROLES)
def list_invoices():
    limit, offset = parse_pagination(request.args)
    f = request.args
    vendor_id = f.get("vendor_id")
    purchase_order_id = f.get("purchase_order_id")
    goods_receipt_id = f.get("goods_receipt_id")
    match_status = f.get("match_status")
    payment_status = f.get("payment_status")
    items = []
    for rec in db.invoices.values():
        if vendor_id is not None and rec["vendor_id"] != vendor_id:
            continue
        if purchase_order_id is not None and rec["purchase_order_id"] != purchase_order_id:
            continue
        if goods_receipt_id is not None and rec["goods_receipt_id"] != goods_receipt_id:
            continue
        if match_status is not None and rec["match_status"] != match_status:
            continue
        if payment_status is not None and rec["payment_status"] != payment_status:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/procurement/invoices/<iid>/match", methods=["POST"])
@require_roles("Matcher")
def match_invoice(iid):
    rec = resolve(db.invoices, iid)
    if rec["match_status"] != "UNMATCHED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Invoice is not UNMATCHED")

    receipt = db.goods_receipts.get(rec["goods_receipt_id"])
    if receipt is None or receipt["status"] != "POSTED":
        raise ApiError(errors.ERR_NO_RECEIPT, 409,
                       "No POSTED goods receipt for this invoice")

    po = db.purchase_orders.get(rec["purchase_order_id"])

    passed, reason, detail = evaluate_match(rec, po, receipt)
    if passed:
        rec["match_status"] = "MATCHED"
        touch(rec)
        return object_response(public(rec))

    # Fail: EXCEPTION + create MatchException + recompute vendor status.
    rec["match_status"] = "EXCEPTION"
    touch(rec)

    ex = {
        "invoice_id": rec["id"],
        "vendor_id": rec["vendor_id"],
        "reason": reason,
        "detail": detail,
        "status": "OPEN",
    }
    init_common(ex)
    db.match_exceptions[ex["id"]] = ex

    vendor = db.vendors.get(rec["vendor_id"])
    if vendor is not None:
        recompute_vendor_status(vendor)

    return object_response(public(rec))


@bp.route("/procurement/invoices/<iid>/approve-payment", methods=["POST"])
@require_roles("PayablesClerk")
def approve_payment(iid):
    rec = resolve(db.invoices, iid)
    if rec["payment_status"] != "PENDING":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Invoice payment is not PENDING")
    if rec["match_status"] != "MATCHED":
        raise ApiError(errors.ERR_INVOICE_NOT_MATCHED, 409,
                       "Invoice is not MATCHED")
    rec["payment_status"] = "APPROVED_FOR_PAY"
    touch(rec)
    return object_response(public(rec))


@bp.route("/procurement/invoices/<iid>/reject-payment", methods=["POST"])
@require_roles("PayablesClerk")
def reject_payment(iid):
    rec = resolve(db.invoices, iid)
    if rec["payment_status"] != "PENDING":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Invoice payment is not PENDING")
    rec["payment_status"] = "REJECTED"
    touch(rec)
    return object_response(public(rec))


@bp.route("/procurement/invoices/<iid>/pay", methods=["POST"])
@require_roles("PayablesClerk")
def pay_invoice(iid):
    rec = resolve(db.invoices, iid)
    if rec["payment_status"] != "APPROVED_FOR_PAY":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Invoice is not APPROVED_FOR_PAY")
    rec["payment_status"] = "PAID"
    touch(rec)
    return object_response(public(rec))


# -----------------------------------------------------------------------------
# MatchException
# -----------------------------------------------------------------------------
@bp.route("/procurement/match-exceptions/<eid>", methods=["GET"])
@require_roles(*EXCEPTION_READ_ROLES)
def get_match_exception(eid):
    rec = resolve(db.match_exceptions, eid)
    return object_response(public(rec))


@bp.route("/procurement/match-exceptions", methods=["GET"])
@require_roles(*EXCEPTION_READ_ROLES)
def list_match_exceptions():
    limit, offset = parse_pagination(request.args)
    invoice_id = request.args.get("invoice_id")
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    items = []
    for rec in db.match_exceptions.values():
        if invoice_id is not None and rec["invoice_id"] != invoice_id:
            continue
        if vendor_id is not None and rec["vendor_id"] != vendor_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


def _close_invoice_if_clear(invoice_id):
    """If no OPEN exception remains for the invoice, EXCEPTION -> MATCHED."""
    invoice = db.invoices.get(invoice_id)
    if invoice is None:
        return
    if invoice["match_status"] != "EXCEPTION":
        return
    remaining = any(
        ex["invoice_id"] == invoice_id and ex["status"] == "OPEN"
        for ex in db.match_exceptions.values()
    )
    if not remaining:
        invoice["match_status"] = "MATCHED"
        touch(invoice)


@bp.route("/procurement/match-exceptions/<eid>/resolve", methods=["POST"])
@require_roles("Matcher")
def resolve_match_exception(eid):
    rec = resolve(db.match_exceptions, eid)
    if rec["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Exception is not OPEN")
    rec["status"] = "RESOLVED"
    touch(rec)
    vendor = db.vendors.get(rec["vendor_id"])
    if vendor is not None:
        recompute_vendor_status(vendor)
    _close_invoice_if_clear(rec["invoice_id"])
    return object_response(public(rec))


@bp.route("/procurement/match-exceptions/<eid>/waive", methods=["POST"])
@require_roles("Matcher")
def waive_match_exception(eid):
    rec = resolve(db.match_exceptions, eid)
    # SOD (priority 5): matcher may not be the receipt poster.
    invoice = db.invoices.get(rec["invoice_id"])
    if invoice is not None:
        receipt = db.goods_receipts.get(invoice["goods_receipt_id"])
        if receipt is not None and g.user_id == receipt["posted_by_id"]:
            raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                           "Waiver must not be the receipt poster")
    if rec["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Exception is not OPEN")
    rec["status"] = "WAIVED"
    touch(rec)
    vendor = db.vendors.get(rec["vendor_id"])
    if vendor is not None:
        recompute_vendor_status(vendor)
    _close_invoice_if_clear(rec["invoice_id"])
    return object_response(public(rec))
