import os
import json
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, g

app = Flask(__name__)

# =====================================================================
# Constants
# =====================================================================
KNOWN_ROLES = {"Customer", "Merchandiser", "FulfillmentOps", "PlatformAdmin"}

CONCENTRATIONS = {"EDT", "EDP", "PARFUM", "COLOGNE"}
PRODUCT_KINDS = {"SINGLE", "BUNDLE", "DISCOVERY_SET"}
NOTE_FAMILIES = {"CITRUS", "FLORAL", "WOODY", "ORIENTAL", "FOUGERE", "GOURMAND"}
NOTE_LEVELS = {"TOP", "HEART", "BASE"}
VARIANT_KINDS = {"FULL_BOTTLE", "DECANT", "SAMPLE"}
SUB_TIERS = {"BASIC", "PREMIUM"}
RETURN_CONDITIONS = {"SEALED", "OPENED"}

# order_pricing
DISCOUNT_TIER_1_MIN_CENTS = 10000
DISCOUNT_TIER_2_MIN_CENTS = 30000
DISCOUNT_TIER_1_RATE = Decimal("0.05")
DISCOUNT_TIER_2_RATE = Decimal("0.10")
FREE_SHIP_THRESHOLD_CENTS = 7500
SHIPPING_FLAT_CENTS = 595

# tiering
SILVER_MIN_CENTS = 50000
GOLD_MIN_CENTS = 200000
TIER_MULT = {"BRONZE": Decimal("1.0"), "SILVER": Decimal("1.25"), "GOLD": Decimal("1.5")}

# returns
RESTOCK_FEE_ESTIMATE_CENTS = 500
OPENED_RESTOCK_PCT = Decimal("0.20")

# allocation
ALLOCATION_BUFFER_SECONDS = 24 * 3600

CLOCK_DEFAULT_ISO = "2026-07-01T00:00:00Z"


# =====================================================================
# In-memory store
# =====================================================================
class Store:
    def __init__(self):
        self.customers = {}
        self.products = {}
        self.variants = {}
        self.orders = {}
        self.order_lines = {}
        self.subscriptions = {}
        self.shipments = {}
        self.allocation_windows = {}
        self.allocation_claims = {}
        self.returns = {}
        self.loyalty_txns = {}
        self.seq = 0
        self.clock = parse_iso(CLOCK_DEFAULT_ISO)

    def next_seq(self):
        self.seq += 1
        return self.seq


db = None  # initialized after helpers are defined


# =====================================================================
# Errors
# =====================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# =====================================================================
# Time helpers
# =====================================================================
def parse_iso(s):
    if isinstance(s, datetime):
        dt = s
    else:
        if not isinstance(s, str):
            raise ValueError("not a datetime string")
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def try_parse_iso(s):
    try:
        return parse_iso(s)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime")


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def canonical_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_one_month(dt):
    month = dt.month + 1
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    # clamp day
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=dt.tzinfo)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=dt.tzinfo)
    last_day = (nxt - timedelta(days=1)).day
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def rhu(dec_value):
    """Round-half-up a Decimal to an integer."""
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =====================================================================
# Response envelope
# =====================================================================
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(pagination=None):
    meta = {
        "api_request_id": _req_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def respond(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": make_meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return app.response_class(
        response=json.dumps(body),
        status=status,
        mimetype="application/json",
    )


def respond_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return app.response_class(
        response=json.dumps(body),
        status=err.http_status,
        mimetype="application/json",
    )


@app.errorhandler(ApiError)
def handle_api_error(err):
    return respond_error(err)


@app.errorhandler(404)
def handle_404(e):
    return respond_error(ApiError("ERR_INVALID_REQUEST", 400, "unknown route")), 400


@app.errorhandler(405)
def handle_405(e):
    return respond_error(ApiError("ERR_INVALID_REQUEST", 400, "method not allowed")), 400


# =====================================================================
# Auth / RBAC
# =====================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    g.user_id = uid
    g.role = role
    return uid, role


def authorize(allowed_roles):
    if g.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")


# =====================================================================
# Body / param helpers
# =====================================================================
def get_body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid JSON body")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "body must be an object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} is required")
    return v


def require_int(body, field, min_value=None):
    v = body.get(field)
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be an integer")
    if min_value is not None and v < min_value:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be >= {min_value}")
    return v


