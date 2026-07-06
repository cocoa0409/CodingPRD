"""Toy & Hobby Store REST API. Flask + in-memory store."""
import os
from datetime import datetime, timezone, timedelta

from flask import Flask, request

from db import db, new_id, now_dt, now_ts, fmt_ts
import errors as E
from errors import ApiError
from response import ok, ok_list, err

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
CATALOG_ADMIN = "CatalogAdmin"
STORE_MANAGER = "StoreManager"
STORE_ASSOCIATE = "StoreAssociate"
CUSTOMER = "Customer"
ANY = "Any"
VALID_ROLES = {CATALOG_ADMIN, STORE_MANAGER, STORE_ASSOCIATE, CUSTOMER, ANY}
ALL_AUTHENTICATED = VALID_ROLES  # for GET (Any = read access for all roles)

# Enums
CATEGORIES = {"BOARD_GAME", "MODEL_KIT", "PLUSH", "ACTION_FIGURE", "CRAFT_KIT"}
SAFETY_LABELS = {"CHOKING_HAZARD", "SMALL_PARTS", "FLAMMABLE", "BATTERY", "NONE"}
SEVERITIES = {"ADVISORY", "MANDATORY"}
REGISTRY_TYPES = {"BIRTHDAY", "HOLIDAY", "WISHLIST"}
FULFILLMENT_TYPES = {"BOPIS", "SHIP_FROM_STORE"}


# ---------------------------------------------------------------------------
# Auth / role helpers
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError(
            E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
            "Missing or invalid X-User-ID / X-User-Role header",
        )
    return uid, role


def require_role(role, allowed):
    if allowed is ALL_AUTHENTICATED:
        return
    if role not in allowed:
        raise ApiError(E.ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this operation")


def require_owner(role, uid, owner_customer_id):
    if role == CUSTOMER and owner_customer_id != uid:
        raise ApiError(E.ERR_FORBIDDEN_ROLE, 403, "Customer may only act on own resources")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError(E.ERR_VALIDATION, 400, "Malformed request body")
    return b


def _bad(msg):
    raise ApiError(E.ERR_VALIDATION, 400, msg)


def req_str(b, k):
    v = b.get(k)
    if not isinstance(v, str) or v == "":
        _bad(f"Missing or invalid field: {k}")
    return v


def opt_str(b, k, default=None):
    if k not in b or b[k] is None:
        return default
    v = b[k]
    if not isinstance(v, str):
        _bad(f"Invalid field: {k}")
    return v


def req_int(b, k, minimum=None):
    v = b.get(k)
    if not isinstance(v, int) or isinstance(v, bool):
        _bad(f"Missing or invalid integer field: {k}")
    if minimum is not None and v < minimum:
        _bad(f"Field {k} must be >= {minimum}")
    return v


def opt_int(b, k, default=None, minimum=None):
    if k not in b or b[k] is None:
        return default
    v = b[k]
    if not isinstance(v, int) or isinstance(v, bool):
        _bad(f"Invalid integer field: {k}")
    if minimum is not None and v < minimum:
        _bad(f"Field {k} must be >= {minimum}")
    return v


def req_bool(b, k, default=None):
    if k not in b or b[k] is None:
        if default is not None:
            return default
        _bad(f"Missing field: {k}")
    v = b[k]
    if not isinstance(v, bool):
        _bad(f"Invalid boolean field: {k}")
    return v


def req_enum(b, k, choices):
    v = req_str(b, k)
    if v not in choices:
        _bad(f"Invalid value for {k}")
    return v


def parse_dt(s):
    if not isinstance(s, str):
        _bad("Invalid datetime")
    try:
        t = s
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        _bad("Invalid ISO 8601 datetime")


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def base_entity(with_common=True):
    ent = {"id": new_id(), "_seq": db.next_seq(), "created_at": now_dt()}
    if with_common:
        ent["updated_at"] = now_dt()
        ent["version"] = 1
    return ent


def touch(ent):
    ent["updated_at"] = now_dt()
    ent["version"] = ent.get("version", 1) + 1


def serialize(ent):
    out = {}
    for k, v in ent.items():
        if k.startswith("_"):
            continue
        if k in ("created_at", "updated_at") and isinstance(v, datetime):
            out[k] = fmt_ts(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Pagination + list
# ---------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    if "limit" in request.args:
        try:
            limit = int(request.args["limit"])
        except (ValueError, TypeError):
            _bad("Invalid limit")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in request.args:
        try:
            offset = int(request.args["offset"])
        except (ValueError, TypeError):
            _bad("Invalid offset")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(items, filters=None):
    """items: iterable of entity dicts. filters: list of (field, value) to match."""
    rows = list(items)
    if filters:
        for field, val in filters:
            if val is not None:
                rows = [r for r in rows if str(r.get(field)) == str(val)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    limit, offset = pagination()
    page = rows[offset:offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(coll, ident, error_id):
    ent = coll.get(ident)
    if ent is None:
        raise ApiError(error_id, 404, "Resource not found")
    return ent


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def tier_of(lifetime):
    if lifetime >= 5000:
        return "GOLD"
    if lifetime >= 1000:
        return "SILVER"
    return "BRONZE"


def line_discount(extended, tier, is_exclusive):
    if is_exclusive:
        return 0
    if tier == "SILVER":
        return (extended * 5) // 100
    if tier == "GOLD":
        return (extended * 10) // 100
    return 0


# (num, den) tier multipliers for loyalty points
MULT = {"BRONZE": (1, 1), "SILVER": (3, 2), "GOLD": (2, 1)}


def recompute_customer(cust):
    cust["points_balance"] = cust["lifetime_points"] - cust["points_redeemed"]
    cust["loyalty_tier"] = tier_of(cust["lifetime_points"])


def recompute_inventory(item):
    item["available_qty"] = item["on_hand_qty"] - item["reserved_qty"] - item["quarantined_qty"]


def recompute_allocation(alloc):
    alloc["available_alloc_qty"] = alloc["allocated_qty"] - alloc["committed_qty"]


def active_lines(order_id):
    return [l for l in db.order_lines.values()
            if l["order_id"] == order_id and l["status"] == "ACTIVE"]


def recompute_order_pricing(order):
    """Recompute pricing over ACTIVE lines using the customer's current tier."""
    cust = db.customers.get(order["customer_id"])
    tier = cust["loyalty_tier"] if cust else "BRONZE"
    subtotal = 0
    discount = 0
    for l in active_lines(order["id"]):
        prod = db.products.get(l["product_id"])
        is_excl = prod["is_exclusive"] if prod else False
        ext = l["unit_price_cents"] * l["qty"]
        l["extended_cents"] = ext
        disc = line_discount(ext, tier, is_excl)
        l["line_discount_cents"] = disc
        subtotal += ext
        discount += disc
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["total_cents"] = subtotal - discount


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return err(e.error_id, e.http_status, e.message)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return err(e.error_id, e.http_status, e.message)
    return err("ERR_INTERNAL", 500, str(e))


# ===========================================================================
# PRODUCTS
# ===========================================================================
@app.route("/products", methods=["POST"])
def create_product():
    _, role = auth()
    require_role(role, {CATALOG_ADMIN})
    b = get_body()
    sku = req_str(b, "sku")
    name = req_str(b, "name")
    category = req_enum(b, "category", CATEGORIES)
    age = req_int(b, "age_grade_min_months", minimum=0)
    labels = b.get("safety_labels")
    if not isinstance(labels, list) or any(x not in SAFETY_LABELS for x in labels):
        _bad("Invalid safety_labels")
    msrp = req_int(b, "msrp_cents", minimum=0)
    is_excl = req_bool(b, "is_exclusive", default=False)
    if any(p["sku"] == sku for p in db.products.values()):
        raise ApiError(E.ERR_DUPLICATE_SKU, 409, "sku already exists")
    p = base_entity()
    p.update({
        "sku": sku, "name": name, "category": category,
        "age_grade_min_months": age, "safety_labels": labels,
        "msrp_cents": msrp, "is_exclusive": is_excl,
        "status": "DRAFT", "recall_status": "CLEARED",
    })
    db.products[p["id"]] = p
    return ok(serialize(p), 201)


@app.route("/products", methods=["GET"])
def list_products():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.products.values(), [
        ("category", request.args.get("category")),
        ("sku", request.args.get("sku")),
    ])


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.products, pid, E.ERR_PRODUCT_NOT_FOUND)))


