"""
Fishing, Tackle & Bait Shop API — Python + Flask reference implementation.

In-memory only. State is wiped on every process start (per-test-server isolation).
No entity is seeded at startup; every entity is created via the declared API.
All behavior traces to workspace/PRD.md.
"""

import math
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

UTC = timezone.utc

# =============================================================================
# Constants (from PRD / SCAFFOLD)
# =============================================================================
VALID_ROLES = {"Customer", "ShopClerk", "Guide", "TournamentDirector", "ShopManager"}

PEAK_MONTHS = {5, 6, 7, 8}

CHARTER_INCLUDED_ANGLERS = 2
EQUIPMENT_RENTAL_PER_ANGLER_CENTS = 2500
SEASONAL_SURCHARGE_MULT = Decimal("1.20")
DEPOSIT_PCT = Decimal("0.25")
TIER_DISCOUNT_PCT = {"BRONZE": Decimal("0.00"), "SILVER": Decimal("0.05"), "GOLD": Decimal("0.10")}
TIER_MULTIPLIER = {"BRONZE": Decimal("1.00"), "SILVER": Decimal("1.10"), "GOLD": Decimal("1.25")}
CHARTER_BUFFER = timedelta(minutes=60)

LOYALTY_SEASONAL_BONUS_PCT = Decimal("0.10")

TAX_BPS = 800

SPECIAL_ORDER_DEPOSIT_PCT = Decimal("0.50")
RESTOCK_FEE_PCT = Decimal("0.20")

SILVER_MIN = 500
GOLD_MIN = 2000

LICENSE_DURATION_DAYS = {
    "RESIDENT_ANNUAL": 365,
    "NONRESIDENT_ANNUAL": 365,
    "ONE_DAY": 1,
    "SENIOR": 365,
}
LICENSE_PRICE_CENTS = {
    "RESIDENT_ANNUAL": 5200,
    "NONRESIDENT_ANNUAL": 12000,
    "ONE_DAY": 1500,
    "SENIOR": 2600,
}
LICENSE_MIN_AGE = {
    "RESIDENT_ANNUAL": 16,
    "NONRESIDENT_ANNUAL": 16,
    "ONE_DAY": 16,
    "SENIOR": 65,
}
LICENSE_TYPES = set(LICENSE_DURATION_DAYS.keys())

PRODUCT_CATEGORIES = {"ROD", "REEL", "TERMINAL_TACKLE", "APPAREL", "DRY_BAIT"}
BAIT_SPECIES = {"MINNOW", "SHINER", "NIGHTCRAWLER", "SHRIMP"}
WATER_TYPES = {"LAKE", "RIVER", "SALTWATER", "POND"}
TRIP_TYPES = {"HALF_DAY", "FULL_DAY"}
SERVICE_TYPES = {"SPOOLING", "REEL_SERVICE", "ROD_REPAIR", "GUIDE_LINE"}

DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)


# =============================================================================
# In-memory store
# =============================================================================
class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        self.customers = {}
        self.products = {}
        self.licenses = {}
        self.bait_tanks = {}
        self.guides = {}
        self.venues = {}
        self.charter_bookings = {}
        self.tournaments = {}
        self.tournament_entries = {}
        self.service_orders = {}
        self.special_orders = {}
        self.sales = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    return db.clock


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# =============================================================================
# Response envelope helpers
# =============================================================================
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": serialize_dt(datetime.now(UTC)),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


