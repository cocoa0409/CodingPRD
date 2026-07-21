"""
Model, RC & Hobby Store API — Python + Flask reference implementation.

All state is in-memory and re-initialised on every process start (the test
harness re-launches this server via start.sh before every test). Nothing is
seeded at startup: every entity is created by tests through the declared API.
"""

import os
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR
from uuid import uuid4

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD calculations / PRD §2.6, §2.8)
# ---------------------------------------------------------------------------
DISCOUNT_PCT = {"BRONZE": 0, "SILVER": 5, "GOLD": 10}
MULT_X100 = {"BRONZE": 100, "SILVER": 150, "GOLD": 200}
HAZMAT_SURCHARGE_CENTS = 500
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 200000
SERVICE_LABOR_RATE_CENTS = 6000
REWORK_SURCHARGE_CENTS = 2500
SERVICE_BUFFER_MINUTES = 30
CHECKIN_WINDOW_LEAD_MINUTES = 60  # scaffold leaves value unpinned (not boundary-relevant)

ROLES = ("Customer", "StoreStaff", "StoreManager")
STAFF = {"StoreStaff", "StoreManager"}
ALL_ROLES = {"Customer", "StoreStaff", "StoreManager"}

PRODUCT_TYPES = {"KIT", "RC_VEHICLE", "PART", "BATTERY"}
JOB_TYPES = {"BUILD", "REPAIR"}
RACE_CLASSES = {"STOCK", "MODIFIED", "PRO"}
ORDER_SOURCES = {"STANDARD", "PRE_ORDER"}

DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# In-memory store (fresh on every boot)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.customers = {}
        self.products = {}
        self.campaigns = {}
        self.reservations = {}
        self.orders = {}
        self.service_jobs = {}
        self.race_events = {}
        self.race_entries = {}
        self.clock = DEFAULT_CLOCK
        self.seq = 0


DB = Store()


def now_dt():
    return DB.clock


def next_seq():
    DB.seq += 1
    return DB.seq


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_iso(value):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def floor_labor(hours):
    return int((Decimal(str(hours)) * SERVICE_LABOR_RATE_CENTS).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def base_entity():
    n = now_dt()
    return {
        "id": str(uuid4()),
        "created_at": n,
        "updated_at": n,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_dt()


def serialize(entity, kind=None):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_iso(v)
        else:
            out[k] = v
    if kind == "campaign":
        out["remaining_units"] = entity["total_allocation_units"] - entity["allocated_units"]
    return out


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": fmt_iso(now_dt())}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH", 401, "missing or unknown authentication headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")


def forbid_not_owner(role, uid, owner_id):
    if role == "Customer" and owner_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only act on their own resources")


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(force=True, silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "body must be a JSON object")
    return body


def need(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", 400, "missing field: " + key)
    return body[key]


def need_str(body, key):
    v = need(body, key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, "invalid string: " + key)
    return v


def need_int(body, key, min_val=None):
    v = need(body, key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "invalid integer: " + key)
    if min_val is not None and v < min_val:
        raise ApiError("ERR_VALIDATION", 400, key + " out of range")
    return v


def opt_int(body, key, default, min_val=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "invalid integer: " + key)
    if min_val is not None and v < min_val:
        raise ApiError("ERR_VALIDATION", 400, key + " out of range")
    return v


def need_number(body, key, min_val=None):
    v = need(body, key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, "invalid number: " + key)
    if min_val is not None and v < min_val:
        raise ApiError("ERR_VALIDATION", 400, key + " out of range")
    return v


def lookup(collection, key, error="ERR_NOT_FOUND"):
    ent = collection.get(key)
    if ent is None:
        raise ApiError(error, 404, "resource not found")
    return ent


def parse_pagination():
    a = request.args

    def pint(name, default):
        raw = a.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "invalid pagination parameter: " + name)

    limit = pint("limit", 10)
    offset = pint("offset", 0)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 400, "limit out of range")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 400, "offset out of range")
    return limit, offset