@app.route("/products/<pid>", methods=["PATCH"])
def update_product(pid):
    _, role = auth()
    require_role(role, {CATALOG_ADMIN})
    p = get_or_404(db.products, pid, E.ERR_PRODUCT_NOT_FOUND)
    b = get_body()
    if "name" in b:
        p["name"] = req_str(b, "name")
    if "age_grade_min_months" in b:
        p["age_grade_min_months"] = req_int(b, "age_grade_min_months", minimum=0)
    if "safety_labels" in b:
        labels = b.get("safety_labels")
        if not isinstance(labels, list) or any(x not in SAFETY_LABELS for x in labels):
            _bad("Invalid safety_labels")
        p["safety_labels"] = labels
    if "msrp_cents" in b:
        p["msrp_cents"] = req_int(b, "msrp_cents", minimum=0)
    if "is_exclusive" in b:
        p["is_exclusive"] = req_bool(b, "is_exclusive")
    touch(p)
    return ok(serialize(p))


@app.route("/products/<pid>/activate", methods=["POST"])
def activate_product(pid):
    _, role = auth()
    require_role(role, {CATALOG_ADMIN})
    p = get_or_404(db.products, pid, E.ERR_PRODUCT_NOT_FOUND)
    if p["status"] == "DISCONTINUED":
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409, "Product discontinued")
    if p["status"] != "DRAFT":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Product not in DRAFT")
    p["status"] = "ACTIVE"
    touch(p)
    return ok(serialize(p))


@app.route("/products/<pid>/discontinue", methods=["POST"])
def discontinue_product(pid):
    _, role = auth()
    require_role(role, {CATALOG_ADMIN})
    p = get_or_404(db.products, pid, E.ERR_PRODUCT_NOT_FOUND)
    if p["status"] == "DISCONTINUED":
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409, "Product already discontinued")
    if p["status"] != "ACTIVE":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Product not ACTIVE")
    p["status"] = "DISCONTINUED"
    touch(p)
    return ok(serialize(p))


# ===========================================================================
# STORES
# ===========================================================================
@app.route("/stores", methods=["POST"])
def create_store():
    _, role = auth()
    require_role(role, {CATALOG_ADMIN})
    b = get_body()
    name = req_str(b, "name")
    state_code = req_str(b, "state_code")
    buf = opt_int(b, "event_buffer_minutes", default=30, minimum=0)
    s = base_entity()
    s.update({"name": name, "state_code": state_code, "event_buffer_minutes": buf})
    db.stores[s["id"]] = s
    return ok(serialize(s), 201)


@app.route("/stores", methods=["GET"])
def list_stores():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.stores.values())


@app.route("/stores/<sid>", methods=["GET"])
def get_store(sid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.stores, sid, E.ERR_STORE_NOT_FOUND)))


# ===========================================================================
# INVENTORY
# ===========================================================================
@app.route("/inventory", methods=["POST"])
def create_inventory():
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    b = get_body()
    product_id = req_str(b, "product_id")
    store_id = req_str(b, "store_id")
    on_hand = req_int(b, "on_hand_qty", minimum=0)
    get_or_404(db.products, product_id, E.ERR_PRODUCT_NOT_FOUND)
    get_or_404(db.stores, store_id, E.ERR_STORE_NOT_FOUND)
    it = base_entity()
    it.update({
        "product_id": product_id, "store_id": store_id,
        "on_hand_qty": on_hand, "reserved_qty": 0,
        "quarantined_qty": 0, "available_qty": on_hand,
    })
    db.inventory[it["id"]] = it
    return ok(serialize(it), 201)


