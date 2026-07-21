import os
import uuid
import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
MEMBER = "Member"
FITTER = "Fitter"
MANAGER = "StoreManager"
ANON = "Anonymous"
KNOWN_ROLES = {MEMBER, FITTER, MANAGER, ANON}

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD calculations)
# ---------------------------------------------------------------------------
SUBSCRIPTION_DISCOUNT_PCT = {"BASIC": Decimal("0.05"), "PLUS": Decimal("0.10"), "ELITE": Decimal("0.15")}
LOYALTY_TIER_DISCOUNT_PCT = {"STANDARD": Decimal("0.00"), "SILVER": Decimal("0.05"), "GOLD": Decimal("0.10")}
PROMO_CODES = {"WELCOME10": Decimal("0.10"), "SPRING15": Decimal("0.15")}
MAX_STACK_DISCOUNT_PCT = Decimal("0.12")
MAX_TOTAL_DISCOUNT_PCT = Decimal("0.20")
PROMO_MIN_SUBTOTAL_CENTS = 5000

LOYALTY_POINT_VALUE_CENTS = 1
FREE_SHIP_THRESHOLD_CENTS = 7500
SHIPPING_FEE_CENTS = 599

TIER_SILVER_MIN_CENTS = 50000
TIER_GOLD_MIN_CENTS = 150000

POINTS_PER_DOLLAR = 10
TIER_MULTIPLIER = {"STANDARD": Decimal("1.0"), "SILVER": Decimal("1.25"), "GOLD": Decimal("1.5")}

SERVICE_BUFFER_MINUTES = 15

VALID_CATEGORY = {"SHOE", "NUTRITION", "GEAR", "APPAREL"}
VALID_PLAN = {"BASIC", "PLUS", "ELITE"}

DEFAULT_MILEAGE_LIFE = 500

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start)
# ---------------------------------------------------------------------------
DB = {
    "members": {},
    "products": {},
    "orders": {},
    "order_lines": {},
    "returns": {},
    "subscriptions": {},
    "running_shoes": {},
    "fitters": {},
    "fitment_sessions": {},
    "training_sessions": {},
    "training_bookings": {},
}
STATE = {"clock": datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc), "seq": 0}


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def now_dt():
    return STATE["clock"]


def now_iso():
    dt = STATE["clock"]
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def base_fields():
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": next_seq(),
    }


def touch(e):
    e["version"] += 1
    e["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta(pag=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": now_iso()}
    if pag:
        m.update(pag)
    return m


def success(data, response_type="object", status=200, pag=None):
    return jsonify({"meta": meta(pag), "response_type": response_type, "data": data}), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate(allowed):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    anon_ok = ANON in allowed
    if role is not None and role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Unknown role")
    if not role or not uid:
        if anon_ok:
            g.role = ANON
            g.uid = uid
            return
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing authentication headers")
    g.role = role
    g.uid = uid
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted")


def auth(*allowed):
    def deco(fn):
        @wraps(fn)
        def w(*a, **k):
            authenticate(allowed)
            return fn(*a, **k)
        return w
    return deco


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def body():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def require_field(d, key):
    if key not in d or d[key] is None:
        raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {key}")
    return d[key]


def as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an integer")
    return v


def get_or_404(table, rid):
    e = DB[table].get(rid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Resource not found: {rid}")
    return e


def ensure_member_owner(mid):
    if g.role == MEMBER and mid != g.uid:
        raise ApiError("ERR_OWNERSHIP_FORBIDDEN", 403, "Caller does not own this resource")


def ensure_fitter_owner(fid):
    if g.role == FITTER and fid != g.uid:
        raise ApiError("ERR_OWNERSHIP_FORBIDDEN", 403, "Caller does not own this resource")


def parse_dt(s, field="datetime"):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an ISO 8601 string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} is not a valid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 1
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items, serializer):
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    limit, offset = pagination()
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return success([serializer(x) for x in page], "array", 200, pag)


# ---------------------------------------------------------------------------
# Derived / calculation helpers
# ---------------------------------------------------------------------------
def member_active_subscription_pct(member_id):
    best = Decimal("0")
    for s in DB["subscriptions"].values():
        if s["member_id"] == member_id and s["status"] == "ACTIVE":
            p = SUBSCRIPTION_DISCOUNT_PCT.get(s["plan"], Decimal("0"))
            if p > best:
                best = p
    return best


def member_tier_spend(member_id):
    window_start = now_dt() - timedelta(days=365)
    total = 0
    for o in DB["orders"].values():
        if o["member_id"] != member_id:
            continue
        fa = o.get("_fulfilled_at")
        if fa is None:
            continue
        if fa >= window_start:
            total += o.get("_tier_contribution", 0)
    return total


def tier_from_spend(spend):
    if spend >= TIER_GOLD_MIN_CENTS:
        return "GOLD"
    if spend >= TIER_SILVER_MIN_CENTS:
        return "SILVER"
    return "STANDARD"


def member_tier(member_id):
    return tier_from_spend(member_tier_spend(member_id))


def order_lines_of(order_id):
    return [l for l in DB["order_lines"].values() if l["order_id"] == order_id]


def effective_discount_pct(member_id, promo_code, subtotal_cents):
    sub_pct = member_active_subscription_pct(member_id)
    loyalty_pct = LOYALTY_TIER_DISCOUNT_PCT[member_tier(member_id)]
    promo_pct = PROMO_CODES.get(promo_code, Decimal("0")) if promo_code else Decimal("0")
    base = sub_pct + loyalty_pct
    capped = min(base, MAX_STACK_DISCOUNT_PCT)
    if promo_pct > 0 and subtotal_cents >= PROMO_MIN_SUBTOTAL_CENTS:
        return min(capped + promo_pct, MAX_TOTAL_DISCOUNT_PCT)
    return capped


def compute_line_points(line_gross_cents, tier):
    tm = TIER_MULTIPLIER[tier]
    val = (Decimal(line_gross_cents) / Decimal(100)) * Decimal(POINTS_PER_DOLLAR) * tm
    return rhu(val)


