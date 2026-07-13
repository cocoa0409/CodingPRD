"""Returns: policy gates, settlement, hygiene strikes."""
from datetime import timedelta

from flask import Blueprint, request

from db import base_record, db, public, touch
from errors import ApiError
from middleware import (
    as_enum,
    as_int,
    as_str,
    authenticate,
    body,
    get_order_line,
    get_return,
    own_customer,
    page,
    pagination,
    required,
)
from response import created, ok, ok_list
from services.loyalty import append_ledger, tier_evaluation_rolling
from services.pricing import refund_settlement
from util import iso, parse_dt

bp = Blueprint("returns", __name__)

REASONS = ("WRONG_SHADE", "DAMAGED", "CHANGED_MIND", "ALLERGIC_REACTION")
DENY_REASONS = ("HYGIENE_VIOLATION", "NOT_AS_DESCRIBED", "OUT_OF_POLICY")
DECISIONS = ("APPROVE", "DENY")
RETURN_STATUSES = ("REQUESTED", "APPROVED", "DENIED")
RETURN_WINDOW_DAYS = 30
HYGIENE_STRIKE_LIMIT = 3
FULFILLED_STATES = ("PICKED_UP", "SHIPPED")


@bp.post("/return-requests")
def create_return():
    auth = authenticate("Customer")
    payload = body()

    order_line_id = as_str(required(payload, "order_line_id"), "order_line_id")
    quantity = as_int(required(payload, "quantity"), "quantity", minimum=1)
    reason = as_enum(required(payload, "reason"), "reason", REASONS)

    line = get_order_line(order_line_id)
    order = db.orders[line["order_id"]]
    customer = db.customers[order["customer_id"]]

    own_customer(auth, order["customer_id"])

    if order["fulfillment_status"] not in FULFILLED_STATES:
        raise ApiError("ERR_INVALID_RETURN_STATE", "the order has not been fulfilled")

    # gate 1 — the customer's return privilege
    if customer["return_privilege"] != "ACTIVE":
        raise ApiError("ERR_RETURN_PRIVILEGE_SUSPENDED", "this customer may not open new return requests")

    # gate 2 — hygiene
    if line["hygiene_class"] == "DIRECT_CONTACT":
        raise ApiError("ERR_HYGIENE_NON_RETURNABLE", "a direct-contact good is never returnable")

    # gate 3 — the thirty-day return window, on the logical clock
    fulfilled_at = parse_dt(order["fulfilled_at"])
    if fulfilled_at is None or db.clock > fulfilled_at + timedelta(days=RETURN_WINDOW_DAYS):
        raise ApiError("ERR_RETURN_WINDOW_EXPIRED", "the return window has closed")

    # gate 4 — the units must exist to be returned
    if line["returned_quantity"] + quantity > line["quantity"]:
        raise ApiError("ERR_RETURN_QUANTITY_EXCEEDS_LINE", "more units returned than the line holds")

    record = base_record()
    record.update({
        "order_line_id": line["id"],
        "quantity": quantity,
        "reason": reason,
        "status": "REQUESTED",
        "deny_reason": None,
        "disposition": None,
        "refund_line_cents": 0,
        "restocking_fee_cents": 0,
        "refund_cents": 0,
        "points_clawback": 0,
        "decided_at": None,
    })
    db.returns[record["id"]] = record
    return created(public(record))


@bp.get("/return-requests/<return_id>")
def read_return(return_id):
    auth = authenticate("MerchandisingAdmin", "StoreAssociate", "Customer")
    record = get_return(return_id)
    line = db.order_lines[record["order_line_id"]]
    own_customer(auth, db.orders[line["order_id"]]["customer_id"])
    return ok(public(record))


@bp.get("/return-requests")
def list_returns():
    auth = authenticate("MerchandisingAdmin", "StoreAssociate", "Customer")
    limit, offset = pagination()
    order_line_id = request.args.get("order_line_id")
    status = request.args.get("status")

    records = list(db.returns.values())
    if auth.is_customer:
        records = [
            r for r in records
            if db.orders[db.order_lines[r["order_line_id"]]["order_id"]]["customer_id"] == auth.user_id
        ]
    if order_line_id:
        records = [r for r in records if r["order_line_id"] == order_line_id]
    if status:
        records = [r for r in records if r["status"] == status]
    items, total = page(records, limit, offset, public)
    return ok_list(items, limit, offset, total)


@bp.post("/return-requests/<return_id>/decision")
def decide_return(return_id):
    authenticate("StoreAssociate")
    record = get_return(return_id)
    payload = body()

    decision = as_enum(required(payload, "decision"), "decision", DECISIONS)
    deny_reason = payload.get("deny_reason")
    if decision == "DENY":
        deny_reason = as_enum(required(payload, "deny_reason"), "deny_reason", DENY_REASONS)

    if record["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_RETURN_STATE", "this return request has already been decided")

    line = db.order_lines[record["order_line_id"]]
    order = db.orders[line["order_id"]]
    customer = db.customers[order["customer_id"]]

    if decision == "DENY":
        record["status"] = "DENIED"
        record["deny_reason"] = deny_reason
        record["decided_at"] = iso(db.clock)
        touch(record)
        if deny_reason == "HYGIENE_VIOLATION":
            customer["hygiene_strikes"] += 1
            if customer["hygiene_strikes"] >= HYGIENE_STRIKE_LIMIT:
                customer["return_privilege"] = "SUSPENDED"
            touch(customer)
        return ok(public(record))

    # ---- APPROVE ----
    if line["returned_quantity"] + record["quantity"] > line["quantity"]:
        raise ApiError("ERR_RETURN_QUANTITY_EXCEEDS_LINE", "more units returned than the line holds")

    settlement = refund_settlement(order, line, record["quantity"])
    record.update(settlement)
    record["status"] = "APPROVED"
    record["decided_at"] = iso(db.clock)
    touch(record)

    refund_cents = settlement["refund_cents"]

    # the order absorbs the refund
    if order["refunded_cents"] + refund_cents >= order["total_due_cents"]:
        order["refunded_cents"] = order["total_due_cents"]
        order["payment_status"] = "REFUNDED"
    else:
        order["refunded_cents"] += refund_cents
        order["payment_status"] = "PARTIALLY_REFUNDED"

    # the customer gives back what the refunded cash had bought
    customer["qualifying_spend_cents"] -= refund_cents
    customer["lifetime_spend_cents"] -= refund_cents
    append_ledger(customer, "CLAWBACK", -settlement["points_clawback"], order["id"])
    tier_evaluation_rolling(customer)
    touch(customer)

    # the physical units come back
    lot = db.lots.get(line["_lot_id"]) if line["_lot_id"] else None
    if lot is not None:
        lot["sold_units"] -= record["quantity"]
        if settlement["disposition"] == "RESTOCK":
            lot["on_hand_units"] += record["quantity"]
        else:
            lot["destroyed_units"] += record["quantity"]
        touch(lot)

    line["returned_quantity"] += record["quantity"]
    touch(line)

    touch(order)
    return ok(public(record))
