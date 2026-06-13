"""Standing orders (subscriptions)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import store
from middleware import get_identity, require_role
from helpers import (
    get_body, require_fields, as_str, as_int, require_positive_number,
    parse_pagination, paginate, sort_by_created, new_record, touch,
)
from response import object_response, array_response
from services import lookups, serializers
from services.clock import parse_iso8601
from services.orders import build_order

bp = Blueprint("standing_orders", __name__)


@bp.post("/accounts/<aid>/standing-orders")
def create_standing_order(aid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "WholesaleBuyer"})
    lookups.assert_buyer_owns_account(role, user_id, aid)
    account = lookups.get_account(aid)
    body = get_body()
    require_fields(body, ["product_id", "qty_kg", "cadence_days", "next_release_at"])
    qty_kg = require_positive_number(body["qty_kg"], "qty_kg")
    cadence_days = as_int(body["cadence_days"], "cadence_days")
    if cadence_days not in (7, 14, 28):
        raise errors.invalid_request("cadence_days must be one of 7, 14, 28")
    next_release_at = parse_iso8601(body["next_release_at"])
    product = lookups.get_product(as_str(body["product_id"], "product_id"))

    rec = new_record()
    rec.update({
        "account_id": account["id"],
        "product_id": product["id"],
        "qty_kg": round(float(qty_kg), 3),
        "cadence_days": cadence_days,
        "next_release_at": next_release_at,
        "cycles_released": 0,
        "status": "ACTIVE",
    })
    store.standing_orders[rec["id"]] = rec
    return object_response(serializers.standing_order_public(rec), 201)


@bp.get("/accounts/<aid>/standing-orders")
def list_account_standing_orders(aid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    lookups.assert_buyer_owns_account(role, user_id, aid)
    lookups.get_account(aid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [s for s in store.standing_orders.values() if s["account_id"] == aid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.standing_order_public(s) for s in page], limit, offset, total)


@bp.get("/standing-orders")
def list_standing_orders():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    limit, offset = parse_pagination()
    product_id = request.args.get("product_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(store.standing_orders.values())
    if product_id is not None:
        items = [s for s in items if s["product_id"] == product_id]
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.standing_order_public(s) for s in page], limit, offset, total)


@bp.get("/standing-orders/<sid>")
def get_standing_order(sid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    rec = lookups.get_standing_order(sid)
    lookups.assert_buyer_owns_account(role, user_id, rec["account_id"])
    return object_response(serializers.standing_order_public(rec))


@bp.post("/standing-orders/<sid>/release")
def release_standing_order(sid):
    _, role = get_identity()
    require_role(role, {"SalesRep"})
    rec = lookups.get_standing_order(sid)
    # state gate (priority 6)
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("standing order is not ACTIVE")
    account = store.accounts[rec["account_id"]]
    product = store.products[rec["product_id"]]
    # product mismatch: archived product (priority 7, §3.2 -> ERR_PRODUCT_MISMATCH)
    if product["archived"]:
        raise errors.product_mismatch("subscribed product is archived")
    # §3.2: the owning account must be ACTIVE (not on credit hold). The catalog has
    # no dedicated error for this precondition, so it surfaces as ERR_INVALID_STATE.
    if account["status"] != "ACTIVE":
        raise errors.invalid_state("account is not ACTIVE")
    # release timing (priority 9)
    if store.clock() < rec["next_release_at"]:
        raise errors.release_not_due("release is not due yet")

    order = build_order(
        account,
        [{"product_id": product["id"], "qty_kg": rec["qty_kg"], "product": product}],
        standing_order_id=rec["id"],
    )
    rec["next_release_at"] = rec["next_release_at"] + timedelta(days=rec["cadence_days"])
    rec["cycles_released"] += 1
    touch(rec)
    return object_response(serializers.order_public(order), 201)


@bp.post("/standing-orders/<sid>/pause")
def pause_standing_order(sid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "WholesaleBuyer"})
    rec = lookups.get_standing_order(sid)
    lookups.assert_buyer_owns_account(role, user_id, rec["account_id"])
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("standing order is not ACTIVE")
    rec["status"] = "PAUSED"
    touch(rec)
    return object_response(serializers.standing_order_public(rec), 200)


@bp.post("/standing-orders/<sid>/resume")
def resume_standing_order(sid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "WholesaleBuyer"})
    rec = lookups.get_standing_order(sid)
    lookups.assert_buyer_owns_account(role, user_id, rec["account_id"])
    if rec["status"] != "PAUSED":
        raise errors.invalid_state("standing order is not PAUSED")
    rec["status"] = "ACTIVE"
    touch(rec)
    return object_response(serializers.standing_order_public(rec), 200)


@bp.post("/standing-orders/<sid>/cancel")
def cancel_standing_order(sid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "WholesaleBuyer"})
    rec = lookups.get_standing_order(sid)
    lookups.assert_buyer_owns_account(role, user_id, rec["account_id"])
    if rec["status"] not in ("ACTIVE", "PAUSED"):
        raise errors.invalid_state("standing order cannot be cancelled")
    rec["status"] = "CANCELLED"
    touch(rec)
    return object_response(serializers.standing_order_public(rec), 200)