def reprice(order, variant):
    """Compute pricing fields on the order. variant: 'provisional' | 'final'."""
    lines = order_lines_of(order["id"])
    subtotal = sum(l["unit_price_cents"] * l["quantity"] for l in lines)
    pct = effective_discount_pct(order["member_id"], order.get("promo_code"), subtotal)

    if order.get("price_override_discount_cents") is not None:
        discount_cents = order["price_override_discount_cents"]
    else:
        discount_cents = rhu(Decimal(subtotal) * pct)

    subtotal_after_discount = subtotal - discount_cents

    if variant == "provisional":
        redeemed = 0
    else:
        redeemed = order.get("redeemed_points", 0)
    redemption_cents = redeemed * LOYALTY_POINT_VALUE_CENTS

    shipping = 0 if subtotal_after_discount >= FREE_SHIP_THRESHOLD_CENTS else SHIPPING_FEE_CENTS
    total = subtotal_after_discount - redemption_cents + shipping

    order["subtotal_cents"] = subtotal
    order["discount_pct_applied"] = float(pct)
    order["discount_cents"] = discount_cents
    order["shipping_fee_cents"] = shipping
    order["redemption_cents"] = redemption_cents

    if variant == "provisional":
        order["provisional_total_cents"] = total
    else:
        order["final_total_cents"] = total
        order["net_paid_cents"] = total
    return total


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def base_out(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def member_out(m):
    spend = member_tier_spend(m["id"])
    o = base_out(m)
    o.update({
        "email": m["email"],
        "full_name": m["full_name"],
        "state_code": m["state_code"],
        "status": m["status"],
        "loyalty_points_balance": m["loyalty_points_balance"],
        "tier_qualifying_spend_cents": spend,
        "loyalty_tier": tier_from_spend(spend),
    })
    return o


def product_out(p):
    o = base_out(p)
    o.update({
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "unit_price_cents": p["unit_price_cents"],
        "mileage_life_miles": p["mileage_life_miles"],
        "stock_on_hand": p["stock_on_hand"],
        "stock_reserved": p["stock_reserved"],
        "available_units": p["stock_on_hand"] - p["stock_reserved"],
        "availability": "IN_STOCK" if p["stock_on_hand"] > 0 else "OUT_OF_STOCK",
    })
    return o


def order_out(o_):
    o = base_out(o_)
    o.update({
        "member_id": o_["member_id"],
        "promo_code": o_.get("promo_code"),
        "payment_status": o_["payment_status"],
        "fulfillment_status": o_["fulfillment_status"],
        "subtotal_cents": o_.get("subtotal_cents"),
        "discount_pct_applied": o_.get("discount_pct_applied"),
        "discount_cents": o_.get("discount_cents"),
        "price_override_discount_cents": o_.get("price_override_discount_cents"),
        "redeemed_points": o_.get("redeemed_points", 0),
        "redemption_cents": o_.get("redemption_cents", 0),
        "shipping_fee_cents": o_.get("shipping_fee_cents"),
        "provisional_total_cents": o_.get("provisional_total_cents"),
        "final_total_cents": o_.get("final_total_cents"),
        "net_paid_cents": o_.get("net_paid_cents"),
        "estimated_points_earned": o_.get("estimated_points_earned"),
    })
    return o


def order_line_out(l):
    o = base_out(l)
    o.update({
        "order_id": l["order_id"],
        "product_id": l["product_id"],
        "quantity": l["quantity"],
        "unit_price_cents": l["unit_price_cents"],
        "line_gross_cents": l["unit_price_cents"] * l["quantity"],
        "line_points_earned": l.get("line_points_earned"),
        "is_returned": l["is_returned"],
    })
    return o


def wear_return_out(r):
    o = base_out(r)
    o.update({
        "order_line_id": r["order_line_id"],
        "member_id": r["member_id"],
        "reason": r["reason"],
        "wear_days": r.get("wear_days"),
        "status": r["status"],
        "inspection_notes": r.get("inspection_notes"),
    })
    return o


def subscription_out(s):
    o = base_out(s)
    pct = float(SUBSCRIPTION_DISCOUNT_PCT[s["plan"]]) if s["status"] == "ACTIVE" else 0.0
    o.update({
        "member_id": s["member_id"],
        "plan": s["plan"],
        "status": s["status"],
        "discount_pct": pct,
    })
    return o


def running_shoe_out(sh):
    o = base_out(sh)
    o.update({
        "member_id": sh["member_id"],
        "product_id": sh["product_id"],
        "source_order_id": sh.get("source_order_id"),
        "retirement_threshold_miles": sh["retirement_threshold_miles"],
        "total_mileage_miles": sh["total_mileage_miles"],
        "status": sh["status"],
    })
    return o


def fitter_out(f):
    o = base_out(f)
    o.update({"full_name": f["full_name"], "is_active": f["is_active"]})
    return o


def fitment_session_out(fs):
    o = base_out(fs)
    o.update({
        "member_id": fs["member_id"],
        "fitter_id": fs["fitter_id"],
        "scheduled_start": fs["scheduled_start"],
        "scheduled_end": fs["scheduled_end"],
        "status": fs["status"],
        "recommended_product_id": fs.get("recommended_product_id"),
        "notes": fs.get("notes"),
    })
    return o


def session_booked_count(session_id):
    return sum(1 for b in DB["training_bookings"].values()
               if b["session_id"] == session_id and b["status"] == "BOOKED")


def training_session_out(ts):
    o = base_out(ts)
    bc = session_booked_count(ts["id"])
    o.update({
        "title": ts["title"],
        "start_time": ts["start_time"],
        "end_time": ts["end_time"],
        "capacity": ts["capacity"],
        "fitter_id": ts.get("fitter_id"),
        "booked_count": bc,
        "available_slots": ts["capacity"] - bc,
    })
    return o


def waitlist_position_of(booking):
    if booking["status"] != "WAITLISTED":
        return None
    pos = 1
    for b in DB["training_bookings"].values():
        if (b["session_id"] == booking["session_id"] and b["status"] == "WAITLISTED"
                and b["_seq"] < booking["_seq"]):
            pos += 1
    return pos


def training_booking_out(b):
    o = base_out(b)
    o.update({
        "session_id": b["session_id"],
        "member_id": b["member_id"],
        "status": b["status"],
        "waitlist_position": waitlist_position_of(b),
    })
    return o


# ---------------------------------------------------------------------------
# Schedule / overlap helpers
# ---------------------------------------------------------------------------
def member_busy_intervals(member_id):
    intervals = []
    for fs in DB["fitment_sessions"].values():
        if fs["member_id"] == member_id and fs["status"] not in ("CANCELLED", "NO_SHOW"):
            intervals.append((parse_dt(fs["scheduled_start"]), parse_dt(fs["scheduled_end"])))
    for b in DB["training_bookings"].values():
        if b["member_id"] == member_id and b["status"] in ("BOOKED", "WAITLISTED"):
            ts = DB["training_sessions"].get(b["session_id"])
            if ts:
                intervals.append((parse_dt(ts["start_time"]), parse_dt(ts["end_time"])))
    return intervals


def half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def member_has_conflict(member_id, start, end):
    for (s, e) in member_busy_intervals(member_id):
        if half_open_overlap(start, end, s, e):
            return True
    return False


def fitter_has_conflict(fitter_id, start, end):
    buf = timedelta(minutes=SERVICE_BUFFER_MINUTES)
    for fs in DB["fitment_sessions"].values():
        if fs["fitter_id"] != fitter_id:
            continue
        if fs["status"] in ("CANCELLED", "NO_SHOW"):
            continue
        es = parse_dt(fs["scheduled_start"])
        ee = parse_dt(fs["scheduled_end"])
        # require a gap of at least buffer on either side; conflict when gap < buffer
        if start < ee + buf and es < end + buf:
            return True
    return False


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
@auth(MANAGER)
def set_clock():
    d = body()
    val = require_field(d, "to_iso8601")
    STATE["clock"] = parse_dt(val, "to_iso8601")
    return success({"current_utc": now_iso()}, "object", 200)


# ===========================================================================
# MEMBERS
# ===========================================================================
@app.route("/members", methods=["POST"])
@auth(ANON, MANAGER)
def create_member():
    d = body()
    email = require_field(d, "email")
    full_name = require_field(d, "full_name")
    state_code = require_field(d, "state_code")
    m = base_fields()
    m.update({
        "email": email,
        "full_name": full_name,
        "state_code": state_code,
        "status": "ACTIVE",
        "loyalty_points_balance": 0,
    })
    DB["members"][m["id"]] = m
    return success(member_out(m), "object", 201)


@app.route("/members/<member_id>", methods=["GET"])
@auth(MEMBER, FITTER, MANAGER)
def get_member(member_id):
    m = get_or_404("members", member_id)
    return success(member_out(m), "object", 200)


@app.route("/members/<member_id>/loyalty-adjustments", methods=["POST"])
@auth(MANAGER)
def loyalty_adjustment(member_id):
    m = get_or_404("members", member_id)
    d = body()
    delta = as_int(require_field(d, "points_delta"), "points_delta")
    require_field(d, "reason")
    m["loyalty_points_balance"] = max(0, m["loyalty_points_balance"] + delta)
    touch(m)
    return success(member_out(m), "object", 200)


# ===========================================================================
# PRODUCTS
# ===========================================================================
@app.route("/products", methods=["POST"])
@auth(MANAGER)
def create_product():
    d = body()
    sku = require_field(d, "sku")
    name = require_field(d, "name")
    category = require_field(d, "category")
    if category not in VALID_CATEGORY:
        raise ApiError("ERR_VALIDATION", 422, "Invalid category")
    unit_price = as_int(require_field(d, "unit_price_cents"), "unit_price_cents")
    if unit_price < 0:
        raise ApiError("ERR_VALIDATION", 422, "unit_price_cents must be >= 0")
    mileage = d.get("mileage_life_miles")
    if mileage is None:
        mileage = DEFAULT_MILEAGE_LIFE
    else:
        mileage = as_int(mileage, "mileage_life_miles")
    initial_stock = d.get("initial_stock", 0)
    if initial_stock is None:
        initial_stock = 0
    initial_stock = as_int(initial_stock, "initial_stock")
    if initial_stock < 0:
        raise ApiError("ERR_VALIDATION", 422, "initial_stock must be >= 0")
    p = base_fields()
    p.update({
        "sku": sku,
        "name": name,
        "category": category,
        "unit_price_cents": unit_price,
        "mileage_life_miles": mileage,
        "stock_on_hand": initial_stock,
        "stock_reserved": 0,
    })
    DB["products"][p["id"]] = p
    return success(product_out(p), "object", 201)


@app.route("/products/<product_id>", methods=["GET"])
@auth(ANON, MEMBER, FITTER, MANAGER)
def get_product(product_id):
    p = get_or_404("products", product_id)
    return success(product_out(p), "object", 200)


@app.route("/products", methods=["GET"])
@auth(ANON, MEMBER, FITTER, MANAGER)
def list_products():
    items = list(DB["products"].values())
    cat = request.args.get("category")
    if cat:
        items = [p for p in items if p["category"] == cat]
    return list_response(items, product_out)


@app.route("/products/<product_id>/restock", methods=["POST"])
@auth(MANAGER)
def restock_product(product_id):
    p = get_or_404("products", product_id)
    d = body()
    qty = as_int(require_field(d, "quantity"), "quantity")
    if qty < 1:
        raise ApiError("ERR_VALIDATION", 422, "quantity must be >= 1")
    p["stock_on_hand"] += qty
    touch(p)
    return success(product_out(p), "object", 200)


# ===========================================================================
# ORDERS
# ===========================================================================
@app.route("/orders", methods=["POST"])
@auth(MEMBER, MANAGER)
def create_order():
    d = body()
    member_id = require_field(d, "member_id")
    member = DB["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Member not found")
    ensure_member_owner(member_id)

    lines = d.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise ApiError("ERR_EMPTY_ORDER", 422, "Order must have at least one line")

    # existence of product FKs first (priority 3)
    for entry in lines:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", 422, "Each line must be an object")
        pid = entry.get("product_id")
        if pid is not None and pid not in DB["products"]:
            raise ApiError("ERR_NOT_FOUND", 404, "Product not found")
    # well-formedness (priority 5)
    for entry in lines:
        pid = entry.get("product_id")
        if pid is None:
            raise ApiError("ERR_VALIDATION", 422, "line.product_id required")
        q = entry.get("quantity")
        if q is None:
            raise ApiError("ERR_VALIDATION", 422, "line.quantity required")
        q = as_int(q, "quantity")
        if q < 1:
            raise ApiError("ERR_VALIDATION", 422, "quantity must be >= 1")

    promo_code = d.get("promo_code")

    order = base_fields()
    order.update({
        "member_id": member_id,
        "promo_code": promo_code,
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
        "price_override_discount_cents": None,
        "redeemed_points": 0,
        "final_total_cents": None,
        "net_paid_cents": None,
        "_fulfilled_at": None,
        "_tier_contribution": 0,
    })
    DB["orders"][order["id"]] = order

    for entry in lines:
        pid = entry["product_id"]
        product = DB["products"][pid]
        line = base_fields()
        line.update({
            "order_id": order["id"],
            "product_id": pid,
            "quantity": as_int(entry["quantity"], "quantity"),
            "unit_price_cents": product["unit_price_cents"],
            "is_returned": False,
            "line_points_earned": None,
        })
        DB["order_lines"][line["id"]] = line

    # provisional pricing + estimated points
    reprice(order, "provisional")
    tier = member_tier(member_id)
    est = 0
    for line in order_lines_of(order["id"]):
        pts = compute_line_points(line["unit_price_cents"] * line["quantity"], tier)
        line["line_points_earned"] = pts
        est += pts
    order["estimated_points_earned"] = est

    return success(order_out(order), "object", 201)


@app.route("/orders/<order_id>", methods=["GET"])
@auth(MEMBER, MANAGER)
def get_order(order_id):
    o = get_or_404("orders", order_id)
    ensure_member_owner(o["member_id"])
    return success(order_out(o), "object", 200)


@app.route("/orders", methods=["GET"])
@auth(MEMBER, MANAGER)
def list_orders():
    items = list(DB["orders"].values())
    mid = request.args.get("member_id")
    if mid:
        items = [o for o in items if o["member_id"] == mid]
    if g.role == MEMBER:
        items = [o for o in items if o["member_id"] == g.uid]
    return list_response(items, order_out)


@app.route("/orders/<order_id>/apply-redemption", methods=["POST"])
@auth(MEMBER, MANAGER)
def apply_redemption(order_id):
    o = get_or_404("orders", order_id)
    ensure_member_owner(o["member_id"])
    d = body()
    points = as_int(require_field(d, "points_to_redeem"), "points_to_redeem")
    if o["payment_status"] != "UNPAID":
        raise ApiError("ERR_ORDER_NOT_MODIFIABLE", 409, "Order not modifiable")
    member = DB["members"][o["member_id"]]
    # fiscal: sufficient points
    if points > member["loyalty_points_balance"]:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 402, "Insufficient loyalty points")
    # fiscal: multiple of 100 and <= 50% of subtotal_after_discount
    subtotal_after_discount = o.get("subtotal_cents", 0) - o.get("discount_cents", 0)
    redemption_cents = points * LOYALTY_POINT_VALUE_CENTS
    if points % 100 != 0 or redemption_cents * 2 > subtotal_after_discount:
        raise ApiError("ERR_REDEMPTION_EXCEEDS_CAP", 422, "Redemption exceeds cap or not a multiple of 100")
    o["redeemed_points"] = points
    o["redemption_cents"] = redemption_cents
    member["loyalty_points_balance"] -= points
    touch(member)
    touch(o)
    return success(order_out(o), "object", 200)


