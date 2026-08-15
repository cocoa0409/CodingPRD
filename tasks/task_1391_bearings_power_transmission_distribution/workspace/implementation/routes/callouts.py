"""Emergency after-hours call-outs."""

from flask import Blueprint, request

import domain
from db import store
from errors import err
from helpers import get_body, local_time, new_id, now, req_int, req_str, stamp_new, touch
from middleware import require_any, require_roles
from response import ok, ok_list, paginate
from serialize import serialize, serialize_list

bp = Blueprint("callouts", __name__)


def get_callout(cid):
    c = store.call_outs.get(cid)
    if c is None:
        raise err("ERR_CALL_OUT_NOT_FOUND", f"call-out {cid} not found")
    return c


@bp.route("/motion/call-outs", methods=["POST"])
@require_roles("CustomerPlant", "CounterSalesRep")
def create_callout(user_id, role):
    body = get_body()
    branch_id = req_str(body, "branch_id") if "branch_id" in body else None
    customer_id = req_str(body, "customer_id") if "customer_id" in body else None
    product_id = req_str(body, "product_id") if "product_id" in body else None
    # body FK existence (priority 3)
    for val, coll, eid in (
        (branch_id, store.branches, "ERR_BRANCH_NOT_FOUND"),
        (customer_id, store.customers, "ERR_CUSTOMER_NOT_FOUND"),
        (product_id, store.products, "ERR_PRODUCT_NOT_FOUND"),
    ):
        if val is not None and val not in coll:
            raise err(eid, f"referenced resource {val} not found")
    # identity (priority 4): CustomerPlant acts only on its own account
    if role == "CustomerPlant" and customer_id is not None and customer_id != user_id:
        raise err("ERR_IDENTITY_MISMATCH", "CustomerPlant may act only on its own account")
    # shape (priority 7)
    if branch_id is None or customer_id is None or product_id is None:
        raise err("ERR_INVALID_REQUEST", "branch_id, customer_id, product_id are required")
    qty = req_int(body, "qty", minimum=1)
    rec = stamp_new({
        "id": new_id(),
        "branch_id": branch_id,
        "customer_id": customer_id,
        "product_id": product_id,
        "qty": qty,
        "call_out_fee_cents": 0,
        "parts_amount_cents": 0,
        "total_charge_cents": 0,
        "responder_id": None,
        "preempted_reservation_ids": [],
        "status": "REQUESTED",
    })
    store.call_outs[rec["id"]] = rec
    return ok(serialize("CallOut", rec), 201)


@bp.route("/motion/call-outs", methods=["GET"])
@require_any
def list_callouts(user_id, role):
    items = list(store.call_outs.values())
    q = request.args
    for param in ("branch_id", "customer_id", "product_id", "status"):
        if q.get(param) is not None:
            items = [c for c in items if c[param] == q[param]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("CallOut", page), limit, offset, total)


@bp.route("/motion/call-outs/<cid>", methods=["GET"])
@require_any
def get_callout_route(user_id, role, cid):
    return ok(serialize("CallOut", get_callout(cid)))


@bp.route("/motion/call-outs/<cid>/dispatch", methods=["POST"])
@require_roles("OnCallTechnician")
def dispatch_callout(user_id, role, cid):
    c = get_callout(cid)
    # state (priority 5)
    if c["status"] != "REQUESTED":
        raise err("ERR_CALL_OUT_NOT_REQUESTED", "dispatch requires call-out REQUESTED")
    branch = store.branches[c["branch_id"]]
    # temporal (priority 8): after-hours, then one-truck capacity
    local_hour = local_time(branch).hour
    if not (local_hour < branch["business_open_hour"] or local_hour >= branch["business_close_hour"]):
        raise err("ERR_CALL_OUT_NOT_AFTER_HOURS", "dispatch requires branch-local after-hours")
    if any(o["id"] != c["id"] and o["branch_id"] == c["branch_id"] and o["status"] == "DISPATCHED"
           for o in store.call_outs.values()):
        raise err("ERR_BRANCH_CALLOUT_CAPACITY", "branch already has a DISPATCHED call-out")
    c["responder_id"] = user_id
    c["call_out_fee_cents"] = domain.call_out_fee(branch, c["qty"], now())
    c["status"] = "DISPATCHED"
    touch(c)
    return ok(serialize("CallOut", c))


@bp.route("/motion/call-outs/<cid>/fulfill", methods=["POST"])
@require_roles("OnCallTechnician")
def fulfill_callout(user_id, role, cid):
    c = get_callout(cid)
    if c["status"] != "DISPATCHED":
        raise err("ERR_CALL_OUT_NOT_DISPATCHED", "fulfill requires call-out DISPATCHED")
    stock = domain.find_stock(c["branch_id"], c["product_id"])
    if stock is None or stock["on_hand_qty"] < c["qty"]:
        c["status"] = "STOCK_UNAVAILABLE"
        touch(c)
        return ok(serialize("CallOut", c))
    # emergency override: seize ACTIVE reservations (newest created_at first)
    available = domain.available_qty(stock)
    if available < c["qty"]:
        candidates = sorted(
            (r for r in store.reservations.values()
             if r["status"] == "ACTIVE"
             and store.stocks.get(r["branch_stock_id"]) is stock),
            key=lambda r: (r["created_at"], r["_seq"]),
            reverse=True,
        )
        for r in candidates:
            if domain.available_qty(stock) >= c["qty"]:
                break
            r["status"] = "PREEMPTED"
            touch(r)
            c["preempted_reservation_ids"].append(r["id"])
            line = store.order_lines.get(r["order_line_id"])
            if line and line["sourcing_status"] == "STOCK_RESERVED":
                line["sourcing_status"] = "PENDING_SOURCING"
                touch(line)
                order = store.orders.get(line["order_id"])
                if order:
                    domain.reevaluate_order_fulfillment(order)
    stock["on_hand_qty"] -= c["qty"]
    touch(stock)
    product = store.products[c["product_id"]]
    unit, _ = domain.contract_lag_unit_price(c["customer_id"], product, now())
    c["parts_amount_cents"] = c["qty"] * unit
    c["total_charge_cents"] = c["call_out_fee_cents"] + c["parts_amount_cents"]
    c["status"] = "FULFILLED"
    touch(c)
    return ok(serialize("CallOut", c))


@bp.route("/motion/call-outs/<cid>/cancel", methods=["POST"])
@require_roles("OnCallTechnician", "CustomerPlant")
def cancel_callout(user_id, role, cid):
    c = get_callout(cid)
    # identity (priority 4): CustomerPlant may cancel only its own call-out
    if role == "CustomerPlant" and c["customer_id"] != user_id:
        raise err("ERR_IDENTITY_MISMATCH", "CustomerPlant may cancel only its own call-out")
    if c["status"] not in ("REQUESTED", "DISPATCHED"):
        raise err("ERR_CALL_OUT_NOT_CANCELLABLE", "cancel requires REQUESTED or DISPATCHED")
    c["status"] = "CANCELLED"
    touch(c)
    return ok(serialize("CallOut", c))
