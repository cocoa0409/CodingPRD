"""Orders, fulfillments, and invoicing transitions."""
from datetime import timedelta
from decimal import Decimal as Dc

from flask import Blueprint, request

import errors
from db import store
from middleware import get_identity, require_role
from helpers import (
    get_body, require_fields, as_str, as_int, require_positive_number,
    parse_pagination, paginate, sort_by_created, new_record, touch, round_kg, D,
)
from response import object_response, array_response
from services import lookups, serializers
from services.orders import (
    build_order, derive_fulfillment_status, active_alloc_kg_for_product,
)
from services.inventory import recompute_roasted_lot, recompute_account_balance

bp = Blueprint("orders", __name__)


# ==========================================================================
# Orders
# ==========================================================================
@bp.post("/accounts/<aid>/orders")
def create_order(aid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "WholesaleBuyer"})
    lookups.assert_buyer_owns_account(role, user_id, aid)
    account = lookups.get_account(aid)
    body = get_body()
    require_fields(body, ["lines"])
    lines = body["lines"]
    if not isinstance(lines, list) or len(lines) == 0:
        raise errors.invalid_request("lines must be a non-empty array")

    resolved = []
    for line in lines:
        if not isinstance(line, dict):
            raise errors.invalid_request("each line must be an object")
        if "product_id" not in line or "qty_kg" not in line:
            raise errors.invalid_request("each line needs product_id and qty_kg")
        qty = require_positive_number(line["qty_kg"], "qty_kg")
        product = lookups.get_product(as_str(line["product_id"], "product_id"))
        if product["archived"]:
            raise errors.invalid_request("archived product may not be ordered")
        resolved.append({"product_id": product["id"], "qty_kg": round_kg(qty), "product": product})

    order = build_order(account, resolved, standing_order_id=None)
    return object_response(serializers.order_public(order), 201)


@bp.get("/accounts/<aid>/orders")
def list_account_orders(aid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    lookups.assert_buyer_owns_account(role, user_id, aid)
    lookups.get_account(aid)
    limit, offset = parse_pagination()
    items = [o for o in store.orders.values() if o["account_id"] == aid]
    items = _filter_orders(items)
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.order_public(o) for o in page], limit, offset, total)


@bp.get("/orders")
def list_orders():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    limit, offset = parse_pagination()
    items = list(store.orders.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        items = [o for o in items if o["account_id"] == account_id]
    items = _filter_orders(items)
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.order_public(o) for o in page], limit, offset, total)


def _filter_orders(items):
    fulfillment_status = request.args.get("fulfillment_status")
    billing_status = request.args.get("billing_status")
    standing_order_id = request.args.get("standing_order_id")
    if fulfillment_status is not None:
        items = [o for o in items if o["fulfillment_status"] == fulfillment_status]
    if billing_status is not None:
        items = [o for o in items if o["billing_status"] == billing_status]
    if standing_order_id is not None:
        items = [o for o in items if o.get("standing_order_id") == standing_order_id]
    return items


@bp.get("/orders/<oid>")
def get_order(oid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    rec = lookups.get_order(oid)
    lookups.assert_buyer_owns_account(role, user_id, rec["account_id"])
    return object_response(serializers.order_public(rec))


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "WholesaleBuyer"})
    rec = lookups.get_order(oid)
    lookups.assert_buyer_owns_account(role, user_id, rec["account_id"])
    # cancellation only while OPEN and UNBILLED (priority 6)
    if rec["fulfillment_status"] != "OPEN" or rec["billing_status"] != "UNBILLED":
        raise errors.invalid_state("order is not open and unbilled")

    rec["fulfillment_status"] = "CANCELLED"
    # cascade-cancel RESERVED fulfillments, releasing roasted-lot reservations
    for f in store.fulfillments.values():
        if f["order_id"] == rec["id"] and f["status"] == "RESERVED":
            f["status"] = "CANCELLED"
            touch(f)
            lot = store.roasted_lots[f["roasted_lot_id"]]
            recompute_roasted_lot(lot, bump=True)
    touch(rec)
    return object_response(serializers.order_public(rec), 200)


# ==========================================================================
# Invoicing
# ==========================================================================
@bp.post("/orders/<oid>/invoice")
def invoice_order(oid):
    _, role = get_identity()
    require_role(role, {"SalesRep"})
    order = lookups.get_order(oid)
    # state gate (priority 6): order must still be UNBILLED
    if order["billing_status"] != "UNBILLED":
        raise errors.invalid_state("order is already invoiced")
    # at least one fulfillment shipped (PARTIALLY_FULFILLED or FULFILLED) -> ERR_INVALID_STATE
    if order["fulfillment_status"] not in ("PARTIALLY_FULFILLED", "FULFILLED"):
        raise errors.invalid_state("order has not shipped anything to bill")

    account = store.accounts[order["account_id"]]
    recompute_account_balance(account)
    # credit gate (priority 13)
    projected = account["outstanding_balance_cents"] + order["total_cents"]
    if account["status"] != "ACTIVE" or projected > account["credit_limit_cents"]:
        raise errors.credit_limit_exceeded("credit ceiling exceeded or account not active")

    issued_at = store.clock()
    due_at = issued_at + timedelta(days=account["net_terms_days"])
    inv = new_record()
    inv.update({
        "account_id": account["id"],
        "order_id": order["id"],
        "amount_cents": order["total_cents"],
        "issued_at": issued_at,
        "due_at": due_at,
        "status": "ISSUED",
    })
    store.invoices[inv["id"]] = inv

    order["billing_status"] = "INVOICED"
    touch(order)
    recompute_account_balance(account, bump=True)
    return object_response(serializers.invoice_public(inv), 201)