@app.route("/orders/<order_id>/authorize-payment", methods=["POST"])
@auth(MEMBER, MANAGER)
def authorize_payment(order_id):
    o = get_or_404("orders", order_id)
    ensure_member_owner(o["member_id"])
    if o["payment_status"] != "UNPAID":
        raise ApiError("ERR_INVALID_STATE", 409, "Payment not UNPAID")
    o["payment_status"] = "AUTHORIZED"
    touch(o)
    return success(order_out(o), "object", 200)


@app.route("/orders/<order_id>/capture-payment", methods=["POST"])
@auth(MEMBER, MANAGER)
def capture_payment(order_id):
    o = get_or_404("orders", order_id)
    ensure_member_owner(o["member_id"])
    if o["payment_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Payment not AUTHORIZED")
    o["payment_status"] = "PAID"
    reprice(o, "final")
    touch(o)
    return success(order_out(o), "object", 200)


@app.route("/orders/<order_id>/reserve", methods=["POST"])
@auth(MEMBER, MANAGER)
def reserve_order(order_id):
    o = get_or_404("orders", order_id)
    ensure_member_owner(o["member_id"])
    if o["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not PENDING")
    lines = order_lines_of(order_id)
    needed = {}
    for l in lines:
        needed[l["product_id"]] = needed.get(l["product_id"], 0) + l["quantity"]
    for pid, q in needed.items():
        p = DB["products"][pid]
        avail = p["stock_on_hand"] - p["stock_reserved"]
        if avail < q:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409, "Insufficient stock")
    for pid, q in needed.items():
        p = DB["products"][pid]
        p["stock_reserved"] += q
        touch(p)
    o["fulfillment_status"] = "RESERVED"
    touch(o)
    return success(order_out(o), "object", 200)


