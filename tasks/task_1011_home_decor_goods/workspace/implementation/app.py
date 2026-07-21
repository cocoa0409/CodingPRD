"""
Home Decor & Home-Goods Store API (HomeGoods style).

Single-file Flask implementation. In-memory storage only; the store starts
empty on every process boot (the test harness restarts the server before every
test via start.sh). Nothing is seeded at startup.
"""

import os
import random
import string
import math
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from uuid import uuid4

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (reset on every process boot)
# ---------------------------------------------------------------------------
KINDS = [
    "Store", "Product", "StoreInventory", "LoyaltyMember", "Order", "OrderLine",
    "DeliveryBooking", "AssemblyCrew", "Return", "Registry", "RegistryItem",
    "SpecialOrder",
]
DB = {k: {} for k in KINDS}
_SEQ = 0

# Logical clock: startup default 2026-07-01T00:00:00Z; never falls back to wall clock.
CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

VALID_ROLES = {"Admin", "MerchandisingManager", "StoreAssociate",
               "DeliveryCoordinator", "Customer"}

# Enums
PRODUCT_CATEGORIES = {"DECOR", "FURNITURE", "KITCHEN", "TEXTILE", "SEASONAL"}
ORDER_TYPES = {"CARRYOUT", "BOPIS", "OVERSIZED_DELIVERY"}
RETURN_VARIANTS = {"RECEIPTED", "NON_RECEIPTED"}

# Pricing ladders (Decimal percentages)
REGULAR_LADDER = [
    (4, "FULL", Decimal("0.00")),
    (8, "MARKDOWN_1", Decimal("0.15")),
    (12, "MARKDOWN_2", Decimal("0.30")),
]
REGULAR_CLEARANCE = ("CLEARANCE", Decimal("0.50"))
TREASURE_THRESHOLD = 8
TREASURE_FULL = ("FULL", Decimal("0.00"))
TREASURE_CLEARANCE = ("CLEARANCE", Decimal("0.40"))

TIER_DISCOUNT = {"STANDARD": Decimal("0.00"), "SILVER": Decimal("0.05"), "GOLD": Decimal("0.10")}
TIER_RATE = {"STANDARD": 1, "SILVER": 2, "GOLD": 3}

SILVER_MIN = 50000
GOLD_MIN = 200000


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def rand_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def rhu(dec_value):
    """Round half up to a whole integer."""
    if not isinstance(dec_value, Decimal):
        dec_value = Decimal(dec_value)
    return int(dec_value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_dt(s):
    """Parse an ISO-8601 datetime; always returns an aware UTC datetime."""
    if not isinstance(s, str) or not s:
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str) or not s:
        raise ApiError("ERR_VALIDATION", 400, "Invalid date")
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "Invalid date: %s" % s)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": rand_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, code=200, page_meta=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {"meta": _meta(page_meta), "response_type": rtype, "data": data}
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"}}
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "Missing or invalid user-context headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


ALL_ROLES = list(VALID_ROLES)


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return b


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, "Missing or invalid field: %s" % name)
    return v


def req_int(b, name, minimum=None):
    v = b.get(name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, "Missing or invalid integer field: %s" % name)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be >= %s" % (name, minimum))
    return v


def opt_int(b, name, default=0, minimum=None):
    if name not in b or b.get(name) is None:
        return default
    return req_int(b, name, minimum)


def opt_bool(b, name, default=False):
    if name not in b or b.get(name) is None:
        return default
    v = b.get(name)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be boolean" % name)
    return v


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "Invalid value for %s" % name)
    return v


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_entity(kind, fields):
    global _SEQ
    _SEQ += 1
    now = now_iso()
    e = {"id": uuid4().hex, "created_at": now, "updated_at": now, "version": 1, "_seq": _SEQ}
    e.update(fields)
    DB[kind][e["id"]] = e
    return e


def touch(e):
    e["updated_at"] = now_iso()
    e["version"] += 1


NOT_FOUND = {
    "Store": "ERR_STORE_NOT_FOUND",
    "Product": "ERR_PRODUCT_NOT_FOUND",
    "StoreInventory": "ERR_INVENTORY_NOT_FOUND",
    "LoyaltyMember": "ERR_MEMBER_NOT_FOUND",
    "Order": "ERR_ORDER_NOT_FOUND",
    "DeliveryBooking": "ERR_BOOKING_NOT_FOUND",
    "AssemblyCrew": "ERR_CREW_NOT_FOUND",
    "Return": "ERR_RETURN_NOT_FOUND",
    "Registry": "ERR_REGISTRY_NOT_FOUND",
    "SpecialOrder": "ERR_SPECIAL_ORDER_NOT_FOUND",
    "RegistryItem": "ERR_REGISTRY_NOT_FOUND",
    "OrderLine": "ERR_ORDER_NOT_FOUND",
}


def find(kind, id_):
    e = DB[kind].get(id_)
    if e is None:
        raise ApiError(NOT_FOUND[kind], 404, "%s not found" % kind)
    return e


def get_page():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "Invalid limit")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "Invalid offset")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    items = sorted(items, key=lambda e: e["_seq"])
    limit, offset = get_page()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": (offset + limit) < total}
    return page, meta