# ==========================================================================
# Fulfillments
# ==========================================================================
@bp.post("/orders/<oid>/fulfillments")
def reserve_fulfillment(oid):
    _, role = get_identity()
    require_role(role, {"SalesRep"})
    order = lookups.get_order(oid)
    body = get_body()
    require_fields(body, ["product_id", "roasted_lot_id", "allocated_kg", "expected_roasted_lot_version"])
    allocated_kg = require_positive_number(body["allocated_kg"], "allocated_kg")
    expected_version = as_int(body["expected_roasted_lot_version"], "expected_roasted_lot_version")
    product = lookups.get_product(as_str(body["product_id"], "product_id"))
    lot = lookups.get_roasted_lot(as_str(body["roasted_lot_id"], "roasted_lot_id"))

    # state gate (priority 6): order must be OPEN or PARTIALLY_FULFILLED
    if order["fulfillment_status"] not in ("OPEN", "PARTIALLY_FULFILLED"):
        raise errors.invalid_state("order takes no new shipments")

    # product mismatch (priority 7): lot product == fulfillment product
    if lot["product_id"] != product["id"]:
        raise errors.product_mismatch("roasted lot is a different product")

    # the fulfillment product must correspond to an order line
    line = next((l for l in order["lines"] if l["product_id"] == product["id"]), None)
    if line is None:
        raise errors.product_mismatch("product is not on this order")

    account = store.accounts[order["account_id"]]
    tier = store.price_tiers[account["price_tier_id"]]

    # freshness gate (priority 8)
    age_days = _age_days(lot["roast_date"])
    effective_max = min(product["freshness_window_days"], tier["freshness_max_days"])
    if age_days > effective_max:
        raise errors.stale_roast("roasted lot exceeds the effective freshness ceiling")

    # roasted sufficiency + line over-allocation (priority 11)
    recompute_roasted_lot(lot)
    if D(allocated_kg) > D(lot["available_kg"]):
        raise errors.insufficient_roasted("not enough roasted stock available")
    already = active_alloc_kg_for_product(order, product["id"])
    if D(already) + D(allocated_kg) > D(line["qty_kg"]):
        raise errors.insufficient_roasted("allocation exceeds ordered quantity for the line")

    # OCC (priority 15) on roasted lot version
    if expected_version != lot["version"]:
        raise errors.stale_version("roasted lot version mismatch")

    rec = new_record()
    rec.update({
        "order_id": order["id"],
        "product_id": product["id"],
        "roasted_lot_id": lot["id"],
        "allocated_kg": round_kg(allocated_kg),
        "roast_date": lot["roast_date"],
        "status": "RESERVED",
    })
    store.fulfillments[rec["id"]] = rec
    # cascade to roasted lot (recompute + bump version)
    recompute_roasted_lot(lot, bump=True)
    # order version increments by one
    touch(order)
    return object_response(serializers.fulfillment_public(rec), 201)


def _age_days(roast_date):
    """Whole days between roast_date and the simulated clock, floored."""
    delta = store.clock() - roast_date
    seconds = delta.total_seconds()
    if seconds < 0:
        seconds = 0
    return int(seconds // 86400)


@bp.get("/orders/<oid>/fulfillments")
def list_order_fulfillments(oid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    order = lookups.get_order(oid)
    lookups.assert_buyer_owns_account(role, user_id, order["account_id"])
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [f for f in store.fulfillments.values() if f["order_id"] == oid]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.fulfillment_public(f) for f in page], limit, offset, total)


@bp.get("/fulfillments")
def list_fulfillments():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    limit, offset = parse_pagination()
    roasted_lot_id = request.args.get("roasted_lot_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    items = list(store.fulfillments.values())
    if roasted_lot_id is not None:
        items = [f for f in items if f["roasted_lot_id"] == roasted_lot_id]
    if product_id is not None:
        items = [f for f in items if f["product_id"] == product_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.fulfillment_public(f) for f in page], limit, offset, total)


@bp.get("/fulfillments/<fid>")
def get_fulfillment(fid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    rec = lookups.get_fulfillment(fid)
    order = store.orders[rec["order_id"]]
    lookups.assert_buyer_owns_account(role, user_id, order["account_id"])
    return object_response(serializers.fulfillment_public(rec))


@bp.post("/fulfillments/<fid>/ship")
def ship_fulfillment(fid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff"})
    rec = lookups.get_fulfillment(fid)
    if rec["status"] != "RESERVED":
        raise errors.invalid_state("fulfillment is not RESERVED")
    rec["status"] = "SHIPPED"
    touch(rec)
    # reservation becomes consumption: roasted lot on_hand falls; recompute + bump
    lot = store.roasted_lots[rec["roasted_lot_id"]]
    recompute_roasted_lot(lot, bump=True)
    # bubble up order fulfillment_status; order version increments
    order = store.orders[rec["order_id"]]
    order["fulfillment_status"] = derive_fulfillment_status(order)
    touch(order)
    return object_response(serializers.fulfillment_public(rec), 200)


@bp.post("/fulfillments/<fid>/cancel")
def cancel_fulfillment(fid):
    _, role = get_identity()
    require_role(role, {"SalesRep"})
    rec = lookups.get_fulfillment(fid)
    if rec["status"] != "RESERVED":
        raise errors.invalid_state("fulfillment is not RESERVED")
    rec["status"] = "CANCELLED"
    touch(rec)
    lot = store.roasted_lots[rec["roasted_lot_id"]]
    recompute_roasted_lot(lot, bump=True)
    order = store.orders[rec["order_id"]]
    touch(order)
    return object_response(serializers.fulfillment_public(rec), 200)
