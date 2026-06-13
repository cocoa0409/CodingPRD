"""Fulfillment routes (PRD §3.7)."""

from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services import serialize
from services import pricing
from services.ownership import require_order_owner
from services.common import (
    get_body, require_fields, require_int, require_str, lookup, list_collection,
)

bp = Blueprint("fulfillments", __name__)


@bp.post("/fulfillments")
@require_roles("ShopStaff", "Customer")
def create_fulfillment():
    body = get_body()
    require_fields(body, "order_id", "method")
    order_id = require_str(body, "order_id")
    order = lookup(db.orders, order_id)
    require_order_owner(order)

    method = body.get("method")
    if method not in ("PICKUP", "SHIP"):
        raise err(errors.ERR_VALIDATION, "method must be PICKUP or SHIP")

    ship_address = body.get("ship_address")
    ship_fee_cents = body.get("ship_fee_cents", 0)
    if ship_fee_cents is None:
        ship_fee_cents = 0
    if isinstance(ship_fee_cents, bool) or not isinstance(ship_fee_cents, int):
        raise err(errors.ERR_VALIDATION, "ship_fee_cents must be an integer")

    # Field rules (ERR_FULFILLMENT_FIELDS_INVALID, 422):
    #   SHIP -> ship_address present AND ship_fee_cents > 0
    #   PICKUP -> no ship_address AND ship_fee_cents == 0
    if method == "SHIP":
        if not ship_address or ship_fee_cents <= 0:
            raise err(errors.ERR_FULFILLMENT_FIELDS_INVALID,
                      "SHIP requires ship_address and ship_fee_cents > 0")
    else:  # PICKUP
        if ship_address not in (None, "") or ship_fee_cents != 0:
            raise err(errors.ERR_FULFILLMENT_FIELDS_INVALID,
                      "PICKUP must carry no address and ship_fee_cents == 0")
        ship_address = None

    rec = {
        "order_id": order_id,
        "method": method,
        "ship_address": ship_address,
        "ship_fee_cents": ship_fee_cents,
        "status": "SCHEDULED",
    }
    db.stamp_new(rec)
    db.fulfillments[rec["id"]] = rec
    return object_response(serialize.fulfillment(rec), 201)


@bp.get("/fulfillments")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def list_fulfillments():
    order_id = request.args.get("order_id")
    items, limit, offset, total = list_collection(
        db.fulfillments,
        (lambda r: r["order_id"] == order_id) if order_id else None)
    return array_response([serialize.fulfillment(r) for r in items], limit, offset, total)


@bp.get("/fulfillments/<fulfillment_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_fulfillment(fulfillment_id):
    rec = lookup(db.fulfillments, fulfillment_id)
    return object_response(serialize.fulfillment(rec), 200)


@bp.post("/fulfillments/<fulfillment_id>/hand-off")
@require_roles("ShopStaff")
def hand_off(fulfillment_id):
    ful = lookup(db.fulfillments, fulfillment_id)
    order = lookup(db.orders, ful["order_id"])

    # Permitted only when order READY and PAID (PRD §3.7).
    if ful["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Fulfillment is not SCHEDULED")
    if order["production_status"] != "READY" or order["payment_status"] != "PAID":
        raise err(errors.ERR_INVALID_STATE,
                  "Order must be READY and PAID to hand off")

    ful["status"] = "HANDED_OFF"
    db.touch(ful)

    # Order READY -> FULFILLED.
    order["production_status"] = "FULFILLED"
    db.touch(order)

    # Loyalty settlement: increment completed_order_count, recompute committed score/tier.
    cust = db.customers.get(order["customer_id"])
    if cust is not None:
        cust["completed_order_count"] += 1
        cust["loyalty_score"] = pricing.compute_loyalty_score(
            cust["completed_order_count"], cust["lifetime_paid_cents"])
        cust["loyalty_tier"] = pricing.tier_for_score(cust["loyalty_score"])
        db.touch(cust)

    return object_response(serialize.fulfillment(ful), 200)