@app.route("/inventory", methods=["GET"])
def list_inventory():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.inventory.values(), [
        ("product_id", request.args.get("product_id")),
        ("store_id", request.args.get("store_id")),
    ])


@app.route("/inventory/<iid>", methods=["GET"])
def get_inventory(iid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.inventory, iid, E.ERR_INVENTORY_NOT_FOUND)))


@app.route("/inventory/<iid>/receive", methods=["POST"])
def receive_inventory(iid):
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    it = get_or_404(db.inventory, iid, E.ERR_INVENTORY_NOT_FOUND)
    b = get_body()
    qty = req_int(b, "qty", minimum=1)
    it["on_hand_qty"] += qty
    recompute_inventory(it)
    touch(it)
    return ok(serialize(it))


# ===========================================================================
# ALLOCATIONS
# ===========================================================================
def _intervals_overlap_halfopen(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@app.route("/allocations", methods=["POST"])
def create_allocation():
    _, role = auth()
    require_role(role, {STORE_MANAGER})
    b = get_body()
    product_id = req_str(b, "product_id")
    store_id = req_str(b, "store_id")
    allocated = req_int(b, "allocated_qty", minimum=1)
    ss_raw = req_str(b, "season_start")
    se_raw = req_str(b, "season_end")
    ss = parse_dt(ss_raw)
    se = parse_dt(se_raw)
    get_or_404(db.products, product_id, E.ERR_PRODUCT_NOT_FOUND)
    get_or_404(db.stores, store_id, E.ERR_STORE_NOT_FOUND)
    for a in db.allocations.values():
        if a["product_id"] == product_id and a["store_id"] == store_id and a["status"] != "RELEASED":
            if _intervals_overlap_halfopen(ss, se, a["_ss"], a["_se"]):
                raise ApiError(E.ERR_ALLOCATION_WINDOW_OVERLAP, 409, "Allocation window overlaps")
    a = base_entity()
    a.update({
        "product_id": product_id, "store_id": store_id,
        "allocated_qty": allocated, "committed_qty": 0, "released_qty": 0,
        "available_alloc_qty": allocated,
        "season_start": ss_raw, "season_end": se_raw,
        "_ss": ss, "_se": se, "status": "ACTIVE",
    })
    db.allocations[a["id"]] = a
    return ok(serialize(a), 201)


@app.route("/allocations", methods=["GET"])
def list_allocations():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.allocations.values(), [
        ("product_id", request.args.get("product_id")),
        ("store_id", request.args.get("store_id")),
    ])


@app.route("/allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.allocations, aid, E.ERR_ALLOCATION_NOT_FOUND)))


@app.route("/allocations/<aid>/release", methods=["POST"])
def release_allocation(aid):
    _, role = auth()
    require_role(role, {STORE_MANAGER})
    a = get_or_404(db.allocations, aid, E.ERR_ALLOCATION_NOT_FOUND)
    if a["status"] == "RELEASED":
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409, "Allocation already released")
    if a["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise ApiError(E.ERR_INVALID_STATE, 409, "Allocation not releasable")
    a["released_qty"] = a["available_alloc_qty"]
    a["available_alloc_qty"] = 0
    a["status"] = "RELEASED"
    touch(a)
    return ok(serialize(a))


# ===========================================================================
# CUSTOMERS
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    b = get_body()
    name = req_str(b, "name")
    email = req_str(b, "email")
    if any(c["email"] == email for c in db.customers.values()):
        raise ApiError(E.ERR_DUPLICATE_EMAIL, 409, "email already exists")
    c = base_entity()
    c.update({
        "name": name, "email": email,
        "lifetime_points": 0, "points_redeemed": 0,
        "points_balance": 0, "loyalty_tier": "BRONZE",
    })
    db.customers[c["id"]] = c
    return ok(serialize(c), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.customers, cid, E.ERR_CUSTOMER_NOT_FOUND)))


# ===========================================================================
# ORDERS
# ===========================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = auth()
    require_role(role, {CUSTOMER, STORE_ASSOCIATE})
    b = get_body()
    customer_id = req_str(b, "customer_id")
    store_id = req_str(b, "store_id")
    ftype = req_enum(b, "fulfillment_type", FULFILLMENT_TYPES)
    require_owner(role, uid, customer_id)
    get_or_404(db.customers, customer_id, E.ERR_CUSTOMER_NOT_FOUND)
    get_or_404(db.stores, store_id, E.ERR_STORE_NOT_FOUND)
    o = base_entity()
    o.update({
        "customer_id": customer_id, "store_id": store_id,
        "fulfillment_type": ftype, "fulfillment_status": "OPEN",
        "payment_status": "UNPAID", "subtotal_cents": 0,
        "discount_cents": 0, "total_cents": 0, "amount_paid_cents": 0,
        "pricing_variant": "PROVISIONAL",
    })
    db.orders[o["id"]] = o
    return ok(serialize(o), 201)


@app.route("/orders", methods=["GET"])
def list_orders():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.orders.values(), [
        ("customer_id", request.args.get("customer_id")),
        ("store_id", request.args.get("store_id")),
    ])


@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.orders, oid, E.ERR_ORDER_NOT_FOUND)))


def _find_inventory(product_id, store_id):
    for it in db.inventory.values():
        if it["product_id"] == product_id and it["store_id"] == store_id:
            return it
    return None


