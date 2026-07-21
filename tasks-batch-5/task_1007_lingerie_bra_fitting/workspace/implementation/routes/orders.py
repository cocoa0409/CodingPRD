"""Order and OrderLine endpoints + order lifecycle (PRD §3.3-3.5)."""
from flask import Blueprint, g

import store
import api as h
import calc
import serialize as s
from errors import ApiError

bp = Blueprint("orders", __name__)

ORDER_TYPES = {"STANDARD", "SPECIAL_ORDER", "GIFT"}


def _order_lines_sorted(order_id):
    lines = [l for l in store.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda r: r["_seq"])
    return lines


def _active_lines(order_id):
    return [l for l in _order_lines_sorted(order_id) if l["status"] == "ACTIVE"]


# --- Order CRUD ------------------------------------------------------------
@bp.post("/boutique/orders")
def create_order():
    h.require_role("Customer", "StoreManager")
    body = h.get_body()
    if body.get("customer_id") is not None:
        customer = h.lookup("customers", body["customer_id"])
    else:
        customer = None
    if customer is not None:
        h.owner_guard(customer["id"])
    h.require_fields(body, ["customer_id"])
    order_type = body.get("order_type", "STANDARD")
    if order_type is None:
        order_type = "STANDARD"
    h.check_enum(order_type, ORDER_TYPES, "order_type")
    is_gift = body.get("is_gift", False)
    if not isinstance(is_gift, bool):
        raise ApiError("ERR_VALIDATION", "is_gift must be boolean")
    rec = store.new_record({
        "customer_id": body["customer_id"],
        "order_type": order_type,
        "is_gift": is_gift,
        "gift_message": body.get("gift_message"),
        "gift_recipient_name": body.get("gift_recipient_name"),
        "payment_status": "UNPAID",
        "fulfillment_status": "DRAFT",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "gift_wrap_fee_cents": 0,
        "special_order_fee_cents": 0,
        "total_cents": 0,
        "provisional_points": 0,
        "final_points": 0,
        "fulfilled_at": None,
    })
    store.orders[rec["id"]] = rec
    return h.success(s.order_out(rec), status=201)


@bp.get("/boutique/orders/<oid>")
def get_order(oid):
    h.require_role("Customer", "StoreManager", "BillingClerk")
    rec = h.lookup("orders", oid)
    if g.role == "Customer":
        h.owner_guard(rec["customer_id"])
    return h.success(s.order_out(rec))


@bp.get("/boutique/orders")
def list_orders():
    h.require_role("Customer", "StoreManager", "BillingClerk")
    customer_id = h.filter_arg("customer_id")

    def pred(r):
        return customer_id is None or r["customer_id"] == customer_id

    return h.list_response("orders", s.order_out, pred)


# --- OrderLine -------------------------------------------------------------
@bp.post("/boutique/orders/<oid>/lines")
def add_line(oid):
    h.require_role("Customer", "StoreManager")
    order = h.lookup("orders", oid)
    body = h.get_body()
    if body.get("sku_id") is not None:
        sku = h.lookup("skus", body["sku_id"])
    else:
        sku = None
    h.owner_guard(order["customer_id"])
    h.require_fields(body, ["sku_id", "quantity"])
    qty = h.require_int(body, "quantity", minimum=1)
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Lines can only be added to a DRAFT order")
    available = sku["stock_on_hand"] - s.sku_reserved_count(sku["id"])
    is_special = order["order_type"] == "SPECIAL_ORDER" and available <= 0
    unit_price = sku["price_cents"]
    rec = store.new_record({
        "order_id": oid,
        "sku_id": sku["id"],
        "quantity": qty,
        "unit_price_cents": unit_price,
        "line_gross_cents": unit_price * qty,
        "line_discount_cents": 0,
        "line_net_cents": 0,
        "is_special_order": is_special,
        "status": "ACTIVE",
    })
    store.order_lines[rec["id"]] = rec
    return h.success(s.order_line_out(rec), status=201)


@bp.get("/boutique/order-lines/<lid>")
def get_line(lid):
    h.require_role("Customer", "StoreManager", "BillingClerk")
    rec = h.lookup("order_lines", lid)
    if g.role == "Customer":
        order = store.orders.get(rec["order_id"])
        if order:
            h.owner_guard(order["customer_id"])
    return h.success(s.order_line_out(rec))


@bp.get("/boutique/order-lines")
def list_lines():
    h.require_role("Customer", "StoreManager", "BillingClerk")
    order_id = h.filter_arg("order_id")
    sku_id = h.filter_arg("sku_id")

    def pred(r):
        if order_id is not None and r["order_id"] != order_id:
            return False
        if sku_id is not None and r["sku_id"] != sku_id:
            return False
        return True

    return h.list_response("order_lines", s.order_line_out, pred)


