"""Order routes: create (posture-gated, stock-reserved), get, list, and the two
parallel state dimensions — payment (pay/refund) and fulfillment
(confirm/deliver/cancel).
"""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, require_field, paginate_and_respond)
from lookups import get_order, get_campaign, get_seller
from services import validation, calc
from services.mutations import touch

bp = Blueprint("orders", __name__)


def _parse_lines(body):
    lines = require_field(body, "lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise errors.invalid_request("lines must be a non-empty array")
    parsed = []
    for line in lines:
        if not isinstance(line, dict):
            raise errors.invalid_request("each line must be an object")
        product_id = line.get("product_id")
        quantity = line.get("quantity")
        if not isinstance(product_id, str) or product_id == "":
            raise errors.invalid_request("each line must name a product_id")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise errors.invalid_request("each line quantity must be an integer")
        if quantity < 1:
            raise errors.invalid_request("each line quantity must be at least 1")
        parsed.append({"product_id": product_id, "quantity": quantity})
    return parsed


@bp.route("/fundraising/orders", methods=["POST"])
@require_roles("CampaignAdmin", "Seller")
def create_order():
    body = get_body()
    # priority 2 (RBAC ownership): Seller may only credit themselves.
    seller_id = require_str(body, "seller_id")
    validation.enforce_seller_ownership(seller_id)
    # priority 4: reference existence — campaign, seller, each product within campaign.
    campaign_id = require_str(body, "campaign_id")
    campaign = validation.resolve_campaign_ref(campaign_id)
    validation.resolve_seller_ref(seller_id, campaign_id)
    # priority 5: body shape (buyer fields + lines).
    buyer_name = require_str(body, "buyer_name")
    buyer_email = require_str(body, "buyer_email")
    lines = _parse_lines(body)
    products_by_id = {}
    for line in lines:
        if line["product_id"] not in products_by_id:
            products_by_id[line["product_id"]] = validation.resolve_product_ref(
                line["product_id"], campaign_id)
    with lock:
        # priority 8: posture gate — order create requires ACTIVE.
        validation.require_campaign_active_for_create(campaign)
        # priority 10: stock sufficiency, aggregated per product across this order's
        # lines, against available headroom (stock_qty - reserved_qty), inclusive.
        requested_per_product = {}
        for line in lines:
            requested_per_product[line["product_id"]] = \
                requested_per_product.get(line["product_id"], 0) + line["quantity"]
        for pid, requested in requested_per_product.items():
            product = products_by_id[pid]
            headroom = product["stock_qty"] - calc.compute_reserved_qty(product)
            if requested > headroom:
                raise errors.insufficient_stock(
                    "Requested %d units of product exceeds headroom %d" % (requested, headroom))
        gross, tax, total = calc.compute_order_totals(lines, products_by_id)
        oid = new_id()
        ts = now_ts()
        order = {
            "id": oid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "campaign_id": campaign_id,
            "seller_id": seller_id,
            "buyer_name": buyer_name,
            "buyer_email": buyer_email,
            "lines": lines,
            "payment_status": "PENDING",
            "fulfillment_status": "PLACED",
            "gross_cents": gross,
            "tax_cents": tax,
            "total_charged_cents": total,
            "receipt_number": None,
        }
        db.orders[oid] = order
    return success(serializers.order(order), status=201)


@bp.route("/fundraising/orders", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def list_orders():
    items = list(db.orders.values())
    campaign_id = request.args.get("campaign_id")
    seller_id = request.args.get("seller_id")
    payment_status = request.args.get("payment_status")
    fulfillment_status = request.args.get("fulfillment_status")
    if campaign_id is not None:
        items = [o for o in items if o["campaign_id"] == campaign_id]
    if seller_id is not None:
        items = [o for o in items if o["seller_id"] == seller_id]
    if payment_status is not None:
        items = [o for o in items if o["payment_status"] == payment_status]
    if fulfillment_status is not None:
        items = [o for o in items if o["fulfillment_status"] == fulfillment_status]
    return paginate_and_respond(items, serializers.order)


@bp.route("/fundraising/orders/<order_id>", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial", "Seller")
def get_order_route(order_id):
    o = get_order(order_id)
    validation.enforce_seller_reads_own(o["seller_id"])
    return success(serializers.order(o), status=200)


@bp.route("/fundraising/orders/<order_id>/pay", methods=["POST"])
@require_roles("CampaignAdmin")
def pay(order_id):
    o = get_order(order_id)
    campaign = get_campaign(o["campaign_id"])
    with lock:
        # priority 7: state legality.
        if o["payment_status"] != "PENDING":
            raise errors.invalid_state("Order must be PENDING to pay")
        # The order must not be CANCELLED on the fulfillment dimension.
        if o["fulfillment_status"] == "CANCELLED":
            raise errors.invalid_state("Cannot pay a CANCELLED order")
        # priority 8: posture gate (forward progress requires ACTIVE).
        validation.require_campaign_active(campaign)
        # priority 9: seller-block guard.
        seller = get_seller(o["seller_id"])
        if seller["status"] == "BLOCKED":
            raise errors.seller_blocked()
        o["payment_status"] = "PAID"
        o["receipt_number"] = db.next_receipt()
        touch(o)
    return success(serializers.order(o), status=200)


@bp.route("/fundraising/orders/<order_id>/confirm", methods=["POST"])
@require_roles("CampaignAdmin")
def confirm(order_id):
    o = get_order(order_id)
    campaign = get_campaign(o["campaign_id"])
    with lock:
        # priority 7: state legality (PLACED -> CONFIRMED requires PAID).
        if o["fulfillment_status"] != "PLACED":
            raise errors.invalid_state("Order fulfillment must be PLACED to confirm")
        if o["payment_status"] != "PAID":
            raise errors.invalid_state("Order must be PAID to confirm")
        # priority 8: posture gate.
        validation.require_campaign_active(campaign)
        o["fulfillment_status"] = "CONFIRMED"
        touch(o)
    return success(serializers.order(o), status=200)


@bp.route("/fundraising/orders/<order_id>/deliver", methods=["POST"])
@require_roles("CampaignAdmin")
def deliver(order_id):
    o = get_order(order_id)
    campaign = get_campaign(o["campaign_id"])
    with lock:
        # priority 7: state legality (CONFIRMED -> DELIVERED requires PAID).
        if o["fulfillment_status"] != "CONFIRMED":
            raise errors.invalid_state("Order fulfillment must be CONFIRMED to deliver")
        if o["payment_status"] != "PAID":
            raise errors.invalid_state("Order must be PAID to deliver")
        # priority 8: posture gate — deliver allowed in ACTIVE or CLOSED.
        if campaign["posture"] not in ("ACTIVE", "CLOSED"):
            raise errors.campaign_not_active(
                "Deliver requires campaign posture ACTIVE or CLOSED")
        o["fulfillment_status"] = "DELIVERED"
        touch(o)
    return success(serializers.order(o), status=200)


@bp.route("/fundraising/orders/<order_id>/cancel", methods=["POST"])
@require_roles("CampaignAdmin")
def cancel(order_id):
    o = get_order(order_id)
    with lock:
        # priority 7: state legality (cancel legal from PLACED or CONFIRMED).
        if o["fulfillment_status"] not in ("PLACED", "CONFIRMED"):
            raise errors.invalid_state("Order fulfillment must be PLACED or CONFIRMED to cancel")
        # priority 13: cannot cancel a PAID order — must refund instead.
        if o["payment_status"] == "PAID":
            raise errors.paid_order_not_cancellable()
        o["fulfillment_status"] = "CANCELLED"
        touch(o)
    return success(serializers.order(o), status=200)


@bp.route("/fundraising/orders/<order_id>/refund", methods=["POST"])
@require_roles("CampaignAdmin")
def refund(order_id):
    o = get_order(order_id)
    with lock:
        # priority 7: state legality (PAID -> REFUNDED).
        if o["payment_status"] != "PAID":
            raise errors.invalid_state("Order must be PAID to refund")
        o["payment_status"] = "REFUNDED"
        # Compensating fulfillment cancellation unless already DELIVERED/CANCELLED.
        if o["fulfillment_status"] not in ("DELIVERED", "CANCELLED"):
            o["fulfillment_status"] = "CANCELLED"
        touch(o)
    return success(serializers.order(o), status=200)