@app.route("/orders/<oid>/lines", methods=["POST"])
def add_order_line(oid):
    uid, role = auth()
    require_role(role, {CUSTOMER, STORE_ASSOCIATE})
    o = get_or_404(db.orders, oid, E.ERR_ORDER_NOT_FOUND)
    require_owner(role, uid, o["customer_id"])
    b = get_body()
    product_id = req_str(b, "product_id")
    qty = req_int(b, "qty", minimum=1)
    age = req_int(b, "recipient_age_months", minimum=0)
    p = get_or_404(db.products, product_id, E.ERR_PRODUCT_NOT_FOUND)
    if o["fulfillment_status"] != "OPEN":
        raise ApiError(E.ERR_ORDER_NOT_OPEN, 409, "Order not OPEN")
    # age-grade gate (5)
    if age < p["age_grade_min_months"]:
        raise ApiError(E.ERR_AGE_GRADE_VIOLATION, 422, "Recipient below age grade")
    # recall gate (6)
    if p["recall_status"] != "CLEARED":
        raise ApiError(E.ERR_PRODUCT_RECALLED, 409, "Product under recall")
    # inventory (9)
    it = _find_inventory(product_id, o["store_id"])
    if it is None or it["available_qty"] < qty:
        raise ApiError(E.ERR_INSUFFICIENT_INVENTORY, 409, "Insufficient inventory")
    line = base_entity()
    line.update({
        "order_id": oid, "product_id": product_id, "qty": qty,
        "recipient_age_months": age,
        "unit_price_cents": p["msrp_cents"],
        "extended_cents": p["msrp_cents"] * qty,
        "line_discount_cents": 0, "status": "ACTIVE",
        "_inventory_item_id": it["id"],
    })
    db.order_lines[line["id"]] = line
    it["reserved_qty"] += qty
    recompute_inventory(it)
    touch(it)
    return ok(serialize(line), 201)


@app.route("/order-lines", methods=["GET"])
def list_order_lines():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.order_lines.values(), [
        ("order_id", request.args.get("order_id")),
        ("product_id", request.args.get("product_id")),
    ])


@app.route("/order-lines/<lid>", methods=["GET"])
def get_order_line(lid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.order_lines, lid, E.ERR_ORDER_LINE_NOT_FOUND)))


@app.route("/orders/<oid>/submit", methods=["POST"])
def submit_order(oid):
    uid, role = auth()
    require_role(role, {CUSTOMER, STORE_ASSOCIATE})
    o = get_or_404(db.orders, oid, E.ERR_ORDER_NOT_FOUND)
    require_owner(role, uid, o["customer_id"])
    if o["fulfillment_status"] != "OPEN":
        raise ApiError(E.ERR_ORDER_NOT_OPEN, 409, "Order not OPEN")
    if not active_lines(oid):
        raise ApiError(E.ERR_INVALID_STATE, 409, "Order has no active lines")
    o["fulfillment_status"] = "SUBMITTED"
    recompute_order_pricing(o)
    o["pricing_variant"] = "PROVISIONAL"
    touch(o)
    return ok(serialize(o))


@app.route("/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    uid, role = auth()
    require_role(role, {CUSTOMER, STORE_ASSOCIATE})
    o = get_or_404(db.orders, oid, E.ERR_ORDER_NOT_FOUND)
    require_owner(role, uid, o["customer_id"])
    b = get_body()
    amount = req_int(b, "amount_cents", minimum=1)
    if o["fulfillment_status"] == "CANCELLED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Order cancelled")
    if o["amount_paid_cents"] + amount > o["total_cents"]:
        raise ApiError(E.ERR_OVERPAYMENT, 409, "Payment exceeds remaining balance")
    o["amount_paid_cents"] += amount
    if o["amount_paid_cents"] >= o["total_cents"]:
        o["payment_status"] = "PAID"
    else:
        o["payment_status"] = "PARTIALLY_PAID"
    touch(o)
    return ok(serialize(o))


@app.route("/orders/<oid>/mark-ready", methods=["POST"])
def mark_ready_order(oid):
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    o = get_or_404(db.orders, oid, E.ERR_ORDER_NOT_FOUND)
    if o["fulfillment_status"] != "SUBMITTED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Order not SUBMITTED")
    for l in active_lines(oid):
        p = db.products.get(l["product_id"])
        if p and p["recall_status"] != "CLEARED":
            raise ApiError(E.ERR_PRODUCT_RECALLED, 409, "Product under recall")
    o["fulfillment_status"] = "READY"
    o["pricing_variant"] = "FINAL"
    recompute_order_pricing(o)
    touch(o)
    return ok(serialize(o))


@app.route("/orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    o = get_or_404(db.orders, oid, E.ERR_ORDER_NOT_FOUND)
    if o["fulfillment_status"] != "READY":
        raise ApiError(E.ERR_ORDER_NOT_READY, 409, "Order not READY")
    if o["payment_status"] != "PAID":
        raise ApiError(E.ERR_ORDER_NOT_PAID, 409, "Order not fully paid")
    for l in active_lines(oid):
        it = db.inventory.get(l.get("_inventory_item_id")) or _find_inventory(l["product_id"], o["store_id"])
        if it:
            it["on_hand_qty"] -= l["qty"]
            it["reserved_qty"] -= l["qty"]
            recompute_inventory(it)
            touch(it)
        # commit allocation if ACTIVE
        for a in db.allocations.values():
            if (a["product_id"] == l["product_id"] and a["store_id"] == o["store_id"]
                    and a["status"] == "ACTIVE"):
                a["committed_qty"] += l["qty"]
                recompute_allocation(a)
                if a["available_alloc_qty"] == 0:
                    a["status"] = "EXHAUSTED"
                touch(a)
                break
        # registry purchased_qty
        for reg in db.registries.values():
            if reg["customer_id"] == o["customer_id"] and reg["status"] == "ACTIVE":
                for ri in db.registry_items.values():
                    if ri["registry_id"] == reg["id"] and ri["product_id"] == l["product_id"]:
                        ri["purchased_qty"] += l["qty"]
    # loyalty points on FINAL total
    cust = db.customers.get(o["customer_id"])
    if cust:
        num, den = MULT[cust["loyalty_tier"]]
        base = o["total_cents"] // 100
        earned = (base * num) // den
        cust["lifetime_points"] += earned
        recompute_customer(cust)
        touch(cust)
        o["_earn_mult"] = MULT[cust["loyalty_tier"]]  # tier after credit == unchanged tier basis
    o["_earn_mult"] = o.get("_earn_mult", MULT.get(cust["loyalty_tier"], (1, 1)) if cust else (1, 1))
    o["fulfillment_status"] = "FULFILLED"
    o["_fulfilled_at"] = now_dt()
    touch(o)
    return ok(serialize(o))


def _void_line_release_inventory(line):
    """Order-cancel chain: release reserved units back to inventory."""
    it = db.inventory.get(line.get("_inventory_item_id")) or _find_inventory(
        line["product_id"], db.orders[line["order_id"]]["store_id"])
    if it:
        it["reserved_qty"] -= line["qty"]
        recompute_inventory(it)
        touch(it)
    line["status"] = "VOIDED"
    touch(line)


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, role = auth()
    require_role(role, {CUSTOMER, STORE_ASSOCIATE})
    o = get_or_404(db.orders, oid, E.ERR_ORDER_NOT_FOUND)
    require_owner(role, uid, o["customer_id"])
    if o["fulfillment_status"] == "CANCELLED":
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409, "Order already cancelled")
    if o["fulfillment_status"] not in ("OPEN", "SUBMITTED", "READY"):
        raise ApiError(E.ERR_INVALID_STATE, 409, "Order not cancellable")
    for l in active_lines(oid):
        _void_line_release_inventory(l)
    o["fulfillment_status"] = "CANCELLED"
    recompute_order_pricing(o)
    touch(o)
    return ok(serialize(o))