@app.route("/orders/<order_id>/fulfill", methods=["POST"])
@auth(MANAGER)
def fulfill_order(order_id):
    o = get_or_404("orders", order_id)
    if o["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not RESERVED")
    if o["payment_status"] != "PAID":
        raise ApiError("ERR_PAYMENT_NOT_CAPTURED", 409, "Payment not captured")
    member = DB["members"][o["member_id"]]
    lines = order_lines_of(order_id)

    # Cascade B link2/link3: draw down stock
    for l in lines:
        p = DB["products"][l["product_id"]]
        p["stock_reserved"] -= l["quantity"]
        p["stock_on_hand"] -= l["quantity"]
        touch(p)

    # recompute final total (tier as of fulfillment, this order not yet crediting spend)
    reprice(o, "final")

    # settled loyalty points (tier as of fulfillment)
    tier = member_tier(member["id"])
    settled = 0
    for l in lines:
        if l.get("is_returned"):
            continue
        pts = compute_line_points(l["unit_price_cents"] * l["quantity"], tier)
        l["line_points_earned"] = pts
        touch(l)
        settled += pts
    member["loyalty_points_balance"] += settled

    # mint running shoes per SHOE unit
    for l in lines:
        product = DB["products"][l["product_id"]]
        if product["category"] == "SHOE":
            for _ in range(l["quantity"]):
                sh = base_fields()
                sh.update({
                    "member_id": o["member_id"],
                    "product_id": product["id"],
                    "source_order_id": o["id"],
                    "retirement_threshold_miles": product["mileage_life_miles"],
                    "total_mileage_miles": 0,
                    "status": "ACTIVE",
                })
                DB["running_shoes"][sh["id"]] = sh

    o["fulfillment_status"] = "FULFILLED"
    o["_fulfilled_at"] = now_dt()
    o["_tier_contribution"] = o["net_paid_cents"]
    touch(o)
    touch(member)
    return success(order_out(o), "object", 200)


