"""Maternity & Nursing Apparel DTC API — Python + Flask, in-memory."""
import math
import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask, request

from helpers import (
    ApiError, ok, err_response, authenticate, require_role, get_body,
    require_field, as_str, as_int, as_bool, as_number, as_enum,
    paginate, now_wall, fmt_dt, parse_dt, round_half_up,
)
from store import store

app = Flask(__name__)

# =====================================================================
# Constants (from SCAFFOLD §1.3 calculations)
# =====================================================================
TIER_RATE = {"BRONZE": Decimal("0.00"), "SILVER": Decimal("0.05"), "GOLD": Decimal("0.10")}
SUBSCRIBER_PERK_RATE = Decimal("0.05")
MAX_DISCOUNT_RATE = Decimal("0.20")
FREE_SHIP_THRESHOLD_CENTS = 8000
FLAT_SHIP_CENTS = 799
LATE_FEE_PER_DAY_CENTS = 500
DAYS_PER_WEEK = 7
LOST_GRACE_DAYS = 14
CLEANING_BUFFER_DAYS = 2
CAPSULE_KEEP_PCT = Decimal("0.70")
CAPSULE_LOAN_DAYS = 30
RESTOCK_RATE = Decimal("0.10")
SILVER_THRESHOLD = 2000
GOLD_THRESHOLD = 5000
FULL_TERM_WEEKS = 40
RETURN_WINDOW_DAYS = 30

CATEGORIES = {"MATERNITY", "NURSING", "POSTPARTUM", "CAPSULE"}
PRODUCT_STATUS = {"ACTIVE", "DISCONTINUED"}
ORDER_TYPES = {"BUY", "RENTAL"}
PLAN_TIERS = {"CAPSULE_BASIC", "CAPSULE_PLUS"}
RETURN_TYPES = {"REFUND", "STORE_CREDIT", "EXCHANGE"}
SIZE_ORDER = ["XS", "S", "M", "L", "XL"]