# ===========================================================================
# LAYAWAYS
# ===========================================================================
@app.route("/layaways", methods=["POST"])
def create_layaway():
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    b = get_body()
    customer_id = req_str(b, "customer_id")
    total = req_int(b, "total_cents", minimum=1)
    count = req_int(b, "installment_count", minimum=1)
    order_id = opt_str(b, "order_id", default=None)
    get_or_404(db.customers, customer_id, E.ERR_CUSTOMER_NOT_FOUND)
    if order_id is not None:
        get_or_404(db.orders, order_id, E.ERR_ORDER_NOT_FOUND)
    base = total // count
    schedule = [base] * count
    schedule[-1] += total - base * count
    lay = base_entity()
    lay.update({
        "customer_id": customer_id, "order_id": order_id,
        "total_cents": total, "installment_count": count,
        "installment_schedule_cents": schedule,
        "paid_cents": 0, "remaining_cents": total, "status": "ACTIVE",
    })
    db.layaways[lay["id"]] = lay
    return ok(serialize(lay), 201)


@app.route("/layaways", methods=["GET"])
def list_layaways():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.layaways.values(), [
        ("customer_id", request.args.get("customer_id")),
        ("order_id", request.args.get("order_id")),
    ])


@app.route("/layaways/<lid>", methods=["GET"])
def get_layaway(lid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.layaways, lid, E.ERR_LAYAWAY_NOT_FOUND)))


@app.route("/layaways/<lid>/payments", methods=["POST"])
def pay_layaway(lid):
    uid, role = auth()
    require_role(role, {CUSTOMER, STORE_ASSOCIATE})
    lay = get_or_404(db.layaways, lid, E.ERR_LAYAWAY_NOT_FOUND)
    require_owner(role, uid, lay["customer_id"])
    b = get_body()
    amount = req_int(b, "amount_cents", minimum=1)
    if lay["status"] != "ACTIVE":
        raise ApiError(E.ERR_LAYAWAY_NOT_ACTIVE, 409, "Layaway not ACTIVE")
    if amount > lay["remaining_cents"]:
        raise ApiError(E.ERR_LAYAWAY_OVERPAYMENT, 409, "Payment exceeds remaining")
    lay["paid_cents"] += amount
    lay["remaining_cents"] = lay["total_cents"] - lay["paid_cents"]
    if lay["paid_cents"] >= lay["total_cents"]:
        lay["status"] = "PAID_IN_FULL"
        lay["remaining_cents"] = 0
    touch(lay)
    return ok(serialize(lay))


@app.route("/layaways/<lid>/cancel", methods=["POST"])
def cancel_layaway(lid):
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    lay = get_or_404(db.layaways, lid, E.ERR_LAYAWAY_NOT_FOUND)
    if lay["status"] != "ACTIVE":
        raise ApiError(E.ERR_LAYAWAY_NOT_ACTIVE, 409, "Layaway not ACTIVE")
    lay["status"] = "CANCELLED"
    touch(lay)
    return ok(serialize(lay))


# ===========================================================================
# SPECIAL ORDERS
# ===========================================================================
@app.route("/special-orders", methods=["POST"])
def create_special_order():
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    b = get_body()
    customer_id = req_str(b, "customer_id")
    product_id = req_str(b, "product_id")
    requested = req_int(b, "requested_qty", minimum=1)
    get_or_404(db.customers, customer_id, E.ERR_CUSTOMER_NOT_FOUND)
    get_or_404(db.products, product_id, E.ERR_PRODUCT_NOT_FOUND)
    so = base_entity()
    so.update({
        "customer_id": customer_id, "product_id": product_id,
        "requested_qty": requested, "quoted_unit_price_cents": None,
        "deposit_cents": None, "quote_revision": 0,
        "status": "DRAFT", "converted_order_id": None,
    })
    db.special_orders[so["id"]] = so
    return ok(serialize(so), 201)


@app.route("/special-orders", methods=["GET"])
def list_special_orders():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.special_orders.values(), [
        ("customer_id", request.args.get("customer_id")),
        ("product_id", request.args.get("product_id")),
        ("converted_order_id", request.args.get("converted_order_id")),
    ])


@app.route("/special-orders/<sid>", methods=["GET"])
def get_special_order(sid):
    uid, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    so = get_or_404(db.special_orders, sid, E.ERR_SPECIAL_ORDER_NOT_FOUND)
    # auto-transition QUOTED -> CUSTOMER_REVIEW on first customer read
    if role == CUSTOMER and so["status"] == "QUOTED" and so["customer_id"] == uid:
        so["status"] = "CUSTOMER_REVIEW"
        touch(so)
    return ok(serialize(so))


