"""Hydroponics & Indoor-Garden Store API — Flask entry point.

Every route, field, side effect and error traces to a PRD sentence. Storage is
in-memory only; the process starts with empty state and seeds nothing.
"""
import os
from datetime import timedelta
from functools import wraps

from flask import Flask, request, g

from errors import ApiError
from store import (
    store, base_fields, touch, public, iso, real_now, clock_now,
    parse_iso, sort_by_created,
)
from envelope import ok_object, ok_list, error_response
import calc
import domain

app = Flask(__name__)

ROLES = {"StoreAdmin", "Customer", "CommercialBuyer", "Consultant"}
PRODUCT_CATEGORIES = {"SYSTEM", "LIGHTING", "NUTRIENT", "CONSUMABLE", "ACCESSORY"}
DISCOUNT_TIERS = {"STANDARD", "SILVER", "GOLD"}


# ============================================================ auth / routing ==
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or unrecognized credentials")
    return uid, role


def endpoint(rule, methods, roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(**kwargs):
            uid, role = authenticate()
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED", "role not permitted")
            g.uid = uid
            g.role = role
            return fn(**kwargs)
        app.add_url_rule(rule, fn.__name__, wrapper, methods=methods)
        return fn
    return deco


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


# ============================================================ helpers =========
def body_json():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def v_str(body, field, required=True, default=None, allow_empty=False):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{field} is required")
        return default
    val = body[field]
    if not isinstance(val, str):
        raise ApiError("ERR_VALIDATION", f"{field} must be a string")
    if not allow_empty and val == "":
        raise ApiError("ERR_VALIDATION", f"{field} must not be empty")
    return val


def v_int(body, field, required=True, default=None, min_val=None, max_val=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{field} is required")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", f"{field} must be an integer")
    if min_val is not None and val < min_val:
        raise ApiError("ERR_VALIDATION", f"{field} out of range")
    if max_val is not None and val > max_val:
        raise ApiError("ERR_VALIDATION", f"{field} out of range")
    return val


def v_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise ApiError("ERR_VALIDATION", f"{field} must be a boolean")
    return val


def v_enum(body, field, choices, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{field} is required")
        return default
    val = body[field]
    if val not in choices:
        raise ApiError("ERR_VALIDATION", f"{field} invalid")
    return val


def must_exist(coll, id_):
    ent = coll.get(id_)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", "resource not found")
    return ent


def check_owner(owner_id):
    if owner_id != g.uid:
        raise ApiError("ERR_OWNERSHIP_REQUIRED", "not the owner")


def parse_pagination():
    args = request.args
    limit, offset = 10, 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit invalid")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit out of range")
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset invalid")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset out of range")
    return limit, offset


def list_response(items):
    limit, offset = parse_pagination()
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([public(e) for e in page], limit, offset, total)


def build_order_lines(body):
    lines = body.get("lines")
    if not isinstance(lines, list) or len(lines) < 1:
        raise ApiError("ERR_VALIDATION", "lines is required")
    for item in lines:
        if not isinstance(item, dict):
            raise ApiError("ERR_VALIDATION", "line malformed")
        pid = item.get("product_id")
        if not isinstance(pid, str) or not pid:
            raise ApiError("ERR_VALIDATION", "line.product_id required")
    for item in lines:  # existence (404) before quantity validation (422)
        if item["product_id"] not in store.products:
            raise ApiError("ERR_NOT_FOUND", "product not found")
    result = []
    for item in lines:
        q = item.get("quantity")
        if isinstance(q, bool) or not isinstance(q, int) or q <= 0:
            raise ApiError("ERR_VALIDATION", "quantity must be > 0")
        prod = store.products[item["product_id"]]
        unit = prod["unit_price_cents"]
        result.append({
            "product_id": item["product_id"],
            "quantity": q,
            "unit_price_cents": unit,
            "line_total_cents": unit * q,
        })
    return result


def price_order(order, discount_tier):
    calc_lines = []
    for l in order["lines"]:
        prod = store.products[l["product_id"]]
        calc_lines.append({
            "unit_price_cents": l["unit_price_cents"],
            "quantity": l["quantity"],
            "_is_hazmat": prod["is_hazmat"],
            "_unit_weight_g": prod["unit_weight_g"],
        })
    return calc.order_net_total(calc_lines, order["order_type"], discount_tier)


def check_stock(lines):
    demand = {}
    for l in lines:
        demand[l["product_id"]] = demand.get(l["product_id"], 0) + l["quantity"]
    for pid, qty in demand.items():
        if store.products[pid]["total_available_units"] < qty:
            raise ApiError("ERR_INSUFFICIENT_STOCK", "insufficient stock")