# ---------------------------------------------------------------------------
# Computations
# ---------------------------------------------------------------------------
def weeks_on_shelf(product):
    first = parse_dt(product["first_received_at"])
    delta = (CLOCK - first).total_seconds()
    weeks = math.floor(delta / (7 * 86400))
    return max(0, weeks)


def compute_pricing(product):
    weeks = weeks_on_shelf(product)
    if product["is_treasure_hunt"]:
        if weeks < TREASURE_THRESHOLD:
            tier, pct = TREASURE_FULL
        else:
            tier, pct = TREASURE_CLEARANCE
    else:
        tier, pct = REGULAR_CLEARANCE
        for threshold, t_name, t_pct in REGULAR_LADDER:
            if weeks < threshold:
                tier, pct = t_name, t_pct
                break
    base = product["base_price_cents"]
    discounted = rhu(Decimal(base) * (Decimal(1) - pct))
    price = max(discounted, product["clearance_floor_cents"])
    return weeks, tier, price


def compute_tier(spend):
    if spend < SILVER_MIN:
        return "STANDARD"
    if spend < GOLD_MIN:
        return "SILVER"
    return "GOLD"


def update_member_tier(member):
    member["tier"] = compute_tier(member["lifetime_spend_cents"])


def order_member(order):
    if order.get("member_id"):
        return DB["LoyaltyMember"].get(order["member_id"])
    return None


def order_lines(order_id):
    return [l for l in DB["OrderLine"].values() if l["order_id"] == order_id]


