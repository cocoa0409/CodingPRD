"""Customer routes + loyalty preview + test-driving loyalty injection
(PRD §3.2, §3.7, §3.9)."""

from flask import Blueprint, jsonify, request

import db
import errors
from errors import err
from middleware import require_roles
from response import object_response, array_response, _meta
from services import serialize
from services import pricing
from services.common import (
    get_body, require_fields, require_int, require_str, lookup, list_collection,
)

bp = Blueprint("customers", __name__)


@bp.post("/customers")
@require_roles("ShopStaff", "Customer")
def create_customer():
    body = get_body()
    require_fields(body, "shop_id", "email", "name")
    shop_id = require_str(body, "shop_id")
    lookup(db.shops, shop_id)
    email = require_str(body, "email")
    name = require_str(body, "name")

    rec = {
        "email": email,
        "name": name,
        "shop_id": shop_id,
        "completed_order_count": 0,
        "lifetime_paid_cents": 0,
        "loyalty_score": 0,
        "loyalty_tier": "NONE",
    }
    db.stamp_new(rec)
    db.customers[rec["id"]] = rec
    return object_response(serialize.customer(rec), 201)


@bp.get("/customers")
@require_roles("ShopStaff")
def list_customers():
    shop_id = request.args.get("shop_id")
    items, limit, offset, total = list_collection(
        db.customers, (lambda r: r["shop_id"] == shop_id) if shop_id else None)
    return array_response([serialize.customer(r) for r in items], limit, offset, total)


@bp.get("/customers/<customer_id>")
@require_roles("ShopStaff", "Customer")
def read_customer(customer_id):
    rec = lookup(db.customers, customer_id)
    return object_response(serialize.customer(rec), 200)


@bp.get("/customers/<customer_id>/loyalty-preview")
@require_roles("ShopStaff", "Customer")
def loyalty_preview(customer_id):
    cust = lookup(db.customers, customer_id)

    # Project forward as if confirmed-but-not-yet-fulfilled orders completed.
    projected_count = cust["completed_order_count"]
    projected_paid = cust["lifetime_paid_cents"]
    for order in db.orders.values():
        if order["customer_id"] != customer_id:
            continue
        if order["production_status"] in ("CONFIRMED", "IN_PRODUCTION", "READY"):
            projected_count += 1
            # Add spend only when not already realized into lifetime_paid_cents.
            if order["payment_status"] != "PAID":
                projected_paid += order["total_cents"]

    projected_score = pricing.compute_loyalty_score(projected_count, projected_paid)
    projected_tier = pricing.tier_for_score(projected_score)

    data = {
        "projected_loyalty_score": projected_score,
        "projected_loyalty_tier": projected_tier,
        "committed_loyalty_score": cust["loyalty_score"],
    }
    return object_response(data, 200)


# ---------------------------------------------------------------------------
# Test-driving: pin clock + inject loyalty (PRD §3.9, ShopStaff only).
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@require_roles("ShopStaff")
def set_clock():
    body = get_body()
    require_fields(body, "to_iso8601")
    to_iso = require_str(body, "to_iso8601")
    db.set_clock(to_iso)
    return object_response({"current_utc": db.current_utc()}, 200)


@bp.post("/_inject/customer-loyalty")
@require_roles("ShopStaff")
def inject_loyalty():
    body = get_body()
    require_fields(body, "customer_id", "completed_order_count",
                   "lifetime_paid_cents", "loyalty_score", "loyalty_tier")
    customer_id = require_str(body, "customer_id")
    cust = lookup(db.customers, customer_id)
    completed_order_count = require_int(body, "completed_order_count", min_value=0)
    lifetime_paid_cents = require_int(body, "lifetime_paid_cents", min_value=0)
    loyalty_score = body["loyalty_score"]
    if isinstance(loyalty_score, bool) or not isinstance(loyalty_score, (int, float)):
        raise err(errors.ERR_VALIDATION, "loyalty_score must be a number")
    loyalty_tier = body["loyalty_tier"]
    if loyalty_tier not in ("NONE", "SILVER", "GOLD"):
        raise err(errors.ERR_VALIDATION, "loyalty_tier must be NONE/SILVER/GOLD")

    cust["completed_order_count"] = completed_order_count
    cust["lifetime_paid_cents"] = lifetime_paid_cents
    cust["loyalty_score"] = loyalty_score
    cust["loyalty_tier"] = loyalty_tier
    db.touch(cust)
    return object_response(serialize.customer(cust), 200)