@app.route("/special-orders/<sid>/quotes", methods=["POST"])
def quote_special_order(sid):
    _, role = auth()
    require_role(role, {STORE_MANAGER})
    so = get_or_404(db.special_orders, sid, E.ERR_SPECIAL_ORDER_NOT_FOUND)
    b = get_body()
    unit_price = req_int(b, "unit_price_cents", minimum=0)
    deposit = req_int(b, "deposit_cents", minimum=0)
    expected = req_int(b, "expected_special_order_version")
    if so["status"] not in ("DRAFT", "QUOTED", "CUSTOMER_REVIEW"):
        raise ApiError(E.ERR_INVALID_STATE, 409, "Special order not quotable")
    if expected != so["version"]:
        raise ApiError(E.ERR_STALE_SPECIAL_ORDER_VERSION, 412, "Stale special order version")
    so["quoted_unit_price_cents"] = unit_price
    so["deposit_cents"] = deposit
    so["quote_revision"] += 1
    so["status"] = "QUOTED"
    touch(so)
    return ok(serialize(so))


@app.route("/special-orders/<sid>/approve", methods=["POST"])
def approve_special_order(sid):
    uid, role = auth()
    require_role(role, {CUSTOMER})
    so = get_or_404(db.special_orders, sid, E.ERR_SPECIAL_ORDER_NOT_FOUND)
    require_owner(role, uid, so["customer_id"])
    if so["status"] not in ("QUOTED", "CUSTOMER_REVIEW"):
        raise ApiError(E.ERR_INVALID_STATE, 409, "Special order not in reviewable state")
    so["status"] = "APPROVED"
    touch(so)
    return ok(serialize(so))


@app.route("/special-orders/<sid>/convert", methods=["POST"])
def convert_special_order(sid):
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    so = get_or_404(db.special_orders, sid, E.ERR_SPECIAL_ORDER_NOT_FOUND)
    if so["status"] != "APPROVED":
        raise ApiError(E.ERR_SPECIAL_ORDER_NOT_APPROVED, 409, "Special order not APPROVED")
    # find an ACTIVE allocation for the product
    active_allocs = [a for a in db.allocations.values()
                     if a["product_id"] == so["product_id"] and a["status"] == "ACTIVE"]
    if not active_allocs:
        raise ApiError(E.ERR_NO_ALLOCATION, 409, "No active allocation")
    alloc = None
    for a in sorted(active_allocs, key=lambda x: (x["created_at"], x["_seq"])):
        if a["available_alloc_qty"] >= so["requested_qty"]:
            alloc = a
            break
    if alloc is None:
        raise ApiError(E.ERR_INSUFFICIENT_ALLOCATION, 409, "Insufficient allocation")
    p = db.products.get(so["product_id"])
    o = base_entity()
    o.update({
        "customer_id": so["customer_id"], "store_id": alloc["store_id"],
        "fulfillment_type": "BOPIS", "fulfillment_status": "OPEN",
        "payment_status": "UNPAID", "subtotal_cents": 0, "discount_cents": 0,
        "total_cents": 0, "amount_paid_cents": 0, "pricing_variant": "PROVISIONAL",
    })
    db.orders[o["id"]] = o
    unit_price = so["quoted_unit_price_cents"] if so["quoted_unit_price_cents"] is not None else (p["msrp_cents"] if p else 0)
    line = base_entity()
    line.update({
        "order_id": o["id"], "product_id": so["product_id"],
        "qty": so["requested_qty"], "recipient_age_months": 0,
        "unit_price_cents": unit_price,
        "extended_cents": unit_price * so["requested_qty"],
        "line_discount_cents": 0, "status": "ACTIVE",
        "_inventory_item_id": None,
    })
    db.order_lines[line["id"]] = line
    alloc["committed_qty"] += so["requested_qty"]
    recompute_allocation(alloc)
    if alloc["available_alloc_qty"] == 0:
        alloc["status"] = "EXHAUSTED"
    touch(alloc)
    so["status"] = "CONVERTED"
    so["converted_order_id"] = o["id"]
    touch(so)
    return ok(serialize(o))


# ===========================================================================
# RECALLS
# ===========================================================================
def _apply_recall_to_product(product):
    """Product recall_status CLEARED -> RECALLED with quarantine + line-void cascade."""
    if product["recall_status"] != "CLEARED":
        return
    product["recall_status"] = "RECALLED"
    touch(product)
    # link2: quarantine inventory
    for it in db.inventory.values():
        if it["product_id"] == product["id"]:
            it["quarantined_qty"] += it["available_qty"] + it["reserved_qty"]
            it["reserved_qty"] = 0
            it["available_qty"] = 0
            touch(it)
    # link3/4: void ACTIVE order lines on this product (no inventory release; already quarantined)
    for line in db.order_lines.values():
        if line["product_id"] == product["id"] and line["status"] == "ACTIVE":
            line["status"] = "VOIDED"
            touch(line)
            order = db.orders.get(line["order_id"])
            if order:
                recompute_order_pricing(order)
                if not active_lines(order["id"]) and order["fulfillment_status"] not in ("CANCELLED", "FULFILLED"):
                    order["fulfillment_status"] = "CANCELLED"
                touch(order)


def _clear_recall_from_product(product):
    if product["recall_status"] != "RECALLED":
        return
    product["recall_status"] = "CLEARED"
    touch(product)
    for it in db.inventory.values():
        if it["product_id"] == product["id"]:
            it["quarantined_qty"] = 0
            it["available_qty"] = it["on_hand_qty"] - it["reserved_qty"]
            touch(it)


@app.route("/recalls", methods=["POST"])
def create_recall():
    _, role = auth()
    require_role(role, {CATALOG_ADMIN})
    b = get_body()
    product_id = req_str(b, "product_id")
    severity = req_enum(b, "severity", SEVERITIES)
    reason = req_str(b, "reason")
    get_or_404(db.products, product_id, E.ERR_PRODUCT_NOT_FOUND)
    r = base_entity()
    r.update({"product_id": product_id, "severity": severity,
              "reason": reason, "status": "OPEN"})
    db.recalls[r["id"]] = r
    return ok(serialize(r), 201)