@app.route("/orders/<order_id>/cancel", methods=["POST"])
@auth(MEMBER, MANAGER)
def cancel_order(order_id):
    o = get_or_404("orders", order_id)
    ensure_member_owner(o["member_id"])
    if o["fulfillment_status"] not in ("PENDING", "RESERVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order not cancellable")
    member = DB["members"][o["member_id"]]
    if o["fulfillment_status"] == "RESERVED":
        for l in order_lines_of(order_id):
            p = DB["products"][l["product_id"]]
            p["stock_reserved"] -= l["quantity"]
            touch(p)
    if o.get("redeemed_points", 0) > 0:
        member["loyalty_points_balance"] += o["redeemed_points"]
        touch(member)
    if o["payment_status"] in ("AUTHORIZED", "PAID"):
        was_paid = o["payment_status"] == "PAID"
        o["payment_status"] = "REFUNDED"
        if was_paid:
            o["net_paid_cents"] = 0
    o["fulfillment_status"] = "CANCELLED"
    touch(o)
    return success(order_out(o), "object", 200)


@app.route("/orders/<order_id>/price-overrides", methods=["POST"])
@auth(MANAGER)
def price_override(order_id):
    o = get_or_404("orders", order_id)
    d = body()
    expected = as_int(require_field(d, "expected_order_version"), "expected_order_version")
    override = as_int(require_field(d, "override_discount_cents"), "override_discount_cents")
    if o["payment_status"] != "UNPAID":
        raise ApiError("ERR_ORDER_NOT_MODIFIABLE", 409, "Order not modifiable")
    if expected != o["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale order version")
    o["price_override_discount_cents"] = override
    reprice(o, "provisional")
    touch(o)
    return success(order_out(o), "object", 200)


# ===========================================================================
# ORDER LINES
# ===========================================================================
@app.route("/order-lines/<line_id>", methods=["GET"])
@auth(MEMBER, MANAGER)
def get_order_line(line_id):
    l = get_or_404("order_lines", line_id)
    order = DB["orders"].get(l["order_id"])
    if order is not None:
        ensure_member_owner(order["member_id"])
    return success(order_line_out(l), "object", 200)


@app.route("/order-lines", methods=["GET"])
@auth(MEMBER, MANAGER)
def list_order_lines():
    items = list(DB["order_lines"].values())
    oid = request.args.get("order_id")
    pid = request.args.get("product_id")
    if oid:
        items = [l for l in items if l["order_id"] == oid]
    if pid:
        items = [l for l in items if l["product_id"] == pid]
    if g.role == MEMBER:
        items = [l for l in items
                 if DB["orders"].get(l["order_id"], {}).get("member_id") == g.uid]
    return list_response(items, order_line_out)


# ===========================================================================
# RETURNS
# ===========================================================================
@app.route("/returns", methods=["POST"])
@auth(MEMBER, MANAGER)
def create_return():
    d = body()
    line_id = require_field(d, "order_line_id")
    line = DB["order_lines"].get(line_id)
    if line is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Order line not found")
    order = DB["orders"].get(line["order_id"])
    if order is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Order not found")
    ensure_member_owner(order["member_id"])
    reason = require_field(d, "reason")
    if order["fulfillment_status"] != "FULFILLED":
        raise ApiError("ERR_ORDER_NOT_FULFILLED", 409, "Order not fulfilled")
    r = base_fields()
    wear_days = d.get("wear_days")
    if wear_days is not None:
        wear_days = as_int(wear_days, "wear_days")
    r.update({
        "order_line_id": line_id,
        "member_id": order["member_id"],
        "reason": reason,
        "wear_days": wear_days,
        "status": "REQUESTED",
        "inspection_notes": None,
    })
    DB["returns"][r["id"]] = r
    return success(wear_return_out(r), "object", 201)


@app.route("/returns/<return_id>", methods=["GET"])
@auth(MEMBER, MANAGER)
def get_return(return_id):
    r = get_or_404("returns", return_id)
    ensure_member_owner(r["member_id"])
    return success(wear_return_out(r), "object", 200)


@app.route("/returns", methods=["GET"])
@auth(MEMBER, MANAGER)
def list_returns():
    items = list(DB["returns"].values())
    line_id = request.args.get("order_line_id")
    mid = request.args.get("member_id")
    if line_id:
        items = [r for r in items if r["order_line_id"] == line_id]
    if mid:
        items = [r for r in items if r["member_id"] == mid]
    if g.role == MEMBER:
        items = [r for r in items if r["member_id"] == g.uid]
    return list_response(items, wear_return_out)