# =============================================================================
# Datetime helpers
# =============================================================================
def serialize_dt(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def parse_dt(s):
    if not isinstance(s, str):
        raise err("ERR_INVALID_REQUEST", 400, "Invalid datetime.")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", 400, "Invalid datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date(s):
    if not isinstance(s, str):
        raise err("ERR_INVALID_REQUEST", 400, "Invalid date.")
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        raise err("ERR_INVALID_REQUEST", 400, "Invalid date.")


def compute_age(birth_str, at):
    b = date.fromisoformat(birth_str)
    n = at.date()
    return n.year - b.year - ((n.month, n.day) < (b.month, b.day))


# =============================================================================
# Money / points
# =============================================================================
def q(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mult_round(amount_cents, multiplier):
    return q(Decimal(int(amount_cents)) * multiplier)


# =============================================================================
# Common fields / mutation
# =============================================================================
def common(rec):
    n = now()
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = n
    rec["updated_at"] = n
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


def common_out(rec):
    return {
        "id": rec["id"],
        "created_at": serialize_dt(rec["created_at"]),
        "updated_at": serialize_dt(rec["updated_at"]),
        "version": rec["version"],
    }


# =============================================================================
# Auth / RBAC
# =============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    g.uid = uid
    g.role = role
    return uid, role


def require_roles(allowed):
    if g.role not in allowed:
        raise err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")


def forbid():
    raise err("ERR_UNAUTHORIZED", 403, "Not permitted.")


# =============================================================================
# Body / validation helpers
# =============================================================================
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", 400, "Body must be a JSON object.")
    return data


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {name}")
    return v


def opt_str(b, name, default=None):
    if name not in b or b.get(name) is None:
        return default
    v = b.get(name)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", 400, f"Invalid field: {name}")
    return v


def req_enum(b, name, choices):
    v = req_str(b, name)
    if v not in choices:
        raise err("ERR_INVALID_REQUEST", 400, f"Invalid value for {name}.")
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, name, min_value=None):
    v = b.get(name)
    if not is_int(v):
        raise err("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {name}")
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {name} out of range.")
    return v


def opt_int(b, name, default=None, min_value=None):
    if name not in b or b.get(name) is None:
        return default
    v = b.get(name)
    if not is_int(v):
        raise err("ERR_INVALID_REQUEST", 400, f"Invalid field: {name}")
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {name} out of range.")
    return v


def req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {name}")
    return v


def opt_bool(b, name, default):
    if name not in b or b.get(name) is None:
        return default
    v = b.get(name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 400, f"Invalid field: {name}")
    return v


# =============================================================================
# Pagination / listing
# =============================================================================
def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_result(records, serialize, extra_filter=None):
    items = list(records.values())
    if extra_filter:
        items = [r for r in items if extra_filter(r)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = pagination()
    page = items[offset:offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, total)


# =============================================================================
# Lookups
# =============================================================================
def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", 404, "Resource not found.")
    return rec


def exists_or_404(coll, rid):
    if rid not in coll:
        raise err("ERR_NOT_FOUND", 404, "Referenced resource not found.")
    return coll[rid]


# =============================================================================
# Loyalty
# =============================================================================
def customer_balance(c):
    return max(0, sum(e["delta_points"] for e in c["loyalty_ledger"]))


def tier_from_balance(balance):
    if balance < SILVER_MIN:
        return "BRONZE"
    if balance < GOLD_MIN:
        return "SILVER"
    return "GOLD"


def customer_tier(c):
    return tier_from_balance(customer_balance(c))


def add_ledger(c, delta, reason, ref_type, ref_id):
    c["loyalty_ledger"].append({
        "entry_id": str(uuid.uuid4()),
        "delta_points": int(delta),
        "reason": reason,
        "ref_type": ref_type,
        "ref_id": ref_id,
        "created_at": now(),
    })
    touch(c)


# =============================================================================
# Serializers
# =============================================================================
def ser_customer(c):
    out = common_out(c)
    balance = customer_balance(c)
    out.update({
        "name": c["name"],
        "email": c["email"],
        "state_code": c["state_code"],
        "birth_date": c["birth_date"],
        "loyalty_ledger": [{
            "entry_id": e["entry_id"],
            "delta_points": e["delta_points"],
            "reason": e["reason"],
            "ref_type": e["ref_type"],
            "ref_id": e["ref_id"],
            "created_at": serialize_dt(e["created_at"]),
        } for e in c["loyalty_ledger"]],
        "loyalty_points_balance": balance,
        "loyalty_tier": tier_from_balance(balance),
        "lifetime_spend_cents": c["lifetime_spend_cents"],
    })
    return out


def ser_product(p):
    out = common_out(p)
    out.update({
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "unit_price_cents": p["unit_price_cents"],
        "stock_qty": p["stock_qty"],
        "is_active": p["is_active"],
        "is_special_order_eligible": p["is_special_order_eligible"],
    })
    return out


def ser_license(l):
    out = common_out(l)
    out.update({
        "customer_id": l["customer_id"],
        "license_type": l["license_type"],
        "state_code": l["state_code"],
        "valid_from": serialize_dt(l["valid_from"]),
        "valid_to": serialize_dt(l["valid_to"]),
        "price_cents": l["price_cents"],
        "status": license_status(l),
        "is_voided": l["is_voided"],
        "issued_by_user_id": l["issued_by_user_id"],
    })
    return out


def license_status(l):
    if l["is_voided"]:
        return "VOID"
    n = now()
    if n < l["valid_from"]:
        return "SCHEDULED"
    if l["valid_from"] <= n < l["valid_to"]:
        return "ACTIVE"
    return "EXPIRED"


def tank_state(t):
    n = now()
    total = 0
    for b in t["batches"]:
        delta = (n - b["delivered_at"]).total_seconds()
        age_days = max(0, math.floor(delta / 86400))
        dead = (b["initial_count"] * t["mortality_rate_bps_per_day"] * age_days) // 10000
        survivors = max(0, b["initial_count"] - dead)
        total += survivors
    available = max(0, total - t["sold_count"])
    threshold = (t["capacity_units"] + 9) // 10  # ceil(capacity * 0.10)
    if available == 0:
        status = "EMPTY"
    elif available < threshold:
        status = "LOW"
    else:
        status = "HEALTHY"
    return available, threshold, status


def ser_tank(t):
    out = common_out(t)
    available, threshold, status = tank_state(t)
    out.update({
        "name": t["name"],
        "species": t["species"],
        "capacity_units": t["capacity_units"],
        "mortality_rate_bps_per_day": t["mortality_rate_bps_per_day"],
        "batches": [{
            "batch_id": b["batch_id"],
            "initial_count": b["initial_count"],
            "delivered_at": serialize_dt(b["delivered_at"]),
            "created_at": serialize_dt(b["created_at"]),
        } for b in t["batches"]],
        "sold_count": t["sold_count"],
        "available_count": available,
        "low_stock_threshold": threshold,
        "status": status,
    })
    return out


def ser_guide(gd):
    out = common_out(gd)
    out.update({
        "name": gd["name"],
        "guide_license_no": gd["guide_license_no"],
        "half_day_rate_cents": gd["half_day_rate_cents"],
        "full_day_rate_cents": gd["full_day_rate_cents"],
        "per_extra_angler_cents": gd["per_extra_angler_cents"],
        "max_party_size": gd["max_party_size"],
        "fuel_surcharge_cents": gd["fuel_surcharge_cents"],
        "status": gd["status"],
    })
    return out


def ser_venue(v):
    out = common_out(v)
    out.update({
        "name": v["name"],
        "water_type": v["water_type"],
        "daily_permit_cents": v["daily_permit_cents"],
    })
    return out


def ser_booking(bk):
    out = common_out(bk)
    out.update({
        "customer_id": bk["customer_id"],
        "guide_id": bk["guide_id"],
        "venue_id": bk["venue_id"],
        "trip_type": bk["trip_type"],
        "party_size": bk["party_size"],
        "start_at": serialize_dt(bk["start_at"]),
        "end_at": serialize_dt(bk["end_at"]),
        "add_equipment_rental": bk["add_equipment_rental"],
        "status": bk["status"],
        "season_at_quote": bk["season_at_quote"],
        "provisional_total_cents": bk["provisional_total_cents"],
        "deposit_cents": bk["deposit_cents"],
        "final_total_cents": bk["final_total_cents"],
        "points_awarded": bk["points_awarded"],
        "cancel_reason": bk["cancel_reason"],
    })
    return out


def entry_scores(e, bag_limit):
    accepted = [w for w in e["weigh_ins"] if w["accepted"]]
    if not accepted:
        return 0, 0
    ordered = sorted(accepted, key=lambda w: (-w["weight_grams"], w["created_at"]))
    top = ordered[:bag_limit]
    bag = sum(w["weight_grams"] for w in top)
    big = max(w["weight_grams"] for w in accepted)
    return bag, big


def ser_tournament(t):
    out = common_out(t)
    entry_count = sum(1 for e in db.tournament_entries.values() if e["tournament_id"] == t["id"])
    out.update({
        "venue_id": t["venue_id"],
        "name": t["name"],
        "entry_fee_cents": t["entry_fee_cents"],
        "bag_limit": t["bag_limit"],
        "registration_open_at": serialize_dt(t["registration_open_at"]),
        "registration_close_at": serialize_dt(t["registration_close_at"]),
        "start_at": serialize_dt(t["start_at"]),
        "end_at": serialize_dt(t["end_at"]),
        "max_entries": t["max_entries"],
        "prize_points": t["prize_points"],
        "status": t["status"],
        "entry_count": entry_count,
        "winner_entry_id": t["winner_entry_id"],
    })
    return out


def ser_entry(e):
    out = common_out(e)
    t = db.tournaments.get(e["tournament_id"])
    bag_limit = t["bag_limit"] if t else 5
    bag, big = entry_scores(e, bag_limit)
    out.update({
        "tournament_id": e["tournament_id"],
        "customer_id": e["customer_id"],
        "status": e["status"],
        "entry_fee_paid_cents": e["entry_fee_paid_cents"],
        "weigh_ins": [{
            "weigh_in_id": w["weigh_in_id"],
            "species": w["species"],
            "weight_grams": w["weight_grams"],
            "accepted": w["accepted"],
            "created_at": serialize_dt(w["created_at"]),
        } for w in e["weigh_ins"]],
        "bag_weight_grams": bag,
        "big_fish_grams": big,
        "placement": e["placement"],
    })
    return out


def ser_service(s):
    out = common_out(s)
    out.update({
        "customer_id": s["customer_id"],
        "item_description": s["item_description"],
        "service_type": s["service_type"],
        "quoted_cents": s["quoted_cents"],
        "line_length_yards": s["line_length_yards"],
        "status": s["status"],
        "final_cents": s["final_cents"],
    })
    return out


def ser_special(s):
    out = common_out(s)
    out.update({
        "customer_id": s["customer_id"],
        "product_id": s["product_id"],
        "quantity": s["quantity"],
        "unit_price_cents": s["unit_price_cents"],
        "deposit_cents": s["deposit_cents"],
        "status": s["status"],
        "refund_cents": s["refund_cents"],
    })
    return out


def sale_totals(sale):
    subtotal = sum(l["line_total_cents"] for l in sale["lines"] if not l["refunded"])
    tax = q(Decimal(subtotal) * Decimal(TAX_BPS) / Decimal(10000))
    total = subtotal + tax
    return subtotal, tax, total


def ser_sale(s):
    out = common_out(s)
    subtotal, tax, total = sale_totals(s)
    out.update({
        "customer_id": s["customer_id"],
        "clerk_user_id": s["clerk_user_id"],
        "lines": [{
            "line_id": l["line_id"],
            "product_id": l["product_id"],
            "qty": l["qty"],
            "unit_price_cents": l["unit_price_cents"],
            "line_total_cents": l["line_total_cents"],
            "refunded": l["refunded"],
        } for l in s["lines"]],
        "status": s["status"],
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "total_cents": total,
        "points_provisional": s["points_provisional"],
        "points_final": s["points_final"],
    })
    return out


# =============================================================================
# Health
# =============================================================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# =============================================================================
# Logical clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    require_roles({"ShopManager"})
    b = body()
    to = req_str(b, "to_iso8601")
    db.clock = parse_dt(to)
    return ok({}, 200)


# =============================================================================
# Customers
# =============================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    b = body()
    name = req_str(b, "name")
    email = req_str(b, "email")
    state_code = req_str(b, "state_code")
    birth_date = req_str(b, "birth_date")
    parse_date(birth_date)
    c = common({
        "name": name,
        "email": email,
        "state_code": state_code,
        "birth_date": birth_date,
        "loyalty_ledger": [],
        "lifetime_spend_cents": 0,
    })
    db.customers[c["id"]] = c
    return ok(ser_customer(c), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "Guide", "TournamentDirector", "ShopManager"})
    c = get_or_404(db.customers, cid)
    if g.role == "Customer" and g.uid != cid:
        forbid()
    return ok(ser_customer(c), 200)


@app.route("/customers", methods=["GET"])
def list_customers():
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    state = request.args.get("state_code")

    def flt(r):
        return state is None or r["state_code"] == state

    return list_result(db.customers, ser_customer, flt)


@app.route("/customers/<cid>/licenses", methods=["GET"])
def list_customer_licenses(cid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    get_or_404(db.customers, cid)
    if g.role == "Customer" and g.uid != cid:
        forbid()
    status = request.args.get("status")

    def flt(r):
        if r["customer_id"] != cid:
            return False
        return status is None or license_status(r) == status

    return list_result(db.licenses, ser_license, flt)


@app.route("/customers/<cid>/service-orders", methods=["GET"])
def list_customer_service_orders(cid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    get_or_404(db.customers, cid)
    if g.role == "Customer" and g.uid != cid:
        forbid()
    status = request.args.get("status")

    def flt(r):
        if r["customer_id"] != cid:
            return False
        return status is None or r["status"] == status

    return list_result(db.service_orders, ser_service, flt)


@app.route("/customers/<cid>/sales", methods=["GET"])
def list_customer_sales(cid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    get_or_404(db.customers, cid)
    if g.role == "Customer" and g.uid != cid:
        forbid()
    status = request.args.get("status")

    def flt(r):
        if r["customer_id"] != cid:
            return False
        return status is None or r["status"] == status

    return list_result(db.sales, ser_sale, flt)


# =============================================================================
# Products
# =============================================================================
@app.route("/products", methods=["POST"])
def create_product():
    authenticate()
    require_roles({"ShopManager"})
    b = body()
    sku = req_str(b, "sku")
    name = req_str(b, "name")
    category = req_enum(b, "category", PRODUCT_CATEGORIES)
    unit_price = req_int(b, "unit_price_cents", 0)
    stock_qty = req_int(b, "stock_qty", 0)
    is_active = opt_bool(b, "is_active", True)
    is_soe = opt_bool(b, "is_special_order_eligible", False)
    for p in db.products.values():
        if p["sku"] == sku:
            raise err("ERR_INVALID_REQUEST", 400, "sku must be unique.")
    p = common({
        "sku": sku,
        "name": name,
        "category": category,
        "unit_price_cents": unit_price,
        "stock_qty": stock_qty,
        "is_active": is_active,
        "is_special_order_eligible": is_soe,
    })
    db.products[p["id"]] = p
    return ok(ser_product(p), 201)


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "Guide", "TournamentDirector", "ShopManager"})
    p = get_or_404(db.products, pid)
    return ok(ser_product(p), 200)


@app.route("/products", methods=["GET"])
def list_products():
    authenticate()
    require_roles({"Customer", "ShopClerk", "Guide", "TournamentDirector", "ShopManager"})
    category = request.args.get("category")
    is_active = request.args.get("is_active")

    def flt(r):
        if category is not None and r["category"] != category:
            return False
        if is_active is not None and r["is_active"] != (is_active.lower() == "true"):
            return False
        return True

    return list_result(db.products, ser_product, flt)


@app.route("/products/<pid>", methods=["PATCH"])
def update_product(pid):
    authenticate()
    require_roles({"ShopManager"})
    p = get_or_404(db.products, pid)
    b = body()
    changed = False
    if "unit_price_cents" in b and b["unit_price_cents"] is not None:
        p["unit_price_cents"] = req_int(b, "unit_price_cents", 0)
        changed = True
    if "stock_qty" in b and b["stock_qty"] is not None:
        p["stock_qty"] = req_int(b, "stock_qty", 0)
        changed = True
    if "is_active" in b and b["is_active"] is not None:
        p["is_active"] = req_bool(b, "is_active")
        changed = True
    if changed:
        touch(p)
    return ok(ser_product(p), 200)


# =============================================================================
# Fishing licenses
# =============================================================================
@app.route("/licenses", methods=["POST"])
def create_license():
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    b = body()
    customer_id = req_str(b, "customer_id")
    license_type = req_enum(b, "license_type", LICENSE_TYPES)
    state_code = req_str(b, "state_code")
    valid_from = parse_dt(req_str(b, "valid_from"))
    c = exists_or_404(db.customers, customer_id)

    # License compliance (priority 7) before referential uniqueness (priority 8)
    age = compute_age(c["birth_date"], now())
    if age < LICENSE_MIN_AGE[license_type]:
        raise err("ERR_LICENSE_AGE_RESTRICTION", 422, "Holder does not meet the minimum age.")
    if license_type in ("RESIDENT_ANNUAL", "SENIOR") and state_code != c["state_code"]:
        raise err("ERR_LICENSE_STATE_MISMATCH", 422, "License state does not match holder state.")

    for l in db.licenses.values():
        if l["customer_id"] == customer_id and l["license_type"] == license_type \
                and license_status(l) == "ACTIVE":
            raise err("ERR_DUPLICATE_LICENSE", 409, "Customer already holds an ACTIVE license of this type.")

    valid_to = valid_from + timedelta(days=LICENSE_DURATION_DAYS[license_type])
    l = common({
        "customer_id": customer_id,
        "license_type": license_type,
        "state_code": state_code,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "price_cents": LICENSE_PRICE_CENTS[license_type],
        "is_voided": False,
        "issued_by_user_id": g.uid,
    })
    db.licenses[l["id"]] = l
    return ok(ser_license(l), 201)


@app.route("/licenses/<lid>", methods=["GET"])
def get_license(lid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    l = get_or_404(db.licenses, lid)
    if g.role == "Customer" and g.uid != l["customer_id"]:
        forbid()
    return ok(ser_license(l), 200)


@app.route("/licenses/<lid>/void", methods=["POST"])
def void_license(lid):
    authenticate()
    require_roles({"ShopManager"})
    l = get_or_404(db.licenses, lid)
    if l["is_voided"]:
        raise err("ERR_INVALID_STATE", 409, "License is already VOID.")
    l["is_voided"] = True
    touch(l)
    return ok(ser_license(l), 200)


# =============================================================================
# Bait tanks
# =============================================================================
@app.route("/bait-tanks", methods=["POST"])
def create_tank():
    authenticate()
    require_roles({"ShopManager"})
    b = body()
    name = req_str(b, "name")
    species = req_enum(b, "species", BAIT_SPECIES)
    capacity = req_int(b, "capacity_units", 1)
    mortality = req_int(b, "mortality_rate_bps_per_day", 0)
    t = common({
        "name": name,
        "species": species,
        "capacity_units": capacity,
        "mortality_rate_bps_per_day": mortality,
        "batches": [],
        "sold_count": 0,
    })
    db.bait_tanks[t["id"]] = t
    return ok(ser_tank(t), 201)


@app.route("/bait-tanks/<tid>", methods=["GET"])
def get_tank(tid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    t = get_or_404(db.bait_tanks, tid)
    return ok(ser_tank(t), 200)


@app.route("/bait-tanks", methods=["GET"])
def list_tanks():
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    species = request.args.get("species")

    def flt(r):
        return species is None or r["species"] == species

    return list_result(db.bait_tanks, ser_tank, flt)


@app.route("/bait-tanks/<tid>/batches", methods=["POST"])
def deliver_batch(tid):
    authenticate()
    require_roles({"ShopManager"})
    b = body()
    initial_count = req_int(b, "initial_count", 1)
    expected_version = req_int(b, "expected_bait_tank_version")
    delivered_at = parse_dt(b["delivered_at"]) if b.get("delivered_at") is not None else now()
    t = get_or_404(db.bait_tanks, tid)
    # OCC (priority 5)
    if expected_version != t["version"]:
        raise err("ERR_STALE_VERSION", 412, "expected_bait_tank_version does not match tank version.")
    # Capacity (priority 10)
    available, _, _ = tank_state(t)
    if available + initial_count > t["capacity_units"]:
        raise err("ERR_TANK_CAPACITY_EXCEEDED", 409, "Delivery would exceed tank capacity.")
    t["batches"].append({
        "batch_id": str(uuid.uuid4()),
        "initial_count": initial_count,
        "delivered_at": delivered_at,
        "created_at": now(),
    })
    touch(t)
    return ok(ser_tank(t), 201)


@app.route("/bait-tanks/<tid>/dispense", methods=["POST"])
def dispense_bait(tid):
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    b = body()
    qty = req_int(b, "qty", 1)
    t = get_or_404(db.bait_tanks, tid)
    available, _, _ = tank_state(t)
    if qty > available:
        raise err("ERR_INSUFFICIENT_BAIT", 409, "Dispense quantity exceeds available bait.")
    t["sold_count"] += qty
    touch(t)
    return ok(ser_tank(t), 200)


@app.route("/bait-tanks/<tid>/returns", methods=["POST"])
def return_bait(tid):
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    b = body()
    qty = req_int(b, "qty", 1)
    t = get_or_404(db.bait_tanks, tid)
    t["sold_count"] = max(0, t["sold_count"] - qty)
    touch(t)
    return ok(ser_tank(t), 200)


# =============================================================================
# Guides
# =============================================================================
@app.route("/guides", methods=["POST"])
def create_guide():
    authenticate()
    require_roles({"ShopManager"})
    b = body()
    guide = common({
        "name": req_str(b, "name"),
        "guide_license_no": req_str(b, "guide_license_no"),
        "half_day_rate_cents": req_int(b, "half_day_rate_cents", 0),
        "full_day_rate_cents": req_int(b, "full_day_rate_cents", 0),
        "per_extra_angler_cents": req_int(b, "per_extra_angler_cents", 0),
        "max_party_size": req_int(b, "max_party_size", 1),
        "fuel_surcharge_cents": opt_int(b, "fuel_surcharge_cents", 0, 0),
        "status": "AVAILABLE",
    })
    db.guides[guide["id"]] = guide
    return ok(ser_guide(guide), 201)


@app.route("/guides/<gid>", methods=["GET"])
def get_guide(gid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "Guide", "ShopManager"})
    guide = get_or_404(db.guides, gid)
    if g.role == "Guide" and g.uid != gid:
        forbid()
    return ok(ser_guide(guide), 200)


@app.route("/guides", methods=["GET"])
def list_guides():
    authenticate()
    require_roles({"Customer", "ShopClerk", "Guide", "ShopManager"})
    status = request.args.get("status")

    def flt(r):
        return status is None or r["status"] == status

    return list_result(db.guides, ser_guide, flt)


@app.route("/guides/<gid>", methods=["PATCH"])
def update_guide(gid):
    authenticate()
    require_roles({"Guide", "ShopManager"})
    guide = get_or_404(db.guides, gid)
    if g.role == "Guide" and g.uid != gid:
        forbid()
    b = body()
    changed = False
    if "status" in b and b["status"] is not None:
        guide["status"] = req_enum(b, "status", {"AVAILABLE", "SUSPENDED"})
        changed = True
    for fld in ("half_day_rate_cents", "full_day_rate_cents", "per_extra_angler_cents", "fuel_surcharge_cents"):
        if fld in b and b[fld] is not None:
            guide[fld] = req_int(b, fld, 0)
            changed = True
    if "max_party_size" in b and b["max_party_size"] is not None:
        guide["max_party_size"] = req_int(b, "max_party_size", 1)
        changed = True
    if changed:
        touch(guide)
    return ok(ser_guide(guide), 200)


# =============================================================================
# Venues
# =============================================================================
@app.route("/venues", methods=["POST"])
def create_venue():
    authenticate()
    require_roles({"ShopManager"})
    b = body()
    v = common({
        "name": req_str(b, "name"),
        "water_type": req_enum(b, "water_type", WATER_TYPES),
        "daily_permit_cents": opt_int(b, "daily_permit_cents", 0, 0),
    })
    db.venues[v["id"]] = v
    return ok(ser_venue(v), 201)


@app.route("/venues/<vid>", methods=["GET"])
def get_venue(vid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "TournamentDirector", "ShopManager"})
    v = get_or_404(db.venues, vid)
    return ok(ser_venue(v), 200)


@app.route("/venues", methods=["GET"])
def list_venues():
    authenticate()
    require_roles({"Customer", "ShopClerk", "TournamentDirector", "ShopManager"})
    water_type = request.args.get("water_type")

    def flt(r):
        return water_type is None or r["water_type"] == water_type

    return list_result(db.venues, ser_venue, flt)


# =============================================================================
# Charter bookings
# =============================================================================
def charter_components(bk, guide):
    base = guide["full_day_rate_cents"] if bk["trip_type"] == "FULL_DAY" else guide["half_day_rate_cents"]
    extra = max(0, bk["party_size"] - CHARTER_INCLUDED_ANGLERS) * guide["per_extra_angler_cents"]
    equip = EQUIPMENT_RENTAL_PER_ANGLER_CENTS * bk["party_size"] if bk["add_equipment_rental"] else 0
    return base + extra + equip


@app.route("/charter-bookings", methods=["POST"])
def create_booking():
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    b = body()
    customer_id = req_str(b, "customer_id")
    guide_id = req_str(b, "guide_id")
    venue_id = req_str(b, "venue_id")
    trip_type = req_enum(b, "trip_type", TRIP_TYPES)
    party_size = req_int(b, "party_size", 1)
    start_at = parse_dt(req_str(b, "start_at"))
    end_at = parse_dt(req_str(b, "end_at"))
    add_equipment = opt_bool(b, "add_equipment_rental", False)
    if g.role == "Customer" and g.uid != customer_id:
        forbid()
    exists_or_404(db.customers, customer_id)
    exists_or_404(db.guides, guide_id)
    exists_or_404(db.venues, venue_id)
    bk = common({
        "customer_id": customer_id,
        "guide_id": guide_id,
        "venue_id": venue_id,
        "trip_type": trip_type,
        "party_size": party_size,
        "start_at": start_at,
        "end_at": end_at,
        "add_equipment_rental": add_equipment,
        "status": "REQUESTED",
        "season_at_quote": None,
        "provisional_total_cents": None,
        "deposit_cents": None,
        "final_total_cents": None,
        "points_awarded": None,
        "cancel_reason": None,
    })
    db.charter_bookings[bk["id"]] = bk
    return ok(ser_booking(bk), 201)


@app.route("/charter-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "Guide", "ShopManager"})
    bk = get_or_404(db.charter_bookings, bid)
    if g.role == "Customer" and g.uid != bk["customer_id"]:
        forbid()
    if g.role == "Guide" and g.uid != bk["guide_id"]:
        forbid()
    return ok(ser_booking(bk), 200)


@app.route("/charter-bookings", methods=["GET"])
def list_bookings():
    authenticate()
    require_roles({"Customer", "ShopClerk", "Guide", "ShopManager"})
    customer_id = request.args.get("customer_id")
    guide_id = request.args.get("guide_id")
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")

    def flt(r):
        if customer_id is not None and r["customer_id"] != customer_id:
            return False
        if guide_id is not None and r["guide_id"] != guide_id:
            return False
        if venue_id is not None and r["venue_id"] != venue_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    return list_result(db.charter_bookings, ser_booking, flt)


CHARTER_ACTION_ROLES = {
    "QUOTE": {"ShopClerk", "ShopManager"},
    "CONFIRM": {"Customer", "ShopManager"},
    "RESCHEDULE": {"Customer", "ShopManager"},
    "COMPLETE": {"Guide", "ShopManager"},
    "CANCEL": {"Customer", "ShopManager"},
}


@app.route("/charter-bookings/<bid>/transition", methods=["POST"])
def booking_transition(bid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "Guide", "ShopManager"})
    b = body()
    action = req_enum(b, "action", set(CHARTER_ACTION_ROLES.keys()))
    if g.role not in CHARTER_ACTION_ROLES[action]:
        forbid()
    bk = get_or_404(db.charter_bookings, bid)
    # ownership
    if g.role == "Customer" and g.uid != bk["customer_id"]:
        forbid()
    if g.role == "Guide" and g.uid != bk["guide_id"]:
        forbid()

    guide = db.guides[bk["guide_id"]]
    customer = db.customers[bk["customer_id"]]
    status = bk["status"]

    if action == "QUOTE":
        if status != "REQUESTED":
            raise err("ERR_INVALID_STATE", 409, "Booking is not in REQUESTED state.")
        if bk["party_size"] > guide["max_party_size"]:
            raise err("ERR_PARTY_TOO_LARGE", 409, "Party size exceeds guide maximum.")
        comp = charter_components(bk, guide)
        season = "PEAK" if now().month in PEAK_MONTHS else "OFF"
        mult = SEASONAL_SURCHARGE_MULT if now().month in PEAK_MONTHS else Decimal("1.00")
        prov = mult_round(comp, mult)
        deposit = mult_round(prov, DEPOSIT_PCT)
        bk["season_at_quote"] = season
        bk["provisional_total_cents"] = prov
        bk["deposit_cents"] = deposit
        bk["status"] = "QUOTED"
        touch(bk)

    elif action == "CONFIRM":
        if status != "QUOTED":
            raise err("ERR_INVALID_STATE", 409, "Booking is not in QUOTED state.")
        if guide["status"] != "AVAILABLE":
            raise err("ERR_GUIDE_SUSPENDED", 409, "Guide is suspended.")
        for other in db.charter_bookings.values():
            if other["id"] == bk["id"]:
                continue
            if other["guide_id"] != bk["guide_id"]:
                continue
            if other["status"] not in ("CONFIRMED", "COMPLETED"):
                continue
            a_start = bk["start_at"] - CHARTER_BUFFER
            a_end = bk["end_at"] + CHARTER_BUFFER
            o_start = other["start_at"] - CHARTER_BUFFER
            o_end = other["end_at"] + CHARTER_BUFFER
            if a_start < o_end and o_start < a_end:
                raise err("ERR_GUIDE_UNAVAILABLE", 409, "Guide has an overlapping booking.")
        bk["status"] = "CONFIRMED"
        touch(bk)

    elif action == "RESCHEDULE":
        if status not in ("QUOTED", "CONFIRMED"):
            raise err("ERR_INVALID_STATE", 409, "Booking cannot be rescheduled from its current state.")
        new_start = parse_dt(req_str(b, "start_at"))
        new_end = parse_dt(req_str(b, "end_at"))
        bk["start_at"] = new_start
        bk["end_at"] = new_end
        if "trip_type" in b and b["trip_type"] is not None:
            bk["trip_type"] = req_enum(b, "trip_type", TRIP_TYPES)
        if "party_size" in b and b["party_size"] is not None:
            bk["party_size"] = req_int(b, "party_size", 1)
        bk["provisional_total_cents"] = None
        bk["deposit_cents"] = None
        bk["season_at_quote"] = None
        bk["status"] = "REQUESTED"
        touch(bk)

    elif action == "COMPLETE":
        if status != "CONFIRMED":
            raise err("ERR_INVALID_STATE", 409, "Booking is not in CONFIRMED state.")
        tier = customer_tier(customer)
        comp = charter_components(bk, guide)
        mult = SEASONAL_SURCHARGE_MULT if bk["start_at"].month in PEAK_MONTHS else Decimal("1.00")
        subtotal = mult_round(comp, mult)
        discount = mult_round(subtotal, TIER_DISCOUNT_PCT[tier])
        final_total = subtotal - discount + guide["fuel_surcharge_cents"]
        points = q(Decimal(final_total) / Decimal(100) * TIER_MULTIPLIER[tier])
        bk["final_total_cents"] = final_total
        bk["points_awarded"] = points
        bk["status"] = "COMPLETED"
        touch(bk)
        add_ledger(customer, points, "CHARTER_COMPLETE", "CharterBooking", bk["id"])
        customer["lifetime_spend_cents"] += final_total

    elif action == "CANCEL":
        if status not in ("REQUESTED", "QUOTED", "CONFIRMED"):
            raise err("ERR_INVALID_STATE", 409, "Booking cannot be cancelled from its current state.")
        bk["cancel_reason"] = opt_str(b, "cancel_reason", None)
        bk["status"] = "CANCELLED"
        touch(bk)

    return ok(ser_booking(bk), 200)


# =============================================================================
# Tournaments
# =============================================================================
@app.route("/tournaments", methods=["POST"])
def create_tournament():
    authenticate()
    require_roles({"TournamentDirector", "ShopManager"})
    b = body()
    venue_id = req_str(b, "venue_id")
    name = req_str(b, "name")
    entry_fee = req_int(b, "entry_fee_cents", 0)
    reg_open = parse_dt(req_str(b, "registration_open_at"))
    reg_close = parse_dt(req_str(b, "registration_close_at"))
    start_at = parse_dt(req_str(b, "start_at"))
    end_at = parse_dt(req_str(b, "end_at"))
    max_entries = req_int(b, "max_entries", 1)
    prize_points = req_int(b, "prize_points", 0)
    bag_limit = opt_int(b, "bag_limit", 5, 1)
    exists_or_404(db.venues, venue_id)
    # venue occupancy (temporal): overlap with non-cancelled tournament at same venue
    for other in db.tournaments.values():
        if other["venue_id"] != venue_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        if start_at < other["end_at"] and other["start_at"] < end_at:
            raise err("ERR_VENUE_DOUBLE_BOOKED", 409, "Venue is already booked for this window.")
    t = common({
        "venue_id": venue_id,
        "name": name,
        "entry_fee_cents": entry_fee,
        "bag_limit": bag_limit,
        "registration_open_at": reg_open,
        "registration_close_at": reg_close,
        "start_at": start_at,
        "end_at": end_at,
        "max_entries": max_entries,
        "prize_points": prize_points,
        "status": "SCHEDULED",
        "winner_entry_id": None,
    })
    db.tournaments[t["id"]] = t
    return ok(ser_tournament(t), 201)


@app.route("/tournaments/<tid>", methods=["GET"])
def get_tournament(tid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "TournamentDirector", "ShopManager"})
    t = get_or_404(db.tournaments, tid)
    return ok(ser_tournament(t), 200)


@app.route("/tournaments", methods=["GET"])
def list_tournaments():
    authenticate()
    require_roles({"Customer", "ShopClerk", "TournamentDirector", "ShopManager"})
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")

    def flt(r):
        if venue_id is not None and r["venue_id"] != venue_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    return list_result(db.tournaments, ser_tournament, flt)


TOURNAMENT_ACTIONS = {"OPEN", "START", "FINALIZE", "CANCEL"}


@app.route("/tournaments/<tid>/transition", methods=["POST"])
def tournament_transition(tid):
    authenticate()
    require_roles({"TournamentDirector", "ShopManager"})
    b = body()
    action = req_enum(b, "action", TOURNAMENT_ACTIONS)
    t = get_or_404(db.tournaments, tid)
    status = t["status"]

    if action == "OPEN":
        if status != "SCHEDULED":
            raise err("ERR_INVALID_STATE", 409, "Tournament is not SCHEDULED.")
        t["status"] = "REGISTRATION_OPEN"
        touch(t)
    elif action == "START":
        if status != "REGISTRATION_OPEN":
            raise err("ERR_INVALID_STATE", 409, "Tournament is not REGISTRATION_OPEN.")
        t["status"] = "IN_PROGRESS"
        touch(t)
    elif action == "FINALIZE":
        if status != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", 409, "Tournament is not IN_PROGRESS.")
        finalize_tournament(t)
    elif action == "CANCEL":
        if status not in ("SCHEDULED", "REGISTRATION_OPEN", "IN_PROGRESS"):
            raise err("ERR_INVALID_STATE", 409, "Tournament cannot be cancelled from its current state.")
        t["status"] = "CANCELLED"
        touch(t)

    return ok(ser_tournament(t), 200)


def finalize_tournament(t):
    bag_limit = t["bag_limit"]
    entries = [e for e in db.tournament_entries.values() if e["tournament_id"] == t["id"]]
    ranked = []
    for e in entries:
        accepted = [w for w in e["weigh_ins"] if w["accepted"]]
        if not accepted:
            continue
        ordered = sorted(accepted, key=lambda w: (-w["weight_grams"], w["created_at"]))
        top = ordered[:bag_limit]
        bag = sum(w["weight_grams"] for w in top)
        if bag <= 0:
            continue
        last_bag_created = max(w["created_at"] for w in top)
        ranked.append((e, bag, last_bag_created))
    ranked.sort(key=lambda x: (-x[1], x[2], x[0]["created_at"], x[0]["_seq"]))

    t["status"] = "FINALIZED"
    winner_entry = None
    for idx, (e, bag, _last) in enumerate(ranked):
        e["placement"] = idx + 1
        e["status"] = "PLACED"
        touch(e)
        if idx == 0:
            winner_entry = e
    if winner_entry is not None:
        t["winner_entry_id"] = winner_entry["id"]
        winner_customer = db.customers[winner_entry["customer_id"]]
        add_ledger(winner_customer, t["prize_points"], "TOURNAMENT_PRIZE", "Tournament", t["id"])
    touch(t)


@app.route("/tournaments/<tid>/entries", methods=["POST"])
def register_entry(tid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    b = body()
    customer_id = req_str(b, "customer_id")
    if g.role == "Customer" and g.uid != customer_id:
        forbid()
    t = get_or_404(db.tournaments, tid)
    exists_or_404(db.customers, customer_id)
    # registration window
    if t["status"] != "REGISTRATION_OPEN" or now() >= t["registration_close_at"]:
        raise err("ERR_REGISTRATION_CLOSED", 409, "Registration is closed.")
    # duplicate
    for e in db.tournament_entries.values():
        if e["tournament_id"] == tid and e["customer_id"] == customer_id:
            raise err("ERR_DUPLICATE_ENTRY", 409, "Customer already registered in this tournament.")
    # capacity
    count = sum(1 for e in db.tournament_entries.values() if e["tournament_id"] == tid)
    if count >= t["max_entries"]:
        raise err("ERR_MAX_ENTRIES_REACHED", 409, "Tournament is at maximum entries.")
    e = common({
        "tournament_id": tid,
        "customer_id": customer_id,
        "status": "REGISTERED",
        "entry_fee_paid_cents": t["entry_fee_cents"],
        "weigh_ins": [],
        "placement": None,
    })
    db.tournament_entries[e["id"]] = e
    return ok(ser_entry(e), 201)


# =============================================================================
# Tournament entries
# =============================================================================
@app.route("/tournament-entries/<eid>", methods=["GET"])
def get_entry(eid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "TournamentDirector", "ShopManager"})
    e = get_or_404(db.tournament_entries, eid)
    if g.role == "Customer" and g.uid != e["customer_id"]:
        forbid()
    return ok(ser_entry(e), 200)


@app.route("/tournament-entries", methods=["GET"])
def list_entries():
    authenticate()
    require_roles({"Customer", "ShopClerk", "TournamentDirector", "ShopManager"})
    tournament_id = request.args.get("tournament_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")

    def flt(r):
        if tournament_id is not None and r["tournament_id"] != tournament_id:
            return False
        if customer_id is not None and r["customer_id"] != customer_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    return list_result(db.tournament_entries, ser_entry, flt)


@app.route("/tournament-entries/<eid>/weigh-ins", methods=["POST"])
def add_weigh_in(eid):
    authenticate()
    require_roles({"TournamentDirector", "ShopManager"})
    b = body()
    species = req_str(b, "species")
    weight_grams = req_int(b, "weight_grams", 1)  # must be positive
    e = get_or_404(db.tournament_entries, eid)
    t = db.tournaments.get(e["tournament_id"])
    if t is None or t["status"] != "IN_PROGRESS":
        raise err("ERR_TOURNAMENT_NOT_IN_PROGRESS", 409, "Parent tournament is not IN_PROGRESS.")
    e["weigh_ins"].append({
        "weigh_in_id": str(uuid.uuid4()),
        "species": species,
        "weight_grams": weight_grams,
        "accepted": True,
        "created_at": now(),
    })
    if e["status"] == "REGISTERED":
        e["status"] = "WEIGHED"
    touch(e)
    return ok(ser_entry(e), 201)


# =============================================================================
# Service orders
# =============================================================================
@app.route("/service-orders", methods=["POST"])
def create_service_order():
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    b = body()
    customer_id = req_str(b, "customer_id")
    item_description = req_str(b, "item_description")
    service_type = req_enum(b, "service_type", SERVICE_TYPES)
    quoted_cents = req_int(b, "quoted_cents", 0)
    line_length = opt_int(b, "line_length_yards", None, 1)
    exists_or_404(db.customers, customer_id)
    s = common({
        "customer_id": customer_id,
        "item_description": item_description,
        "service_type": service_type,
        "quoted_cents": quoted_cents,
        "line_length_yards": line_length,
        "status": "RECEIVED",
        "final_cents": None,
    })
    db.service_orders[s["id"]] = s
    return ok(ser_service(s), 201)


@app.route("/service-orders/<sid>", methods=["GET"])
def get_service_order(sid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    s = get_or_404(db.service_orders, sid)
    if g.role == "Customer" and g.uid != s["customer_id"]:
        forbid()
    return ok(ser_service(s), 200)


SERVICE_ACTIONS = {"START", "AWAIT_PARTS", "RESUME", "READY", "PICKUP", "CANCEL"}


@app.route("/service-orders/<sid>/transition", methods=["POST"])
def service_transition(sid):
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    b = body()
    action = req_enum(b, "action", SERVICE_ACTIONS)
    s = get_or_404(db.service_orders, sid)
    status = s["status"]

    if action == "START":
        if status != "RECEIVED":
            raise err("ERR_INVALID_STATE", 409, "Service order is not RECEIVED.")
        s["status"] = "IN_PROGRESS"
    elif action == "AWAIT_PARTS":
        if status != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", 409, "Service order is not IN_PROGRESS.")
        s["status"] = "AWAITING_PARTS"
    elif action == "RESUME":
        if status != "AWAITING_PARTS":
            raise err("ERR_INVALID_STATE", 409, "Service order is not AWAITING_PARTS.")
        s["status"] = "IN_PROGRESS"
    elif action == "READY":
        if status != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", 409, "Service order is not IN_PROGRESS.")
        s["status"] = "READY"
    elif action == "PICKUP":
        if status != "READY":
            raise err("ERR_INVALID_STATE", 409, "Service order is not READY.")
        s["final_cents"] = s["quoted_cents"]
        s["status"] = "PICKED_UP"
        touch(s)
        customer = db.customers[s["customer_id"]]
        pts = q(Decimal(s["final_cents"]) / Decimal(100))
        add_ledger(customer, pts, "SERVICE_PICKUP", "ServiceOrder", s["id"])
        return ok(ser_service(s), 200)
    elif action == "CANCEL":
        if status not in ("RECEIVED", "IN_PROGRESS", "AWAITING_PARTS"):
            raise err("ERR_INVALID_STATE", 409, "Service order cannot be cancelled from its current state.")
        s["status"] = "CANCELLED"

    touch(s)
    return ok(ser_service(s), 200)


# =============================================================================
# Special orders
# =============================================================================
@app.route("/special-orders", methods=["POST"])
def create_special_order():
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    b = body()
    customer_id = req_str(b, "customer_id")
    product_id = req_str(b, "product_id")
    quantity = req_int(b, "quantity", 1)
    if g.role == "Customer" and g.uid != customer_id:
        forbid()
    exists_or_404(db.customers, customer_id)
    p = exists_or_404(db.products, product_id)
    if not p["is_active"]:
        raise err("ERR_PRODUCT_INACTIVE", 409, "Product is inactive.")
    if not p["is_special_order_eligible"]:
        raise err("ERR_NOT_SPECIAL_ORDER_ELIGIBLE", 409, "Product is not special-order eligible.")
    unit_price = p["unit_price_cents"]
    deposit = q(Decimal(unit_price) * Decimal(quantity) * SPECIAL_ORDER_DEPOSIT_PCT)
    s = common({
        "customer_id": customer_id,
        "product_id": product_id,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "deposit_cents": deposit,
        "status": "REQUESTED",
        "refund_cents": None,
    })
    db.special_orders[s["id"]] = s
    return ok(ser_special(s), 201)


@app.route("/special-orders/<sid>", methods=["GET"])
def get_special_order(sid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    s = get_or_404(db.special_orders, sid)
    if g.role == "Customer" and g.uid != s["customer_id"]:
        forbid()
    return ok(ser_special(s), 200)


@app.route("/special-orders", methods=["GET"])
def list_special_orders():
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    customer_id = request.args.get("customer_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")

    def flt(r):
        if customer_id is not None and r["customer_id"] != customer_id:
            return False
        if product_id is not None and r["product_id"] != product_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    return list_result(db.special_orders, ser_special, flt)


SPECIAL_ACTIONS = {"ORDER", "ARRIVE", "FULFILL", "CANCEL"}


@app.route("/special-orders/<sid>/transition", methods=["POST"])
def special_transition(sid):
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    b = body()
    action = req_enum(b, "action", SPECIAL_ACTIONS)
    s = get_or_404(db.special_orders, sid)
    status = s["status"]
    p = db.products.get(s["product_id"])

    if action == "ORDER":
        if status != "REQUESTED":
            raise err("ERR_INVALID_STATE", 409, "Special order is not REQUESTED.")
        if p is None or not p["is_active"]:
            raise err("ERR_PRODUCT_INACTIVE", 409, "Product is inactive.")
        s["status"] = "ORDERED"
        touch(s)
    elif action == "ARRIVE":
        if status != "ORDERED":
            raise err("ERR_INVALID_STATE", 409, "Special order is not ORDERED.")
        s["status"] = "ARRIVED"
        touch(s)
    elif action == "FULFILL":
        if status != "ARRIVED":
            raise err("ERR_INVALID_STATE", 409, "Special order is not ARRIVED.")
        s["status"] = "FULFILLED"
        touch(s)
        customer = db.customers[s["customer_id"]]
        pts = q(Decimal(s["unit_price_cents"] * s["quantity"]) / Decimal(100))
        add_ledger(customer, pts, "SPECIAL_ORDER_FULFILL", "SpecialOrder", s["id"])
    elif action == "CANCEL":
        if status not in ("REQUESTED", "ORDERED"):
            raise err("ERR_INVALID_STATE", 409, "Special order cannot be cancelled from its current state.")
        deposit = s["deposit_cents"]
        if status == "REQUESTED":
            refund = deposit
        else:
            restock_fee = q(Decimal(deposit) * RESTOCK_FEE_PCT)
            refund = deposit - restock_fee
        s["refund_cents"] = refund
        s["status"] = "CANCELLED"
        touch(s)

    return ok(ser_special(s), 200)


# =============================================================================
# Sales
# =============================================================================
@app.route("/sales", methods=["POST"])
def create_sale():
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    b = body()
    customer_id = req_str(b, "customer_id")
    exists_or_404(db.customers, customer_id)
    s = common({
        "customer_id": customer_id,
        "clerk_user_id": g.uid,
        "lines": [],
        "status": "OPEN",
        "points_provisional": None,
        "points_final": None,
    })
    db.sales[s["id"]] = s
    return ok(ser_sale(s), 201)


@app.route("/sales/<sid>", methods=["GET"])
def get_sale(sid):
    authenticate()
    require_roles({"Customer", "ShopClerk", "ShopManager"})
    s = get_or_404(db.sales, sid)
    if g.role == "Customer" and g.uid != s["customer_id"]:
        forbid()
    return ok(ser_sale(s), 200)


@app.route("/sales/<sid>/lines", methods=["POST"])
def add_sale_line(sid):
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    b = body()
    product_id = req_str(b, "product_id")
    qty = req_int(b, "qty", 1)
    s = get_or_404(db.sales, sid)
    p = exists_or_404(db.products, product_id)
    if s["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", 409, "Sale is not OPEN.")
    if not p["is_active"]:
        raise err("ERR_PRODUCT_INACTIVE", 409, "Product is inactive.")
    s["lines"].append({
        "line_id": str(uuid.uuid4()),
        "product_id": product_id,
        "qty": qty,
        "unit_price_cents": p["unit_price_cents"],
        "line_total_cents": p["unit_price_cents"] * qty,
        "refunded": False,
    })
    touch(s)
    return ok(ser_sale(s), 200)


def base_points(sale):
    total = 0
    for l in sale["lines"]:
        if l["refunded"]:
            continue
        total += q(Decimal(l["line_total_cents"]) / Decimal(100))
    return total


SALE_ACTION_ROLES = {
    "COMPLETE": {"ShopClerk", "ShopManager"},
    "SETTLE": {"ShopClerk", "ShopManager"},
    "REFUND": {"ShopManager"},
    "VOID": {"ShopManager"},
}


@app.route("/sales/<sid>/transition", methods=["POST"])
def sale_transition(sid):
    authenticate()
    require_roles({"ShopClerk", "ShopManager"})
    b = body()
    action = req_enum(b, "action", set(SALE_ACTION_ROLES.keys()))
    if g.role not in SALE_ACTION_ROLES[action]:
        forbid()
    s = get_or_404(db.sales, sid)
    status = s["status"]
    customer = db.customers[s["customer_id"]]

    if action == "COMPLETE":
        if status != "OPEN":
            raise err("ERR_INVALID_STATE", 409, "Sale is not OPEN.")
        if not s["lines"]:
            raise err("ERR_EMPTY_SALE", 409, "Sale has no lines.")
        remaining = {}
        for l in s["lines"]:
            p = db.products.get(l["product_id"])
            if p is None:
                raise err("ERR_NOT_FOUND", 404, "Product not found.")
            if l["product_id"] not in remaining:
                remaining[l["product_id"]] = p["stock_qty"]
            if remaining[l["product_id"]] < l["qty"]:
                raise err("ERR_INSUFFICIENT_STOCK", 409, "Insufficient stock for a sale line.")
            remaining[l["product_id"]] -= l["qty"]
        touched_products = set()
        for l in s["lines"]:
            p = db.products[l["product_id"]]
            p["stock_qty"] -= l["qty"]
            touched_products.add(l["product_id"])
        for pid in touched_products:
            touch(db.products[pid])
        tier = customer_tier(customer)
        bp = base_points(s)
        points_prov = q(Decimal(bp) * TIER_MULTIPLIER[tier])
        s["points_provisional"] = points_prov
        s["status"] = "COMPLETED"
        touch(s)
        _, _, total = sale_totals(s)
        add_ledger(customer, points_prov, "SALE_COMPLETE", "Sale", s["id"])
        customer["lifetime_spend_cents"] += total

    elif action == "SETTLE":
        if status != "COMPLETED":
            raise err("ERR_INVALID_STATE", 409, "Sale is not COMPLETED.")
        tier = customer_tier(customer)
        bp = base_points(s)
        tier_adjusted = q(Decimal(bp) * TIER_MULTIPLIER[tier])
        if now().month in PEAK_MONTHS:
            bonus = q(Decimal(bp) * TIER_MULTIPLIER[tier] * LOYALTY_SEASONAL_BONUS_PCT)
        else:
            bonus = 0
        points_final = tier_adjusted + bonus
        s["points_final"] = points_final
        s["status"] = "SETTLED"
        touch(s)
        delta = points_final - s["points_provisional"]
        add_ledger(customer, delta, "SALE_SETTLE_ADJUST", "Sale", s["id"])

    elif action == "REFUND":
        if status != "COMPLETED":
            raise err("ERR_INVALID_STATE", 409, "Sale is not COMPLETED.")
        _, _, total = sale_totals(s)
        touched_products = set()
        for l in s["lines"]:
            p = db.products.get(l["product_id"])
            if p is not None:
                p["stock_qty"] += l["qty"]
                touched_products.add(l["product_id"])
            l["refunded"] = True
        for pid in touched_products:
            touch(db.products[pid])
        s["status"] = "REFUNDED"
        touch(s)
        add_ledger(customer, -s["points_provisional"], "SALE_REFUND", "Sale", s["id"])
        customer["lifetime_spend_cents"] -= total

    elif action == "VOID":
        if status != "OPEN":
            raise err("ERR_INVALID_STATE", 409, "Sale is not OPEN.")
        s["status"] = "VOIDED"
        touch(s)

    return ok(ser_sale(s), 200)


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