@app.route("/recalls", methods=["GET"])
def list_recalls():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.recalls.values(), [
        ("product_id", request.args.get("product_id")),
    ])


@app.route("/recalls/<rid>", methods=["GET"])
def get_recall(rid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.recalls, rid, E.ERR_RECALL_NOT_FOUND)))


@app.route("/recalls/<rid>/issue", methods=["POST"])
def issue_recall(rid):
    _, role = auth()
    require_role(role, {CATALOG_ADMIN})
    r = get_or_404(db.recalls, rid, E.ERR_RECALL_NOT_FOUND)
    b = get_body()
    resolve = req_bool(b, "resolve", default=False)
    product = db.products.get(r["product_id"])
    if resolve:
        if r["status"] != "ISSUED":
            raise ApiError(E.ERR_INVALID_STATE, 409, "Recall not ISSUED")
        r["status"] = "RESOLVED"
        touch(r)
        if product:
            _clear_recall_from_product(product)
        return ok(serialize(r))
    # issue
    if r["status"] != "OPEN":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Recall not OPEN")
    if product and product["status"] == "DRAFT":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Product in DRAFT")
    r["status"] = "ISSUED"
    touch(r)
    if product:
        _apply_recall_to_product(product)
    return ok(serialize(r))


# ===========================================================================
# DEMO EVENTS
# ===========================================================================
@app.route("/events", methods=["POST"])
def create_event():
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    b = get_body()
    store_id = req_str(b, "store_id")
    product_id = req_str(b, "product_id")
    start_raw = req_str(b, "start_at")
    end_raw = req_str(b, "end_at")
    capacity = req_int(b, "capacity", minimum=1)
    start = parse_dt(start_raw)
    end = parse_dt(end_raw)
    store = get_or_404(db.stores, store_id, E.ERR_STORE_NOT_FOUND)
    get_or_404(db.products, product_id, E.ERR_PRODUCT_NOT_FOUND)
    buf = timedelta(minutes=store["event_buffer_minutes"])
    exp_start = start - buf
    exp_end = end + buf
    for ev in db.events.values():
        if ev["store_id"] == store_id and ev["status"] == "SCHEDULED":
            # closed-interval overlap of expanded new interval with existing
            if exp_start <= ev["_end"] and ev["_start"] <= exp_end:
                raise ApiError(E.ERR_EVENT_OVERLAP, 409, "Event overlaps existing event")
    ev = base_entity()
    ev.update({
        "store_id": store_id, "product_id": product_id,
        "start_at": start_raw, "end_at": end_raw,
        "_start": start, "_end": end,
        "capacity": capacity, "registered_customer_ids": [],
        "registered_count": 0, "status": "SCHEDULED",
    })
    db.events[ev["id"]] = ev
    return ok(serialize(ev), 201)


@app.route("/events", methods=["GET"])
def list_events():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.events.values(), [
        ("store_id", request.args.get("store_id")),
        ("product_id", request.args.get("product_id")),
    ])


@app.route("/events/<eid>", methods=["GET"])
def get_event(eid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.events, eid, E.ERR_EVENT_NOT_FOUND)))


@app.route("/events/<eid>/register", methods=["POST"])
def register_event(eid):
    uid, role = auth()
    require_role(role, {CUSTOMER})
    ev = get_or_404(db.events, eid, E.ERR_EVENT_NOT_FOUND)
    b = get_body()
    customer_id = req_str(b, "customer_id")
    require_owner(role, uid, customer_id)
    get_or_404(db.customers, customer_id, E.ERR_CUSTOMER_NOT_FOUND)
    if ev["status"] != "SCHEDULED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Event not SCHEDULED")
    if ev["registered_count"] >= ev["capacity"]:
        raise ApiError(E.ERR_EVENT_FULL, 409, "Event full")
    if customer_id in ev["registered_customer_ids"]:
        raise ApiError(E.ERR_DUPLICATE_EVENT_REGISTRATION, 409, "Already registered")
    ev["registered_customer_ids"].append(customer_id)
    ev["registered_count"] += 1
    touch(ev)
    return ok(serialize(ev))


# ===========================================================================
# GIFT REGISTRIES
# ===========================================================================
@app.route("/registries", methods=["POST"])
def create_registry():
    uid, role = auth()
    require_role(role, {CUSTOMER})
    b = get_body()
    customer_id = req_str(b, "customer_id")
    registry_type = req_enum(b, "registry_type", REGISTRY_TYPES)
    require_owner(role, uid, customer_id)
    get_or_404(db.customers, customer_id, E.ERR_CUSTOMER_NOT_FOUND)
    reg = base_entity()
    reg.update({"customer_id": customer_id, "registry_type": registry_type, "status": "ACTIVE"})
    db.registries[reg["id"]] = reg
    return ok(serialize(reg), 201)


@app.route("/registries", methods=["GET"])
def list_registries():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.registries.values(), [
        ("customer_id", request.args.get("customer_id")),
    ])


@app.route("/registries/<rid>", methods=["GET"])
def get_registry(rid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.registries, rid, E.ERR_REGISTRY_NOT_FOUND)))


@app.route("/registries/<rid>/items", methods=["POST"])
def add_registry_item(rid):
    uid, role = auth()
    require_role(role, {CUSTOMER})
    reg = get_or_404(db.registries, rid, E.ERR_REGISTRY_NOT_FOUND)
    require_owner(role, uid, reg["customer_id"])
    b = get_body()
    product_id = req_str(b, "product_id")
    desired = req_int(b, "desired_qty", minimum=1)
    p = get_or_404(db.products, product_id, E.ERR_PRODUCT_NOT_FOUND)
    if reg["status"] != "ACTIVE":
        raise ApiError(E.ERR_REGISTRY_NOT_ACTIVE, 409, "Registry not ACTIVE")
    ri = base_entity(with_common=False)
    ri.update({
        "registry_id": rid, "product_id": product_id,
        "desired_qty": desired, "purchased_qty": 0,
    })
    db.registry_items[ri["id"]] = ri
    return ok(serialize(ri), 201)