def require_enum(body, field, choices):
    v = body.get(field)
    if v not in choices:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be one of {sorted(choices)}")
    return v


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit out of range")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate_list(items):
    """items: already-sorted list of serialized dicts."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination


def sorted_by_seq(entities):
    return sorted(entities, key=lambda e: e["_seq"])


# =====================================================================
# Common fields
# =====================================================================
def new_common(full=True):
    ts = now_iso()
    base = {"id": str(uuid.uuid4()), "created_at": ts, "_seq": db.next_seq()}
    if full:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def pub(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# =====================================================================
# Serializers with derived fields
# =====================================================================
def serialize_customer(c):
    return pub(c)


def serialize_variant(v):
    d = pub(v)
    d["status"] = "AVAILABLE" if v["on_hand_qty"] > 0 else "OUT_OF_STOCK"
    return d


def window_status(w):
    ws = parse_iso(w["window_start"])
    we = parse_iso(w["window_end"])
    now = db.clock
    if now < ws:
        return "SCHEDULED"
    if ws <= now <= we:
        return "OPEN"
    return "CLOSED"


def serialize_window(w):
    d = pub(w)
    d["status"] = window_status(w)
    return d


def fee_effective_at(sub, t):
    fed = sub.get("fee_effective_date")
    if fed is not None and sub.get("pending_fee_cents") is not None:
        if t >= parse_iso(fed):
            return sub["pending_fee_cents"]
    return sub["monthly_fee_cents"]


def projected_charge(sub):
    cpe = parse_iso(sub["current_period_end"])
    return fee_effective_at(sub, cpe)


def serialize_subscription(s):
    d = pub(s)
    d["projected_next_charge_cents"] = projected_charge(s)
    return d


# =====================================================================
# Lookup helpers
# =====================================================================
def get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "customer not found")
    return c


def get_product(pid):
    p = db.products.get(pid)
    if p is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
    return p


def get_variant(vid):
    v = db.variants.get(vid)
    if v is None:
        raise ApiError("ERR_VARIANT_NOT_FOUND", 404, "variant not found")
    return v


def get_order(oid):
    o = db.orders.get(oid)
    if o is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "order not found")
    return o


def get_subscription(sid):
    s = db.subscriptions.get(sid)
    if s is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "subscription not found")
    return s


def get_shipment(sid):
    s = db.shipments.get(sid)
    if s is None:
        raise ApiError("ERR_SHIPMENT_NOT_FOUND", 404, "shipment not found")
    return s


def get_window(wid):
    w = db.allocation_windows.get(wid)
    if w is None:
        raise ApiError("ERR_ALLOCATION_WINDOW_NOT_FOUND", 404, "allocation window not found")
    return w


def get_return(rid):
    r = db.returns.get(rid)
    if r is None:
        raise ApiError("ERR_RETURN_NOT_FOUND", 404, "return request not found")
    return r


def order_lines_of(order_id):
    return [l for l in db.order_lines.values() if l["order_id"] == order_id]


def recompute_tier(customer):
    ls = customer["lifetime_spend_cents"]
    if ls >= GOLD_MIN_CENTS:
        customer["tier"] = "GOLD"
    elif ls >= SILVER_MIN_CENTS:
        customer["tier"] = "SILVER"
    else:
        customer["tier"] = "BRONZE"


def add_loyalty_txn(customer_id, delta, reason, source_type, source_id):
    txn = new_common(full=False)
    txn.update({
        "customer_id": customer_id,
        "points_delta": delta,
        "reason": reason,
        "source_type": source_type,
        "source_id": source_id,
    })
    db.loyalty_txns[txn["id"]] = txn
    return txn


# =====================================================================
# Customers
# =====================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    authenticate()
    authorize({"PlatformAdmin"})
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    for c in db.customers.values():
        if c["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", 400, "email already exists")
    c = new_common()
    c.update({
        "email": email,
        "full_name": full_name,
        "status": "ACTIVE",
        "loyalty_points_balance": 0,
        "lifetime_spend_cents": 0,
        "tier": "BRONZE",
    })
    db.customers[c["id"]] = c
    return respond(serialize_customer(c), "object", 201)


@app.route("/customers/<cid>", methods=["GET"])
def fetch_customer(cid):
    authenticate()
    authorize(KNOWN_ROLES)
    c = get_customer(cid)
    return respond(serialize_customer(c), "object", 200)


@app.route("/customers/<cid>/suspend", methods=["POST"])
def suspend_customer(cid):
    authenticate()
    authorize({"PlatformAdmin"})
    c = get_customer(cid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "customer not ACTIVE")
    c["status"] = "SUSPENDED"
    touch(c)
    return respond(serialize_customer(c), "object", 200)


@app.route("/customers/<cid>/allocation-claims", methods=["GET"])
def list_customer_claims(cid):
    authenticate()
    authorize(KNOWN_ROLES)
    get_customer(cid)
    items = sorted_by_seq([c for c in db.allocation_claims.values() if c["customer_id"] == cid])
    page, pg = paginate_list([pub(c) for c in items])
    return respond(page, "array", 200, pg)


@app.route("/customers/<cid>/loyalty-transactions", methods=["GET"])
def list_customer_loyalty(cid):
    authenticate()
    authorize(KNOWN_ROLES)
    get_customer(cid)
    items = sorted_by_seq([t for t in db.loyalty_txns.values() if t["customer_id"] == cid])
    page, pg = paginate_list([pub(t) for t in items])
    return respond(page, "array", 200, pg)


# =====================================================================
# Products / Variants
# =====================================================================
@app.route("/products", methods=["POST"])
def create_product():
    authenticate()
    authorize({"Merchandiser", "PlatformAdmin"})
    body = get_body()
    name = require_str(body, "name")
    brand = require_str(body, "brand")
    concentration = require_enum(body, "concentration", CONCENTRATIONS)

    kind = body.get("kind", "SINGLE")
    if kind not in PRODUCT_KINDS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid kind")

    notes = body.get("notes", [])
    if not isinstance(notes, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "notes must be an array")
    for n in notes:
        if not isinstance(n, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "note must be an object")
        if not isinstance(n.get("name"), str) or n.get("name") == "":
            raise ApiError("ERR_INVALID_REQUEST", 400, "note.name required")
        if n.get("family") not in NOTE_FAMILIES:
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid note.family")
        if n.get("level") not in NOTE_LEVELS:
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid note.level")

    is_exclusive = body.get("is_exclusive", False)
    if not isinstance(is_exclusive, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "is_exclusive must be boolean")

    per_customer_limit = body.get("per_customer_limit", None)
    if per_customer_limit is not None and not is_int(per_customer_limit):
        raise ApiError("ERR_INVALID_REQUEST", 400, "per_customer_limit must be integer or null")

    component_variant_ids = body.get("component_variant_ids", [])
    if not isinstance(component_variant_ids, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "component_variant_ids must be an array")

    hygiene_returnable = body.get("hygiene_returnable", False)
    if not isinstance(hygiene_returnable, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "hygiene_returnable must be boolean")

    p = new_common()
    p.update({
        "name": name,
        "brand": brand,
        "kind": kind,
        "concentration": concentration,
        "notes": notes,
        "is_exclusive": is_exclusive,
        "per_customer_limit": per_customer_limit,
        "component_variant_ids": component_variant_ids,
        "hygiene_returnable": hygiene_returnable,
    })
    db.products[p["id"]] = p
    return respond(pub(p), "object", 201)


@app.route("/products/<pid>", methods=["GET"])
def fetch_product(pid):
    authenticate()
    authorize(KNOWN_ROLES)
    p = get_product(pid)
    return respond(pub(p), "object", 200)


@app.route("/products", methods=["GET"])
def list_products():
    authenticate()
    authorize(KNOWN_ROLES)
    note = request.args.get("note")
    family = request.args.get("family")
    kind = request.args.get("kind")

    result = []
    for p in db.products.values():
        if kind is not None and p["kind"] != kind:
            continue
        if note is not None and not any(n.get("name") == note for n in p["notes"]):
            continue
        if family is not None and not any(n.get("family") == family for n in p["notes"]):
            continue
        result.append(p)
    items = sorted_by_seq(result)
    page, pg = paginate_list([pub(p) for p in items])
    return respond(page, "array", 200, pg)


@app.route("/products/<pid>/variants", methods=["POST"])
def create_variant(pid):
    authenticate()
    authorize({"Merchandiser", "PlatformAdmin"})
    p = get_product(pid)
    body = get_body()
    kind = require_enum(body, "kind", VARIANT_KINDS)
    volume_ml = body.get("volume_ml")
    if not (is_int(volume_ml) or isinstance(volume_ml, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "volume_ml must be a number")
    unit_price_cents = require_int(body, "unit_price_cents", min_value=0)
    on_hand_qty = require_int(body, "on_hand_qty", min_value=0)

    v = new_common()
    v.update({
        "product_id": p["id"],
        "kind": kind,
        "volume_ml": volume_ml,
        "unit_price_cents": unit_price_cents,
        "on_hand_qty": on_hand_qty,
        "reserved_qty": 0,
        "status": "AVAILABLE" if on_hand_qty > 0 else "OUT_OF_STOCK",
    })
    db.variants[v["id"]] = v
    return respond(serialize_variant(v), "object", 201)


@app.route("/products/<pid>/variants", methods=["GET"])
def list_product_variants(pid):
    authenticate()
    authorize(KNOWN_ROLES)
    get_product(pid)
    items = sorted_by_seq([v for v in db.variants.values() if v["product_id"] == pid])
    page, pg = paginate_list([serialize_variant(v) for v in items])
    return respond(page, "array", 200, pg)


@app.route("/variants/<vid>", methods=["GET"])
def fetch_variant(vid):
    authenticate()
    authorize(KNOWN_ROLES)
    v = get_variant(vid)
    return respond(serialize_variant(v), "object", 200)


@app.route("/variants/<vid>/order-lines", methods=["GET"])
def list_variant_order_lines(vid):
    authenticate()
    authorize({"Merchandiser", "FulfillmentOps", "PlatformAdmin"})
    get_variant(vid)
    items = sorted_by_seq([l for l in db.order_lines.values() if l["variant_id"] == vid])
    page, pg = paginate_list([pub(l) for l in items])
    return respond(page, "array", 200, pg)


# =====================================================================
# Allocation windows / claims
# =====================================================================
def _overlap_or_within_buffer(new_s, new_e, ex_s, ex_e):
    # OK only if a >=24h gap separates them; otherwise conflict.
    if (new_s - ex_e).total_seconds() >= ALLOCATION_BUFFER_SECONDS:
        return False
    if (ex_s - new_e).total_seconds() >= ALLOCATION_BUFFER_SECONDS:
        return False
    return True


@app.route("/products/<pid>/allocation-windows", methods=["POST"])
def create_allocation_window(pid):
    authenticate()
    authorize({"Merchandiser", "PlatformAdmin"})
    p = get_product(pid)
    body = get_body()
    ws_raw = require_str(body, "window_start")
    we_raw = require_str(body, "window_end")
    total_allocation = require_int(body, "total_allocation", min_value=1)
    per_customer_cap = require_int(body, "per_customer_cap", min_value=1)
    ws = try_parse_iso(ws_raw)
    we = try_parse_iso(we_raw)

    # temporal overlap / buffer check against existing windows of same product
    for ex in db.allocation_windows.values():
        if ex["product_id"] != pid:
            continue
        ex_s = parse_iso(ex["window_start"])
        ex_e = parse_iso(ex["window_end"])
        if _overlap_or_within_buffer(ws, we, ex_s, ex_e):
            raise ApiError("ERR_ALLOCATION_WINDOW_OVERLAP", 409, "window overlaps or within buffer")

    w = new_common()
    w.update({
        "product_id": p["id"],
        "window_start": ws_raw,
        "window_end": we_raw,
        "total_allocation": total_allocation,
        "per_customer_cap": per_customer_cap,
        "claimed_units": 0,
    })
    db.allocation_windows[w["id"]] = w
    return respond(serialize_window(w), "object", 201)


@app.route("/products/<pid>/allocation-windows", methods=["GET"])
def list_product_windows(pid):
    authenticate()
    authorize(KNOWN_ROLES)
    get_product(pid)
    items = sorted_by_seq([w for w in db.allocation_windows.values() if w["product_id"] == pid])
    page, pg = paginate_list([serialize_window(w) for w in items])
    return respond(page, "array", 200, pg)


@app.route("/allocation-windows/<wid>", methods=["GET"])
def fetch_window(wid):
    authenticate()
    authorize(KNOWN_ROLES)
    w = get_window(wid)
    return respond(serialize_window(w), "object", 200)


@app.route("/allocation-windows/<wid>/claims", methods=["POST"])
def create_claim(wid):
    authenticate()
    authorize({"Customer"})
    w = get_window(wid)  # existence: window (path)
    body = get_body()

    # existence: body FK customer_id (if provided)
    customer = None
    if "customer_id" in body and body.get("customer_id") is not None:
        customer = get_customer(body["customer_id"])

    product = db.products.get(w["product_id"])

    # referential (tier 6): product must be exclusive
    if product is not None and not product["is_exclusive"]:
        raise ApiError("ERR_PRODUCT_NOT_EXCLUSIVE", 422, "product not exclusive")

    # temporal (tier 7): window must be OPEN
    if window_status(w) != "OPEN":
        raise ApiError("ERR_ALLOCATION_WINDOW_NOT_OPEN", 409, "window not open")

    # capacity (tier 8): suspended
    if customer is not None and customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 403, "customer suspended")

    # capacity (tier 8): allocation exhausted (needs units)
    units = body.get("units")
    if is_int(units) and units >= 1:
        remaining = w["total_allocation"] - w["claimed_units"]
        if units > remaining:
            raise ApiError("ERR_ALLOCATION_EXHAUSTED", 409, "allocation exhausted")

        # per-customer ceilings
        if customer is not None:
            in_window = sum(
                c["units"] for c in db.allocation_claims.values()
                if c["window_id"] == w["id"] and c["customer_id"] == customer["id"]
            )
            if in_window + units > w["per_customer_cap"]:
                raise ApiError("ERR_PER_CUSTOMER_LIMIT", 409, "per-window cap exceeded")
            if product is not None and product["per_customer_limit"] is not None:
                across = 0
                for c in db.allocation_claims.values():
                    cw = db.allocation_windows.get(c["window_id"])
                    if cw is not None and cw["product_id"] == product["id"] and c["customer_id"] == customer["id"]:
                        across += c["units"]
                if across + units > product["per_customer_limit"]:
                    raise ApiError("ERR_PER_CUSTOMER_LIMIT", 409, "product per-customer limit exceeded")

    # fiscal (tier 9): OCC stale version (only when provided)
    ewv = body.get("expected_window_version")
    if is_int(ewv):
        if ewv != w["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "stale window version")

    # generic body validation (tier 10)
    if customer is None:
        require_str(body, "customer_id")  # raises if missing/blank
        get_customer(body["customer_id"])
    units = require_int(body, "units", min_value=1)
    if not is_int(ewv):
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_window_version required")

    claim = new_common(full=False)
    claim.update({
        "window_id": w["id"],
        "customer_id": customer["id"],
        "units": units,
    })
    db.allocation_claims[claim["id"]] = claim
    w["claimed_units"] += units
    touch(w)
    return respond(pub(claim), "object", 201)


@app.route("/allocation-windows/<wid>/claims", methods=["GET"])
def list_window_claims(wid):
    authenticate()
    authorize(KNOWN_ROLES)
    get_window(wid)
    items = sorted_by_seq([c for c in db.allocation_claims.values() if c["window_id"] == wid])
    page, pg = paginate_list([pub(c) for c in items])
    return respond(page, "array", 200, pg)


# =====================================================================
# Subscriptions / shipments
# =====================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    authenticate()
    authorize({"Customer", "PlatformAdmin"})
    body = get_body()
    # existence of body FK first
    if "customer_id" in body and body.get("customer_id") is not None:
        get_customer(body["customer_id"])
    customer_id = require_str(body, "customer_id")
    customer = get_customer(customer_id)
    tier = require_enum(body, "tier", SUB_TIERS)
    monthly_fee_cents = require_int(body, "monthly_fee_cents", min_value=0)

    included_sample_credits = body.get("included_sample_credits", 0)
    if not is_int(included_sample_credits) or included_sample_credits < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "included_sample_credits must be a non-negative integer")

    pending_fee_cents = body.get("pending_fee_cents", None)
    if pending_fee_cents is not None and (not is_int(pending_fee_cents) or pending_fee_cents < 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "pending_fee_cents must be a non-negative integer or null")

    fee_effective_date = body.get("fee_effective_date", None)
    if fee_effective_date is not None:
        if not isinstance(fee_effective_date, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "fee_effective_date must be a string or null")
        try_parse_iso(fee_effective_date)

    period_start = db.clock
    current_period_end = add_one_month(period_start)

    s = new_common()
    s.update({
        "customer_id": customer["id"],
        "tier": tier,
        "monthly_fee_cents": monthly_fee_cents,
        "pending_fee_cents": pending_fee_cents,
        "fee_effective_date": fee_effective_date,
        "included_sample_credits": included_sample_credits,
        "status": "ACTIVE",
        "current_period_end": canonical_iso(current_period_end),
        "_period_start": canonical_iso(period_start),
    })
    db.subscriptions[s["id"]] = s
    return respond(serialize_subscription(s), "object", 201)


@app.route("/subscriptions/<sid>", methods=["GET"])
def fetch_subscription(sid):
    authenticate()
    authorize(KNOWN_ROLES)
    s = get_subscription(sid)
    return respond(serialize_subscription(s), "object", 200)


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    authenticate()
    authorize(KNOWN_ROLES)
    customer_id = request.args.get("customer_id")
    result = [s for s in db.subscriptions.values()
              if customer_id is None or s["customer_id"] == customer_id]
    items = sorted_by_seq(result)
    page, pg = paginate_list([serialize_subscription(s) for s in items])
    return respond(page, "array", 200, pg)


def _sub_transition(sid, from_states, to_state):
    s = get_subscription(sid)
    if s["status"] not in from_states:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid subscription state")
    s["status"] = to_state
    touch(s)
    return s


@app.route("/subscriptions/<sid>/pause", methods=["POST"])
def pause_subscription(sid):
    authenticate()
    authorize({"Customer", "PlatformAdmin"})
    s = _sub_transition(sid, {"ACTIVE"}, "PAUSED")
    return respond(serialize_subscription(s), "object", 200)


@app.route("/subscriptions/<sid>/resume", methods=["POST"])
def resume_subscription(sid):
    authenticate()
    authorize({"Customer", "PlatformAdmin"})
    s = _sub_transition(sid, {"PAUSED"}, "ACTIVE")
    return respond(serialize_subscription(s), "object", 200)


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    authenticate()
    authorize({"Customer", "PlatformAdmin"})
    s = _sub_transition(sid, {"ACTIVE", "PAUSED"}, "CANCELLED")
    return respond(serialize_subscription(s), "object", 200)


@app.route("/subscriptions/<sid>/shipments", methods=["POST"])
def create_shipment(sid):
    authenticate()
    authorize({"FulfillmentOps", "PlatformAdmin"})
    s = get_subscription(sid)
    body = get_body()

    # state gate (tier 4-ish): subscription must be ACTIVE
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "subscription not active")

    ps_raw = require_str(body, "period_start")
    pe_raw = require_str(body, "period_end")
    ps = try_parse_iso(ps_raw)
    pe = try_parse_iso(pe_raw)

    # temporal (tier 7): half-open overlap with existing shipments
    for ex in db.shipments.values():
        if ex["subscription_id"] != sid:
            continue
        ex_s = parse_iso(ex["period_start"])
        ex_e = parse_iso(ex["period_end"])
        if ps < ex_e and ex_s < pe:
            raise ApiError("ERR_SHIPMENT_PERIOD_OVERLAP", 409, "shipment period overlap")

    charge = fee_effective_at(s, ps)

    ship = new_common()
    ship.update({
        "subscription_id": s["id"],
        "period_start": ps_raw,
        "period_end": pe_raw,
        "charge_cents": charge,
        "status": "PENDING",
    })
    db.shipments[ship["id"]] = ship
    return respond(pub(ship), "object", 201)


@app.route("/subscriptions/<sid>/shipments", methods=["GET"])
def list_subscription_shipments(sid):
    authenticate()
    authorize(KNOWN_ROLES)
    get_subscription(sid)
    items = sorted_by_seq([sh for sh in db.shipments.values() if sh["subscription_id"] == sid])
    page, pg = paginate_list([pub(sh) for sh in items])
    return respond(page, "array", 200, pg)


@app.route("/shipments/<shid>", methods=["GET"])
def fetch_shipment(shid):
    authenticate()
    authorize(KNOWN_ROLES)
    sh = get_shipment(shid)
    return respond(pub(sh), "object", 200)


@app.route("/shipments/<shid>/fulfill", methods=["POST"])
def fulfill_shipment(shid):
    authenticate()
    authorize({"FulfillmentOps", "PlatformAdmin"})
    sh = get_shipment(shid)
    if sh["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "shipment not PENDING")
    sub = db.subscriptions.get(sh["subscription_id"])
    customer = db.customers.get(sub["customer_id"]) if sub else None

    sh["status"] = "FULFILLED"
    touch(sh)

    if customer is not None:
        mult = TIER_MULT[customer["tier"]]
        points = rhu(Decimal(sh["charge_cents"]) / Decimal(100) * mult)
        if points != 0:
            add_loyalty_txn(customer["id"], points, "EARN", "ORDER", sh["id"])
            customer["loyalty_points_balance"] += points
        customer["lifetime_spend_cents"] += sh["charge_cents"]
        recompute_tier(customer)
        touch(customer)

    return respond(pub(sh), "object", 200)


# =====================================================================
# Orders / lines
# =====================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    authenticate()
    authorize({"Customer", "PlatformAdmin"})
    body = get_body()
    if "customer_id" in body and body.get("customer_id") is not None:
        get_customer(body["customer_id"])
    customer_id = require_str(body, "customer_id")
    customer = get_customer(customer_id)

    o = new_common()
    o.update({
        "customer_id": customer["id"],
        "fulfillment_status": "CART",
        "payment_status": "UNPAID",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "loyalty_redeemed_cents": 0,
        "shipping_fee_cents": 0,
        "total_cents": 0,
        "_net_after_loyalty": 0,
    })
    db.orders[o["id"]] = o
    return respond(pub(o), "object", 201)


@app.route("/orders/<oid>", methods=["GET"])
def fetch_order(oid):
    authenticate()
    authorize(KNOWN_ROLES)
    o = get_order(oid)
    return respond(pub(o), "object", 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    authenticate()
    authorize(KNOWN_ROLES)
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    result = []
    for o in db.orders.values():
        if customer_id is not None and o["customer_id"] != customer_id:
            continue
        if status is not None and o["fulfillment_status"] != status:
            continue
        result.append(o)
    items = sorted_by_seq(result)
    page, pg = paginate_list([pub(o) for o in items])
    return respond(page, "array", 200, pg)


@app.route("/orders/<oid>/lines", methods=["POST"])
def add_order_line(oid):
    authenticate()
    authorize({"Customer", "PlatformAdmin"})
    o = get_order(oid)
    body = get_body()
    if o["fulfillment_status"] != "CART":
        raise ApiError("ERR_INVALID_STATE", 409, "order not in CART")
    if "variant_id" in body and body.get("variant_id") is not None:
        get_variant(body["variant_id"])
    variant_id = require_str(body, "variant_id")
    variant = get_variant(variant_id)
    quantity = require_int(body, "quantity", min_value=1)

    line = new_common()
    line.update({
        "order_id": o["id"],
        "variant_id": variant["id"],
        "quantity": quantity,
        "unit_price_cents": variant["unit_price_cents"],
        "line_total_cents": variant["unit_price_cents"] * quantity,
        "points_earned": 0,
        "status": "ACTIVE",
    })
    db.order_lines[line["id"]] = line
    return respond(pub(line), "object", 201)


@app.route("/orders/<oid>/lines", methods=["GET"])
def list_order_lines(oid):
    authenticate()
    authorize(KNOWN_ROLES)
    get_order(oid)
    items = sorted_by_seq([l for l in db.order_lines.values() if l["order_id"] == oid])
    page, pg = paginate_list([pub(l) for l in items])
    return respond(page, "array", 200, pg)


@app.route("/orders/<oid>/place", methods=["POST"])
def place_order(oid):
    authenticate()
    authorize({"Customer"})
    o = get_order(oid)
    # ownership
    if o["customer_id"] != g.user_id:
        raise ApiError("ERR_NOT_ORDER_OWNER", 403, "not order owner")
    body = get_body()
    # state
    if o["fulfillment_status"] != "CART":
        raise ApiError("ERR_INVALID_STATE", 409, "order not in CART")

    customer = db.customers.get(o["customer_id"])
    active_lines = [l for l in order_lines_of(o["id"]) if l["status"] == "ACTIVE"]

    # tier 8: suspended
    if customer is not None and customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 403, "customer suspended")
    # tier 8: empty order
    if len(active_lines) == 0:
        raise ApiError("ERR_EMPTY_ORDER", 422, "order has no active lines")
    # tier 8: insufficient stock (check all first)
    for l in active_lines:
        v = db.variants.get(l["variant_id"])
        if v is None or v["on_hand_qty"] < l["quantity"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409, "insufficient stock")

    # redeem points
    redeem_points = body.get("redeem_points", 0)
    if redeem_points is None:
        redeem_points = 0
    if not is_int(redeem_points) or redeem_points < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "redeem_points must be a non-negative integer")

    balance = customer["loyalty_points_balance"] if customer else 0
    # tier 9: insufficient points
    if redeem_points > balance:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 422, "insufficient loyalty points")

    # pricing
    subtotal = sum(l["line_total_cents"] for l in active_lines)
    if subtotal < DISCOUNT_TIER_1_MIN_CENTS:
        rate = Decimal("0")
    elif subtotal < DISCOUNT_TIER_2_MIN_CENTS:
        rate = DISCOUNT_TIER_1_RATE
    else:
        rate = DISCOUNT_TIER_2_RATE
    discount = rhu(Decimal(subtotal) * rate)
    net = subtotal - discount
    loyalty_redeemed = min(redeem_points, balance, net)
    net_after_loyalty = net - loyalty_redeemed
    shipping = 0 if net_after_loyalty >= FREE_SHIP_THRESHOLD_CENTS else SHIPPING_FLAT_CENTS
    total = net_after_loyalty + shipping

    # side effects: reserve inventory
    for l in active_lines:
        v = db.variants.get(l["variant_id"])
        v["on_hand_qty"] -= l["quantity"]
        v["reserved_qty"] += l["quantity"]
        v["status"] = "AVAILABLE" if v["on_hand_qty"] > 0 else "OUT_OF_STOCK"
        touch(v)

    o["subtotal_cents"] = subtotal
    o["discount_cents"] = discount
    o["loyalty_redeemed_cents"] = loyalty_redeemed
    o["shipping_fee_cents"] = shipping
    o["total_cents"] = total
    o["_net_after_loyalty"] = net_after_loyalty
    o["fulfillment_status"] = "PLACED"
    o["payment_status"] = "PAID"
    touch(o)

    if loyalty_redeemed > 0 and customer is not None:
        add_loyalty_txn(customer["id"], -loyalty_redeemed, "REDEEM", "ORDER", o["id"])
        customer["loyalty_points_balance"] -= loyalty_redeemed
        touch(customer)

    return respond(pub(o), "object", 200)


@app.route("/orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    authenticate()
    authorize({"FulfillmentOps", "PlatformAdmin"})
    o = get_order(oid)
    if o["fulfillment_status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", 409, "order not PLACED")
    customer = db.customers.get(o["customer_id"])
    active_lines = [l for l in order_lines_of(o["id"]) if l["status"] == "ACTIVE"]
    mult = TIER_MULT[customer["tier"]] if customer else Decimal("1.0")

    total_points = 0
    for l in active_lines:
        v = db.variants.get(l["variant_id"])
        if v is not None:
            v["reserved_qty"] -= l["quantity"]
            v["status"] = "AVAILABLE" if v["on_hand_qty"] > 0 else "OUT_OF_STOCK"
            touch(v)
        pts = rhu(Decimal(l["line_total_cents"]) / Decimal(100) * mult)
        l["points_earned"] = pts
        touch(l)
        total_points += pts

    o["fulfillment_status"] = "FULFILLED"
    touch(o)

    if customer is not None:
        if total_points != 0:
            add_loyalty_txn(customer["id"], total_points, "EARN", "ORDER", o["id"])
            customer["loyalty_points_balance"] += total_points
        customer["lifetime_spend_cents"] += o["_net_after_loyalty"]
        recompute_tier(customer)
        touch(customer)

    return respond(pub(o), "object", 200)


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    authenticate()
    authorize({"Customer", "FulfillmentOps", "PlatformAdmin"})
    o = get_order(oid)
    if g.role == "Customer" and o["customer_id"] != g.user_id:
        raise ApiError("ERR_NOT_ORDER_OWNER", 403, "not order owner")
    if o["fulfillment_status"] not in {"CART", "PLACED"}:
        raise ApiError("ERR_INVALID_STATE", 409, "order not cancellable")

    if o["fulfillment_status"] == "CART":
        o["fulfillment_status"] = "CANCELLED"
        touch(o)
        return respond(pub(o), "object", 200)

    # PLACED -> CANCELLED cascade
    customer = db.customers.get(o["customer_id"])
    active_lines = [l for l in order_lines_of(o["id"]) if l["status"] == "ACTIVE"]
    for l in active_lines:
        l["status"] = "CANCELLED"
        touch(l)
        v = db.variants.get(l["variant_id"])
        if v is not None:
            v["reserved_qty"] -= l["quantity"]
            v["on_hand_qty"] += l["quantity"]
            v["status"] = "AVAILABLE" if v["on_hand_qty"] > 0 else "OUT_OF_STOCK"
            touch(v)

    o["payment_status"] = "REFUNDED"
    o["fulfillment_status"] = "CANCELLED"
    touch(o)

    if o["loyalty_redeemed_cents"] > 0 and customer is not None:
        restore = o["loyalty_redeemed_cents"]
        add_loyalty_txn(customer["id"], restore, "REVERSAL", "ORDER", o["id"])
        customer["loyalty_points_balance"] += restore
        touch(customer)

    return respond(pub(o), "object", 200)


# =====================================================================
# Returns
# =====================================================================
@app.route("/returns", methods=["POST"])
def create_return():
    authenticate()
    authorize({"Customer"})
    body = get_body()
    # existence: order_id (body FK)
    if "order_id" in body and body.get("order_id") is not None:
        o = get_order(body["order_id"])
    else:
        raise ApiError("ERR_INVALID_REQUEST", 400, "order_id is required")

    # ownership
    if o["customer_id"] != g.user_id:
        raise ApiError("ERR_NOT_ORDER_OWNER", 403, "not order owner")

    # state gate: order must be FULFILLED or PARTIALLY_RETURNED
    if o["fulfillment_status"] not in {"FULFILLED", "PARTIALLY_RETURNED"}:
        raise ApiError("ERR_ORDER_NOT_FULFILLED", 409, "order not fulfilled")

    line_ids = body.get("line_ids")
    if not isinstance(line_ids, list) or len(line_ids) == 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "line_ids must be a non-empty array")
    condition = require_enum(body, "condition", RETURN_CONDITIONS)

    # hygiene (tier 5) takes precedence over line-membership (tier 6).
    # Evaluate over resolvable lines.
    if condition == "OPENED":
        for lid in line_ids:
            line = db.order_lines.get(lid)
            if line is None:
                continue
            variant = db.variants.get(line["variant_id"])
            product = db.products.get(variant["product_id"]) if variant else None
            if product is not None and not product["hygiene_returnable"]:
                raise ApiError("ERR_HYGIENE_NON_RETURNABLE", 422, "hygiene non-returnable")

    # referential (tier 6): every line belongs to order and is ACTIVE
    for lid in line_ids:
        line = db.order_lines.get(lid)
        if line is None or line["order_id"] != o["id"] or line["status"] != "ACTIVE":
            raise ApiError("ERR_LINE_NOT_IN_ORDER", 422, "line not in order or not active")

    returned_merch = sum(db.order_lines[lid]["line_total_cents"] for lid in line_ids)
    refund_estimate = returned_merch - RESTOCK_FEE_ESTIMATE_CENTS

    r = new_common()
    r.update({
        "order_id": o["id"],
        "line_ids": list(line_ids),
        "condition": condition,
        "refund_estimate_cents": refund_estimate,
        "final_refund_cents": 0,
        "status": "REQUESTED",
    })
    db.returns[r["id"]] = r
    return respond(pub(r), "object", 201)


@app.route("/returns/<rid>", methods=["GET"])
def fetch_return(rid):
    authenticate()
    authorize(KNOWN_ROLES)
    r = get_return(rid)
    return respond(pub(r), "object", 200)


@app.route("/returns", methods=["GET"])
def list_returns():
    authenticate()
    authorize(KNOWN_ROLES)
    order_id = request.args.get("order_id")
    result = [r for r in db.returns.values()
              if order_id is None or r["order_id"] == order_id]
    items = sorted_by_seq(result)
    page, pg = paginate_list([pub(r) for r in items])
    return respond(page, "array", 200, pg)


@app.route("/returns/<rid>/approve", methods=["POST"])
def approve_return(rid):
    authenticate()
    authorize({"FulfillmentOps", "PlatformAdmin"})
    r = get_return(rid)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "return not REQUESTED")

    o = db.orders.get(r["order_id"])
    customer = db.customers.get(o["customer_id"]) if o else None
    returned_lines = [db.order_lines[lid] for lid in r["line_ids"] if lid in db.order_lines]

    returned_merch = sum(l["line_total_cents"] for l in returned_lines)

    # final refund (condition-driven)
    if r["condition"] == "SEALED":
        final_refund = returned_merch
    else:  # OPENED on hygiene-returnable product (guaranteed by request-time check)
        final_refund = rhu(Decimal(returned_merch) * (Decimal(1) - OPENED_RESTOCK_PCT))
    r["final_refund_cents"] = final_refund
    r["status"] = "APPROVED"
    touch(r)

    # retire lines
    reversed_points = 0
    for l in returned_lines:
        l["status"] = "RETURNED"
        reversed_points += l["points_earned"]
        touch(l)

    # recompute order status dimensions
    remaining_active = [l for l in order_lines_of(o["id"]) if l["status"] == "ACTIVE"]
    if len(remaining_active) == 0:
        o["fulfillment_status"] = "RETURNED"
        o["payment_status"] = "REFUNDED"
    else:
        o["fulfillment_status"] = "PARTIALLY_RETURNED"
        o["payment_status"] = "PARTIALLY_REFUNDED"
    touch(o)

    # net contribution of returned lines for lifetime rollback (proportional to net_after_loyalty)
    subtotal = o["subtotal_cents"]
    if subtotal > 0:
        net_contribution = rhu(Decimal(o["_net_after_loyalty"]) * Decimal(returned_merch) / Decimal(subtotal))
    else:
        net_contribution = 0

    if customer is not None:
        if reversed_points != 0:
            add_loyalty_txn(customer["id"], -reversed_points, "REVERSAL", "RETURN", r["id"])
            customer["loyalty_points_balance"] -= reversed_points
        customer["lifetime_spend_cents"] -= net_contribution
        recompute_tier(customer)
        touch(customer)

    return respond(pub(r), "object", 200)


@app.route("/returns/<rid>/reject", methods=["POST"])
def reject_return(rid):
    authenticate()
    authorize({"FulfillmentOps", "PlatformAdmin"})
    r = get_return(rid)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "return not REQUESTED")
    r["status"] = "REJECTED"
    touch(r)
    return respond(pub(r), "object", 200)


# =====================================================================
# Logical clock
# =====================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    authorize({"PlatformAdmin"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    db.clock = try_parse_iso(to_iso)
    return respond({}, "object", 200)


# =====================================================================
# Boot
# =====================================================================
db = Store()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
