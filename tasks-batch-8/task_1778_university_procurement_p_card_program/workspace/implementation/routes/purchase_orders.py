"""Purchase orders, receipts (post/void), and invoice creation (PRD 3.5/3.6)."""

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    require_fk,
)
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_PO_NOT_RECEIVABLE,
    ERR_PO_NOT_CANCELLABLE,
    ERR_PO_NOT_INVOICABLE,
    ERR_PO_INVOICING_CLOSED,
    ERR_OVER_RECEIPT,
    ERR_INVOICE_LINE_UNKNOWN,
    ERR_RECEIPT_NOT_VOIDABLE,
)

bp = make_blueprint("purchase_orders")

RECEIPT_LINE_SPEC = {
    "line_no": {"type": "integer", "required": True, "min": 0},
    "quantity": {"type": "integer", "required": True, "min_exclusive": 0},
}

INVOICE_LINE_SPEC = {
    "line_no": {"type": "integer", "required": True, "min": 0},
    "quantity": {"type": "integer", "required": True, "min_exclusive": 0},
    "unit_price_cents": {"type": "integer", "required": True, "min": 0},
}


@bp.get("/purchase-orders")
def list_pos():
    authenticate(ROLES)
    limit, offset = pagination_params()
    items = db.all_of("purchase_orders")
    from flask import request
    for field in ("requisition_id", "vendor_id", "contract_id", "grant_id", "fulfillment_status"):
        if field in request.args:
            wanted = request.args.get(field)
            items = [p for p in items if (p.get(field) is not None and str(p.get(field)) == wanted)]
    if "match_status" in request.args:
        wanted = request.args.get("match_status")
        items = [p for p in items if svc.po_match_status(p) == wanted]
    page, total, has_more = paginate(items, limit, offset)
    return success_list([svc.po_public(p) for p in page], limit, offset, total, has_more)


@bp.get("/purchase-orders/<pid>")
def get_po(pid):
    authenticate(ROLES)
    po = require_fk("purchase_orders", pid)
    return success_obj(svc.po_public(po), 200)


@bp.post("/purchase-orders/<pid>/cancel")
def cancel_po(pid):
    """Cancel an untouched PO: releases the grant encumbrance (computed ledger)
    and returns the source requisition to APPROVED for re-issue."""
    authenticate(["Buyer"])
    po = require_fk("purchase_orders", pid)
    has_posted_receipts = bool(svc.posted_receipts_of_po(po["id"]))
    has_invoices = bool(svc.invoices_of_po(po["id"]))
    if po["fulfillment_status"] != "ISSUED" or has_posted_receipts or has_invoices:
        raise ApiError(ERR_PO_NOT_CANCELLABLE, 409, "cancel requires ISSUED with no POSTED receipts and no invoices")
    po["fulfillment_status"] = "CANCELLED"
    db.touch(po)
    req = db.get("requisitions", po["requisition_id"])
    if req is not None and req["status"] == "PO_ISSUED":
        req["status"] = "APPROVED"
        db.touch(req)
    return success_obj(svc.po_public(po), 200)


@bp.post("/purchase-orders/<pid>/receipts")
def post_receipt(pid):
    user_id, _ = authenticate(["ReceivingClerk"])
    po = require_fk("purchase_orders", pid)
    if po["fulfillment_status"] not in ("ISSUED", "PARTIALLY_RECEIVED"):
        raise ApiError(ERR_PO_NOT_RECEIVABLE, 409, "receipt requires fulfillment ISSUED or PARTIALLY_RECEIVED")
    body = body_json()
    check_shape(body, {"lines": {"type": "array", "items": RECEIPT_LINE_SPEC, "required": True}})
    lines = body["lines"]
    if not lines:
        raise ApiError(ERR_INVALID_REQUEST, 400, "lines must be non-empty")
    po_line_nos = {ln["line_no"] for ln in po["lines"]}
    for ln in lines:
        if ln["line_no"] not in po_line_nos:
            raise ApiError(ERR_INVALID_REQUEST, 400, "line_no does not exist on the purchase order")
    # p9 structural, atomic: cumulative POSTED + new must not exceed ordered.
    received = svc.received_qty_by_line(po["id"])
    ordered = {ln["line_no"]: ln["quantity"] for ln in po["lines"]}
    new_qty = {}
    for ln in lines:
        n = ln["line_no"]
        new_qty[n] = new_qty.get(n, 0) + ln["quantity"]
    for n, q in new_qty.items():
        if received.get(n, 0) + q > ordered[n]:
            raise ApiError(ERR_OVER_RECEIPT, 422, "cumulative received quantity would exceed the ordered quantity")
    receipt = db.new_entity("receipts", {
        "po_id": po["id"],
        "lines": [{"line_no": ln["line_no"], "quantity": ln["quantity"]} for ln in lines],
        "received_by": user_id,
        "received_at": db.logical_ts(),
        "status": "POSTED",
    })
    svc.recompute_fulfillment(po)
    db.touch(po)
    return success_obj(db.public(receipt), 201)