# ============================================================ Products ========
@endpoint("/products", ["POST"], {"StoreAdmin"})
def create_product():
    body = body_json()
    sku = v_str(body, "sku_code")
    name = v_str(body, "name")
    category = v_enum(body, "category", PRODUCT_CATEGORIES)
    unit_price = v_int(body, "unit_price_cents", min_val=1)
    is_hazmat = v_bool(body, "is_hazmat", False)
    warranty_months = v_int(body, "warranty_months", required=False, default=0, min_val=0)
    is_subscribable = v_bool(body, "is_subscribable", False)
    reorder_threshold = v_int(body, "reorder_threshold", required=False, default=0, min_val=0)
    unit_weight_g = v_int(body, "unit_weight_g", required=False, default=0, min_val=0)

    if any(p["sku_code"] == sku for p in store.products.values()):
        raise ApiError("ERR_VALIDATION", "sku_code must be unique")

    product = base_fields()
    product.update({
        "sku_code": sku, "name": name, "category": category,
        "unit_price_cents": unit_price, "is_hazmat": is_hazmat,
        "warranty_months": warranty_months, "is_subscribable": is_subscribable,
        "reorder_threshold": reorder_threshold, "unit_weight_g": unit_weight_g,
        "total_available_units": 0, "reorder_flag": False,
    })
    domain.set_product_derived(product)  # total=0, reorder_flag = 0 < threshold
    store.products[product["id"]] = product
    return ok_object(public(product), 201)


@endpoint("/products/<pid>", ["GET"], ROLES)
def get_product(pid):
    return ok_object(public(must_exist(store.products, pid)))


@endpoint("/products/<pid>/inventory-lots", ["POST"], {"StoreAdmin"})
def create_lot(pid):
    product = must_exist(store.products, pid)
    body = body_json()
    lot_code = v_str(body, "lot_code")
    qoh = v_int(body, "quantity_on_hand", min_val=0)
    unit_cost = v_int(body, "unit_cost_cents", required=False, default=0, min_val=0)

    if any(l["product_id"] == pid and l["lot_code"] == lot_code
           for l in store.inventory_lots.values()):
        raise ApiError("ERR_VALIDATION", "lot_code must be unique per product")

    lot = base_fields()
    lot.update({
        "product_id": pid, "lot_code": lot_code, "quantity_on_hand": qoh,
        "quantity_reserved": 0, "quantity_available": qoh,
        "unit_cost_cents": unit_cost, "status": "ACTIVE",
    })
    domain.set_lot_derived(lot)
    store.inventory_lots[lot["id"]] = lot
    domain.set_product_derived(product)
    touch(product)
    return ok_object(public(lot), 201)


@endpoint("/products/<pid>/inventory-lots", ["GET"], {"StoreAdmin"})
def list_lots(pid):
    must_exist(store.products, pid)
    items = [l for l in store.inventory_lots.values() if l["product_id"] == pid]
    return list_response(items)


# ============================================================ Customers =======
@endpoint("/customers", ["POST"], {"StoreAdmin"})
def create_customer():
    body = body_json()
    email = v_str(body, "email")
    full_name = v_str(body, "full_name")
    if any(c["email"] == email for c in store.customers.values()):
        raise ApiError("ERR_VALIDATION", "email must be unique")
    customer = base_fields()
    customer.update({
        "email": email, "full_name": full_name,
        "wallet_credit_cents": 0, "loyalty_points": 0,
        "loyalty_tier": "BRONZE", "status": "ACTIVE",
    })
    store.customers[customer["id"]] = customer
    return ok_object(public(customer), 201)


@endpoint("/customers/<cid>", ["GET"], {"StoreAdmin", "Customer"})
def get_customer(cid):
    customer = must_exist(store.customers, cid)
    if g.role == "Customer":
        check_owner(cid)
    return ok_object(public(customer))


# ============================================================ Commercial acct =
@endpoint("/commercial-accounts", ["POST"], {"StoreAdmin"})
def create_commercial_account():
    body = body_json()
    business_name = v_str(body, "business_name")
    credit_limit = v_int(body, "credit_limit_cents", min_val=1)
    net_days = v_int(body, "payment_terms_net_days", required=False, default=30, min_val=0)
    tier = v_enum(body, "discount_tier", DISCOUNT_TIERS, required=False, default="STANDARD")
    acct = base_fields()
    acct.update({
        "business_name": business_name, "credit_limit_cents": credit_limit,
        "credit_used_cents": 0, "payment_terms_net_days": net_days,
        "discount_tier": tier, "status": "PENDING",
    })
    store.commercial_accounts[acct["id"]] = acct
    return ok_object(public(acct), 201)