@app.route("/returns/<return_id>/start-inspection", methods=["POST"])
@auth(MANAGER)
def start_inspection(return_id):
    r = get_or_404("returns", return_id)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_RETURN_NOT_INSPECTABLE", 409, "Return not inspectable")
    r["status"] = "UNDER_INSPECTION"
    touch(r)
    return success(wear_return_out(r), "object", 200)


@app.route("/returns/<return_id>/approve", methods=["POST"])
@auth(MANAGER)
def approve_return(return_id):
    r = get_or_404("returns", return_id)
    if r["status"] != "UNDER_INSPECTION":
        raise ApiError("ERR_RETURN_NOT_INSPECTABLE", 409, "Return not inspectable")
    line = DB["order_lines"][r["order_line_id"]]
    order = DB["orders"][line["order_id"]]
    member = DB["members"][order["member_id"]]

    # Cascade A link1
    r["status"] = "APPROVED"
    touch(r)
    line["is_returned"] = True
    returned_net = line["unit_price_cents"] * line["quantity"]
    returned_points = line.get("line_points_earned") or 0
    touch(line)

    # Cascade A link2
    order["fulfillment_status"] = "RETURNED"
    order["payment_status"] = "REFUNDED"
    if order.get("net_paid_cents") is not None:
        order["net_paid_cents"] -= returned_net
    order["_tier_contribution"] = order.get("_tier_contribution", 0) - returned_net
    touch(order)

    # Cascade A link3/link4
    member["loyalty_points_balance"] -= returned_points
    touch(member)
    return success(wear_return_out(r), "object", 200)


@app.route("/returns/<return_id>/reject", methods=["POST"])
@auth(MANAGER)
def reject_return(return_id):
    r = get_or_404("returns", return_id)
    if r["status"] != "UNDER_INSPECTION":
        raise ApiError("ERR_RETURN_NOT_INSPECTABLE", 409, "Return not inspectable")
    d = body()
    r["status"] = "REJECTED"
    r["inspection_notes"] = d.get("reason")
    touch(r)
    return success(wear_return_out(r), "object", 200)


@app.route("/returns/<return_id>/resubmit", methods=["POST"])
@auth(MEMBER, MANAGER)
def resubmit_return(return_id):
    r = get_or_404("returns", return_id)
    ensure_member_owner(r["member_id"])
    if r["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Return not REJECTED")
    r["status"] = "REQUESTED"
    touch(r)
    return success(wear_return_out(r), "object", 200)


