"""Purchase order endpoints (PRD §3.5)."""
from flask import Blueprint, request

import serialize
from db import db, stamp_create, touch
from errors import ApiError, invalid_state, ERR_SHORT_RECEIPT
from middleware import require_roles
from money import D
from response import object_response, array_response
from routes.lookup import get_purchase_order, get_product
from validate import (get_json_body, require, as_str, as_int, parse_pagination, paginate)
from timeutil import parse_iso

bp = Blueprint("purchase_orders", __name__)


@bp.route("/purchase-orders", methods=["POST"])
@require_roles("PurchasingAgent")
def create_purchase_order():
    body = get_json_body()
    vendor_name = as_str(require(body, "vendor_name"), "vendor_name")
    expected_at_raw = require(body, "expected_at")
    parse_iso(expected_at_raw, "expected_at")
    record = {
        "vendor_name": vendor_name,
        "expected_at": expected_at_raw,
        "status": "DRAFT",
        "ordered_total_cents": 0,
    }
    stamp_create(record)
    db.purchase_orders[record["id"]] = record
    return object_response(serialize.purchase_order(record), 201)


@bp.route("/purchase-orders/<poid>", methods=["GET"])
@require_roles("PurchasingAgent", "InventoryManager")
def read_purchase_order(poid):
    po = get_purchase_order(poid)
    return object_response(serialize.purchase_order(po))


@bp.route("/purchase-orders", methods=["GET"])
@require_roles("PurchasingAgent", "InventoryManager")
def list_purchase_orders():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = list(db.purchase_orders.values())
    if status is not None:
        items = [po for po in items if po["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.purchase_order(po) for po in page], limit, offset, total)


@bp.route("/purchase-orders/<poid>/lines", methods=["POST"])
@require_roles("PurchasingAgent")
def add_po_line(poid):
    po = get_purchase_order(poid)
    body = get_json_body()
    product_id = require(body, "product_id")
    ordered_qty = as_int(require(body, "ordered_qty"), "ordered_qty", gt=0)
    unit_cost_cents = as_int(require(body, "unit_cost_cents"), "unit_cost_cents", ge=0)
    # body FK existence (404)
    get_product(product_id)
    # state: lines added while DRAFT
    if po["status"] != "DRAFT":
        raise invalid_state("Order lines may only be added to a DRAFT purchase order.")
    record = {
        "purchase_order_id": poid,
        "product_id": product_id,
        "ordered_qty": ordered_qty,
        "unit_cost_cents": unit_cost_cents,
    }
    stamp_create(record)
    db.po_lines[record["id"]] = record
    return object_response(serialize.po_line(record), 201)


@bp.route("/purchase-orders/<poid>/lines", methods=["GET"])
@require_roles("PurchasingAgent", "InventoryManager")
def list_po_lines(poid):
    get_purchase_order(poid)
    limit, offset = parse_pagination()
    items = [pl for pl in db.po_lines.values() if pl["purchase_order_id"] == poid]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.po_line(pl) for pl in page], limit, offset, total)


@bp.route("/purchase-orders/<poid>/submit", methods=["POST"])
@require_roles("PurchasingAgent")
def submit_purchase_order(poid):
    po = get_purchase_order(poid)
    if po["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT purchase order can be submitted.")
    lines = [pl for pl in db.po_lines.values() if pl["purchase_order_id"] == poid]
    if len(lines) < 1:
        raise invalid_state("A purchase order must have at least one line to submit.")
    for pl in lines:
        product = db.products.get(pl["product_id"])
        if product is None or product["status"] != "ACTIVE":
            raise invalid_state("Every order line product must be ACTIVE to submit.")
    total = sum(int(pl["ordered_qty"]) * int(pl["unit_cost_cents"]) for pl in lines)
    po["ordered_total_cents"] = total
    po["status"] = "SUBMITTED"
    touch(po)
    return object_response(serialize.purchase_order(po))


def _posted_invoices_for_po(poid):
    return [inv for inv in db.invoices.values()
            if inv["purchase_order_id"] == poid and inv["status"] == "POSTED"]


@bp.route("/purchase-orders/<poid>/close", methods=["POST"])
@require_roles("PurchasingAgent")
def close_purchase_order(poid):
    po = get_purchase_order(poid)
    if po["status"] != "RECEIVED":
        raise invalid_state("Only a RECEIVED purchase order can be closed.")
    # short-receipt check (422): received per product across posted invoices
    # must cover ordered per product.
    ordered_by_product = {}
    for pl in db.po_lines.values():
        if pl["purchase_order_id"] == poid:
            ordered_by_product[pl["product_id"]] = \
                ordered_by_product.get(pl["product_id"], 0) + int(pl["ordered_qty"])
    received_by_product = {}
    for inv in _posted_invoices_for_po(poid):
        for il in db.invoice_lines.values():
            if il["invoice_id"] == inv["id"]:
                received_by_product[il["product_id"]] = \
                    received_by_product.get(il["product_id"], 0) + int(il["received_qty"])
    for pid, ordered_qty in ordered_by_product.items():
        if received_by_product.get(pid, 0) < ordered_qty:
            raise ApiError(ERR_SHORT_RECEIPT, 422,
                           "Received quantities do not cover ordered quantities for every product.")
    po["status"] = "CLOSED"
    touch(po)
    return object_response(serialize.purchase_order(po))


@bp.route("/purchase-orders/<poid>/cancel", methods=["POST"])
@require_roles("PurchasingAgent")
def cancel_purchase_order(poid):
    po = get_purchase_order(poid)
    if po["status"] == "DRAFT":
        po["status"] = "CANCELLED"
        touch(po)
        return object_response(serialize.purchase_order(po))
    if po["status"] == "SUBMITTED":
        if _posted_invoices_for_po(poid):
            raise invalid_state("Cannot cancel a SUBMITTED order with a posted invoice.")
        po["status"] = "CANCELLED"
        touch(po)
        return object_response(serialize.purchase_order(po))
    raise invalid_state("Only a DRAFT or SUBMITTED order can be cancelled.")