@endpoint("/commercial-accounts/<aid>", ["GET"], {"StoreAdmin", "CommercialBuyer"})
def get_commercial_account(aid):
    acct = must_exist(store.commercial_accounts, aid)
    if g.role == "CommercialBuyer":
        check_owner(aid)
    return ok_object(public(acct))


@endpoint("/commercial-accounts/<aid>/activate", ["POST"], {"StoreAdmin"})
def activate_account(aid):
    acct = must_exist(store.commercial_accounts, aid)
    if acct["status"] not in ("PENDING", "ON_HOLD"):
        raise ApiError("ERR_INVALID_STATE", "cannot activate from current state")
    acct["status"] = "ACTIVE"
    touch(acct)
    return ok_object(public(acct))


@endpoint("/commercial-accounts/<aid>/hold", ["POST"], {"StoreAdmin"})
def hold_account(aid):
    acct = must_exist(store.commercial_accounts, aid)
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "cannot hold from current state")
    acct["status"] = "ON_HOLD"
    touch(acct)
    return ok_object(public(acct))


@endpoint("/commercial-accounts/<aid>/set-tier", ["POST"], {"StoreAdmin"})
def set_tier(aid):
    acct = must_exist(store.commercial_accounts, aid)
    body = body_json()
    tier = v_enum(body, "discount_tier", DISCOUNT_TIERS)
    acct["discount_tier"] = tier
    touch(acct)
    return ok_object(public(acct))


@endpoint("/commercial-accounts/<aid>/orders", ["POST"], {"CommercialBuyer"})
def place_commercial_order(aid):
    acct = must_exist(store.commercial_accounts, aid)
    body = body_json()
    lines = build_order_lines(body)  # existence + field validity (422/404)
    expected_version = v_int(body, "expected_commercial_account_version")
    check_owner(aid)  # ownership: path account must equal X-User-ID

    order = base_fields()
    order.update({
        "customer_id": None, "commercial_account_id": aid, "order_type": "COMMERCIAL",
        "lines": lines, "subtotal_cents": 0, "discount_cents": 0,
        "hazmat_surcharge_cents": 0, "provisional_total_cents": 0,
        "final_total_cents": None, "total_cents": 0,
        "fulfillment_status": "CONFIRMED", "payment_status": "UNPAID",
        "shipped_at": None, "_reservations": {}, "_loyalty_earned": 0,
    })

    # account-specific chain (PRD §3.4): ACTIVE -> stock -> credit -> OCC
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", "account not active")
    check_stock(lines)
    subtotal, discount, hazmat, net = price_order(order, acct["discount_tier"])
    if acct["credit_used_cents"] + net > acct["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", "credit limit exceeded")
    if expected_version != acct["version"]:
        raise ApiError("ERR_STALE_VERSION", "stale account version")

    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["hazmat_surcharge_cents"] = hazmat
    order["provisional_total_cents"] = net
    order["total_cents"] = net
    store.orders[order["id"]] = order
    domain.reserve_for_order(order)
    domain.set_credit_used(acct)
    touch(acct)  # single version increment for the placement
    return ok_object(public(order), 201)


# ============================================================ Orders ==========
@endpoint("/orders", ["POST"], {"Customer"})
def create_retail_order():
    body = body_json()
    customer_id = v_str(body, "customer_id")
    must_exist(store.customers, customer_id)
    lines = build_order_lines(body)
    check_owner(customer_id)

    order = base_fields()
    order.update({
        "customer_id": customer_id, "commercial_account_id": None,
        "order_type": "RETAIL", "lines": lines, "subtotal_cents": 0,
        "discount_cents": 0, "hazmat_surcharge_cents": 0,
        "provisional_total_cents": 0, "final_total_cents": None, "total_cents": 0,
        "fulfillment_status": "DRAFT", "payment_status": "UNPAID",
        "shipped_at": None, "_reservations": {}, "_loyalty_earned": 0,
    })
    subtotal, discount, hazmat, net = price_order(order, None)
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["hazmat_surcharge_cents"] = hazmat
    order["provisional_total_cents"] = net
    order["total_cents"] = net
    store.orders[order["id"]] = order
    return ok_object(public(order), 201)


@endpoint("/orders/<oid>", ["GET"], {"StoreAdmin", "Customer", "CommercialBuyer"})
def get_order(oid):
    order = must_exist(store.orders, oid)
    if g.role == "Customer":
        check_owner(order.get("customer_id"))
    elif g.role == "CommercialBuyer":
        check_owner(order.get("commercial_account_id"))
    return ok_object(public(order))