@bp.get("/purchase-orders/<pid>/receipts")
def list_receipts(pid):
    authenticate(ROLES)
    po = require_fk("purchase_orders", pid)
    limit, offset = pagination_params()
    page, total, has_more = paginate(svc.receipts_of_po(po["id"]), limit, offset)
    return success_list([db.public(r) for r in page], limit, offset, total, has_more)


@bp.post("/receipts/<rid>/void")
def void_receipt(rid):
    """The one operation touching both PO dimensions: recompute fulfillment,
    then re-match PAYABLE invoices (quantity check) to EXCEPTION/RECEIPT_VOIDED."""
    authenticate(["ReceivingClerk"])
    receipt = require_fk("receipts", rid)
    if receipt["status"] != "POSTED":
        raise ApiError(ERR_RECEIPT_NOT_VOIDABLE, 409, "void requires a POSTED receipt")
    receipt["status"] = "VOIDED"
    db.touch(receipt)
    po = db.get("purchase_orders", receipt["po_id"])
    if po is not None:
        svc.recompute_fulfillment(po)
        db.touch(po)
        svc.rematch_payable_invoices_after_void(po)
    return success_obj(db.public(receipt), 200)


@bp.post("/purchase-orders/<pid>/invoices")
def create_invoice(pid):
    """The three-way match runs immediately; the invoice is born PAYABLE or
    EXCEPTION. One open invoice per PO; PAID closes invoicing permanently."""
    authenticate(["APClerk"])
    po = require_fk("purchase_orders", pid)
    if po["fulfillment_status"] == "CANCELLED":
        raise ApiError(ERR_PO_NOT_INVOICABLE, 409, "invoice creation requires a non-CANCELLED PO")
    for inv in svc.invoices_of_po(po["id"]):
        if inv["status"] in ("PAYABLE", "EXCEPTION", "PAID"):
            raise ApiError(ERR_PO_INVOICING_CLOSED, 409, "an open or PAID invoice already exists for this PO")
    body = body_json()
    check_shape(body, {
        "invoice_number": {"type": "string", "required": True},
        "lines": {"type": "array", "items": INVOICE_LINE_SPEC, "required": True},
    })
    lines = body["lines"]
    if not lines:
        raise ApiError(ERR_INVALID_REQUEST, 400, "lines must be non-empty")
    po_line_nos = {ln["line_no"] for ln in po["lines"]}
    for ln in lines:
        if ln["line_no"] not in po_line_nos:
            raise ApiError(ERR_INVOICE_LINE_UNKNOWN, 422, "line_no is not present on the purchase order")
    match = svc.run_three_way_match(po, lines)
    invoice = db.new_entity("invoices", {
        "po_id": po["id"],
        "vendor_id": po["vendor_id"],
        "invoice_number": body["invoice_number"],
        "lines": [
            {"line_no": ln["line_no"], "quantity": ln["quantity"], "unit_price_cents": ln["unit_price_cents"]}
            for ln in lines
        ],
        "total_cents": sum(ln["quantity"] * ln["unit_price_cents"] for ln in lines),
        "total_variance_cents": match["total_variance_cents"],
        "total_tolerance_cents": match["total_tolerance_cents"],
        "status": match["status"],
        "exception_reason": match["exception_reason"],
        "variance_accepted_by": None,
        "paid_at": None,
    })
    return success_obj(db.public(invoice), 201)


@bp.get("/purchase-orders/<pid>/invoices")
def list_po_invoices(pid):
    authenticate(ROLES)
    po = require_fk("purchase_orders", pid)
    limit, offset = pagination_params()
    page, total, has_more = paginate(svc.invoices_of_po(po["id"]), limit, offset)
    return success_list([db.public(i) for i in page], limit, offset, total, has_more)
