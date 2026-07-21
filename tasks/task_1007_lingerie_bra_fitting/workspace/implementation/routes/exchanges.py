"""Exchange (hygiene-restricted after-sale) endpoints (PRD §3.5)."""
from flask import Blueprint, g

import store
import api as h
import calc
import serialize as s
from errors import ApiError

bp = Blueprint("exchanges", __name__)

ITEM_CONDITIONS = {"SEALED", "TRIED_ON", "WORN"}


@bp.post("/boutique/exchanges")
def request_exchange():
    h.require_role("Customer", "StoreManager")
    body = h.get_body()
    # existence (priority 3), left-to-right
    if body.get("order_id") is not None:
        order = h.lookup("orders", body["order_id"])
    else:
        order = None
    if body.get("order_line_id") is not None:
        line = h.lookup("order_lines", body["order_line_id"])
        if order is not None and line["order_id"] != order["id"]:
            raise ApiError("ERR_ORDER_LINE_NOT_FOUND")
    # ownership (priority 4)
    if order is not None:
        h.owner_guard(order["customer_id"])
    # validation (priority 5)
    h.require_fields(body, ["order_id", "order_line_id", "item_condition"])
    h.check_enum(body["item_condition"], ITEM_CONDITIONS, "item_condition")
    rec = store.new_record({
        "order_id": body["order_id"],
        "order_line_id": body["order_line_id"],
        "item_condition": body["item_condition"],
        "reason": body.get("reason"),
        "store_credit_issued_cents": 0,
        "status": "REQUESTED",
    })
    store.exchanges[rec["id"]] = rec
    return h.success(s.exchange_out(rec), status=201)


@bp.get("/boutique/exchanges/<xid>")
def get_exchange(xid):
    h.require_role("Customer", "StoreManager", "BillingClerk")
    rec = h.lookup("exchanges", xid)
    if g.role == "Customer":
        order = store.orders.get(rec["order_id"])
        if order:
            h.owner_guard(order["customer_id"])
    return h.success(s.exchange_out(rec))


@bp.get("/boutique/exchanges")
def list_exchanges():
    h.require_role("Customer", "StoreManager", "BillingClerk")
    order_id = h.filter_arg("order_id")
    order_line_id = h.filter_arg("order_line_id")

    def pred(r):
        if order_id is not None and r["order_id"] != order_id:
            return False
        if order_line_id is not None and r["order_line_id"] != order_line_id:
            return False
        return True

    return h.list_response("exchanges", s.exchange_out, pred)


@bp.post("/boutique/exchanges/<xid>/approve")
def approve_exchange(xid):
    h.require_role("StoreManager")
    exchange = h.lookup("exchanges", xid)
    # state (priority 7): exchange itself
    if exchange["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    line = store.order_lines.get(exchange["order_line_id"])
    order = store.orders.get(exchange["order_id"])
    # state (priority 7): line must be FULFILLED
    if line is None or line["status"] != "FULFILLED":
        raise ApiError("ERR_LINE_NOT_EXCHANGEABLE_STATE")
    sku = store.skus.get(line["sku_id"])
    product = store.products.get(sku["product_id"]) if sku else None
    # business safety (priority 9): hygiene
    if exchange["item_condition"] != "SEALED" or (product and product["hygiene_class"] != "STANDARD_RETURNABLE"):
        raise ApiError("ERR_ITEM_NOT_EXCHANGEABLE_HYGIENE")
    # temporal (priority 11): exchange window (inclusive at 30 days)
    days = calc.whole_days_between(store.clock_now(), order["fulfilled_at"])
    if days > calc.EXCHANGE_WINDOW_DAYS:
        raise ApiError("ERR_EXCHANGE_WINDOW_EXPIRED")

    # cascade
    line["status"] = "EXCHANGED"          # hop 1
    store.touch(line)
    if sku is not None:
        sku["stock_on_hand"] += line["quantity"]   # hop 2 (+ hop 3 status via serialize)
        store.touch(sku)
    credit = line["line_net_cents"]
    exchange["store_credit_issued_cents"] = credit
    customer = store.customers.get(order["customer_id"])
    if customer is not None:
        customer["store_credit_cents"] += credit
        tier = calc.loyalty_tier(customer["loyalty_points"])
        line_points = calc.base_points(line["line_net_cents"]) * calc.TIER_MULTIPLIER[tier]
        h.append_loyalty_event(customer, -line_points, "EXCHANGE_REVERSAL",
                               order_id=order["id"])
    # cancel any SCHEDULED reminder for this line
    for rem in store.reminders.values():
        if rem["order_line_id"] == line["id"] and rem["status"] == "SCHEDULED":
            rem["status"] = "CANCELLED"
            store.touch(rem)
    exchange["status"] = "APPROVED"
    store.touch(exchange)
    return h.success(s.exchange_out(exchange))


@bp.post("/boutique/exchanges/<xid>/reject")
def reject_exchange(xid):
    h.require_role("StoreManager")
    exchange = h.lookup("exchanges", xid)
    if exchange["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    exchange["status"] = "REJECTED"
    store.touch(exchange)
    return h.success(s.exchange_out(exchange))