# =====================================================================
# Common-field / mutation helpers
# =====================================================================
def base_entity():
    ts = now_wall()
    return {"id": store.new_id(), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": store.seq()}


def touch(e):
    e["updated_at"] = now_wall()
    e["version"] += 1


def _conv(v):
    from datetime import datetime as _dt
    if isinstance(v, _dt):
        return fmt_dt(v)
    return v


def serialize(e):
    return {k: _conv(v) for k, v in e.items() if not k.startswith("_")}


# =====================================================================
# Error handlers
# =====================================================================
@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def _handle_404(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def _handle_405(e):
    return err_response(ApiError("ERR_VALIDATION", 422, "method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return err_response(e)
    return err_response(ApiError("ERR_INTERNAL", 500, str(e)))


# =====================================================================
# Lookups
# =====================================================================
def get_or_404(coll, _id, err_id):
    e = coll.get(_id)
    if e is None:
        raise ApiError(err_id, 404, "resource not found")
    return e


def get_customer(cid):
    return get_or_404(store.customers, cid, "ERR_CUSTOMER_NOT_FOUND")


def get_product(pid):
    return get_or_404(store.products, pid, "ERR_PRODUCT_NOT_FOUND")


def get_variant(vid):
    return get_or_404(store.variants, vid, "ERR_VARIANT_NOT_FOUND")


def get_order(oid):
    return get_or_404(store.orders, oid, "ERR_ORDER_NOT_FOUND")


def get_rental(rid):
    return get_or_404(store.rentals, rid, "ERR_RENTAL_NOT_FOUND")


def get_subscription(sid):
    return get_or_404(store.subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")


def get_capsule(cid):
    return get_or_404(store.capsules, cid, "ERR_CAPSULE_NOT_FOUND")


def get_return(rid):
    return get_or_404(store.returns, rid, "ERR_RETURN_NOT_FOUND")


def check_owner(resource_customer_id, uid):
    if resource_customer_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "shopper does not own this resource")


def sorted_by_seq(items):
    return sorted(items, key=lambda e: e["_seq"])


# =====================================================================
# Domain computations
# =====================================================================
def tier_of(lifetime_points):
    if lifetime_points >= GOLD_THRESHOLD:
        return "GOLD"
    if lifetime_points >= SILVER_THRESHOLD:
        return "SILVER"
    return "BRONZE"


def recompute_tier(customer):
    customer["loyalty_tier"] = tier_of(customer["lifetime_points"])


def trimester_of(customer):
    dd = customer["due_date"]
    if dd is None:
        return 0
    weeks_to_due = (dd - store.clock).total_seconds() / (7 * 86400)
    gestational = FULL_TERM_WEEKS - weeks_to_due
    if gestational < 13:
        t = 1
    elif gestational < 27:
        t = 2
    else:
        t = 3
    return max(1, min(3, t))


def has_active_subscription(customer_id):
    return any(s["customer_id"] == customer_id and s["status"] == "ACTIVE"
               for s in store.subscriptions.values())


def variant_status(variant):
    product = store.products.get(variant["product_id"])
    return product["status"] if product else "ACTIVE"


def add_ledger(customer_id, delta, reason, balance_after, related_order_id=None):
    e = {"id": store.new_id(), "created_at": now_wall(), "_seq": store.seq(),
         "customer_id": customer_id, "points_delta": delta, "reason": reason,
         "balance_after": balance_after, "related_order_id": related_order_id}
    store.ledger[e["id"]] = e
    return e


def compute_discount(subtotal, customer):
    base = TIER_RATE[tier_of(customer["lifetime_points"])]
    perk = SUBSCRIBER_PERK_RATE if has_active_subscription(customer["id"]) else Decimal("0")
    effective = min(MAX_DISCOUNT_RATE, base + perk)
    return round_half_up(subtotal, effective)


def compute_grand_total(subtotal, discount, redeemed_cents):
    net = subtotal - discount
    shipping = 0 if net >= FREE_SHIP_THRESHOLD_CENTS else FLAT_SHIP_CENTS
    grand = max(0, net - redeemed_cents + shipping)
    return shipping, grand


def ceil_days(delta):
    return math.ceil(delta.total_seconds() / 86400)


# =====================================================================
# Serializers with computed fields
# =====================================================================
def serialize_customer(c):
    out = serialize(c)
    out["loyalty_tier"] = tier_of(c["lifetime_points"])
    out["current_trimester"] = trimester_of(c)
    return out


def serialize_variant(v):
    out = serialize(v)
    out["status"] = variant_status(v)
    return out


# =====================================================================
# Serialize a paginated list into an envelope
# =====================================================================
def list_response(all_items, serializer):
    items = sorted_by_seq(all_items)
    page, pg = paginate(items)
    return ok([serializer(x) for x in page], 200, "array", pg)


# =====================================================================
# Products / Variants
# =====================================================================
@app.route("/products", methods=["POST"])
def create_product():
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    name = as_str(require_field(body, "name"), "name")
    category = as_enum(require_field(body, "category"), "category", CATEGORIES)
    buy_price = as_int(require_field(body, "buy_price_cents"), "buy_price_cents")
    rentable = as_bool(body["rentable"], "rentable") if "rentable" in body and body["rentable"] is not None else False
    rental_weekly = as_int(body["rental_weekly_cents"], "rental_weekly_cents") if body.get("rental_weekly_cents") is not None else 0
    size_system = as_str(body["size_system"], "size_system") if body.get("size_system") is not None else "US"
    status = as_enum(body["status"], "status", PRODUCT_STATUS) if body.get("status") is not None else "ACTIVE"

    p = base_entity()
    p.update({"name": name, "category": category, "rentable": rentable,
              "buy_price_cents": buy_price, "rental_weekly_cents": rental_weekly,
              "size_system": size_system, "status": status})
    store.products[p["id"]] = p
    return ok(serialize(p), 201)


@app.route("/products/<pid>", methods=["GET"])
def read_product(pid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin", "Guest"})
    return ok(serialize(get_product(pid)), 200)


@app.route("/products/<pid>/variants", methods=["POST"])
def create_variant(pid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    product = get_product(pid)
    body = get_body()
    size_label = as_str(require_field(body, "size_label"), "size_label")
    trimester_fit = require_field(body, "trimester_fit")
    if not isinstance(trimester_fit, list) or any(t not in (1, 2, 3) or isinstance(t, bool) for t in trimester_fit):
        raise ApiError("ERR_VALIDATION", 422, "trimester_fit must be a subset of [1,2,3]")
    bump_room = as_number(body["bump_room_cm"], "bump_room_cm") if body.get("bump_room_cm") is not None else 0
    inventory = as_int(body["inventory_on_hand"], "inventory_on_hand") if body.get("inventory_on_hand") is not None else 0
    rental_total = as_int(body["rental_units_total"], "rental_units_total") if body.get("rental_units_total") is not None else 0

    v = base_entity()
    v.update({"product_id": pid, "size_label": size_label,
              "trimester_fit": list(trimester_fit), "bump_room_cm": bump_room,
              "inventory_on_hand": inventory, "rental_units_total": rental_total,
              "reserved_rental_units": 0, "status": product["status"]})
    store.variants[v["id"]] = v
    return ok(serialize_variant(v), 201)


@app.route("/products/<pid>/variants", methods=["GET"])
def list_variants(pid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin", "Guest"})
    get_product(pid)
    items = [v for v in store.variants.values() if v["product_id"] == pid]
    return list_response(items, serialize_variant)


@app.route("/variants/<vid>", methods=["GET"])
def read_variant(vid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin", "Guest"})
    return ok(serialize_variant(get_variant(vid)), 200)


# =====================================================================
# Customers / Fit / Loyalty
# =====================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    uid, role = authenticate()
    require_role(role, {"Guest"})
    body = get_body()
    email = as_str(require_field(body, "email"), "email")
    full_name = as_str(require_field(body, "full_name"), "full_name")
    due_date = parse_dt(body["due_date"]) if body.get("due_date") is not None else None
    postpartum = as_bool(body["postpartum_flag"], "postpartum_flag") if body.get("postpartum_flag") is not None else False
    nursing = as_bool(body["nursing_flag"], "nursing_flag") if body.get("nursing_flag") is not None else False

    c = base_entity()
    c.update({"email": email, "full_name": full_name, "due_date": due_date,
              "postpartum_flag": postpartum, "nursing_flag": nursing,
              "loyalty_points": 0, "lifetime_points": 0, "loyalty_tier": "BRONZE",
              "current_trimester": 0, "store_credit_cents": 0})
    store.customers[c["id"]] = c
    return ok(serialize_customer(c), 201)


@app.route("/customers/<cid>", methods=["GET"])
def read_customer(cid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin"})
    return ok(serialize_customer(get_customer(cid)), 200)


@app.route("/customers/<cid>/loyalty-adjustments", methods=["POST"])
def loyalty_adjustment(cid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    customer = get_customer(cid)
    body = get_body()
    delta = as_int(require_field(body, "points_delta"), "points_delta")

    customer["loyalty_points"] += delta
    if delta > 0:
        customer["lifetime_points"] += delta
    recompute_tier(customer)
    touch(customer)
    entry = add_ledger(cid, delta, "ADJUSTMENT", customer["loyalty_points"], None)
    return ok(serialize(entry), 201)


@app.route("/customers/<cid>/loyalty-ledger", methods=["GET"])
def list_ledger(cid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "PlatformAdmin"})
    get_customer(cid)
    items = [e for e in store.ledger.values() if e["customer_id"] == cid]
    return list_response(items, serialize)


@app.route("/fit-profiles", methods=["POST"])
def create_fit_profile():
    uid, role = authenticate()
    require_role(role, {"Shopper"})
    body = get_body()
    customer_id = as_str(require_field(body, "customer_id"), "customer_id")
    bust = as_number(require_field(body, "bust_cm"), "bust_cm")
    waist = as_number(require_field(body, "waist_cm"), "waist_cm")
    hip = as_number(require_field(body, "hip_cm"), "hip_cm")
    pre_size = as_str(require_field(body, "pre_pregnancy_size"), "pre_pregnancy_size")
    customer = get_customer(customer_id)
    check_owner(customer_id, uid)

    if bust < 86:
        base = "XS"
    elif bust < 94:
        base = "S"
    elif bust < 102:
        base = "M"
    elif bust < 110:
        base = "L"
    else:
        base = "XL"
    recommended = base
    if trimester_of(customer) >= 2:
        idx = min(SIZE_ORDER.index(base) + 1, len(SIZE_ORDER) - 1)
        recommended = SIZE_ORDER[idx]

    fp = base_entity()
    fp.update({"customer_id": customer_id, "bust_cm": bust, "waist_cm": waist,
               "hip_cm": hip, "pre_pregnancy_size": pre_size,
               "recommended_size": recommended})
    store.fit_profiles[fp["id"]] = fp
    return ok(serialize(fp), 201)


@app.route("/customers/<cid>/fit-profiles", methods=["GET"])
def list_fit_profiles(cid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "PlatformAdmin"})
    get_customer(cid)
    items = [f for f in store.fit_profiles.values() if f["customer_id"] == cid]
    return list_response(items, serialize)


# =====================================================================
# Orders
# =====================================================================
def rental_availability(variant, req_start, req_end):
    occupied = 0
    for r in store.rentals.values():
        if r["variant_id"] != variant["id"]:
            continue
        if r["status"] not in ("RESERVED", "ACTIVE", "OVERDUE"):
            continue
        occ_start = r["rental_start"]
        occ_end = r["rental_end"] + timedelta(days=CLEANING_BUFFER_DAYS)
        # closed-interval overlap on both ends
        if occ_start <= req_end and req_start <= occ_end:
            occupied += 1
    return variant["rental_units_total"] - occupied


@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = authenticate()
    require_role(role, {"Shopper"})
    body = get_body()

    customer_id = as_str(require_field(body, "customer_id"), "customer_id")
    variant_id = as_str(require_field(body, "variant_id"), "variant_id")
    order_type = as_enum(require_field(body, "order_type"), "order_type", ORDER_TYPES)
    expected_variant_version = as_int(require_field(body, "expected_variant_version"), "expected_variant_version")
    is_gift = as_bool(body["is_gift"], "is_gift") if body.get("is_gift") is not None else False

    quantity = as_int(body["quantity"], "quantity") if body.get("quantity") is not None else 1
    rental_weeks = as_int(body["rental_weeks"], "rental_weeks") if body.get("rental_weeks") is not None else 0
    rental_start_raw = body.get("rental_start")

    if order_type == "BUY":
        if quantity < 1:
            raise ApiError("ERR_VALIDATION", 422, "quantity must be >= 1")
    else:  # RENTAL
        if rental_weeks < 1:
            raise ApiError("ERR_VALIDATION", 422, "rental_weeks must be >= 1 for RENTAL")

    # existence (body-referenced) then ownership
    customer = get_customer(customer_id)
    check_owner(customer_id, uid)
    variant = get_variant(variant_id)
    product = get_product(variant["product_id"])

    # business_referential: product not discontinued
    if product["status"] == "DISCONTINUED":
        raise ApiError("ERR_PRODUCT_DISCONTINUED", 409, "product is discontinued")

    # OCC on variant version
    if expected_variant_version != variant["version"]:
        raise ApiError("ERR_STALE_VARIANT_VERSION", 412, "variant version is stale")

    rental_start = None
    if order_type == "BUY":
        if quantity > variant["inventory_on_hand"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409, "quantity exceeds inventory")
        subtotal = product["buy_price_cents"] * quantity
    else:  # RENTAL
        if customer["due_date"] is None or rental_start_raw is None:
            raise ApiError("ERR_DUE_DATE_REQUIRED", 409, "due_date and rental_start required for rental")
        rental_start = parse_dt(rental_start_raw)
        rental_end = rental_start + timedelta(days=rental_weeks * DAYS_PER_WEEK)
        if rental_availability(variant, rental_start, rental_end) <= 0:
            raise ApiError("ERR_NO_RENTAL_UNITS", 409, "no rental unit available for window")
        subtotal = product["rental_weekly_cents"] * rental_weeks

    discount = compute_discount(subtotal, customer)
    earned = (subtotal - discount) // 100
    shipping, grand = compute_grand_total(subtotal, discount, 0)

    o = base_entity()
    o.update({
        "customer_id": customer_id, "variant_id": variant_id, "order_type": order_type,
        "quantity": quantity,
        "rental_weeks": rental_weeks, "rental_start": rental_start, "is_gift": is_gift,
        "expected_variant_version": expected_variant_version,
        "subtotal_cents": subtotal, "discount_cents": discount, "redeemed_points": 0,
        "redeemed_cents": 0, "shipping_cents": shipping, "grand_total_cents": grand,
        "earned_points": earned, "payment_status": "UNPAID",
        "fulfillment_status": "UNFULFILLED",
    })
    store.orders[o["id"]] = o

    if order_type == "RENTAL":
        variant["reserved_rental_units"] += 1
        rental = base_entity()
        rental.update({
            "order_id": o["id"], "variant_id": variant_id,
            "rental_start": rental_start,
            "rental_end": rental_start + timedelta(days=rental_weeks * DAYS_PER_WEEK),
            "planned_weeks": rental_weeks,
            "weekly_rate_cents": product["rental_weekly_cents"],
            "deposit_cents": product["buy_price_cents"],
            "provisional_charge_cents": product["rental_weekly_cents"] * rental_weeks,
            "final_charge_cents": 0, "late_fee_cents": 0, "returned_at": None,
            "status": "RESERVED",
        })
        store.rentals[rental["id"]] = rental

    touch(variant)  # every accepted order advances variant version
    return ok(serialize(o), 201)


@app.route("/orders/<oid>", methods=["GET"])
def read_order(oid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin"})
    return ok(serialize(get_order(oid)), 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin"})
    cust = request.args.get("customer_id")
    var = request.args.get("variant_id")
    items = list(store.orders.values())
    if cust is not None:
        items = [o for o in items if o["customer_id"] == cust]
    if var is not None:
        items = [o for o in items if o["variant_id"] == var]
    return list_response(items, serialize)


@app.route("/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    uid, role = authenticate()
    require_role(role, {"Shopper"})
    order = get_order(oid)
    check_owner(order["customer_id"], uid)
    body = get_body()
    expected_customer_version = as_int(require_field(body, "expected_customer_version"), "expected_customer_version")
    redeemed_points = as_int(body["redeemed_points"], "redeemed_points") if body.get("redeemed_points") is not None else 0
    if redeemed_points < 0:
        raise ApiError("ERR_VALIDATION", 422, "redeemed_points must be >= 0")

    # state precondition
    if order["payment_status"] != "UNPAID":
        raise ApiError("ERR_ORDER_NOT_PAYABLE", 409, "order is not payable")
    if order["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_ORDER_NOT_PAYABLE", 409, "order is cancelled")

    customer = get_customer(order["customer_id"])
    subtotal = order["subtotal_cents"]

    # fiscal: redemption limits
    if redeemed_points > customer["loyalty_points"]:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 409, "redeemed_points exceed balance")
    if redeemed_points > subtotal // 2:
        raise ApiError("ERR_REDEMPTION_EXCEEDS_LIMIT", 409, "redemption exceeds half of subtotal")

    # OCC on customer version
    if expected_customer_version != customer["version"]:
        raise ApiError("ERR_STALE_CUSTOMER_VERSION", 412, "customer version is stale")

    # recompute in pinned order
    discount = compute_discount(subtotal, customer)
    redeemed_cents = min(redeemed_points, subtotal // 2, customer["loyalty_points"])
    shipping, grand = compute_grand_total(subtotal, discount, redeemed_cents)
    earned = (subtotal - discount) // 100

    order["discount_cents"] = discount
    order["redeemed_points"] = redeemed_points
    order["redeemed_cents"] = redeemed_cents
    order["shipping_cents"] = shipping
    order["grand_total_cents"] = grand
    order["earned_points"] = earned
    order["payment_status"] = "PAID"
    touch(order)

    if redeemed_points > 0:
        customer["loyalty_points"] -= redeemed_points
        add_ledger(customer["id"], -redeemed_points, "REDEEMED", customer["loyalty_points"], order["id"])
    touch(customer)  # paying always advances customer version
    return ok(serialize(order), 200)


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, role = authenticate()
    require_role(role, {"Shopper"})
    order = get_order(oid)
    check_owner(order["customer_id"], uid)

    if order["fulfillment_status"] != "UNFULFILLED":
        raise ApiError("ERR_ORDER_ALREADY_FULFILLED", 409, "order already fulfilled or cancelled")

    order["fulfillment_status"] = "CANCELLED"

    # cascade hop1: linked rental (RESERVED or ACTIVE) -> CANCELLED, release unit
    if order["order_type"] == "RENTAL":
        for r in store.rentals.values():
            if r["order_id"] == order["id"] and r["status"] in ("RESERVED", "ACTIVE"):
                r["status"] = "CANCELLED"
                touch(r)
                variant = store.variants.get(r["variant_id"])
                if variant:
                    variant["reserved_rental_units"] -= 1
                    touch(variant)

    customer = store.customers.get(order["customer_id"])
    customer_changed = False
    if order["payment_status"] == "PAID":
        order["payment_status"] = "REFUNDED"
        if customer:
            customer["store_credit_cents"] += order["grand_total_cents"]
            customer_changed = True
    if order["redeemed_points"] > 0 and customer:
        customer["loyalty_points"] += order["redeemed_points"]
        add_ledger(customer["id"], order["redeemed_points"], "REVERSAL_REDEEM",
                   customer["loyalty_points"], order["id"])
        customer_changed = True

    touch(order)
    if customer_changed:
        touch(customer)
    return ok(serialize(order), 200)


@app.route("/orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    uid, role = authenticate()
    require_role(role, {"FulfillmentAgent"})
    order = get_order(oid)

    if order["payment_status"] != "PAID":
        raise ApiError("ERR_ORDER_NOT_PAID", 409, "order is not paid")
    if order["fulfillment_status"] != "UNFULFILLED":
        raise ApiError("ERR_ORDER_ALREADY_FULFILLED", 409, "order already fulfilled or cancelled")

    order["fulfillment_status"] = "FULFILLED"
    order["_fulfilled_at"] = store.clock

    if order["order_type"] == "BUY":
        variant = store.variants.get(order["variant_id"])
        if variant:
            variant["inventory_on_hand"] -= order["quantity"]
            touch(variant)

    customer = store.customers.get(order["customer_id"])
    if customer:
        earned = order["earned_points"]
        customer["lifetime_points"] += earned
        customer["loyalty_points"] += earned
        add_ledger(customer["id"], earned, "EARNED", customer["loyalty_points"], order["id"])
        recompute_tier(customer)
        touch(customer)

    touch(order)
    return ok(serialize(order), 200)


# =====================================================================
# Rentals
# =====================================================================
@app.route("/rentals/<rid>", methods=["GET"])
def read_rental(rid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin"})
    return ok(serialize(get_rental(rid)), 200)


@app.route("/rentals", methods=["GET"])
def list_rentals():
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin"})
    order_id = request.args.get("order_id")
    variant_id = request.args.get("variant_id")
    items = list(store.rentals.values())
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    if variant_id is not None:
        items = [r for r in items if r["variant_id"] == variant_id]
    return list_response(items, serialize)


@app.route("/rentals/<rid>/activate", methods=["POST"])
def activate_rental(rid):
    uid, role = authenticate()
    require_role(role, {"FulfillmentAgent"})
    rental = get_rental(rid)
    if rental["status"] != "RESERVED":
        raise ApiError("ERR_RENTAL_NOT_ACTIVE", 409, "rental is not RESERVED")
    variant = store.variants.get(rental["variant_id"])
    if variant is None or variant_status(variant) != "ACTIVE":
        raise ApiError("ERR_PRODUCT_DISCONTINUED", 409, "product is discontinued")
    rental["status"] = "ACTIVE"
    touch(rental)
    return ok(serialize(rental), 200)


@app.route("/rentals/<rid>/return", methods=["POST"])
def return_rental(rid):
    uid, role = authenticate()
    require_role(role, {"FulfillmentAgent"})
    rental = get_rental(rid)
    if rental["status"] not in ("ACTIVE", "OVERDUE"):
        raise ApiError("ERR_RENTAL_NOT_ACTIVE", 409, "rental is not active or overdue")

    returned_at = store.clock
    rental["returned_at"] = returned_at

    weekly = rental["weekly_rate_cents"]
    planned = rental["planned_weeks"]
    deposit = rental["deposit_cents"]
    days_used = ceil_days(returned_at - rental["rental_start"])
    actual_weeks = max(1, math.ceil(days_used / DAYS_PER_WEEK))
    if returned_at <= rental["rental_end"]:
        rental["final_charge_cents"] = weekly * min(actual_weeks, planned)
        rental["late_fee_cents"] = 0
    else:
        late_days = ceil_days(returned_at - rental["rental_end"])
        late_fee = min(late_days * LATE_FEE_PER_DAY_CENTS, deposit)
        rental["late_fee_cents"] = late_fee
        rental["final_charge_cents"] = weekly * planned + late_fee

    rental["status"] = "RETURNED"
    touch(rental)

    variant = store.variants.get(rental["variant_id"])
    if variant:
        variant["reserved_rental_units"] -= 1
        touch(variant)
    return ok(serialize(rental), 200)


@app.route("/rentals/<rid>/convert-to-buy", methods=["POST"])
def convert_rental(rid):
    uid, role = authenticate()
    require_role(role, {"Shopper"})
    rental = get_rental(rid)
    order = store.orders.get(rental["order_id"])
    if order is not None:
        check_owner(order["customer_id"], uid)
    if rental["status"] != "ACTIVE":
        raise ApiError("ERR_RENTAL_NOT_ACTIVE", 409, "rental is not ACTIVE")

    deposit = rental["deposit_cents"]
    rental["final_charge_cents"] = deposit - min(rental["provisional_charge_cents"], deposit)
    rental["status"] = "CONVERTED_TO_BUY"
    touch(rental)

    variant = store.variants.get(rental["variant_id"])
    if variant:
        variant["reserved_rental_units"] -= 1
        variant["rental_units_total"] -= 1
        touch(variant)
    return ok(serialize(rental), 200)


# =====================================================================
# Subscriptions / Capsules
# =====================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    uid, role = authenticate()
    require_role(role, {"Shopper"})
    body = get_body()
    customer_id = as_str(require_field(body, "customer_id"), "customer_id")
    plan_tier = as_enum(require_field(body, "plan_tier"), "plan_tier", PLAN_TIERS)
    monthly_fee = as_int(require_field(body, "monthly_fee_cents"), "monthly_fee_cents")
    next_ship = parse_dt(require_field(body, "next_ship_date"))
    items_per = as_int(body["items_per_capsule"], "items_per_capsule") if body.get("items_per_capsule") is not None else 3
    get_customer(customer_id)
    check_owner(customer_id, uid)

    s = base_entity()
    s.update({"customer_id": customer_id, "plan_tier": plan_tier,
              "monthly_fee_cents": monthly_fee, "items_per_capsule": items_per,
              "next_ship_date": next_ship, "capsules_shipped": 0, "status": "ACTIVE"})
    store.subscriptions[s["id"]] = s
    return ok(serialize(s), 201)


@app.route("/subscriptions/<sid>", methods=["GET"])
def read_subscription(sid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin"})
    return ok(serialize(get_subscription(sid)), 200)


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin"})
    customer_id = request.args.get("customer_id")
    items = list(store.subscriptions.values())
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    return list_response(items, serialize)


@app.route("/subscriptions/<sid>/pause", methods=["POST"])
def pause_subscription(sid):
    uid, role = authenticate()
    require_role(role, {"Shopper"})
    s = get_subscription(sid)
    check_owner(s["customer_id"], uid)
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "subscription is not ACTIVE")
    s["status"] = "PAUSED"
    touch(s)
    return ok(serialize(s), 200)


@app.route("/subscriptions/<sid>/resume", methods=["POST"])
def resume_subscription(sid):
    uid, role = authenticate()
    require_role(role, {"Shopper"})
    s = get_subscription(sid)
    check_owner(s["customer_id"], uid)
    if s["status"] != "PAUSED":
        raise ApiError("ERR_SUBSCRIPTION_NOT_PAUSED", 409, "subscription is not PAUSED")
    s["status"] = "ACTIVE"
    touch(s)
    return ok(serialize(s), 200)


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = authenticate()
    require_role(role, {"Shopper"})
    s = get_subscription(sid)
    check_owner(s["customer_id"], uid)
    if s["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_SUBSCRIPTION_TERMINAL", 409, "subscription is terminal")
    s["status"] = "CANCELLED"
    touch(s)
    # cascade: PACKED capsules -> VOIDED
    for c in store.capsules.values():
        if c["subscription_id"] == sid and c["status"] == "PACKED":
            c["status"] = "VOIDED"
            touch(c)
    return ok(serialize(s), 200)


@app.route("/subscriptions/<sid>/capsules", methods=["POST"])
def pack_capsule(sid):
    uid, role = authenticate()
    require_role(role, {"FulfillmentAgent"})
    subscription = get_subscription(sid)
    body = get_body()
    item_variant_ids = require_field(body, "item_variant_ids")
    if not isinstance(item_variant_ids, list) or any(not isinstance(x, str) for x in item_variant_ids):
        raise ApiError("ERR_VALIDATION", 422, "item_variant_ids must be a list of ids")
    ship_date = parse_dt(require_field(body, "ship_date"))

    retail = 0
    for vid in item_variant_ids:
        variant = get_variant(vid)
        product = store.products.get(variant["product_id"])
        retail += round_half_up(product["buy_price_cents"], CAPSULE_KEEP_PCT)

    c = base_entity()
    c.update({"subscription_id": sid, "item_variant_ids": list(item_variant_ids),
              "ship_date": ship_date,
              "possession_end": ship_date + timedelta(days=CAPSULE_LOAN_DAYS),
              "retail_value_cents": retail, "status": "PACKED"})
    store.capsules[c["id"]] = c
    return ok(serialize(c), 201)


@app.route("/subscriptions/<sid>/capsules", methods=["GET"])
def list_capsules(sid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin"})
    get_subscription(sid)
    items = [c for c in store.capsules.values() if c["subscription_id"] == sid]
    return list_response(items, serialize)


@app.route("/capsules/<cid>/ship", methods=["POST"])
def ship_capsule(cid):
    uid, role = authenticate()
    require_role(role, {"FulfillmentAgent"})
    capsule = get_capsule(cid)
    if capsule["status"] != "PACKED":
        raise ApiError("ERR_CAPSULE_NOT_PACKED", 409, "capsule is not PACKED")
    subscription = store.subscriptions.get(capsule["subscription_id"])
    if subscription is None or subscription["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "subscription is not ACTIVE")

    # window overlap against other SHIPPED capsules (half-open [ship_date, possession_end))
    a_start = capsule["ship_date"]
    a_end = capsule["possession_end"]
    for other in store.capsules.values():
        if other["id"] == cid or other["subscription_id"] != capsule["subscription_id"]:
            continue
        if other["status"] != "SHIPPED":
            continue
        if a_start < other["possession_end"] and other["ship_date"] < a_end:
            raise ApiError("ERR_CAPSULE_WINDOW_OVERLAP", 409, "possession window overlaps a shipped capsule")

    capsule["status"] = "SHIPPED"
    touch(capsule)
    subscription["capsules_shipped"] += 1
    touch(subscription)
    return ok(serialize(capsule), 200)


# =====================================================================
# Returns
# =====================================================================
@app.route("/returns", methods=["POST"])
def create_return():
    uid, role = authenticate()
    require_role(role, {"Shopper"})
    body = get_body()
    order_id = as_str(require_field(body, "order_id"), "order_id")
    reason = as_str(require_field(body, "reason"), "reason")
    return_type = as_enum(require_field(body, "return_type"), "return_type", RETURN_TYPES)
    order = get_order(order_id)
    check_owner(order["customer_id"], uid)

    if not (order["payment_status"] == "PAID" and order["fulfillment_status"] == "FULFILLED"):
        raise ApiError("ERR_ORDER_NOT_RETURNABLE", 409, "order is not completed")
    fulfilled_at = order.get("_fulfilled_at")
    if fulfilled_at is not None and (store.clock - fulfilled_at) > timedelta(days=RETURN_WINDOW_DAYS):
        raise ApiError("ERR_RETURN_WINDOW_EXPIRED", 409, "return window expired")

    r = base_entity()
    r.update({"order_id": order_id, "reason": reason, "return_type": return_type,
              "refund_cents": 0, "restocking_fee_cents": 0, "status": "REQUESTED"})
    store.returns[r["id"]] = r
    return ok(serialize(r), 201)


@app.route("/returns/<rid>", methods=["GET"])
def read_return(rid):
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin"})
    return ok(serialize(get_return(rid)), 200)


@app.route("/returns", methods=["GET"])
def list_returns():
    uid, role = authenticate()
    require_role(role, {"Shopper", "FulfillmentAgent", "PlatformAdmin"})
    order_id = request.args.get("order_id")
    items = list(store.returns.values())
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    return list_response(items, serialize)


@app.route("/returns/<rid>/approve", methods=["POST"])
def approve_return(rid):
    uid, role = authenticate()
    require_role(role, {"FulfillmentAgent"})
    ret = get_return(rid)
    if ret["status"] != "REQUESTED":
        raise ApiError("ERR_RETURN_NOT_REQUESTED", 409, "return is not REQUESTED")
    order = store.orders.get(ret["order_id"])

    restocking = round_half_up(order["subtotal_cents"], RESTOCK_RATE) if ret["return_type"] == "REFUND" else 0
    refund = max(0, order["grand_total_cents"] - restocking)
    ret["restocking_fee_cents"] = restocking
    ret["refund_cents"] = refund
    ret["status"] = "APPROVED"
    touch(ret)

    # cascade
    order["payment_status"] = "REFUNDED"
    touch(order)
    customer = store.customers.get(order["customer_id"])
    if customer:
        earned = order["earned_points"]
        customer["lifetime_points"] -= earned
        customer["loyalty_points"] = max(0, customer["loyalty_points"] - earned)
        add_ledger(customer["id"], -earned, "CLAWBACK_EARNED", customer["loyalty_points"], order["id"])
        recompute_tier(customer)
        if ret["return_type"] == "STORE_CREDIT":
            customer["store_credit_cents"] += refund
        touch(customer)
    return ok(serialize(ret), 200)


@app.route("/returns/<rid>/reject", methods=["POST"])
def reject_return(rid):
    uid, role = authenticate()
    require_role(role, {"FulfillmentAgent"})
    ret = get_return(rid)
    if ret["status"] != "REQUESTED":
        raise ApiError("ERR_RETURN_NOT_REQUESTED", 409, "return is not REQUESTED")
    ret["status"] = "REJECTED"
    touch(ret)
    return ok(serialize(ret), 200)


# =====================================================================
# Logical clock
# =====================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    to_iso = require_field(body, "to_iso8601")
    store.clock = parse_dt(to_iso)

    # ACTIVE -> OVERDUE
    for r in store.rentals.values():
        if r["status"] == "ACTIVE" and store.clock > r["rental_end"]:
            r["status"] = "OVERDUE"
            touch(r)
    # OVERDUE -> LOST
    for r in store.rentals.values():
        if r["status"] == "OVERDUE" and store.clock > r["rental_end"] + timedelta(days=LOST_GRACE_DAYS):
            r["final_charge_cents"] = r["deposit_cents"]
            r["late_fee_cents"] = 0
            r["status"] = "LOST"
            touch(r)
            variant = store.variants.get(r["variant_id"])
            if variant:
                variant["reserved_rental_units"] -= 1
                variant["rental_units_total"] -= 1
                touch(variant)
    return ok({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