# --- lifecycle -------------------------------------------------------------
@bp.post("/boutique/orders/<oid>/place")
def place_order(oid):
    h.require_role("Customer", "StoreManager")
    order = h.lookup("orders", oid)
    h.owner_guard(order["customer_id"])
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    active = _active_lines(oid)
    if not active:
        raise ApiError("ERR_EMPTY_ORDER")
    # referential (priority 12): SKU active
    for line in active:
        if line["is_special_order"]:
            continue
        sku = store.skus.get(line["sku_id"])
        if sku is None or not sku["is_active"]:
            raise ApiError("ERR_SKU_INACTIVE")
    # fiscal (priority 13): sufficient available inventory
    for line in active:
        if line["is_special_order"]:
            continue
        sku = store.skus[line["sku_id"]]
        available = sku["stock_on_hand"] - s.sku_reserved_count(sku["id"])
        if available < line["quantity"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK")
    order["fulfillment_status"] = "PLACED"
    store.touch(order)
    return h.success(s.order_out(order))


@bp.post("/boutique/orders/<oid>/pay")
def pay_order(oid):
    h.require_role("BillingClerk")
    order = h.lookup("orders", oid)
    if order["fulfillment_status"] != "PLACED":
        raise ApiError("ERR_ORDER_NOT_PLACED")
    if order["payment_status"] != "UNPAID":
        raise ApiError("ERR_INVALID_STATE")
    customer = store.customers[order["customer_id"]]
    tier = calc.loyalty_tier(customer["loyalty_points"])  # snapshot at pay
    tier_pct = calc.TIER_DISCOUNT_PCT[tier]
    subtotal = 0
    discount = 0
    for line in _active_lines(oid):
        gross = line["unit_price_cents"] * line["quantity"]
        line_disc = calc.pct_cents(gross, tier_pct)
        line["line_gross_cents"] = gross
        line["line_discount_cents"] = line_disc
        line["line_net_cents"] = gross - line_disc
        store.touch(line)
        subtotal += gross
        discount += line_disc
    gift_fee = calc.GIFT_WRAP_FEE_CENTS if order["is_gift"] else 0
    special_fee = calc.SPECIAL_ORDER_FEE_CENTS if order["order_type"] == "SPECIAL_ORDER" else 0
    total = subtotal - discount + gift_fee + special_fee
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["gift_wrap_fee_cents"] = gift_fee
    order["special_order_fee_cents"] = special_fee
    order["total_cents"] = total
    provisional = calc.base_points(total)  # PROVISIONAL: no tier multiplier
    order["provisional_points"] = provisional
    order["payment_status"] = "PAID"
    store.touch(order)
    h.append_loyalty_event(customer, provisional, "ORDER_EARN", order_id=oid)
    return h.success(s.order_out(order))


@bp.post("/boutique/orders/<oid>/fulfill")
def fulfill_order(oid):
    h.require_role("StoreManager")
    order = h.lookup("orders", oid)
    if order["fulfillment_status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE")
    if order["payment_status"] != "PAID":
        raise ApiError("ERR_ORDER_NOT_PAID")
    fulfilled_at = store.clock_now()
    for line in _active_lines(oid):
        sku = store.skus.get(line["sku_id"])
        if sku is not None:
            sku["stock_on_hand"] -= line["quantity"]
            store.touch(sku)
        line["status"] = "FULFILLED"
        store.touch(line)
    order["fulfilled_at"] = fulfilled_at
    customer = store.customers[order["customer_id"]]
    tier = calc.loyalty_tier(customer["loyalty_points"])  # snapshot at fulfill
    final = calc.final_points(order["total_cents"], tier)
    order["final_points"] = final
    order["fulfillment_status"] = "FULFILLED"
    store.touch(order)
    # reconcile loyalty: FINAL_ADJUSTMENT delta = final - provisional
    h.append_loyalty_event(customer, final - order["provisional_points"],
                           "FINAL_ADJUSTMENT", order_id=oid)
    # seed replacement reminders for qualifying bra lines
    due = calc.add_months(fulfilled_at, calc.REPLACEMENT_INTERVAL_MONTHS)
    for line in _order_lines_sorted(oid):
        if line["status"] != "FULFILLED":
            continue
        sku = store.skus.get(line["sku_id"])
        if sku is None:
            continue
        product = store.products.get(sku["product_id"])
        if product and product["category"] in ("EVERYDAY_BRA", "SPORTS_BRA", "MASTECTOMY_BRA"):
            rem = store.new_record({
                "customer_id": order["customer_id"],
                "order_line_id": line["id"],
                "due_date": due,
                "status": "SCHEDULED",
            })
            store.reminders[rem["id"]] = rem
    return h.success(s.order_out(order))


@bp.post("/boutique/orders/<oid>/cancel")
def cancel_order(oid):
    h.require_role("Customer", "StoreManager")
    order = h.lookup("orders", oid)
    h.owner_guard(order["customer_id"])
    if order["fulfillment_status"] not in ("DRAFT", "PLACED"):
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE")
    was_placed = order["fulfillment_status"] == "PLACED"
    for line in _active_lines(oid):
        line["status"] = "CANCELLED"
        store.touch(line)
        if was_placed and not line["is_special_order"]:
            sku = store.skus.get(line["sku_id"])
            if sku is not None:
                store.touch(sku)  # reservation released -> derived fields recomputed
    order["fulfillment_status"] = "CANCELLED"
    if order["payment_status"] == "PAID":
        order["payment_status"] = "REFUNDED"
        store.touch(order)
        customer = store.customers[order["customer_id"]]
        h.append_loyalty_event(customer, -order["provisional_points"],
                               "ORDER_REVERSAL", order_id=oid)
    else:
        store.touch(order)
    return h.success(s.order_out(order))