@endpoint("/orders", ["GET"], {"StoreAdmin", "Customer", "CommercialBuyer"})
def list_orders():
    items = list(store.orders.values())
    if g.role == "Customer":
        items = [o for o in items if o.get("customer_id") == g.uid]
    elif g.role == "CommercialBuyer":
        items = [o for o in items if o.get("commercial_account_id") == g.uid]
    cust = request.args.get("customer_id")
    if cust is not None:
        items = [o for o in items if o.get("customer_id") == cust]
    acct = request.args.get("commercial_account_id")
    if acct is not None:
        items = [o for o in items if o.get("commercial_account_id") == acct]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["fulfillment_status"] == status]
    return list_response(items)


@endpoint("/orders/<oid>/confirm", ["POST"], {"Customer", "StoreAdmin"})
def confirm_order(oid):
    order = must_exist(store.orders, oid)
    if g.role == "Customer":
        check_owner(order.get("customer_id"))
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "order not DRAFT")
    check_stock(order["lines"])
    domain.reserve_for_order(order)
    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    return ok_object(public(order))


@endpoint("/orders/<oid>/pay", ["POST"], {"Customer"})
def pay_order(oid):
    order = must_exist(store.orders, oid)
    check_owner(order.get("customer_id"))
    if order["payment_status"] != "UNPAID" or order["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "order not payable")
    customer = store.customers[order["customer_id"]]
    earned = calc.loyalty_points_earned(
        [l["line_total_cents"] for l in order["lines"]], customer["loyalty_tier"])
    customer["loyalty_points"] += earned
    domain.apply_loyalty_tier(customer)
    touch(customer)
    order["_loyalty_earned"] = earned
    order["payment_status"] = "PAID"
    touch(order)
    return ok_object(public(order))


@endpoint("/orders/<oid>/ship", ["POST"], {"StoreAdmin"})
def ship_order(oid):
    order = must_exist(store.orders, oid)
    if order["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "order not CONFIRMED")
    if order["order_type"] == "COMMERCIAL":
        tier = store.commercial_accounts[order["commercial_account_id"]]["discount_tier"]
    else:
        tier = None
    subtotal, discount, hazmat, net = price_order(order, tier)
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["hazmat_surcharge_cents"] = hazmat
    order["final_total_cents"] = net
    order["total_cents"] = net
    domain.consume_for_order(order)
    order["fulfillment_status"] = "SHIPPED"
    order["shipped_at"] = iso(clock_now())
    touch(order)
    if order["order_type"] == "COMMERCIAL":
        acct = store.commercial_accounts[order["commercial_account_id"]]
        domain.set_credit_used(acct)
        acct["updated_at"] = iso(real_now())
    return ok_object(public(order))


@endpoint("/orders/<oid>/cancel", ["POST"], {"Customer", "StoreAdmin"})
def cancel_order(oid):
    order = must_exist(store.orders, oid)
    if g.role == "Customer":
        check_owner(order.get("customer_id"))
    if order["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "order not cancellable")
    was_confirmed = order["fulfillment_status"] == "CONFIRMED"
    if was_confirmed:
        domain.release_for_order(order)
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    if order["order_type"] == "COMMERCIAL" and was_confirmed:
        acct = store.commercial_accounts[order["commercial_account_id"]]
        domain.set_credit_used(acct)
        touch(acct)
    return ok_object(public(order))


@endpoint("/orders/<oid>/refund", ["POST"], {"StoreAdmin"})
def refund_order(oid):
    order = must_exist(store.orders, oid)
    if order["payment_status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", "order not PAID")
    customer = store.customers.get(order.get("customer_id"))
    if customer is not None:
        customer["wallet_credit_cents"] += order["total_cents"]
        customer["loyalty_points"] = max(0, customer["loyalty_points"] - order.get("_loyalty_earned", 0))
        domain.apply_loyalty_tier(customer)
        touch(customer)
    order["payment_status"] = "REFUNDED"
    touch(order)
    return ok_object(public(order))


# ============================================================ Subscriptions ===
@endpoint("/subscriptions", ["POST"], {"Customer"})
def create_subscription():
    body = body_json()
    customer_id = v_str(body, "customer_id")
    product_id = v_str(body, "product_id")
    must_exist(store.customers, customer_id)
    product = must_exist(store.products, product_id)
    interval_days = v_int(body, "interval_days", min_val=1)
    qty = v_int(body, "quantity_per_cycle", min_val=1)
    check_owner(customer_id)
    if not product["is_subscribable"]:
        raise ApiError("ERR_SUBSCRIPTION_INVALID", "product not subscribable")
    sub = base_fields()
    sub.update({
        "customer_id": customer_id, "product_id": product_id,
        "interval_days": interval_days, "quantity_per_cycle": qty,
        "price_locked_cents": product["unit_price_cents"],
        "next_ship_at": iso(clock_now() + timedelta(days=interval_days)),
        "status": "ACTIVE",
    })
    store.subscriptions[sub["id"]] = sub
    return ok_object(public(sub), 201)


@endpoint("/subscriptions/<sid>", ["GET"], {"StoreAdmin", "Customer"})
def get_subscription(sid):
    sub = must_exist(store.subscriptions, sid)
    if g.role == "Customer":
        check_owner(sub["customer_id"])
    return ok_object(public(sub))


@endpoint("/subscriptions", ["GET"], {"StoreAdmin", "Customer"})
def list_subscriptions():
    items = list(store.subscriptions.values())
    if g.role == "Customer":
        items = [s for s in items if s["customer_id"] == g.uid]
    cust = request.args.get("customer_id")
    if cust is not None:
        items = [s for s in items if s["customer_id"] == cust]
    prod = request.args.get("product_id")
    if prod is not None:
        items = [s for s in items if s["product_id"] == prod]
    return list_response(items)


@endpoint("/subscriptions/<sid>/pause", ["POST"], {"Customer"})
def pause_subscription(sid):
    sub = must_exist(store.subscriptions, sid)
    check_owner(sub["customer_id"])
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_INVALID", "subscription not ACTIVE")
    sub["status"] = "PAUSED"  # next_ship_at frozen
    touch(sub)
    return ok_object(public(sub))


@endpoint("/subscriptions/<sid>/resume", ["POST"], {"Customer"})
def resume_subscription(sid):
    sub = must_exist(store.subscriptions, sid)
    check_owner(sub["customer_id"])
    if sub["status"] != "PAUSED":
        raise ApiError("ERR_SUBSCRIPTION_INVALID", "subscription not PAUSED")
    sub["status"] = "ACTIVE"
    sub["next_ship_at"] = iso(clock_now() + timedelta(days=sub["interval_days"]))
    touch(sub)
    return ok_object(public(sub))


@endpoint("/subscriptions/<sid>/cancel", ["POST"], {"Customer"})
def cancel_subscription(sid):
    sub = must_exist(store.subscriptions, sid)
    check_owner(sub["customer_id"])
    if sub["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", "subscription not cancellable")
    sub["status"] = "CANCELLED"
    touch(sub)
    return ok_object(public(sub))


# ============================================================ Consultants =====
@endpoint("/consultants", ["POST"], {"StoreAdmin"})
def create_consultant():
    body = body_json()
    name = v_str(body, "name")
    specialty = v_str(body, "specialty")
    hourly_rate = v_int(body, "hourly_rate_cents", min_val=1)
    buffer_minutes = v_int(body, "buffer_minutes", required=False, default=30, min_val=0)
    c = base_fields()
    c.update({
        "name": name, "specialty": specialty, "hourly_rate_cents": hourly_rate,
        "buffer_minutes": buffer_minutes, "status": "ACTIVE",
    })
    store.consultants[c["id"]] = c
    return ok_object(public(c), 201)


@endpoint("/consultants/<cid>", ["GET"], {"StoreAdmin", "Customer", "Consultant"})
def get_consultant(cid):
    return ok_object(public(must_exist(store.consultants, cid)))


@endpoint("/consultants/<cid>/bookings", ["POST"], {"Customer"})
def create_booking(cid):
    consultant = must_exist(store.consultants, cid)
    body = body_json()
    customer_id = v_str(body, "customer_id")
    must_exist(store.customers, customer_id)
    start_raw = v_str(body, "start_at")
    end_raw = v_str(body, "end_at")
    start_dt = parse_iso(start_raw)
    end_dt = parse_iso(end_raw)
    if start_dt is None or end_dt is None:
        raise ApiError("ERR_VALIDATION", "invalid datetime")
    if end_dt <= start_dt:
        raise ApiError("ERR_VALIDATION", "end_at must be after start_at")
    design_scope = v_str(body, "design_scope", required=False, default="", allow_empty=True)
    check_owner(customer_id)

    buffer = timedelta(minutes=consultant["buffer_minutes"])
    for b in store.consult_bookings.values():
        if b["consultant_id"] != cid or b["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        s = parse_iso(b["start_at"])
        e = parse_iso(b["end_at"])
        if start_dt < e + buffer and s < end_dt + buffer:
            raise ApiError("ERR_CONSULTANT_UNAVAILABLE", "consultant unavailable")

    scheduled_minutes = int((end_dt - start_dt).total_seconds() // 60)
    booking = base_fields()
    booking.update({
        "consultant_id": cid, "customer_id": customer_id,
        "start_at": start_raw, "end_at": end_raw, "design_scope": design_scope,
        "estimated_fee_cents": calc.estimated_fee(consultant["hourly_rate_cents"], scheduled_minutes),
        "actual_fee_cents": None, "status": "REQUESTED",
    })
    store.consult_bookings[booking["id"]] = booking
    return ok_object(public(booking), 201)


@endpoint("/consultants/<cid>/bookings", ["GET"], {"StoreAdmin", "Consultant"})
def list_consultant_bookings(cid):
    must_exist(store.consultants, cid)
    if g.role == "Consultant":
        check_owner(cid)
    items = [b for b in store.consult_bookings.values() if b["consultant_id"] == cid]
    return list_response(items)


@endpoint("/consult-bookings/<bid>", ["GET"], {"StoreAdmin", "Customer", "Consultant"})
def get_booking(bid):
    booking = must_exist(store.consult_bookings, bid)
    if g.role == "Customer":
        check_owner(booking["customer_id"])
    elif g.role == "Consultant":
        check_owner(booking["consultant_id"])
    return ok_object(public(booking))


@endpoint("/consult-bookings", ["GET"], {"StoreAdmin"})
def list_bookings():
    items = list(store.consult_bookings.values())
    consultant_id = request.args.get("consultant_id")
    if consultant_id is not None:
        items = [b for b in items if b["consultant_id"] == consultant_id]
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [b for b in items if b["customer_id"] == customer_id]
    return list_response(items)


@endpoint("/consult-bookings/<bid>/confirm", ["POST"], {"Consultant", "StoreAdmin"})
def confirm_booking(bid):
    booking = must_exist(store.consult_bookings, bid)
    if g.role == "Consultant":
        check_owner(booking["consultant_id"])
    if booking["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "booking not REQUESTED")
    booking["status"] = "CONFIRMED"
    touch(booking)
    return ok_object(public(booking))


@endpoint("/consult-bookings/<bid>/complete", ["POST"], {"Consultant"})
def complete_booking(bid):
    booking = must_exist(store.consult_bookings, bid)
    body = body_json()
    actual_minutes = v_int(body, "actual_minutes", min_val=1)
    check_owner(booking["consultant_id"])
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "booking not CONFIRMED")
    consultant = store.consultants[booking["consultant_id"]]
    booking["actual_fee_cents"] = calc.actual_fee(consultant["hourly_rate_cents"], actual_minutes)
    booking["status"] = "COMPLETED"
    touch(booking)
    return ok_object(public(booking))


@endpoint("/consult-bookings/<bid>/cancel", ["POST"], {"Customer", "Consultant", "StoreAdmin"})
def cancel_booking(bid):
    booking = must_exist(store.consult_bookings, bid)
    if g.role == "Customer":
        check_owner(booking["customer_id"])
    elif g.role == "Consultant":
        check_owner(booking["consultant_id"])
    if booking["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "booking not cancellable")
    booking["status"] = "CANCELLED"
    touch(booking)
    return ok_object(public(booking))


# ============================================================ Rooms/Workshops =
@endpoint("/rooms", ["POST"], {"StoreAdmin"})
def create_room():
    body = body_json()
    name = v_str(body, "name")
    seat_capacity = v_int(body, "seat_capacity", required=False, default=20, min_val=1)
    room = base_fields()
    room.update({"name": name, "seat_capacity": seat_capacity})
    store.rooms[room["id"]] = room
    return ok_object(public(room), 201)


@endpoint("/rooms/<rid>", ["GET"], {"StoreAdmin", "Customer"})
def get_room(rid):
    return ok_object(public(must_exist(store.rooms, rid)))


@endpoint("/workshop-sessions", ["POST"], {"StoreAdmin"})
def create_session():
    body = body_json()
    room_id = v_str(body, "room_id")
    room = must_exist(store.rooms, room_id)
    title = v_str(body, "title")
    start_raw = v_str(body, "start_at")
    end_raw = v_str(body, "end_at")
    start_dt = parse_iso(start_raw)
    end_dt = parse_iso(end_raw)
    if start_dt is None or end_dt is None:
        raise ApiError("ERR_VALIDATION", "invalid datetime")
    if end_dt <= start_dt:
        raise ApiError("ERR_VALIDATION", "end_at must be after start_at")
    capacity = v_int(body, "capacity", min_val=1, max_val=room["seat_capacity"])

    for sess in store.workshop_sessions.values():
        if sess["room_id"] != room_id or sess["status"] == "CANCELLED":
            continue
        s = parse_iso(sess["start_at"])
        e = parse_iso(sess["end_at"])
        if start_dt < e and s < end_dt:  # half-open overlap; adjacency allowed
            raise ApiError("ERR_ROOM_DOUBLE_BOOKED", "room double booked")

    session = base_fields()
    session.update({
        "room_id": room_id, "title": title, "start_at": start_raw, "end_at": end_raw,
        "capacity": capacity, "seats_taken": 0, "status": "SCHEDULED",
    })
    store.workshop_sessions[session["id"]] = session
    return ok_object(public(session), 201)


@endpoint("/workshop-sessions/<wid>", ["GET"], {"StoreAdmin", "Customer"})
def get_session(wid):
    return ok_object(public(must_exist(store.workshop_sessions, wid)))


@endpoint("/workshop-sessions", ["GET"], {"StoreAdmin", "Customer"})
def list_sessions():
    items = list(store.workshop_sessions.values())
    room_id = request.args.get("room_id")
    if room_id is not None:
        items = [s for s in items if s["room_id"] == room_id]
    return list_response(items)


@endpoint("/workshop-sessions/<wid>/open", ["POST"], {"StoreAdmin"})
def open_session(wid):
    session = must_exist(store.workshop_sessions, wid)
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "session not SCHEDULED")
    session["status"] = "OPEN"
    touch(session)
    return ok_object(public(session))


@endpoint("/workshop-sessions/<wid>/cancel", ["POST"], {"StoreAdmin"})
def cancel_session(wid):
    session = must_exist(store.workshop_sessions, wid)
    if session["status"] not in ("SCHEDULED", "OPEN"):
        raise ApiError("ERR_INVALID_STATE", "session not cancellable")
    for reg in store.workshop_registrations.values():
        if reg["session_id"] == wid and reg["status"] in ("REGISTERED", "WAITLISTED"):
            reg["status"] = "CANCELLED"
            touch(reg)
    session["status"] = "CANCELLED"
    domain.set_seats_taken(session)
    touch(session)
    return ok_object(public(session))


@endpoint("/workshop-sessions/<wid>/registrations", ["POST"], {"Customer"})
def create_registration(wid):
    session = must_exist(store.workshop_sessions, wid)
    body = body_json()
    customer_id = v_str(body, "customer_id")
    must_exist(store.customers, customer_id)
    check_owner(customer_id)
    if session["status"] != "OPEN":
        raise ApiError("ERR_SESSION_NOT_OPEN", "session not OPEN")
    reg = base_fields()
    status = "REGISTERED" if session["seats_taken"] < session["capacity"] else "WAITLISTED"
    reg.update({
        "session_id": wid, "customer_id": customer_id,
        "price_paid_cents": 0, "status": status,
    })
    store.workshop_registrations[reg["id"]] = reg
    domain.set_seats_taken(session)
    touch(session)
    return ok_object(public(reg), 201)


@endpoint("/workshop-sessions/<wid>/registrations", ["GET"], {"StoreAdmin", "Customer"})
def list_session_registrations(wid):
    must_exist(store.workshop_sessions, wid)
    items = [r for r in store.workshop_registrations.values() if r["session_id"] == wid]
    if g.role == "Customer":
        items = [r for r in items if r["customer_id"] == g.uid]
    return list_response(items)


@endpoint("/workshop-registrations/<rid>", ["GET"], {"StoreAdmin", "Customer"})
def get_registration(rid):
    reg = must_exist(store.workshop_registrations, rid)
    if g.role == "Customer":
        check_owner(reg["customer_id"])
    return ok_object(public(reg))


@endpoint("/workshop-registrations", ["GET"], {"StoreAdmin"})
def list_registrations():
    items = list(store.workshop_registrations.values())
    session_id = request.args.get("session_id")
    if session_id is not None:
        items = [r for r in items if r["session_id"] == session_id]
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    return list_response(items)


@endpoint("/workshop-registrations/<rid>/cancel", ["POST"], {"Customer", "StoreAdmin"})
def cancel_registration(rid):
    reg = must_exist(store.workshop_registrations, rid)
    if g.role == "Customer":
        check_owner(reg["customer_id"])
    if reg["status"] not in ("REGISTERED", "WAITLISTED"):
        raise ApiError("ERR_INVALID_STATE", "registration not cancellable")
    was_registered = reg["status"] == "REGISTERED"
    reg["status"] = "CANCELLED"
    touch(reg)
    session = store.workshop_sessions[reg["session_id"]]
    domain.set_seats_taken(session)
    if was_registered:
        waitlisted = [r for r in store.workshop_registrations.values()
                      if r["session_id"] == session["id"] and r["status"] == "WAITLISTED"]
        if waitlisted:
            promote = sort_by_created(waitlisted)[0]
            promote["status"] = "REGISTERED"
            touch(promote)
            domain.set_seats_taken(session)
    touch(session)
    return ok_object(public(reg))


# ============================================================ RMAs ============
@endpoint("/rmas", ["POST"], {"Customer"})
def create_rma():
    body = body_json()
    order_id = v_str(body, "order_id")
    product_id = v_str(body, "product_id")
    order = must_exist(store.orders, order_id)
    product = must_exist(store.products, product_id)
    return_quantity = v_int(body, "return_quantity", min_val=1)
    reason = v_str(body, "reason")
    check_owner(order.get("customer_id"))
    if order["fulfillment_status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_STATE", "order not SHIPPED")
    if product["is_hazmat"]:
        raise ApiError("ERR_HAZMAT_NOT_RETURNABLE", "hazmat goods are non-returnable")
    ordered_qty = sum(l["quantity"] for l in order["lines"] if l["product_id"] == product_id)
    if ordered_qty == 0 or return_quantity > ordered_qty:
        raise ApiError("ERR_PRODUCT_NOT_IN_ORDER", "product not in order or over-quantity")
    rma = base_fields()
    rma.update({
        "order_id": order_id, "product_id": product_id,
        "return_quantity": return_quantity, "reason": reason,
        "within_warranty": None, "refund_cents": None, "status": "SUBMITTED",
    })
    store.rmas[rma["id"]] = rma
    return ok_object(public(rma), 201)


@endpoint("/rmas/<rid>", ["GET"], {"StoreAdmin", "Customer"})
def get_rma(rid):
    rma = must_exist(store.rmas, rid)
    if g.role == "Customer":
        order = store.orders.get(rma["order_id"])
        check_owner(order.get("customer_id") if order else None)
    return ok_object(public(rma))


@endpoint("/rmas", ["GET"], {"StoreAdmin"})
def list_rmas():
    items = list(store.rmas.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [r for r in items if r["product_id"] == product_id]
    return list_response(items)


@endpoint("/rmas/<rid>/review", ["POST"], {"StoreAdmin"})
def review_rma(rid):
    rma = must_exist(store.rmas, rid)
    if rma["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "rma not SUBMITTED")
    rma["status"] = "UNDER_REVIEW"
    touch(rma)
    return ok_object(public(rma))


@endpoint("/rmas/<rid>/request-info", ["POST"], {"StoreAdmin"})
def request_info_rma(rid):
    rma = must_exist(store.rmas, rid)
    if rma["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "rma not UNDER_REVIEW")
    rma["status"] = "INFO_REQUESTED"
    touch(rma)
    return ok_object(public(rma))


@endpoint("/rmas/<rid>/provide-info", ["POST"], {"Customer"})
def provide_info_rma(rid):
    rma = must_exist(store.rmas, rid)
    order = store.orders.get(rma["order_id"])
    check_owner(order.get("customer_id") if order else None)
    if rma["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "rma not INFO_REQUESTED")
    rma["status"] = "UNDER_REVIEW"
    touch(rma)
    return ok_object(public(rma))


@endpoint("/rmas/<rid>/approve", ["POST"], {"StoreAdmin"})
def approve_rma(rid):
    rma = must_exist(store.rmas, rid)
    if rma["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "rma not UNDER_REVIEW")
    order = store.orders[rma["order_id"]]
    product = store.products[rma["product_id"]]
    matched = next(l for l in order["lines"] if l["product_id"] == rma["product_id"])
    shipped_at = parse_iso(order["shipped_at"])
    boundary = shipped_at + timedelta(days=product["warranty_months"] * calc.WARRANTY_DAYS_PER_MONTH)
    within = clock_now() <= boundary
    refund = calc.rma_refund(matched["unit_price_cents"], rma["return_quantity"], within)
    rma["within_warranty"] = within
    rma["refund_cents"] = refund

    lot = base_fields()
    lot.update({
        "product_id": product["id"], "lot_code": f"RMA-{rma['id']}",
        "quantity_on_hand": rma["return_quantity"], "quantity_reserved": 0,
        "quantity_available": rma["return_quantity"], "unit_cost_cents": 0,
        "status": "ACTIVE",
    })
    domain.set_lot_derived(lot)
    store.inventory_lots[lot["id"]] = lot
    domain.set_product_derived(product)
    touch(product)

    customer = store.customers.get(order.get("customer_id"))
    if customer is not None:
        customer["wallet_credit_cents"] += refund
        touch(customer)

    rma["status"] = "APPROVED"
    touch(rma)
    return ok_object(public(rma))


@endpoint("/rmas/<rid>/reject", ["POST"], {"StoreAdmin"})
def reject_rma(rid):
    rma = must_exist(store.rmas, rid)
    if rma["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "rma not UNDER_REVIEW")
    rma["status"] = "REJECTED"
    touch(rma)
    return ok_object(public(rma))


# ============================================================ Clock ===========
@endpoint("/_clock/set_current_utc", ["POST"], {"StoreAdmin"})
def set_clock():
    body = body_json()
    raw = v_str(body, "to_iso8601")
    dt = parse_iso(raw)
    if dt is None:
        raise ApiError("ERR_VALIDATION", "invalid to_iso8601")
    store.logical_clock = dt
    return ok_object({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