def paginate(items):
    """items: iterable of entities. Sorts by created_at asc (seq tiebreak)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_tier(spend):
    if spend >= GOLD_THRESHOLD_CENTS:
        return "GOLD"
    if spend >= SILVER_THRESHOLD_CENTS:
        return "SILVER"
    return "BRONZE"


def compute_order_totals(lines, tier):
    subtotal = sum(l["quantity"] * l["unit_price_cents"] for l in lines)
    discount = (subtotal * DISCOUNT_PCT[tier]) // 100
    hazmat = any(DB.products[l["product_id"]]["is_hazmat"] for l in lines)
    surcharge = HAZMAT_SURCHARGE_CENTS if hazmat else 0
    total = subtotal - discount + surcharge
    return subtotal, discount, surcharge, total


def compute_points(lines, tier):
    mult = MULT_X100[tier]
    return sum((l["quantity"] * l["unit_price_cents"] * mult) // 10000 for l in lines)


def aggregate_quantities(lines):
    agg = {}
    for l in lines:
        agg[l["product_id"]] = agg.get(l["product_id"], 0) + l["quantity"]
    return agg


# ---------------------------------------------------------------------------
# Shared state-effect helpers (used by direct actions and cascades)
# ---------------------------------------------------------------------------
def place_order(order):
    """DRAFT -> PLACED: totals, stock reserve, provisional points. Assumes checks passed."""
    customer = DB.customers[order["customer_id"]]
    tier = customer["loyalty_tier"]
    lines = order["lines"]
    subtotal, discount, surcharge, total = compute_order_totals(lines, tier)
    provisional = compute_points(lines, tier)
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["hazmat_surcharge_cents"] = surcharge
    order["total_cents"] = total
    order["provisional_points"] = provisional
    order["status"] = "PLACED"
    # reserve stock
    for pid, qty in aggregate_quantities(lines).items():
        product = DB.products[pid]
        product["stock_on_hand"] -= qty
        touch(product)
    # credit provisional points
    customer["loyalty_points_balance"] += provisional
    touch(customer)


def cancel_order_internal(order):
    """PENDING fulfillment -> CANCELLED: restock, reverse provisional, refund if paid."""
    if order["fulfillment_status"] != "PENDING":
        return
    for pid, qty in aggregate_quantities(order["lines"]).items():
        product = DB.products[pid]
        product["stock_on_hand"] += qty
        touch(product)
    customer = DB.customers[order["customer_id"]]
    customer["loyalty_points_balance"] -= order["provisional_points"]
    touch(customer)
    if order["payment_status"] == "PAID":
        order["payment_status"] = "REFUNDED"
    order["fulfillment_status"] = "CANCELLED"
    touch(order)


def cancel_reservation_internal(res, cascade_order=True):
    prev = res["status"]
    res["status"] = "CANCELLED"
    touch(res)
    if prev in ("ALLOCATED", "CONVERTED"):
        campaign = DB.campaigns[res["campaign_id"]]
        campaign["allocated_units"] -= res["allocated_units"]
        touch(campaign)
    if cascade_order and res.get("order_id"):
        order = DB.orders.get(res["order_id"])
        if order is not None and order["fulfillment_status"] == "PENDING":
            cancel_order_internal(order)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = auth()
    require_role(role, STAFF)
    body = get_body()
    DB.clock = parse_iso(need(body, "to_iso8601"))
    return ok({}, 200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@app.route("/customers", methods=["POST"])
def create_customer():
    uid, role = auth()
    require_role(role, STAFF)
    body = get_body()
    email = need_str(body, "email")
    full_name = need_str(body, "full_name")
    c = base_entity()
    c.update({
        "email": email,
        "full_name": full_name,
        "lifetime_spend_cents": 0,
        "loyalty_points_balance": 0,
        "loyalty_tier": "BRONZE",
        "hazmat_safety_ack": False,
    })
    DB.customers[c["id"]] = c
    return ok(serialize(c), 201)


@app.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    uid, role = auth()
    if role == "Customer" and customer_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only read their own record")
    c = lookup(DB.customers, customer_id)
    return ok(serialize(c), 200)


@app.route("/customers/<customer_id>/safety-ack", methods=["POST"])
def safety_ack(customer_id):
    uid, role = auth()
    if role == "Customer" and customer_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only ack their own record")
    c = lookup(DB.customers, customer_id)
    c["hazmat_safety_ack"] = True
    touch(c)
    return ok(serialize(c), 200)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@app.route("/products", methods=["POST"])
def create_product():
    uid, role = auth()
    require_role(role, STAFF)
    body = get_body()
    sku = need_str(body, "sku")
    name = need_str(body, "name")
    ptype = need_str(body, "product_type")
    if ptype not in PRODUCT_TYPES:
        raise ApiError("ERR_VALIDATION", 400, "invalid product_type")
    price = need_int(body, "price_cents", 0)
    stock = opt_int(body, "stock_on_hand", 0, 0)
    p = base_entity()
    p.update({
        "sku": sku,
        "name": name,
        "product_type": ptype,
        "price_cents": price,
        "stock_on_hand": stock,
        "is_hazmat": ptype == "BATTERY",
    })
    DB.products[p["id"]] = p
    return ok(serialize(p), 201)


@app.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    auth()
    p = lookup(DB.products, product_id)
    return ok(serialize(p), 200)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------
@app.route("/campaigns", methods=["POST"])
def create_campaign():
    uid, role = auth()
    require_role(role, STAFF)
    body = get_body()
    product_id = need_str(body, "product_id")
    title = need_str(body, "title")
    total_units = need_int(body, "total_allocation_units", 1)
    unit_price = need_int(body, "unit_price_cents", 0)
    open_at = parse_iso(need(body, "reservation_open_at"))
    close_at = parse_iso(need(body, "reservation_close_at"))
    lookup(DB.products, product_id)
    c = base_entity()
    c.update({
        "product_id": product_id,
        "title": title,
        "total_allocation_units": total_units,
        "unit_price_cents": unit_price,
        "reservation_open_at": open_at,
        "reservation_close_at": close_at,
        "allocated_units": 0,
        "status": "DRAFT",
    })
    DB.campaigns[c["id"]] = c
    return ok(serialize(c, "campaign"), 201)


@app.route("/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    auth()
    c = lookup(DB.campaigns, campaign_id)
    return ok(serialize(c, "campaign"), 200)


@app.route("/campaigns", methods=["GET"])
def list_campaigns():
    auth()
    product_id = request.args.get("product_id")
    items = [c for c in DB.campaigns.values()
             if product_id is None or c["product_id"] == product_id]
    page, pg = paginate(items)
    return ok_list([serialize(c, "campaign") for c in page], pg)


@app.route("/campaigns/<campaign_id>/open", methods=["POST"])
def open_campaign(campaign_id):
    uid, role = auth()
    require_role(role, STAFF)
    c = lookup(DB.campaigns, campaign_id)
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "campaign not in DRAFT")
    c["status"] = "OPEN"
    touch(c)
    return ok(serialize(c, "campaign"), 200)


@app.route("/campaigns/<campaign_id>/allocate", methods=["POST"])
def allocate_campaign(campaign_id):
    uid, role = auth()
    require_role(role, STAFF)
    c = lookup(DB.campaigns, campaign_id)
    if c["status"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_ALREADY_ALLOCATED", 409, "campaign not OPEN")
    held = [r for r in DB.reservations.values()
            if r["campaign_id"] == campaign_id and r["status"] == "HELD"]
    held.sort(key=lambda r: (r["created_at"], r["_seq"]))
    remaining = c["total_allocation_units"]
    for r in held:
        if r["requested_units"] <= remaining:
            r["allocated_units"] = r["requested_units"]
            r["status"] = "ALLOCATED"
            remaining -= r["requested_units"]
        else:
            r["allocated_units"] = 0
            r["status"] = "WAITLISTED"
        touch(r)
    c["allocated_units"] = c["total_allocation_units"] - remaining
    c["status"] = "ALLOCATING"
    touch(c)
    return ok(serialize(c, "campaign"), 200)


@app.route("/campaigns/<campaign_id>/cancel", methods=["POST"])
def cancel_campaign(campaign_id):
    uid, role = auth()
    require_role(role, {"StoreManager"})
    c = lookup(DB.campaigns, campaign_id)
    if c["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "campaign already cancelled")
    # CASCADE L1 -> L2 -> L3
    for r in DB.reservations.values():
        if r["campaign_id"] == campaign_id and r["status"] in (
                "HELD", "WAITLISTED", "ALLOCATED", "CONVERTED"):
            r["status"] = "CANCELLED"
            touch(r)
            if r.get("order_id"):
                order = DB.orders.get(r["order_id"])
                if order is not None and order["fulfillment_status"] == "PENDING":
                    cancel_order_internal(order)
    c["status"] = "CANCELLED"
    c["allocated_units"] = 0
    touch(c)
    return ok(serialize(c, "campaign"), 200)


# ---------------------------------------------------------------------------
# Pre-order reservations
# ---------------------------------------------------------------------------
@app.route("/campaigns/<campaign_id>/pre-orders", methods=["POST"])
def create_reservation(campaign_id):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    body = get_body()
    customer_id = body.get("customer_id")
    # ownership (priority 2)
    if role == "Customer" and customer_id is not None and customer_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only reserve for themselves")
    # existence (priority 3)
    campaign = lookup(DB.campaigns, campaign_id)
    if customer_id is not None:
        lookup(DB.customers, customer_id)
    # state (priority 4): campaign must be OPEN for reservations
    if campaign["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "campaign not open for reservations")
    # OCC (priority 5)
    ecv = body.get("expected_campaign_version")
    if ecv is not None and not isinstance(ecv, bool) and isinstance(ecv, int):
        if ecv != campaign["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "expected_campaign_version mismatch")
    # window (priority 7)
    now = now_dt()
    if not (campaign["reservation_open_at"] <= now < campaign["reservation_close_at"]):
        raise ApiError("ERR_WINDOW_CLOSED", 409, "reservation window closed")
    # business constraint (priority 10): requested_units must not exceed pool
    ru = body.get("requested_units")
    if isinstance(ru, int) and not isinstance(ru, bool) and ru >= 1:
        if ru > campaign["total_allocation_units"]:
            raise ApiError("ERR_ALLOCATION_EXHAUSTED", 409, "requested_units exceeds pool")
    # field validation (priority 13)
    customer_id = need_str(body, "customer_id")
    requested_units = need_int(body, "requested_units", 1)
    need_int(body, "expected_campaign_version")  # mandatory

    r = base_entity()
    r.update({
        "campaign_id": campaign_id,
        "customer_id": customer_id,
        "requested_units": requested_units,
        "allocated_units": 0,
        "order_id": None,
        "status": "HELD",
    })
    DB.reservations[r["id"]] = r
    # each reservation create mutates the campaign version by 1
    touch(campaign)
    return ok(serialize(r), 201)


@app.route("/pre-orders/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    uid, role = auth()
    r = lookup(DB.reservations, reservation_id)
    forbid_not_owner(role, uid, r["customer_id"])
    return ok(serialize(r), 200)


@app.route("/pre-orders", methods=["GET"])
def list_reservations():
    uid, role = auth()
    campaign_id = request.args.get("campaign_id")
    customer_id = request.args.get("customer_id")
    order_id = request.args.get("order_id")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only list their own reservations")
        customer_id = uid
    items = []
    for r in DB.reservations.values():
        if campaign_id is not None and r["campaign_id"] != campaign_id:
            continue
        if customer_id is not None and r["customer_id"] != customer_id:
            continue
        if order_id is not None and r.get("order_id") != order_id:
            continue
        items.append(r)
    page, pg = paginate(items)
    return ok_list([serialize(r) for r in page], pg)


@app.route("/pre-orders/<reservation_id>/transition", methods=["POST"])
def transition_reservation(reservation_id):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    r = lookup(DB.reservations, reservation_id)
    forbid_not_owner(role, uid, r["customer_id"])
    body = get_body()
    action = body.get("action")
    if action not in ("CONVERT", "CANCEL"):
        raise ApiError("ERR_INVALID_ACTION", 400, "unknown action")

    if action == "CONVERT":
        require_role(role, STAFF)
        campaign = DB.campaigns[r["campaign_id"]]
        # referential readiness (priority 9)
        if r["status"] != "ALLOCATED":
            raise ApiError("ERR_RESERVATION_NOT_ALLOCATED", 409, "reservation not ALLOCATED")
        # cross-entity state (priority 4 error id, checked after per PRD prose)
        if campaign["status"] != "ALLOCATING":
            raise ApiError("ERR_INVALID_STATE", 409, "campaign not ALLOCATING")
        product = DB.products[campaign["product_id"]]
        if product["stock_on_hand"] < r["allocated_units"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409, "insufficient stock to convert")
        # create an already-PLACED PRE_ORDER order
        order = base_entity()
        order.update({
            "customer_id": r["customer_id"],
            "source": "PRE_ORDER",
            "lines": [{
                "product_id": campaign["product_id"],
                "quantity": r["allocated_units"],
                "unit_price_cents": campaign["unit_price_cents"],
            }],
            "subtotal_cents": 0,
            "discount_cents": 0,
            "hazmat_surcharge_cents": 0,
            "total_cents": 0,
            "amount_paid_cents": 0,
            "provisional_points": 0,
            "final_points": 0,
            "status": "DRAFT",
            "payment_status": "UNPAID",
            "fulfillment_status": "PENDING",
        })
        DB.orders[order["id"]] = order
        place_order(order)  # sets PLACED, totals, reserves stock, provisional points
        r["order_id"] = order["id"]
        r["status"] = "CONVERTED"
        touch(r)
        return ok(serialize(r), 200)

    # CANCEL
    if r["status"] not in ("HELD", "WAITLISTED", "ALLOCATED", "CONVERTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "reservation not cancellable")
    cancel_reservation_internal(r)
    return ok(serialize(r), 200)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = auth()
    require_role(role, ALL_ROLES)
    body = get_body()
    customer_id = body.get("customer_id")
    if role == "Customer" and customer_id is not None and customer_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only order for themselves")
    # existence: customer + each line product
    if customer_id is not None:
        lookup(DB.customers, customer_id)
    lines_in = body.get("lines")
    if isinstance(lines_in, list):
        for l in lines_in:
            if isinstance(l, dict) and isinstance(l.get("product_id"), str):
                lookup(DB.products, l["product_id"])
    # field validation
    customer_id = need_str(body, "customer_id")
    source = body.get("source", "STANDARD")
    if source is None:
        source = "STANDARD"
    if source not in ORDER_SOURCES:
        raise ApiError("ERR_VALIDATION", 400, "invalid source")
    if not isinstance(lines_in, list) or len(lines_in) == 0:
        raise ApiError("ERR_VALIDATION", 400, "lines required")
    lines = []
    for l in lines_in:
        if not isinstance(l, dict):
            raise ApiError("ERR_VALIDATION", 400, "invalid line")
        pid = l.get("product_id")
        qty = l.get("quantity")
        price = l.get("unit_price_cents")
        if not isinstance(pid, str):
            raise ApiError("ERR_VALIDATION", 400, "invalid line.product_id")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise ApiError("ERR_VALIDATION", 400, "invalid line.quantity")
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            raise ApiError("ERR_VALIDATION", 400, "invalid line.unit_price_cents")
        lines.append({"product_id": pid, "quantity": qty, "unit_price_cents": price})

    o = base_entity()
    o.update({
        "customer_id": customer_id,
        "source": source,
        "lines": lines,
        "subtotal_cents": 0,
        "discount_cents": 0,
        "hazmat_surcharge_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "provisional_points": 0,
        "final_points": 0,
        "status": "DRAFT",
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
    })
    DB.orders[o["id"]] = o
    return ok(serialize(o), 201)


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    uid, role = auth()
    o = lookup(DB.orders, order_id)
    forbid_not_owner(role, uid, o["customer_id"])
    return ok(serialize(o), 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    uid, role = auth()
    customer_id = request.args.get("customer_id")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only list their own orders")
        customer_id = uid
    items = [o for o in DB.orders.values()
             if customer_id is None or o["customer_id"] == customer_id]
    page, pg = paginate(items)
    return ok_list([serialize(o) for o in page], pg)


@app.route("/orders/<order_id>/pay", methods=["POST"])
def pay_order(order_id):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    o = lookup(DB.orders, order_id)
    forbid_not_owner(role, uid, o["customer_id"])
    if o["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", 409, "order not PLACED")
    if o["payment_status"] != "UNPAID":
        raise ApiError("ERR_PAYMENT_ALREADY_SETTLED", 409, "payment already settled")
    body = get_body()
    amount = need_int(body, "amount_cents", 0)
    if amount < o["total_cents"]:
        raise ApiError("ERR_INSUFFICIENT_PAYMENT", 402, "amount_cents below total")
    o["amount_paid_cents"] = amount
    o["payment_status"] = "PAID"
    touch(o)
    return ok(serialize(o), 200)


@app.route("/orders/<order_id>/transition", methods=["POST"])
def transition_order(order_id):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    o = lookup(DB.orders, order_id)
    forbid_not_owner(role, uid, o["customer_id"])
    body = get_body()
    action = body.get("action")
    if action not in ("PLACE", "FULFILL", "CANCEL"):
        raise ApiError("ERR_INVALID_ACTION", 400, "unknown action")

    if action == "PLACE":
        if o["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "order not DRAFT")
        customer = DB.customers[o["customer_id"]]
        # hazmat gate (priority 6)
        hazmat = any(DB.products[l["product_id"]]["is_hazmat"] for l in o["lines"])
        if hazmat and not customer["hazmat_safety_ack"]:
            raise ApiError("ERR_HAZMAT_ACK_REQUIRED", 409, "hazmat safety ack required")
        # stock sufficiency (priority 11)
        for pid, qty in aggregate_quantities(o["lines"]).items():
            if DB.products[pid]["stock_on_hand"] < qty:
                raise ApiError("ERR_INSUFFICIENT_STOCK", 409, "insufficient stock")
        place_order(o)
        touch(o)  # PLACE is a mutation of the order itself
        return ok(serialize(o), 200)

    if action == "FULFILL":
        require_role(role, STAFF)
        if o["status"] != "PLACED":
            raise ApiError("ERR_INVALID_STATE", 409, "order not PLACED")
        if o["payment_status"] != "PAID":
            raise ApiError("ERR_INVALID_STATE", 409, "order not PAID")
        if o["fulfillment_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "order not PENDING")
        customer = DB.customers[o["customer_id"]]
        tier_at_fulfill = customer["loyalty_tier"]  # tier as of before adding this total
        final = compute_points(o["lines"], tier_at_fulfill)
        o["final_points"] = final
        customer["loyalty_points_balance"] += (final - o["provisional_points"])
        customer["lifetime_spend_cents"] += o["total_cents"]
        customer["loyalty_tier"] = compute_tier(customer["lifetime_spend_cents"])
        o["fulfillment_status"] = "FULFILLED"
        touch(customer)
        touch(o)
        return ok(serialize(o), 200)

    # CANCEL
    if o["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "order not cancellable")
    cancel_order_internal(o)
    return ok(serialize(o), 200)


# ---------------------------------------------------------------------------
# Service jobs
# ---------------------------------------------------------------------------
@app.route("/service-jobs", methods=["POST"])
def create_service_job():
    uid, role = auth()
    require_role(role, STAFF)
    body = get_body()
    customer_id = need_str(body, "customer_id")
    product_id = body.get("product_id")
    job_type = need_str(body, "job_type")
    if job_type not in JOB_TYPES:
        raise ApiError("ERR_VALIDATION", 400, "invalid job_type")
    est_parts = opt_int(body, "estimated_parts_cents", 0, 0)
    lookup(DB.customers, customer_id)
    if product_id is not None:
        lookup(DB.products, product_id)
    j = base_entity()
    j.update({
        "customer_id": customer_id,
        "product_id": product_id,
        "job_type": job_type,
        "bench_code": None,
        "slot_start": None,
        "slot_end": None,
        "estimated_labor_hours": None,
        "estimated_parts_cents": est_parts,
        "actual_labor_hours": None,
        "actual_parts_cents": None,
        "rework_count": 0,
        "provisional_quote_cents": 0,
        "final_invoice_cents": 0,
        "status": "RECEIVED",
    })
    DB.service_jobs[j["id"]] = j
    return ok(serialize(j), 201)


@app.route("/service-jobs/<job_id>", methods=["GET"])
def get_service_job(job_id):
    uid, role = auth()
    j = lookup(DB.service_jobs, job_id)
    forbid_not_owner(role, uid, j["customer_id"])
    return ok(serialize(j), 200)


@app.route("/service-jobs", methods=["GET"])
def list_service_jobs():
    uid, role = auth()
    customer_id = request.args.get("customer_id")
    product_id = request.args.get("product_id")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only list their own jobs")
        customer_id = uid
    items = []
    for j in DB.service_jobs.values():
        if customer_id is not None and j["customer_id"] != customer_id:
            continue
        if product_id is not None and j.get("product_id") != product_id:
            continue
        items.append(j)
    page, pg = paginate(items)
    return ok_list([serialize(j) for j in page], pg)


SERVICE_TERMINAL = {"COMPLETED", "CANCELLED"}
SERVICE_ACTIONS = {"SCHEDULE", "DIAGNOSE", "AWAIT_PARTS", "START", "QC",
                   "REWORK", "READY", "COMPLETE", "CANCEL"}


def bench_conflict(job, bench_code, slot_start, slot_end):
    buffer = timedelta(minutes=SERVICE_BUFFER_MINUTES)
    for other in DB.service_jobs.values():
        if other["id"] == job["id"]:
            continue
        if other["status"] == "CANCELLED":
            continue
        if other.get("bench_code") != bench_code:
            continue
        os_, oe = other.get("slot_start"), other.get("slot_end")
        if os_ is None or oe is None:
            continue
        # 30-min buffer required between the two intervals
        gap_ok = (slot_start - oe >= buffer) or (os_ - slot_end >= buffer)
        if not gap_ok:
            return True
    return False


@app.route("/service-jobs/<job_id>/transition", methods=["POST"])
def transition_service_job(job_id):
    uid, role = auth()
    require_role(role, STAFF)
    j = lookup(DB.service_jobs, job_id)
    body = get_body()
    action = body.get("action")
    if action not in SERVICE_ACTIONS:
        raise ApiError("ERR_INVALID_ACTION", 400, "unknown action")

    if action == "SCHEDULE":
        if j["status"] in SERVICE_TERMINAL:
            raise ApiError("ERR_INVALID_STATE", 409, "job terminal")
        bench_code = need_str(body, "bench_code")
        slot_start = parse_iso(need(body, "slot_start"))
        slot_end = parse_iso(need(body, "slot_end"))
        if slot_end <= slot_start:
            raise ApiError("ERR_BENCH_CONFLICT", 409, "invalid slot interval")
        if bench_conflict(j, bench_code, slot_start, slot_end):
            raise ApiError("ERR_BENCH_CONFLICT", 409, "bench slot conflict")
        j["bench_code"] = bench_code
        j["slot_start"] = slot_start
        j["slot_end"] = slot_end
        touch(j)
        return ok(serialize(j), 200)

    if action == "DIAGNOSE":
        if j["status"] != "RECEIVED":
            raise ApiError("ERR_INVALID_STATE", 409, "job not RECEIVED")
        est_hours = need_number(body, "estimated_labor_hours", 0)
        if "estimated_parts_cents" in body and body["estimated_parts_cents"] is not None:
            j["estimated_parts_cents"] = opt_int(body, "estimated_parts_cents", 0, 0)
        j["estimated_labor_hours"] = est_hours
        j["provisional_quote_cents"] = floor_labor(est_hours) + j["estimated_parts_cents"]
        j["status"] = "DIAGNOSING"
        touch(j)
        return ok(serialize(j), 200)

    if action == "AWAIT_PARTS":
        if j["status"] != "DIAGNOSING":
            raise ApiError("ERR_INVALID_STATE", 409, "job not DIAGNOSING")
        j["status"] = "AWAITING_PARTS"
        touch(j)
        return ok(serialize(j), 200)

    if action == "START":
        if j["status"] not in ("DIAGNOSING", "AWAITING_PARTS"):
            raise ApiError("ERR_INVALID_STATE", 409, "job not startable")
        if not j.get("bench_code"):
            raise ApiError("ERR_INVALID_STATE", 409, "job not scheduled onto a bench")
        j["status"] = "IN_PROGRESS"
        touch(j)
        return ok(serialize(j), 200)

    if action == "QC":
        if j["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", 409, "job not IN_PROGRESS")
        j["status"] = "QC"
        touch(j)
        return ok(serialize(j), 200)

    if action == "REWORK":
        if j["status"] != "QC":
            raise ApiError("ERR_INVALID_STATE", 409, "job not in QC")
        j["rework_count"] += 1
        j["status"] = "IN_PROGRESS"
        touch(j)
        return ok(serialize(j), 200)

    if action == "READY":
        if j["status"] != "QC":
            raise ApiError("ERR_INVALID_STATE", 409, "job not in QC")
        j["status"] = "READY"
        touch(j)
        return ok(serialize(j), 200)

    if action == "COMPLETE":
        if j["status"] != "READY":
            raise ApiError("ERR_INVALID_STATE", 409, "job not READY")
        actual_hours = need_number(body, "actual_labor_hours", 0)
        actual_parts = need_int(body, "actual_parts_cents", 0)
        j["actual_labor_hours"] = actual_hours
        j["actual_parts_cents"] = actual_parts
        j["final_invoice_cents"] = (floor_labor(actual_hours) + actual_parts
                                    + j["rework_count"] * REWORK_SURCHARGE_CENTS)
        j["status"] = "COMPLETED"
        touch(j)
        return ok(serialize(j), 200)

    # CANCEL
    if j["status"] in SERVICE_TERMINAL:
        raise ApiError("ERR_INVALID_STATE", 409, "job terminal")
    j["status"] = "CANCELLED"
    j["bench_code"] = None
    j["slot_start"] = None
    j["slot_end"] = None
    touch(j)
    return ok(serialize(j), 200)


# ---------------------------------------------------------------------------
# Race events
# ---------------------------------------------------------------------------
@app.route("/race-events", methods=["POST"])
def create_race_event():
    uid, role = auth()
    require_role(role, STAFF)
    body = get_body()
    name = need_str(body, "name")
    event_date = parse_iso(need(body, "event_date"))
    capacity = need_int(body, "capacity", 0)
    lane_count = need_int(body, "lane_count", 1)
    entry_fee = need_int(body, "entry_fee_cents", 0)
    reg_open = parse_iso(need(body, "registration_open_at"))
    reg_close = parse_iso(need(body, "registration_close_at"))
    e = base_entity()
    e.update({
        "name": name,
        "event_date": event_date,
        "capacity": capacity,
        "lane_count": lane_count,
        "entry_fee_cents": entry_fee,
        "registration_open_at": reg_open,
        "registration_close_at": reg_close,
        "entry_count": 0,
        "status": "SCHEDULED",
    })
    DB.race_events[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/race-events/<event_id>", methods=["GET"])
def get_race_event(event_id):
    auth()
    e = lookup(DB.race_events, event_id)
    return ok(serialize(e), 200)


@app.route("/race-events/<event_id>/transition", methods=["POST"])
def transition_race_event(event_id):
    uid, role = auth()
    require_role(role, STAFF)
    e = lookup(DB.race_events, event_id)
    body = get_body()
    action = body.get("action")
    if action not in ("OPEN", "RUN", "FINISH", "CANCEL"):
        raise ApiError("ERR_INVALID_ACTION", 400, "unknown action")

    if action == "OPEN":
        if e["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409, "event not SCHEDULED")
        e["status"] = "OPEN"
        touch(e)
        return ok(serialize(e), 200)

    if action == "RUN":
        if e["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "event not OPEN")
        e["status"] = "RUNNING"
        touch(e)
        return ok(serialize(e), 200)

    if action == "FINISH":
        if e["status"] != "RUNNING":
            raise ApiError("ERR_INVALID_STATE", 409, "event not RUNNING")
        e["status"] = "FINISHED"
        touch(e)
        return ok(serialize(e), 200)

    # CANCEL
    if e["status"] in ("FINISHED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", 409, "event terminal")
    for entry in DB.race_entries.values():
        if entry["event_id"] == event_id and entry["status"] in ("REGISTERED", "CHECKED_IN"):
            entry["status"] = "WITHDRAWN"
            touch(entry)
            customer = DB.customers[entry["customer_id"]]
            customer["loyalty_points_balance"] -= entry["entry_points_awarded"]
            touch(customer)
            e["entry_count"] -= 1
    e["status"] = "CANCELLED"
    touch(e)
    return ok(serialize(e), 200)


# ---------------------------------------------------------------------------
# Race entries
# ---------------------------------------------------------------------------
def lane_conflict(event_id, lane_no, heat_start, heat_end):
    for entry in DB.race_entries.values():
        if entry["event_id"] != event_id or entry["lane_no"] != lane_no:
            continue
        if entry["status"] == "WITHDRAWN":
            continue
        # half-open overlap; adjacency (end == next start) allowed
        if heat_start < entry["heat_end"] and entry["heat_start"] < heat_end:
            return True
    return False


@app.route("/race-events/<event_id>/entries", methods=["POST"])
def create_race_entry(event_id):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    body = get_body()
    customer_id = body.get("customer_id")
    if role == "Customer" and customer_id is not None and customer_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only register themselves")
    event = lookup(DB.race_events, event_id)
    if customer_id is not None:
        lookup(DB.customers, customer_id)
    # state (priority 4): event must be OPEN for registration
    if event["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "event not open for registration")
    # window (priority 7)
    now = now_dt()
    if not (event["registration_open_at"] <= now < event["registration_close_at"]):
        raise ApiError("ERR_WINDOW_CLOSED", 409, "registration window closed")
    # lane conflict (priority 8) — needs valid lane_no + heat interval
    lane_no = body.get("lane_no")
    heat_start_raw = body.get("heat_start")
    heat_end_raw = body.get("heat_end")
    heat_start = heat_end = None
    if isinstance(lane_no, int) and not isinstance(lane_no, bool) \
            and isinstance(heat_start_raw, str) and isinstance(heat_end_raw, str):
        heat_start = parse_iso(heat_start_raw)
        heat_end = parse_iso(heat_end_raw)
        if 1 <= lane_no <= event["lane_count"]:
            if lane_conflict(event_id, lane_no, heat_start, heat_end):
                raise ApiError("ERR_LANE_CONFLICT", 409, "heat interval overlaps another entry")
    # capacity (priority 10)
    if event["entry_count"] >= event["capacity"]:
        raise ApiError("ERR_EVENT_FULL", 409, "event at capacity")
    # duplicate (priority 10)
    if customer_id is not None:
        for entry in DB.race_entries.values():
            if entry["event_id"] == event_id and entry["customer_id"] == customer_id \
                    and entry["status"] in ("REGISTERED", "CHECKED_IN"):
                raise ApiError("ERR_DUPLICATE_ENTRY", 409, "duplicate non-terminal entry")
    # lane range (priority 10)
    if isinstance(lane_no, int) and not isinstance(lane_no, bool):
        if not (1 <= lane_no <= event["lane_count"]):
            raise ApiError("ERR_LANE_OUT_OF_RANGE", 400, "lane_no out of range")
    # field validation (priority 13)
    customer_id = need_str(body, "customer_id")
    race_class = need_str(body, "race_class")
    if race_class not in RACE_CLASSES:
        raise ApiError("ERR_VALIDATION", 400, "invalid race_class")
    lane_no = need_int(body, "lane_no", 1)
    if heat_start is None:
        heat_start = parse_iso(need(body, "heat_start"))
    if heat_end is None:
        heat_end = parse_iso(need(body, "heat_end"))

    points = event["entry_fee_cents"] // 100
    entry = base_entity()
    entry.update({
        "event_id": event_id,
        "customer_id": customer_id,
        "race_class": race_class,
        "lane_no": lane_no,
        "heat_start": heat_start,
        "heat_end": heat_end,
        "entry_points_awarded": points,
        "status": "REGISTERED",
    })
    DB.race_entries[entry["id"]] = entry
    customer = DB.customers[customer_id]
    customer["loyalty_points_balance"] += points
    touch(customer)
    event["entry_count"] += 1
    touch(event)
    return ok(serialize(entry), 201)


@app.route("/race-entries/<entry_id>", methods=["GET"])
def get_race_entry(entry_id):
    uid, role = auth()
    entry = lookup(DB.race_entries, entry_id)
    forbid_not_owner(role, uid, entry["customer_id"])
    return ok(serialize(entry), 200)


@app.route("/race-entries", methods=["GET"])
def list_race_entries():
    uid, role = auth()
    event_id = request.args.get("event_id")
    customer_id = request.args.get("customer_id")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only list their own entries")
        customer_id = uid
    items = []
    for entry in DB.race_entries.values():
        if event_id is not None and entry["event_id"] != event_id:
            continue
        if customer_id is not None and entry["customer_id"] != customer_id:
            continue
        items.append(entry)
    page, pg = paginate(items)
    return ok_list([serialize(entry) for entry in page], pg)


@app.route("/race-entries/<entry_id>/transition", methods=["POST"])
def transition_race_entry(entry_id):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    entry = lookup(DB.race_entries, entry_id)
    forbid_not_owner(role, uid, entry["customer_id"])
    body = get_body()
    action = body.get("action")
    if action not in ("CHECK_IN", "RACED", "DISQUALIFY", "WITHDRAW"):
        raise ApiError("ERR_INVALID_ACTION", 400, "unknown action")

    if action == "CHECK_IN":
        if entry["status"] != "REGISTERED":
            raise ApiError("ERR_INVALID_STATE", 409, "entry not REGISTERED")
        event = DB.race_events[entry["event_id"]]
        if event["status"] != "RUNNING":
            raise ApiError("ERR_INVALID_STATE", 409, "event not RUNNING")
        customer = DB.customers[entry["customer_id"]]
        if not customer["hazmat_safety_ack"]:
            raise ApiError("ERR_SAFETY_INSPECTION_REQUIRED", 409, "safety inspection required")
        now = now_dt()
        lead = timedelta(minutes=CHECKIN_WINDOW_LEAD_MINUTES)
        if not (entry["heat_start"] - lead <= now < entry["heat_end"]):
            raise ApiError("ERR_CHECKIN_WINDOW_CLOSED", 409, "check-in window closed")
        entry["status"] = "CHECKED_IN"
        touch(entry)
        return ok(serialize(entry), 200)

    if action == "RACED":
        require_role(role, STAFF)
        if entry["status"] != "CHECKED_IN":
            raise ApiError("ERR_INVALID_STATE", 409, "entry not CHECKED_IN")
        entry["status"] = "RACED"
        touch(entry)
        return ok(serialize(entry), 200)

    if action == "DISQUALIFY":
        require_role(role, STAFF)
        if entry["status"] not in ("REGISTERED", "CHECKED_IN"):
            raise ApiError("ERR_INVALID_STATE", 409, "entry not disqualifiable")
        entry["status"] = "DISQUALIFIED"
        touch(entry)
        return ok(serialize(entry), 200)

    # WITHDRAW
    if entry["status"] not in ("REGISTERED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "entry not withdrawable")
    entry["status"] = "WITHDRAWN"
    touch(entry)
    customer = DB.customers[entry["customer_id"]]
    customer["loyalty_points_balance"] -= entry["entry_points_awarded"]
    touch(customer)
    event = DB.race_events[entry["event_id"]]
    event["entry_count"] -= 1
    touch(event)
    return ok(serialize(entry), 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