@app.route("/returns/<return_id>/withdraw", methods=["POST"])
@auth(MEMBER, MANAGER)
def withdraw_return(return_id):
    r = get_or_404("returns", return_id)
    ensure_member_owner(r["member_id"])
    if r["status"] not in ("REQUESTED", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Return not withdrawable")
    r["status"] = "WITHDRAWN"
    touch(r)
    return success(wear_return_out(r), "object", 200)


# ===========================================================================
# SUBSCRIPTIONS
# ===========================================================================
@app.route("/subscriptions", methods=["POST"])
@auth(MEMBER, MANAGER)
def create_subscription():
    d = body()
    member_id = require_field(d, "member_id")
    if member_id not in DB["members"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Member not found")
    ensure_member_owner(member_id)
    plan = require_field(d, "plan")
    if plan not in VALID_PLAN:
        raise ApiError("ERR_VALIDATION", 422, "Invalid plan")
    s = base_fields()
    s.update({"member_id": member_id, "plan": plan, "status": "ACTIVE"})
    DB["subscriptions"][s["id"]] = s
    return success(subscription_out(s), "object", 201)


@app.route("/subscriptions/<subscription_id>", methods=["GET"])
@auth(MEMBER, MANAGER)
def get_subscription(subscription_id):
    s = get_or_404("subscriptions", subscription_id)
    ensure_member_owner(s["member_id"])
    return success(subscription_out(s), "object", 200)


@app.route("/subscriptions", methods=["GET"])
@auth(MEMBER, MANAGER)
def list_subscriptions():
    items = list(DB["subscriptions"].values())
    mid = request.args.get("member_id")
    if mid:
        items = [s for s in items if s["member_id"] == mid]
    if g.role == MEMBER:
        items = [s for s in items if s["member_id"] == g.uid]
    return list_response(items, subscription_out)


@app.route("/subscriptions/<subscription_id>/mark-past-due", methods=["POST"])
@auth(MANAGER)
def mark_past_due(subscription_id):
    s = get_or_404("subscriptions", subscription_id)
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription not ACTIVE")
    s["status"] = "PAST_DUE"
    touch(s)
    return success(subscription_out(s), "object", 200)


@app.route("/subscriptions/<subscription_id>/reactivate", methods=["POST"])
@auth(MEMBER, MANAGER)
def reactivate_subscription(subscription_id):
    s = get_or_404("subscriptions", subscription_id)
    ensure_member_owner(s["member_id"])
    if s["status"] != "PAST_DUE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription not PAST_DUE")
    s["status"] = "ACTIVE"
    touch(s)
    return success(subscription_out(s), "object", 200)


@app.route("/subscriptions/<subscription_id>/cancel", methods=["POST"])
@auth(MEMBER, MANAGER)
def cancel_subscription(subscription_id):
    s = get_or_404("subscriptions", subscription_id)
    ensure_member_owner(s["member_id"])
    if s["status"] not in ("ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription not cancellable")
    s["status"] = "CANCELLED"
    touch(s)
    return success(subscription_out(s), "object", 200)


# ===========================================================================
# RUNNING SHOES
# ===========================================================================
@app.route("/running-shoes/<shoe_id>", methods=["GET"])
@auth(MEMBER, MANAGER)
def get_running_shoe(shoe_id):
    sh = get_or_404("running_shoes", shoe_id)
    ensure_member_owner(sh["member_id"])
    return success(running_shoe_out(sh), "object", 200)


@app.route("/running-shoes", methods=["GET"])
@auth(MEMBER, MANAGER)
def list_running_shoes():
    items = list(DB["running_shoes"].values())
    mid = request.args.get("member_id")
    pid = request.args.get("product_id")
    soid = request.args.get("source_order_id")
    if mid:
        items = [x for x in items if x["member_id"] == mid]
    if pid:
        items = [x for x in items if x["product_id"] == pid]
    if soid:
        items = [x for x in items if x.get("source_order_id") == soid]
    if g.role == MEMBER:
        items = [x for x in items if x["member_id"] == g.uid]
    return list_response(items, running_shoe_out)


@app.route("/running-shoes/<shoe_id>/log-mileage", methods=["POST"])
@auth(MEMBER, MANAGER)
def log_mileage(shoe_id):
    sh = get_or_404("running_shoes", shoe_id)
    ensure_member_owner(sh["member_id"])
    d = body()
    miles = as_int(require_field(d, "miles"), "miles")
    if sh["status"] == "RETIRED":
        raise ApiError("ERR_SHOE_ALREADY_RETIRED", 409, "Shoe already retired")
    sh["total_mileage_miles"] += miles
    if sh["status"] == "ACTIVE" and sh["total_mileage_miles"] >= sh["retirement_threshold_miles"]:
        sh["status"] = "RETIREMENT_DUE"
    touch(sh)
    return success(running_shoe_out(sh), "object", 200)


@app.route("/running-shoes/<shoe_id>/retire", methods=["POST"])
@auth(MEMBER, MANAGER)
def retire_shoe(shoe_id):
    sh = get_or_404("running_shoes", shoe_id)
    ensure_member_owner(sh["member_id"])
    if sh["status"] == "RETIRED":
        raise ApiError("ERR_SHOE_ALREADY_RETIRED", 409, "Shoe already retired")
    sh["status"] = "RETIRED"
    touch(sh)
    return success(running_shoe_out(sh), "object", 200)


# ===========================================================================
# FITTERS
# ===========================================================================
@app.route("/fitters", methods=["POST"])
@auth(MANAGER)
def create_fitter():
    d = body()
    full_name = require_field(d, "full_name")
    f = base_fields()
    f.update({"full_name": full_name, "is_active": True})
    DB["fitters"][f["id"]] = f
    return success(fitter_out(f), "object", 201)


@app.route("/fitters/<fitter_id>", methods=["GET"])
@auth(ANON, MEMBER, FITTER, MANAGER)
def get_fitter(fitter_id):
    f = get_or_404("fitters", fitter_id)
    return success(fitter_out(f), "object", 200)


# ===========================================================================
# FITMENT SESSIONS
# ===========================================================================
@app.route("/fitment-sessions", methods=["POST"])
@auth(MEMBER, MANAGER)
def create_fitment_session():
    d = body()
    member_id = require_field(d, "member_id")
    if member_id not in DB["members"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Member not found")
    fitter_id = require_field(d, "fitter_id")
    if fitter_id not in DB["fitters"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Fitter not found")
    ensure_member_owner(member_id)
    start_raw = require_field(d, "scheduled_start")
    end_raw = require_field(d, "scheduled_end")
    start = parse_dt(start_raw, "scheduled_start")
    end = parse_dt(end_raw, "scheduled_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION", 422, "scheduled_end must be after scheduled_start")
    # temporal
    if start < now_dt():
        raise ApiError("ERR_APPOINTMENT_IN_PAST", 422, "Appointment in the past")
    if member_has_conflict(member_id, start, end):
        raise ApiError("ERR_SCHEDULE_CONFLICT", 409, "Member schedule conflict")
    if fitter_has_conflict(fitter_id, start, end):
        raise ApiError("ERR_FITTER_UNAVAILABLE", 409, "Fitter unavailable")
    fs = base_fields()
    fs.update({
        "member_id": member_id,
        "fitter_id": fitter_id,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "status": "SCHEDULED",
        "recommended_product_id": None,
        "notes": None,
    })
    DB["fitment_sessions"][fs["id"]] = fs
    return success(fitment_session_out(fs), "object", 201)


@app.route("/fitment-sessions/<session_id>", methods=["GET"])
@auth(MEMBER, FITTER, MANAGER)
def get_fitment_session(session_id):
    fs = get_or_404("fitment_sessions", session_id)
    if g.role == MEMBER:
        ensure_member_owner(fs["member_id"])
    return success(fitment_session_out(fs), "object", 200)


@app.route("/fitment-sessions", methods=["GET"])
@auth(MEMBER, FITTER, MANAGER)
def list_fitment_sessions():
    items = list(DB["fitment_sessions"].values())
    mid = request.args.get("member_id")
    fid = request.args.get("fitter_id")
    rpid = request.args.get("recommended_product_id")
    if mid:
        items = [x for x in items if x["member_id"] == mid]
    if fid:
        items = [x for x in items if x["fitter_id"] == fid]
    if rpid:
        items = [x for x in items if x.get("recommended_product_id") == rpid]
    if g.role == MEMBER:
        items = [x for x in items if x["member_id"] == g.uid]
    return list_response(items, fitment_session_out)


@app.route("/fitment-sessions/<session_id>/check-in", methods=["POST"])
@auth(FITTER, MANAGER)
def fitment_check_in(session_id):
    fs = get_or_404("fitment_sessions", session_id)
    ensure_fitter_owner(fs["fitter_id"])
    if fs["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Session not SCHEDULED")
    fs["status"] = "CHECKED_IN"
    touch(fs)
    return success(fitment_session_out(fs), "object", 200)


@app.route("/fitment-sessions/<session_id>/complete", methods=["POST"])
@auth(FITTER, MANAGER)
def fitment_complete(session_id):
    fs = get_or_404("fitment_sessions", session_id)
    ensure_fitter_owner(fs["fitter_id"])
    d = body()
    rpid = d.get("recommended_product_id")
    if rpid is not None and rpid not in DB["products"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Recommended product not found")
    if fs["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Session not CHECKED_IN")
    fs["status"] = "COMPLETED"
    fs["recommended_product_id"] = rpid
    fs["notes"] = d.get("notes")
    touch(fs)
    return success(fitment_session_out(fs), "object", 200)


@app.route("/fitment-sessions/<session_id>/cancel", methods=["POST"])
@auth(MEMBER, FITTER, MANAGER)
def fitment_cancel(session_id):
    fs = get_or_404("fitment_sessions", session_id)
    if g.role == MEMBER:
        ensure_member_owner(fs["member_id"])
    elif g.role == FITTER:
        ensure_fitter_owner(fs["fitter_id"])
    if fs["status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "Session not cancellable")
    fs["status"] = "CANCELLED"
    touch(fs)
    return success(fitment_session_out(fs), "object", 200)


# ===========================================================================
# TRAINING SESSIONS
# ===========================================================================
@app.route("/training-sessions", methods=["POST"])
@auth(FITTER, MANAGER)
def create_training_session():
    d = body()
    title = require_field(d, "title")
    start_raw = require_field(d, "start_time")
    end_raw = require_field(d, "end_time")
    start = parse_dt(start_raw, "start_time")
    end = parse_dt(end_raw, "end_time")
    if end <= start:
        raise ApiError("ERR_VALIDATION", 422, "end_time must be after start_time")
    capacity = as_int(require_field(d, "capacity"), "capacity")
    if capacity < 1:
        raise ApiError("ERR_VALIDATION", 422, "capacity must be >= 1")
    fitter_id = d.get("fitter_id")
    if fitter_id is not None and fitter_id not in DB["fitters"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Fitter not found")
    ts = base_fields()
    ts.update({
        "title": title,
        "start_time": start_raw,
        "end_time": end_raw,
        "capacity": capacity,
        "fitter_id": fitter_id,
    })
    DB["training_sessions"][ts["id"]] = ts
    return success(training_session_out(ts), "object", 201)


@app.route("/training-sessions/<session_id>", methods=["GET"])
@auth(ANON, MEMBER, FITTER, MANAGER)
def get_training_session(session_id):
    ts = get_or_404("training_sessions", session_id)
    return success(training_session_out(ts), "object", 200)


@app.route("/training-sessions", methods=["GET"])
@auth(ANON, MEMBER, FITTER, MANAGER)
def list_training_sessions():
    items = list(DB["training_sessions"].values())
    fid = request.args.get("fitter_id")
    if fid:
        items = [x for x in items if x.get("fitter_id") == fid]
    return list_response(items, training_session_out)


# ===========================================================================
# TRAINING BOOKINGS
# ===========================================================================
@app.route("/training-bookings", methods=["POST"])
@auth(MEMBER, MANAGER)
def create_training_booking():
    d = body()
    session_id = require_field(d, "session_id")
    session = DB["training_sessions"].get(session_id)
    if session is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Training session not found")
    member_id = require_field(d, "member_id")
    if member_id not in DB["members"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Member not found")
    ensure_member_owner(member_id)
    # temporal (priority 7): member schedule conflict
    start = parse_dt(session["start_time"])
    end = parse_dt(session["end_time"])
    if member_has_conflict(member_id, start, end):
        raise ApiError("ERR_SCHEDULE_CONFLICT", 409, "Member schedule conflict")
    # cross-entity (priority 8): active subscription required
    has_active = any(s["member_id"] == member_id and s["status"] == "ACTIVE"
                     for s in DB["subscriptions"].values())
    if not has_active:
        raise ApiError("ERR_SUBSCRIPTION_REQUIRED", 409, "Active subscription required")
    bc = session_booked_count(session_id)
    available = session["capacity"] - bc
    status = "BOOKED" if available > 0 else "WAITLISTED"
    b = base_fields()
    b.update({"session_id": session_id, "member_id": member_id, "status": status})
    DB["training_bookings"][b["id"]] = b
    return success(training_booking_out(b), "object", 201)


@app.route("/training-bookings/<booking_id>", methods=["GET"])
@auth(MEMBER, FITTER, MANAGER)
def get_training_booking(booking_id):
    b = get_or_404("training_bookings", booking_id)
    if g.role == MEMBER:
        ensure_member_owner(b["member_id"])
    return success(training_booking_out(b), "object", 200)


@app.route("/training-bookings", methods=["GET"])
@auth(MEMBER, FITTER, MANAGER)
def list_training_bookings():
    items = list(DB["training_bookings"].values())
    sid = request.args.get("session_id")
    mid = request.args.get("member_id")
    if sid:
        items = [x for x in items if x["session_id"] == sid]
    if mid:
        items = [x for x in items if x["member_id"] == mid]
    if g.role == MEMBER:
        items = [x for x in items if x["member_id"] == g.uid]
    return list_response(items, training_booking_out)


@app.route("/training-bookings/<booking_id>/cancel", methods=["POST"])
@auth(MEMBER, MANAGER)
def cancel_training_booking(booking_id):
    b = get_or_404("training_bookings", booking_id)
    ensure_member_owner(b["member_id"])
    if b["status"] not in ("BOOKED", "WAITLISTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Booking not cancellable")
    was_booked = b["status"] == "BOOKED"
    b["status"] = "CANCELLED"
    touch(b)
    if was_booked:
        # promote earliest WAITLISTED booking on same session
        waitlisted = [x for x in DB["training_bookings"].values()
                      if x["session_id"] == b["session_id"] and x["status"] == "WAITLISTED"]
        if waitlisted:
            promote = min(waitlisted, key=lambda x: x["_seq"])
            promote["status"] = "BOOKED"
            touch(promote)
    return success(training_booking_out(b), "object", 200)


@app.route("/training-bookings/<booking_id>/mark-attended", methods=["POST"])
@auth(FITTER, MANAGER)
def mark_attended(booking_id):
    b = get_or_404("training_bookings", booking_id)
    if b["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking not BOOKED")
    b["status"] = "ATTENDED"
    touch(b)
    return success(training_booking_out(b), "object", 200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
