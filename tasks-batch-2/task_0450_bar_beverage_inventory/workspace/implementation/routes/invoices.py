"""Invoice endpoints (PRD §3.6)."""
from flask import Blueprint, request

import serialize
from db import db, stamp_create, touch
from errors import (ApiError, invalid_state, ERR_PRODUCT_NOT_ON_PO)
from clock import clock
from middleware import require_roles
from response import object_response, array_response
from routes.lookup import get_invoice, get_purchase_order, get_product
from services.calc import reconcile_invoice
from services.product import adjust_on_hand, propagate_unit_cost_change
from validate import (get_json_body, require, as_str, as_int, parse_pagination, paginate)

bp = Blueprint("invoices", __name__)


def _po_product_ids(poid):
    return {pl["product_id"] for pl in db.po_lines.values()
            if pl["purchase_order_id"] == poid}


@bp.route("/invoices", methods=["POST"])
@require_roles("PurchasingAgent")
def create_invoice():
    body = get_json_body()
    purchase_order_id = require(body, "purchase_order_id")
    vendor_invoice_no = as_str(require(body, "vendor_invoice_no"), "vendor_invoice_no")
    freight_cents = as_int(body.get("freight_cents", 0)
                           if body.get("freight_cents") is not None else 0,
                           "freight_cents", ge=0)
    # body FK existence (404)
    get_purchase_order(purchase_order_id)
    record = {
        "purchase_order_id": purchase_order_id,
        "vendor_invoice_no": vendor_invoice_no,
        "freight_cents": freight_cents,
        "status": "DRAFT",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "tax_cents": 0,
        "invoice_total_cents": 0,
    }
    stamp_create(record)
    db.invoices[record["id"]] = record
    return object_response(serialize.invoice(record), 201)


@bp.route("/invoices/<iid>", methods=["GET"])
@require_roles("PurchasingAgent", "InventoryManager")
def read_invoice(iid):
    inv = get_invoice(iid)
    return object_response(serialize.invoice(inv))


@bp.route("/invoices", methods=["GET"])
@require_roles("PurchasingAgent", "InventoryManager")
def list_invoices():
    limit, offset = parse_pagination()
    purchase_order_id = request.args.get("purchase_order_id")
    status = request.args.get("status")
    items = list(db.invoices.values())
    if purchase_order_id is not None:
        items = [inv for inv in items if inv["purchase_order_id"] == purchase_order_id]
    if status is not None:
        items = [inv for inv in items if inv["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.invoice(inv) for inv in page], limit, offset, total)


@bp.route("/invoices/<iid>/lines", methods=["POST"])
@require_roles("PurchasingAgent")
def add_invoice_line(iid):
    inv = get_invoice(iid)
    body = get_json_body()
    product_id = require(body, "product_id")
    received_qty = as_int(require(body, "received_qty"), "received_qty", gt=0)
    unit_cost_cents = as_int(require(body, "unit_cost_cents"), "unit_cost_cents", ge=0)
    # body FK existence (404)
    get_product(product_id)
    # state: lines added while DRAFT
    if inv["status"] != "DRAFT":
        raise invalid_state("Lines may only be added to a DRAFT invoice.")
    # business: product must appear on a POLine of the invoice's PO (422)
    if product_id not in _po_product_ids(inv["purchase_order_id"]):
        raise ApiError(ERR_PRODUCT_NOT_ON_PO, 422,
                       "Billed product is not present on any line of the order.")
    record = {
        "invoice_id": iid,
        "product_id": product_id,
        "received_qty": received_qty,
        "unit_cost_cents": unit_cost_cents,
        "extension_cents": 0,
    }
    stamp_create(record)
    db.invoice_lines[record["id"]] = record
    return object_response(serialize.invoice_line(record), 201)


@bp.route("/invoices/<iid>/lines", methods=["GET"])
@require_roles("PurchasingAgent", "InventoryManager")
def list_invoice_lines(iid):
    get_invoice(iid)
    limit, offset = parse_pagination()
    items = [il for il in db.invoice_lines.values() if il["invoice_id"] == iid]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.invoice_line(il) for il in page], limit, offset, total)


@bp.route("/invoices/<iid>/post", methods=["POST"])
@require_roles("PurchasingAgent")
def post_invoice(iid):
    inv = get_invoice(iid)
    po = db.purchase_orders.get(inv["purchase_order_id"])
    # state: invoice DRAFT, PO in {SUBMITTED, RECEIVED}
    if inv["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT invoice can be posted.")
    lines = [il for il in db.invoice_lines.values() if il["invoice_id"] == iid]
    if len(lines) < 1:
        raise invalid_state("An invoice must have at least one line to post.")
    if po is None or po["status"] not in ("SUBMITTED", "RECEIVED"):
        raise invalid_state("Invoice's purchase order must be SUBMITTED or RECEIVED to post.")
    # re-check product-on-PO (422)
    po_products = _po_product_ids(inv["purchase_order_id"])
    for il in lines:
        if il["product_id"] not in po_products:
            raise ApiError(ERR_PRODUCT_NOT_ON_PO, 422,
                           "Billed product is not present on any line of the order.")

    # reconcile (extensions -> subtotal -> discount -> tax -> total)
    reconcile_invoice(inv)

    # land cost + post stock per line
    affected_products = []
    for il in lines:
        product = db.products.get(il["product_id"])
        product["unit_cost_cents"] = int(il["unit_cost_cents"])
        adjust_on_hand(product, int(il["received_qty"]))  # bumps version + recompute needs_reorder
        affected_products.append(product["id"])
    # propagate landed-cost changes into recipe costs / pour-cost pct
    for pid in set(affected_products):
        propagate_unit_cost_change(pid)

    # record post time on the logical clock for depletion windows
    inv["_posted_at"] = clock.now()

    # cascade PO SUBMITTED -> RECEIVED on first posting
    if po["status"] == "SUBMITTED":
        po["status"] = "RECEIVED"
        touch(po)

    inv["status"] = "POSTED"
    touch(inv)
    return object_response(serialize.invoice(inv))


@bp.route("/invoices/<iid>/void", methods=["POST"])
@require_roles("PurchasingAgent")
def void_invoice(iid):
    inv = get_invoice(iid)
    po = db.purchase_orders.get(inv["purchase_order_id"])
    if inv["status"] == "DRAFT":
        inv["status"] = "VOID"
        touch(inv)
        return object_response(serialize.invoice(inv))
    if inv["status"] == "POSTED":
        # permitted only while referenced PO is not CLOSED
        if po is not None and po["status"] == "CLOSED":
            raise invalid_state("Cannot void a posted invoice whose order is CLOSED.")
        lines = [il for il in db.invoice_lines.values() if il["invoice_id"] == iid]
        affected_products = []
        for il in lines:
            product = db.products.get(il["product_id"])
            adjust_on_hand(product, -int(il["received_qty"]))  # reverse received stock
            affected_products.append(product["id"])
        # if this was the only POSTED invoice on the PO, revert RECEIVED -> SUBMITTED
        other_posted = [i for i in db.invoices.values()
                        if i["purchase_order_id"] == inv["purchase_order_id"]
                        and i["status"] == "POSTED" and i["id"] != iid]
        if po is not None and po["status"] == "RECEIVED" and len(other_posted) == 0:
            po["status"] = "SUBMITTED"
            touch(po)
        inv["_posted_at"] = None
        inv["status"] = "VOID"
        touch(inv)
        return object_response(serialize.invoice(inv))
    raise invalid_state("Only a DRAFT or POSTED invoice can be voided.")
