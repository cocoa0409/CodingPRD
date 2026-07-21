from flask import Blueprint, request

import store
import ledger
from calc import TIER_RANK
from common import (
    authorize, get_json, need, as_str, as_int,
    require_found, check_owner, parse_pagination, paginate,
)
from envelope import object_response, array_response
from errors import err

bp = Blueprint("preorders", __name__)

ACTIVE_ALLOC = ("PENDING", "WAITLISTED", "ALLOCATED")


def _find_held_allocation(pre_order_id):
    for a in store.allocations.values():
        if a["pre_order_id"] == pre_order_id and a["status"] == "HELD":
            return a
    return None


def _grant_allocation(pre_order, stock):
    """Create a HELD Allocation and move one unit available -> allocated."""
    alloc = store.make_record({
        "pre_order_id": pre_order["id"],
        "product_stock_id": stock["id"],
        "status": "HELD",
    })
    store.allocations[alloc["id"]] = alloc
    stock["available_count"] -= 1
    stock["allocated_count"] += 1
    return alloc


def _select_promotion(stock):
    """Waitlist promotion selector: WAITLISTED pre-orders on this pool, ranked by
    member tier rank DESC then created_at ASC (_seq is creation order)."""
    cands = [
        p for p in store.pre_orders.values()
        if p["product_stock_id"] == stock["id"] and p["allocation_status"] == "WAITLISTED"
    ]
    if not cands:
        return None
    cands.sort(key=lambda p: (-TIER_RANK[store.members[p["member_id"]]["tier"]], p["_seq"]))
    return cands[0]


@bp.post("/pre-orders")
def create_pre_order():
    _, role = authorize(["Member", "Clerk", "Manager"])
    body = get_json()
    # Priority 3: existence of provided body FKs (before schema).
    mid = body.get("member_id")
    if mid is not None and mid not in store.members:
        raise err("ERR_NOT_FOUND", "member_id does not exist")
    sid = body.get("product_stock_id")
    if sid is not None and sid not in store.product_stocks:
        raise err("ERR_NOT_FOUND", "product_stock_id does not exist")
    # Priority 4: schema.
    member_id = as_str(need(body, "member_id"), "member_id")
    product_stock_id = as_str(need(body, "product_stock_id"), "product_stock_id")
    expected_version = as_int(
        need(body, "expected_product_stock_version"), "expected_product_stock_version")
    member = store.members[member_id]
    stock = store.product_stocks[product_stock_id]
    # Priority 5: ownership.
    check_owner(role, request.headers.get("X-User-ID"), member_id)
    # Priority 9: optimistic concurrency (before one-active check).
    if expected_version != stock["version"]:
        raise err("ERR_STALE_VERSION", "expected_product_stock_version is stale")
    # Priority 15: at most one active pre-order per (member, pool).
    for p in store.pre_orders.values():
        if (p["member_id"] == member_id and p["product_stock_id"] == product_stock_id
                and p["allocation_status"] in ACTIVE_ALLOC):
            raise err("ERR_ONE_ACTIVE_PREORDER", "Member already has an active pre-order for this pool")
    # Resolve allocation dimension immediately.
    can_allocate = stock["release_state"] == "RELEASED" and stock["available_count"] >= 1
    po = store.make_record({
        "member_id": member_id,
        "product_stock_id": product_stock_id,
        "amount_paid_cents": 0,
        "payment_status": "UNPAID",
        "allocation_status": "ALLOCATED" if can_allocate else "WAITLISTED",
    })
    store.pre_orders[po["id"]] = po
    if can_allocate:
        _grant_allocation(po, stock)
    store.touch(stock)  # every successful create advances the pool version by one
    return object_response(store.serialize(po), 201)


@bp.get("/pre-orders/<pid>")
def get_pre_order(pid):
    authorize(["Member", "Clerk", "Manager"])
    po = require_found(store.pre_orders, pid)
    return object_response(store.serialize(po), 200)


@bp.get("/pre-orders")
def list_pre_orders():
    authorize(["Member", "Clerk", "Manager"])
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    product_stock_id = request.args.get("product_stock_id")
    matching = list(store.pre_orders.values())
    if member_id is not None:
        matching = [p for p in matching if p["member_id"] == member_id]
    if product_stock_id is not None:
        matching = [p for p in matching if p["product_stock_id"] == product_stock_id]
    window, total = paginate(matching, limit, offset)
    return array_response([store.serialize(p) for p in window], limit, offset, total)