@app.route("/registries/<rid>/items", methods=["GET"])
def list_registry_items_nested(rid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    get_or_404(db.registries, rid, E.ERR_REGISTRY_NOT_FOUND)
    return list_response(db.registry_items.values(), [("registry_id", rid)])


@app.route("/registry-items", methods=["GET"])
def list_registry_items():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.registry_items.values(), [
        ("registry_id", request.args.get("registry_id")),
        ("product_id", request.args.get("product_id")),
    ])


@app.route("/registry-items/<riid>", methods=["GET"])
def get_registry_item(riid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.registry_items, riid, E.ERR_REGISTRY_ITEM_NOT_FOUND)))


@app.route("/registries/<rid>/close", methods=["POST"])
def close_registry(rid):
    uid, role = auth()
    require_role(role, {CUSTOMER})
    reg = get_or_404(db.registries, rid, E.ERR_REGISTRY_NOT_FOUND)
    require_owner(role, uid, reg["customer_id"])
    if reg["status"] != "ACTIVE":
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409, "Registry already closed")
    reg["status"] = "CLOSED"
    touch(reg)
    return ok(serialize(reg))


# ===========================================================================
# RETURNS
# ===========================================================================
@app.route("/returns", methods=["POST"])
def create_return():
    _, role = auth()
    require_role(role, {STORE_ASSOCIATE})
    b = get_body()
    order_id = req_str(b, "order_id")
    lines = b.get("lines")
    if not isinstance(lines, list) or not lines:
        _bad("Missing or invalid lines")
    norm = []
    for item in lines:
        if not isinstance(item, dict):
            _bad("Invalid line entry")
        ol_id = item.get("order_line_id")
        q = item.get("qty")
        if not isinstance(ol_id, str) or not ol_id:
            _bad("Invalid order_line_id")
        if not isinstance(q, int) or isinstance(q, bool) or q < 1:
            _bad("Invalid qty")
        norm.append({"order_line_id": ol_id, "qty": q})
    get_or_404(db.orders, order_id, E.ERR_ORDER_NOT_FOUND)
    ret = base_entity()
    ret.update({
        "order_id": order_id, "lines": norm,
        "gross_refund_cents": 0, "restocking_fee_cents": 0,
        "net_refund_cents": 0, "status": "REQUESTED",
    })
    db.returns[ret["id"]] = ret
    return ok(serialize(ret), 201)


@app.route("/returns", methods=["GET"])
def list_returns():
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return list_response(db.returns.values(), [
        ("order_id", request.args.get("order_id")),
    ])


@app.route("/returns/<rid>", methods=["GET"])
def get_return(rid):
    _, role = auth()
    require_role(role, ALL_AUTHENTICATED)
    return ok(serialize(get_or_404(db.returns, rid, E.ERR_RETURN_NOT_FOUND)))


def _restock_tier(gross):
    if gross < 5000:
        return (0, 1)
    if gross < 20000:
        return (10, 100)
    return (15, 100)


@app.route("/returns/<rid>/approve", methods=["POST"])
def approve_return(rid):
    _, role = auth()
    require_role(role, {STORE_MANAGER})
    ret = get_or_404(db.returns, rid, E.ERR_RETURN_NOT_FOUND)
    b = get_body()
    decision = req_str(b, "decision")
    if decision not in ("APPROVE", "REJECT"):
        _bad("decision must be APPROVE or REJECT")
    if ret["status"] != "REQUESTED":
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409, "Return not REQUESTED")
    if decision == "REJECT":
        ret["status"] = "REJECTED"
        touch(ret)
        return ok(serialize(ret))
    # APPROVE
    order = db.orders.get(ret["order_id"])
    if not order or order["fulfillment_status"] != "FULFILLED":
        raise ApiError(E.ERR_ORDER_NOT_FULFILLED, 409, "Order not FULFILLED")
    # return window: current clock <= fulfilled_at + 30 days
    fulfilled_at = order.get("_fulfilled_at")
    if fulfilled_at is not None:
        if now_dt() > fulfilled_at + timedelta(days=30):
            raise ApiError(E.ERR_RETURN_WINDOW_EXPIRED, 409, "Return window expired")
    # compute gross refund
    gross = 0
    returned_lines = []
    for entry in ret["lines"]:
        line = db.order_lines.get(entry["order_line_id"])
        if line is None or line["order_id"] != ret["order_id"]:
            continue
        effective_total = line["extended_cents"] - line["line_discount_cents"]
        per_unit = effective_total // line["qty"] if line["qty"] else 0
        gross += per_unit * entry["qty"]
        returned_lines.append((line, entry["qty"]))
    num, den = _restock_tier(gross)
    fee = (gross * num) // den
    net = gross - fee
    ret["gross_refund_cents"] = gross
    ret["restocking_fee_cents"] = fee
    ret["net_refund_cents"] = net
    # transition lines, restock inventory
    for line, qty in returned_lines:
        if line["status"] == "ACTIVE":
            line["status"] = "RETURNED"
            touch(line)
        it = db.inventory.get(line.get("_inventory_item_id")) or _find_inventory(line["product_id"], order["store_id"])
        if it:
            it["on_hand_qty"] += qty
            recompute_inventory(it)
            touch(it)
    # loyalty reversal
    cust = db.customers.get(order["customer_id"])
    if cust:
        mnum, mden = order.get("_earn_mult", MULT.get(cust["loyalty_tier"], (1, 1)))
        reversed_pts = (gross * mnum) // (mden * 100)
        cust["points_redeemed"] += reversed_pts
        recompute_customer(cust)
        touch(cust)
    ret["status"] = "APPROVED"
    touch(ret)
    return ok(serialize(ret))


# ===========================================================================
# LOGICAL CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth()
    require_role(role, {CATALOG_ADMIN})
    b = get_body()
    iso = req_str(b, "to_iso8601")
    db.set_clock(parse_dt(iso))
    return ok({})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