def recompute_order(order):
    member = order_member(order)
    tier = member["tier"] if member else "STANDARD"
    disc = TIER_DISCOUNT[tier]
    rate = TIER_RATE[tier]
    subtotal = 0
    for l in order_lines(order["id"]):
        net = rhu(Decimal(l["unit_price_cents"]) * Decimal(l["qty"]) * (Decimal(1) - disc))
        l["line_net_cents"] = net
        subtotal += net
    order["subtotal_cents"] = subtotal
    order["total_due_cents"] = max(subtotal - order["redeemed_cents"], 0)
    order["provisional_points"] = (subtotal // 100) * rate
    order["earned_points"] = (order["total_due_cents"] // 100) * rate


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def base_out(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def ser_product(p):
    out = base_out(p)
    weeks, tier, price = compute_pricing(p)
    out["weeks_on_shelf"] = weeks
    out["markdown_tier"] = tier
    out["current_price_cents"] = price
    return out


SERIALIZERS = {"Product": ser_product}


def serialize(kind, e):
    fn = SERIALIZERS.get(kind)
    return fn(e) if fn else base_out(e)


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global CLOCK
    _, role = auth()
    authorize(role, {"Admin"})
    b = get_body()
    CLOCK = parse_dt(req_str(b, "to_iso8601"))
    return ok({}, 200)


# ===========================================================================
# STORES
# ===========================================================================
@app.route("/stores", methods=["POST"])
def create_store():
    _, role = auth()
    authorize(role, {"Admin"})
    b = get_body()
    name = req_str(b, "name")
    region = req_str(b, "region_code")
    slots = req_int(b, "oversized_slots_per_day", minimum=1)
    e = new_entity("Store", {
        "name": name, "region_code": region,
        "oversized_slots_per_day": slots, "status": "ACTIVE",
    })
    return ok(serialize("Store", e), 201)


@app.route("/stores/<id_>", methods=["GET"])
def get_store(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    return ok(serialize("Store", find("Store", id_)), 200)


@app.route("/stores/<id_>/lock", methods=["POST"])
def lock_store(id_):
    _, role = auth()
    authorize(role, {"Admin"})
    s = find("Store", id_)
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Store is not ACTIVE")
    s["status"] = "RESET_LOCKED"
    touch(s)
    return ok(serialize("Store", s), 200)


@app.route("/stores/<id_>/unlock", methods=["POST"])
def unlock_store(id_):
    _, role = auth()
    authorize(role, {"Admin"})
    s = find("Store", id_)
    if s["status"] != "RESET_LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Store is not RESET_LOCKED")
    s["status"] = "ACTIVE"
    touch(s)
    return ok(serialize("Store", s), 200)


# ===========================================================================
# PRODUCTS
# ===========================================================================
@app.route("/products", methods=["POST"])
def create_product():
    _, role = auth()
    authorize(role, {"MerchandisingManager"})
    b = get_body()
    sku = req_str(b, "sku")
    name = req_str(b, "name")
    category = req_enum(b, "category", PRODUCT_CATEGORIES)
    base_price = req_int(b, "base_price_cents", minimum=0)
    floor = req_int(b, "clearance_floor_cents", minimum=0)
    if floor > base_price:
        raise ApiError("ERR_VALIDATION", 400, "clearance_floor_cents must be <= base_price_cents")
    first_received = req_str(b, "first_received_at")
    parse_dt(first_received)  # validate
    is_th = opt_bool(b, "is_treasure_hunt", False)
    # SKU uniqueness
    for p in DB["Product"].values():
        if p["sku"] == sku:
            raise ApiError("ERR_VALIDATION", 400, "Duplicate sku")
    e = new_entity("Product", {
        "sku": sku, "name": name, "category": category,
        "base_price_cents": base_price, "clearance_floor_cents": floor,
        "is_treasure_hunt": is_th, "first_received_at": first_received,
        "status": "ACTIVE",
    })
    return ok(serialize("Product", e), 201)


@app.route("/products/<id_>", methods=["GET"])
def get_product(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    return ok(serialize("Product", find("Product", id_)), 200)


@app.route("/products", methods=["GET"])
def list_products():
    _, role = auth()
    authorize(role, ALL_ROLES)
    items = list(DB["Product"].values())
    cat = request.args.get("category")
    if cat is not None:
        items = [p for p in items if p["category"] == cat]
    page, meta = paginate(items)
    return ok([serialize("Product", p) for p in page], 200, meta)


@app.route("/products/<id_>/discontinue", methods=["POST"])
def discontinue_product(id_):
    _, role = auth()
    authorize(role, {"MerchandisingManager"})
    p = find("Product", id_)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Product is not ACTIVE")
    p["status"] = "DISCONTINUED"
    touch(p)
    # CASCADE-A depth-1: ACTIVE StoreInventory rows for this product -> DEAD
    for inv in DB["StoreInventory"].values():
        if inv["product_id"] == id_ and inv["status"] == "ACTIVE":
            inv["status"] = "DEAD"
            touch(inv)
    # CASCADE-A depth-2/3: OPEN RegistryItems for this product -> UNAVAILABLE, refresh parent registry
    touched_registries = set()
    for item in DB["RegistryItem"].values():
        if item["product_id"] == id_ and item["status"] == "OPEN":
            item["status"] = "UNAVAILABLE"
            touch(item)
            reg = DB["Registry"].get(item["registry_id"])
            if reg is not None and reg["id"] not in touched_registries:
                touched_registries.add(reg["id"])
                touch(reg)
    return ok(serialize("Product", p), 200)


# ===========================================================================
# STORE INVENTORY
# ===========================================================================
@app.route("/store-inventory", methods=["POST"])
def create_inventory():
    _, role = auth()
    authorize(role, {"MerchandisingManager"})
    b = get_body()
    store_id = req_str(b, "store_id")
    product_id = req_str(b, "product_id")
    allocated = req_int(b, "allocated_qty", minimum=0)
    find("Store", store_id)
    find("Product", product_id)
    e = new_entity("StoreInventory", {
        "store_id": store_id, "product_id": product_id,
        "allocated_qty": allocated, "on_hand_qty": allocated,
        "reserved_qty": 0, "sold_qty": 0, "status": "ACTIVE",
    })
    return ok(serialize("StoreInventory", e), 201)


@app.route("/store-inventory/<id_>", methods=["GET"])
def get_inventory(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    return ok(serialize("StoreInventory", find("StoreInventory", id_)), 200)


@app.route("/store-inventory", methods=["GET"])
def list_inventory():
    _, role = auth()
    authorize(role, ALL_ROLES)
    items = list(DB["StoreInventory"].values())
    sid = request.args.get("store_id")
    pid = request.args.get("product_id")
    if sid is not None:
        items = [i for i in items if i["store_id"] == sid]
    if pid is not None:
        items = [i for i in items if i["product_id"] == pid]
    page, meta = paginate(items)
    return ok([serialize("StoreInventory", i) for i in page], 200, meta)


@app.route("/store-inventory/<id_>/adjust", methods=["POST"])
def adjust_inventory(id_):
    _, role = auth()
    authorize(role, {"MerchandisingManager"})
    inv = find("StoreInventory", id_)
    b = get_body()
    delta = req_int(b, "delta_qty")
    if inv["on_hand_qty"] + delta < 0:
        raise ApiError("ERR_VALIDATION", 400, "Adjustment would drive on_hand_qty below zero")
    inv["allocated_qty"] += delta
    inv["on_hand_qty"] += delta
    touch(inv)
    return ok(serialize("StoreInventory", inv), 200)


# ===========================================================================
# LOYALTY MEMBERS
# ===========================================================================
@app.route("/loyalty-members", methods=["POST"])
def create_member():
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    b = get_body()
    email = req_str(b, "email")
    full_name = req_str(b, "full_name")
    init_spend = opt_int(b, "initial_lifetime_spend_cents", 0, minimum=0)
    init_points = opt_int(b, "initial_points_balance", 0, minimum=0)
    for m in DB["LoyaltyMember"].values():
        if m["email"] == email:
            raise ApiError("ERR_VALIDATION", 400, "Duplicate email")
    e = new_entity("LoyaltyMember", {
        "email": email, "full_name": full_name,
        "lifetime_spend_cents": init_spend,
        "tier": compute_tier(init_spend),
        "points_balance": init_points,
        "points_earned_total": init_points,
        "points_redeemed_total": 0,
        "status": "ACTIVE",
    })
    return ok(serialize("LoyaltyMember", e), 201)


@app.route("/loyalty-members/<id_>", methods=["GET"])
def get_member(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    return ok(serialize("LoyaltyMember", find("LoyaltyMember", id_)), 200)


# ===========================================================================
# ORDERS
# ===========================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    b = get_body()
    store_id = req_str(b, "store_id")
    order_type = req_enum(b, "order_type", ORDER_TYPES)
    member_id = b.get("member_id")
    if member_id is not None and not isinstance(member_id, str):
        raise ApiError("ERR_VALIDATION", 400, "Invalid member_id")
    redeem = opt_int(b, "requested_redeem_points", 0, minimum=0)
    store = find("Store", store_id)
    member = None
    if member_id:
        member = find("LoyaltyMember", member_id)
    # reset gate (priority 6)
    if store["status"] == "RESET_LOCKED":
        raise ApiError("ERR_STORE_RESET_LOCKED", 409, "Store is in seasonal reset")
    # fiscal (priority 9)
    if redeem > 0:
        if member is None:
            raise ApiError("ERR_INSUFFICIENT_POINTS", 422, "Guest orders cannot redeem points")
        if redeem > member["points_balance"]:
            raise ApiError("ERR_INSUFFICIENT_POINTS", 422, "Redeem exceeds points balance")
    e = new_entity("Order", {
        "store_id": store_id, "member_id": member_id if member_id else None,
        "order_type": order_type, "requested_redeem_points": redeem,
        "fulfillment_status": "PENDING", "payment_status": "AUTHORIZED",
        "subtotal_cents": 0, "redeemed_cents": redeem, "total_due_cents": 0,
        "provisional_points": 0, "earned_points": 0, "fulfilled_at": None,
    })
    # deduct redemption immediately
    if member is not None and redeem > 0:
        member["points_balance"] -= redeem
        member["points_redeemed_total"] += redeem
        touch(member)
    recompute_order(e)
    return ok(serialize("Order", e), 201)


@app.route("/orders/<id_>", methods=["GET"])
def get_order(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    return ok(serialize("Order", find("Order", id_)), 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    _, role = auth()
    authorize(role, ALL_ROLES)
    items = list(DB["Order"].values())
    sid = request.args.get("store_id")
    mid = request.args.get("member_id")
    if sid is not None:
        items = [o for o in items if o["store_id"] == sid]
    if mid is not None:
        items = [o for o in items if o.get("member_id") == mid]
    page, meta = paginate(items)
    return ok([serialize("Order", o) for o in page], 200, meta)


@app.route("/orders/<id_>/lines", methods=["POST"])
def add_line(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    order = find("Order", id_)
    b = get_body()
    product_id = req_str(b, "product_id")
    qty = req_int(b, "qty", minimum=1)
    product = find("Product", product_id)
    # state (priority 4): product must be ACTIVE
    if product["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_DISCONTINUED", 409, "Product is discontinued")
    # referential (priority 5): duplicate line
    for l in order_lines(id_):
        if l["product_id"] == product_id:
            raise ApiError("ERR_DUPLICATE_LINE", 409, "Order already has a line for this product")
    # referential (priority 5): stocked at order's store
    inv = None
    for i in DB["StoreInventory"].values():
        if i["store_id"] == order["store_id"] and i["product_id"] == product_id:
            inv = i
            break
    if inv is None:
        raise ApiError("ERR_PRODUCT_NOT_STOCKED", 409, "Product not stocked at order's store")
    # occupation (priority 8): sufficient inventory
    if inv["on_hand_qty"] < qty:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409, "Insufficient on-hand inventory")
    _, _, price = compute_pricing(product)
    line = new_entity("OrderLine", {
        "order_id": id_, "product_id": product_id, "qty": qty,
        "unit_price_cents": price, "line_net_cents": 0, "returned_qty": 0,
    })
    # reserve
    inv["on_hand_qty"] -= qty
    inv["reserved_qty"] += qty
    touch(inv)
    recompute_order(order)
    touch(order)
    return ok(serialize("OrderLine", line), 201)


@app.route("/orders/<id_>/capture", methods=["POST"])
def capture_order(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    order = find("Order", id_)
    if order["payment_status"] != "AUTHORIZED" or order["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Cannot capture in current state")
    order["payment_status"] = "CAPTURED"
    touch(order)
    return ok(serialize("Order", order), 200)


@app.route("/orders/<id_>/ready", methods=["POST"])
def ready_order(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    order = find("Order", id_)
    if order["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not PENDING")
    if not order_lines(id_):
        raise ApiError("ERR_INVALID_STATE", 409, "Order has no lines")
    store = DB["Store"].get(order["store_id"])
    if store is None or store["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Store is not ACTIVE")
    order["fulfillment_status"] = "READY"
    touch(order)
    return ok(serialize("Order", order), 200)


@app.route("/orders/<id_>/fulfill", methods=["POST"])
def fulfill_order(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    order = find("Order", id_)
    if order["fulfillment_status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not READY")
    if order["payment_status"] != "CAPTURED":
        raise ApiError("ERR_PAYMENT_NOT_CAPTURED", 409, "Payment not captured")
    member = order_member(order)
    # recompute earned using current member tier
    recompute_order(order)
    lines = order_lines(id_)
    # commit inventory
    for l in lines:
        for i in DB["StoreInventory"].values():
            if i["store_id"] == order["store_id"] and i["product_id"] == l["product_id"]:
                i["reserved_qty"] -= l["qty"]
                i["sold_qty"] += l["qty"]
                touch(i)
                break
    earned = order["earned_points"]
    if member is not None:
        member["points_balance"] += earned
        member["points_earned_total"] += earned
        member["lifetime_spend_cents"] += order["total_due_cents"]
        update_member_tier(member)
        touch(member)
        # registry credit
        for l in lines:
            for item in DB["RegistryItem"].values():
                if item["product_id"] != l["product_id"] or item["status"] != "OPEN":
                    continue
                reg = DB["Registry"].get(item["registry_id"])
                if reg is None or reg["status"] != "ACTIVE":
                    continue
                if reg["owner_member_id"] != member["id"]:
                    continue
                item["purchased_qty"] += l["qty"]
                touch(item)
    order["fulfillment_status"] = "FULFILLED"
    order["fulfilled_at"] = fmt_dt(CLOCK)
    touch(order)
    return ok(serialize("Order", order), 200)


@app.route("/orders/<id_>/cancel", methods=["POST"])
def cancel_order(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    order = find("Order", id_)
    if order["fulfillment_status"] not in ("PENDING", "READY"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order cannot be cancelled in current state")
    member = order_member(order)
    # CASCADE-B: release reserved inventory back to on_hand, refresh owning product
    for l in order_lines(id_):
        for i in DB["StoreInventory"].values():
            if i["store_id"] == order["store_id"] and i["product_id"] == l["product_id"]:
                i["reserved_qty"] -= l["qty"]
                i["on_hand_qty"] += l["qty"]
                touch(i)
                prod = DB["Product"].get(i["product_id"])
                if prod is not None:
                    touch(prod)
                break
    # restore redeemed points
    if member is not None and order["redeemed_cents"] > 0:
        member["points_balance"] += order["redeemed_cents"]
        member["points_redeemed_total"] -= order["redeemed_cents"]
        touch(member)
    # void authorization if still authorized
    if order["payment_status"] == "AUTHORIZED":
        order["payment_status"] = "VOIDED"
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return ok(serialize("Order", order), 200)


# ===========================================================================
# ORDER LINES (reads)
# ===========================================================================
@app.route("/order-lines/<id_>", methods=["GET"])
def get_order_line(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    e = DB["OrderLine"].get(id_)
    if e is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Order line not found")
    return ok(serialize("OrderLine", e), 200)


@app.route("/order-lines", methods=["GET"])
def list_order_lines():
    _, role = auth()
    authorize(role, ALL_ROLES)
    items = list(DB["OrderLine"].values())
    oid = request.args.get("order_id")
    pid = request.args.get("product_id")
    if oid is not None:
        items = [l for l in items if l["order_id"] == oid]
    if pid is not None:
        items = [l for l in items if l["product_id"] == pid]
    page, meta = paginate(items)
    return ok([serialize("OrderLine", l) for l in page], 200, meta)


# ===========================================================================
# ASSEMBLY CREWS
# ===========================================================================
@app.route("/assembly-crews", methods=["POST"])
def create_crew():
    _, role = auth()
    authorize(role, {"Admin"})
    b = get_body()
    store_id = req_str(b, "store_id")
    name = req_str(b, "name")
    find("Store", store_id)
    e = new_entity("AssemblyCrew", {"store_id": store_id, "name": name, "status": "ACTIVE"})
    return ok(serialize("AssemblyCrew", e), 201)


@app.route("/assembly-crews/<id_>", methods=["GET"])
def get_crew(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    return ok(serialize("AssemblyCrew", find("AssemblyCrew", id_)), 200)


@app.route("/assembly-crews", methods=["GET"])
def list_crews():
    _, role = auth()
    authorize(role, ALL_ROLES)
    items = list(DB["AssemblyCrew"].values())
    sid = request.args.get("store_id")
    if sid is not None:
        items = [c for c in items if c["store_id"] == sid]
    page, meta = paginate(items)
    return ok([serialize("AssemblyCrew", c) for c in page], 200, meta)


# ===========================================================================
# DELIVERY BOOKINGS
# ===========================================================================
@app.route("/delivery-bookings", methods=["POST"])
def create_booking():
    _, role = auth()
    authorize(role, {"DeliveryCoordinator"})
    b = get_body()
    order_id = req_str(b, "order_id")
    store_id = req_str(b, "store_id")
    delivery_date_str = req_str(b, "delivery_date")
    d_date = parse_date(delivery_date_str)
    needs_assembly = opt_bool(b, "needs_assembly", False)
    crew_id = b.get("crew_id")
    aws = b.get("assembly_window_start")
    awe = b.get("assembly_window_end")
    if needs_assembly:
        if not isinstance(crew_id, str) or not crew_id:
            raise ApiError("ERR_VALIDATION", 400, "crew_id required when needs_assembly")
        aws = req_str(b, "assembly_window_start")
        awe = req_str(b, "assembly_window_end")
        req_start = parse_dt(aws)
        req_end = parse_dt(awe)
    else:
        crew_id = None
        aws = None
        awe = None
    # existence (priority 3): order, store, crew (left to right)
    find("Order", order_id)
    find("Store", store_id)
    crew = None
    if needs_assembly:
        crew = find("AssemblyCrew", crew_id)
    # referential (priority 5): crew belongs to same store
    if needs_assembly and crew["store_id"] != store_id:
        raise ApiError("ERR_CREW_STORE_MISMATCH", 409, "Crew belongs to a different store")
    # temporal (priority 7): date not in the past
    if d_date < CLOCK.date():
        raise ApiError("ERR_DELIVERY_DATE_IN_PAST", 409, "delivery_date is in the past")
    # temporal (priority 7): day capacity
    store = DB["Store"][store_id]
    occupied = 0
    for bk in DB["DeliveryBooking"].values():
        if (bk["store_id"] == store_id and bk["delivery_date"] == delivery_date_str
                and bk["status"] in ("SCHEDULED", "CONFIRMED")):
            occupied += 1
    if occupied >= store["oversized_slots_per_day"]:
        raise ApiError("ERR_DELIVERY_DAY_FULL", 409, "Store day capacity reached")
    # occupation (priority 8): assembly window overlap
    if needs_assembly:
        for bk in DB["DeliveryBooking"].values():
            if (bk["crew_id"] == crew_id and bk["status"] in ("SCHEDULED", "CONFIRMED")
                    and bk.get("assembly_window_start") and bk.get("assembly_window_end")):
                ex_start = parse_dt(bk["assembly_window_start"])
                ex_end = parse_dt(bk["assembly_window_end"])
                if req_start < ex_end and ex_start < req_end:
                    raise ApiError("ERR_ASSEMBLY_CREW_UNAVAILABLE", 409, "Assembly crew window unavailable")
    e = new_entity("DeliveryBooking", {
        "order_id": order_id, "store_id": store_id, "crew_id": crew_id,
        "delivery_date": delivery_date_str, "needs_assembly": needs_assembly,
        "assembly_window_start": aws, "assembly_window_end": awe,
        "status": "SCHEDULED",
    })
    return ok(serialize("DeliveryBooking", e), 201)


@app.route("/delivery-bookings/<id_>", methods=["GET"])
def get_booking(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    return ok(serialize("DeliveryBooking", find("DeliveryBooking", id_)), 200)


@app.route("/delivery-bookings", methods=["GET"])
def list_bookings():
    _, role = auth()
    authorize(role, ALL_ROLES)
    items = list(DB["DeliveryBooking"].values())
    oid = request.args.get("order_id")
    sid = request.args.get("store_id")
    cid = request.args.get("crew_id")
    if oid is not None:
        items = [x for x in items if x["order_id"] == oid]
    if sid is not None:
        items = [x for x in items if x["store_id"] == sid]
    if cid is not None:
        items = [x for x in items if x.get("crew_id") == cid]
    page, meta = paginate(items)
    return ok([serialize("DeliveryBooking", x) for x in page], 200, meta)


@app.route("/delivery-bookings/<id_>/confirm", methods=["POST"])
def confirm_booking(id_):
    _, role = auth()
    authorize(role, {"DeliveryCoordinator"})
    bk = find("DeliveryBooking", id_)
    if bk["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not SCHEDULED")
    store = DB["Store"].get(bk["store_id"])
    if store is not None and store["status"] == "RESET_LOCKED":
        raise ApiError("ERR_STORE_RESET_LOCKED", 409, "Store is in seasonal reset")
    bk["status"] = "CONFIRMED"
    touch(bk)
    return ok(serialize("DeliveryBooking", bk), 200)


@app.route("/delivery-bookings/<id_>/complete", methods=["POST"])
def complete_booking(id_):
    _, role = auth()
    authorize(role, {"DeliveryCoordinator"})
    bk = find("DeliveryBooking", id_)
    if bk["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not CONFIRMED")
    if CLOCK.date() < parse_date(bk["delivery_date"]):
        raise ApiError("ERR_INVALID_STATE", 409, "Cannot complete before delivery_date")
    bk["status"] = "COMPLETED"
    touch(bk)
    return ok(serialize("DeliveryBooking", bk), 200)


@app.route("/delivery-bookings/<id_>/cancel", methods=["POST"])
def cancel_booking(id_):
    _, role = auth()
    authorize(role, {"DeliveryCoordinator"})
    bk = find("DeliveryBooking", id_)
    if bk["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Booking cannot be cancelled in current state")
    bk["status"] = "CANCELLED"
    touch(bk)
    return ok(serialize("DeliveryBooking", bk), 200)


# ===========================================================================
# RETURNS
# ===========================================================================
@app.route("/returns", methods=["POST"])
def create_return():
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    b = get_body()
    order_id = req_str(b, "order_id")
    product_id = req_str(b, "product_id")
    returned_qty = req_int(b, "returned_qty", minimum=1)
    variant = "RECEIPTED"
    if "variant" in b and b.get("variant") is not None:
        variant = req_enum(b, "variant", RETURN_VARIANTS)
    order = find("Order", order_id)
    product = find("Product", product_id)
    # state (priority 4): order must be FULFILLED
    if order["fulfillment_status"] != "FULFILLED":
        raise ApiError("ERR_ORDER_NOT_FULFILLED", 409, "Order is not FULFILLED")
    # referential (priority 5): (order_id, product_id) matches a line
    line = None
    for l in order_lines(order_id):
        if l["product_id"] == product_id:
            line = l
            break
    if line is None:
        raise ApiError("ERR_LINE_NOT_FOUND", 409, "No matching order line")
    # temporal (priority 7): within 30 days of fulfilled_at
    if order.get("fulfilled_at"):
        fulfilled = parse_dt(order["fulfilled_at"])
        if CLOCK > fulfilled + timedelta(days=30):
            raise ApiError("ERR_RETURN_WINDOW_EXPIRED", 409, "Return window expired")
    # fiscal (priority 9): returned_qty <= net sold
    net_sold = line["qty"] - line["returned_qty"]
    if returned_qty > net_sold:
        raise ApiError("ERR_RETURN_QTY_EXCEEDS", 422, "Return qty exceeds net sold")
    # compute refund figures
    if variant == "RECEIPTED":
        unit_basis = line["unit_price_cents"]
    else:
        _, _, unit_basis = compute_pricing(product)
    base_refund = unit_basis * returned_qty
    if order["order_type"] == "OVERSIZED_DELIVERY":
        restock = rhu(Decimal(base_refund) * Decimal("0.15"))
    else:
        restock = 0
    refund = base_refund - restock
    e = new_entity("Return", {
        "order_id": order_id, "product_id": product_id,
        "returned_qty": returned_qty, "variant": variant, "status": "REQUESTED",
        "base_refund_cents": base_refund, "restocking_fee_cents": restock,
        "refund_amount_cents": refund,
    })
    return ok(serialize("Return", e), 201)


@app.route("/returns/<id_>", methods=["GET"])
def get_return(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    return ok(serialize("Return", find("Return", id_)), 200)


@app.route("/returns", methods=["GET"])
def list_returns():
    _, role = auth()
    authorize(role, ALL_ROLES)
    items = list(DB["Return"].values())
    oid = request.args.get("order_id")
    pid = request.args.get("product_id")
    if oid is not None:
        items = [r for r in items if r["order_id"] == oid]
    if pid is not None:
        items = [r for r in items if r["product_id"] == pid]
    page, meta = paginate(items)
    return ok([serialize("Return", r) for r in page], 200, meta)


@app.route("/returns/<id_>/approve", methods=["POST"])
def approve_return(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    ret = find("Return", id_)
    if ret["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Return is not REQUESTED")
    order = DB["Order"].get(ret["order_id"])
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Order not found")
    if order["payment_status"] != "CAPTURED":
        raise ApiError("ERR_PAYMENT_NOT_CAPTURED", 409, "Payment not captured")
    # CASCADE-C depth-1: matching order line returned_qty += qty
    line = None
    for l in order_lines(order["id"]):
        if l["product_id"] == ret["product_id"]:
            line = l
            break
    if line is None:
        raise ApiError("ERR_LINE_NOT_FOUND", 409, "No matching order line")
    line["returned_qty"] += ret["returned_qty"]
    touch(line)
    # CASCADE-C depth-2: restock inventory
    for i in DB["StoreInventory"].values():
        if i["store_id"] == order["store_id"] and i["product_id"] == ret["product_id"]:
            i["sold_qty"] -= ret["returned_qty"]
            i["on_hand_qty"] += ret["returned_qty"]
            touch(i)
            break
    # points clawback
    member = order_member(order)
    if member is not None:
        rate = TIER_RATE[member["tier"]]
        claw = (ret["refund_amount_cents"] // 100) * rate
        effective = min(claw, member["points_balance"])
        if effective != 0:
            member["points_balance"] -= effective
            member["points_earned_total"] -= effective
            touch(member)
    # full-return -> order payment REFUNDED
    total_ordered = sum(l["qty"] for l in order_lines(order["id"]))
    total_returned = sum(l["returned_qty"] for l in order_lines(order["id"]))
    if total_ordered > 0 and total_returned == total_ordered:
        order["payment_status"] = "REFUNDED"
        touch(order)
    ret["status"] = "APPROVED"
    touch(ret)
    return ok(serialize("Return", ret), 200)


# ===========================================================================
# REGISTRIES
# ===========================================================================
@app.route("/registries", methods=["POST"])
def create_registry():
    uid, role = auth()
    authorize(role, {"Customer"})
    b = get_body()
    owner_member_id = req_str(b, "owner_member_id")
    title = req_str(b, "title")
    event_date = req_str(b, "event_date")
    # ownership (Customer is entity-backed): may only create for themselves
    if owner_member_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Cannot create a registry for another member")
    find("LoyaltyMember", owner_member_id)
    e = new_entity("Registry", {
        "owner_member_id": owner_member_id, "title": title,
        "event_date": event_date, "status": "ACTIVE",
    })
    return ok(serialize("Registry", e), 201)


@app.route("/registries/<id_>", methods=["GET"])
def get_registry(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    return ok(serialize("Registry", find("Registry", id_)), 200)


@app.route("/registries", methods=["GET"])
def list_registries():
    _, role = auth()
    authorize(role, ALL_ROLES)
    items = list(DB["Registry"].values())
    owner = request.args.get("owner_member_id")
    if owner is not None:
        items = [r for r in items if r["owner_member_id"] == owner]
    page, meta = paginate(items)
    return ok([serialize("Registry", r) for r in page], 200, meta)


@app.route("/registries/<id_>/items", methods=["POST"])
def add_registry_item(id_):
    uid, role = auth()
    authorize(role, {"Customer"})
    reg = find("Registry", id_)
    if reg["owner_member_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Not the registry owner")
    b = get_body()
    product_id = req_str(b, "product_id")
    desired_qty = req_int(b, "desired_qty", minimum=1)
    find("Product", product_id)
    if reg["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRY_CLOSED", 409, "Registry is closed")
    e = new_entity("RegistryItem", {
        "registry_id": id_, "product_id": product_id,
        "desired_qty": desired_qty, "purchased_qty": 0, "status": "OPEN",
    })
    return ok(serialize("RegistryItem", e), 201)


@app.route("/registries/<id_>/close", methods=["POST"])
def close_registry(id_):
    uid, role = auth()
    authorize(role, {"Customer"})
    reg = find("Registry", id_)
    if reg["owner_member_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Not the registry owner")
    if reg["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Registry is not ACTIVE")
    reg["status"] = "CLOSED"
    touch(reg)
    return ok(serialize("Registry", reg), 200)


# ===========================================================================
# REGISTRY ITEMS (reads)
# ===========================================================================
@app.route("/registry-items/<id_>", methods=["GET"])
def get_registry_item(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    e = DB["RegistryItem"].get(id_)
    if e is None:
        raise ApiError("ERR_REGISTRY_NOT_FOUND", 404, "Registry item not found")
    return ok(serialize("RegistryItem", e), 200)


@app.route("/registry-items", methods=["GET"])
def list_registry_items():
    _, role = auth()
    authorize(role, ALL_ROLES)
    items = list(DB["RegistryItem"].values())
    rid = request.args.get("registry_id")
    pid = request.args.get("product_id")
    if rid is not None:
        items = [x for x in items if x["registry_id"] == rid]
    if pid is not None:
        items = [x for x in items if x["product_id"] == pid]
    page, meta = paginate(items)
    return ok([serialize("RegistryItem", x) for x in page], 200, meta)


# ===========================================================================
# SPECIAL ORDERS
# ===========================================================================
@app.route("/special-orders", methods=["POST"])
def create_special_order():
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    b = get_body()
    store_id = req_str(b, "store_id")
    member_id = req_str(b, "member_id")
    description = req_str(b, "description")
    find("Store", store_id)
    find("LoyaltyMember", member_id)
    e = new_entity("SpecialOrder", {
        "store_id": store_id, "member_id": member_id, "description": description,
        "quoted_price_cents": None, "quote_revision": 0, "deposit_cents": None,
        "status": "DRAFT",
    })
    return ok(serialize("SpecialOrder", e), 201)


@app.route("/special-orders/<id_>", methods=["GET"])
def get_special_order(id_):
    _, role = auth()
    authorize(role, ALL_ROLES)
    return ok(serialize("SpecialOrder", find("SpecialOrder", id_)), 200)


@app.route("/special-orders", methods=["GET"])
def list_special_orders():
    _, role = auth()
    authorize(role, ALL_ROLES)
    items = list(DB["SpecialOrder"].values())
    sid = request.args.get("store_id")
    mid = request.args.get("member_id")
    if sid is not None:
        items = [s for s in items if s["store_id"] == sid]
    if mid is not None:
        items = [s for s in items if s["member_id"] == mid]
    page, meta = paginate(items)
    return ok([serialize("SpecialOrder", s) for s in page], 200, meta)


@app.route("/special-orders/<id_>/quote", methods=["POST"])
def quote_special_order(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    so = find("SpecialOrder", id_)
    b = get_body()
    quoted_price = req_int(b, "quoted_price_cents", minimum=0)
    expected_version = req_int(b, "expected_special_order_version")
    # state (priority 4)
    if so["status"] not in ("DRAFT", "QUOTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Special order not in a quotable state")
    # OCC (priority 10)
    if expected_version != so["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale special-order version")
    so["quoted_price_cents"] = quoted_price
    so["quote_revision"] += 1
    so["status"] = "QUOTED"
    touch(so)
    return ok(serialize("SpecialOrder", so), 200)


@app.route("/special-orders/<id_>/submit-for-review", methods=["POST"])
def submit_special_order(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    so = find("SpecialOrder", id_)
    if so["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Special order is not QUOTED")
    so["status"] = "CUSTOMER_REVIEW"
    touch(so)
    return ok(serialize("SpecialOrder", so), 200)


@app.route("/special-orders/<id_>/request-changes", methods=["POST"])
def request_changes_special_order(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    so = find("SpecialOrder", id_)
    if so["status"] != "CUSTOMER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Special order is not in CUSTOMER_REVIEW")
    so["status"] = "QUOTED"
    touch(so)
    return ok(serialize("SpecialOrder", so), 200)


@app.route("/special-orders/<id_>/confirm", methods=["POST"])
def confirm_special_order(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    so = find("SpecialOrder", id_)
    if so["status"] != "CUSTOMER_REVIEW":
        raise ApiError("ERR_SPECIAL_ORDER_NOT_REVIEWABLE", 409, "Special order not reviewable")
    member = DB["LoyaltyMember"].get(so["member_id"])
    if member is None or member["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Member is not ACTIVE")
    so["deposit_cents"] = rhu(Decimal(so["quoted_price_cents"]) * Decimal("0.25"))
    so["status"] = "CONFIRMED"
    touch(so)
    return ok(serialize("SpecialOrder", so), 200)


@app.route("/special-orders/<id_>/cancel", methods=["POST"])
def cancel_special_order(id_):
    _, role = auth()
    authorize(role, {"StoreAssociate"})
    so = find("SpecialOrder", id_)
    if so["status"] not in ("DRAFT", "QUOTED", "CUSTOMER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409, "Special order cannot be cancelled")
    so["status"] = "CANCELLED"
    touch(so)
    return ok(serialize("SpecialOrder", so), 200)


# ===========================================================================
# Health
# ===========================================================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