@bp.get("/pre-orders/<pid>/allocations")
def list_pre_order_allocations(pid):
    authorize(["Member", "Clerk", "Manager"])
    require_found(store.pre_orders, pid)
    limit, offset = parse_pagination()
    matching = [a for a in store.allocations.values() if a["pre_order_id"] == pid]
    window, total = paginate(matching, limit, offset)
    return array_response([store.serialize(a) for a in window], limit, offset, total)


@bp.post("/pre-orders/<pid>/payments")
def record_payment(pid):
    _, role = authorize(["Member", "Clerk", "Manager"])
    po = require_found(store.pre_orders, pid)
    check_owner(role, request.headers.get("X-User-ID"), po["member_id"])
    body = get_json()
    amount = as_int(need(body, "amount_cents"), "amount_cents")
    if po["payment_status"] == "REFUNDED":
        raise err("ERR_INVALID_STATE", "Pre-order payment is REFUNDED")
    stock = store.product_stocks[po["product_stock_id"]]
    unit_price = stock["unit_price_cents"]
    deposit = stock["deposit_cents"]
    new_total = po["amount_paid_cents"] + amount
    if amount <= 0:
        raise err("ERR_INSUFFICIENT_PAYMENT", "Payment amount must be positive")
    if new_total > unit_price:
        raise err("ERR_INSUFFICIENT_PAYMENT", "Cumulative payment would exceed unit price")
    if po["amount_paid_cents"] == 0 and new_total < deposit:
        raise err("ERR_INSUFFICIENT_PAYMENT", "First payment must reach the deposit")
    po["amount_paid_cents"] = new_total
    if new_total >= unit_price:
        po["payment_status"] = "PAID_IN_FULL"
    elif new_total >= deposit:
        po["payment_status"] = "DEPOSIT_PAID"
    store.touch(po)
    return object_response(store.serialize(po), 200)


@bp.post("/pre-orders/<pid>/fulfill")
def fulfill(pid):
    authorize(["Clerk", "Manager"])
    po = require_found(store.pre_orders, pid)
    if po["allocation_status"] != "ALLOCATED" or po["payment_status"] != "PAID_IN_FULL":
        raise err("ERR_ALLOCATION_NOT_READY", "Pre-order is not allocated and fully paid")
    stock = store.product_stocks[po["product_stock_id"]]
    alloc = _find_held_allocation(po["id"])
    po["allocation_status"] = "FULFILLED"
    if alloc is not None:
        alloc["status"] = "CONSUMED"
        store.touch(alloc)
    stock["allocated_count"] -= 1
    stock["fulfilled_count"] += 1
    store.touch(stock)
    store.touch(po)
    return object_response(store.serialize(po), 200)


@bp.post("/pre-orders/<pid>/cancel")
def cancel(pid):
    _, role = authorize(["Member", "Clerk", "Manager"])
    po = require_found(store.pre_orders, pid)
    check_owner(role, request.headers.get("X-User-ID"), po["member_id"])
    if po["allocation_status"] not in ACTIVE_ALLOC:
        raise err("ERR_INVALID_STATE", "Pre-order cannot be cancelled from its current state")
    stock = store.product_stocks[po["product_stock_id"]]
    if po["allocation_status"] == "ALLOCATED":
        # hop 1: release the held unit
        alloc = _find_held_allocation(po["id"])
        if alloc is not None:
            alloc["status"] = "RELEASED"
            store.touch(alloc)
        stock["allocated_count"] -= 1
        stock["available_count"] += 1
        po["allocation_status"] = "RELEASED"
        store.touch(stock)
        # hop 2 + hop 3: waitlist promotion re-allocates the freed unit
        winner = _select_promotion(stock)
        if winner is not None:
            winner["allocation_status"] = "ALLOCATED"
            _grant_allocation(winner, stock)
            store.touch(winner)
            store.touch(stock)
    else:
        # PENDING or WAITLISTED: no unit to release
        po["allocation_status"] = "RELEASED"
    # payment dimension: always -> REFUNDED; refund paid amount as store credit
    po["payment_status"] = "REFUNDED"
    if po["amount_paid_cents"] > 0:
        ledger.add_entry(po["member_id"], po["amount_paid_cents"], "PREORDER_REFUND", po["id"])
        ledger.recompute_balance(store.members[po["member_id"]])
    store.touch(po)
    return object_response(store.serialize(po), 200)
