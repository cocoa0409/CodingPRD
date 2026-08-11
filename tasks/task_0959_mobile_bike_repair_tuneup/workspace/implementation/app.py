"""
Mobile Bike Repair & Tune-Up API (Task 0959)
Single-file Flask implementation. In-memory storage only; the process starts
with an empty store on every boot (tests build all state via the API surface).
Logical clock starts at exactly 2026-05-01T00:00:00Z and never falls back to
wall-clock time.
"""
import os
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD / PRD)
# ---------------------------------------------------------------------------
ROLES = {"PlatformAdmin", "Dispatcher", "Customer", "Mechanic"}

TAX_RATE = Decimal("0.08")
SURCHARGE_T1_MIN = 10000
SURCHARGE_T1_CENTS = 500
SURCHARGE_T2_MIN = 20000
SURCHARGE_T2_CENTS = 1200
DEFAULT_TRAVEL_BUFFER_MINUTES = 15
BATTERY_MIN_HEALTH_PCT = 70

ACCOUNT_KINDS = {"INDIVIDUAL", "FLEET", "APARTMENT"}
BIKE_TYPES = {"MECHANICAL", "EBIKE"}
TIER_CODES = {"BASIC", "STANDARD", "PREMIUM"}
MOVEMENT_REASONS = {"RECEIVE", "RETURN_TO_WAREHOUSE", "RESERVE", "RELEASE", "CONSUME"}
WORK_STATUSES = {"QUOTED", "DISPATCHED", "ON_SITE", "IN_SERVICE", "ON_HOLD_PARTS",
                 "COMPLETED", "CLOSED", "CANCELLED", "NO_SHOW"}
LIVE_WORK_STATUSES = {"QUOTED", "DISPATCHED", "ON_SITE", "IN_SERVICE", "ON_HOLD_PARTS"}
SUBSCRIPTION_STATUSES = {"ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED"}

# ---------------------------------------------------------------------------
# In-memory store (empty on every boot; nothing is seeded)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}

zones = {}
customers = {}
bikes = {}
mechanics = {}
vans = {}
parts = {}
truck_stock = {}          # keyed by (van_id, part_id)
stock_movements = {}
service_tiers = {}
subscriptions = {}
service_requests = {}
route_days = {}
route_stops = {}
invoices = {}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now():
    return CLOCK["now"]


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if not t:
        raise ValueError("empty")
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(value):
    """Round half-up to integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": fmt_ts(now())}


def respond(data, response_type="object", status=200, pagination=None):
    m = meta_base()
    if pagination:
        m.update(pagination)
    return jsonify({"meta": m, "response_type": response_type, "data": data}), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_generic(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error"},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unknown X-User-Role / X-User-ID headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role not permitted on this endpoint")


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body(allowed_fields=None):
    d = request.get_json(silent=True)
    if d is None:
        d = {}
    if not isinstance(d, dict):
        err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    if allowed_fields is not None:
        for k in d:
            if k not in allowed_fields:
                err("ERR_VALIDATION", 400, "Unknown field: %s" % k)
    return d


def v_int(d, key, required=True, default=None, minimum=None, maximum=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if isinstance(val, bool) or not isinstance(val, int):
        err("ERR_VALIDATION", 400, "%s must be an integer" % key)
    if minimum is not None and val < minimum:
        err("ERR_VALIDATION", 400, "%s below minimum" % key)
    if maximum is not None and val > maximum:
        err("ERR_VALIDATION", 400, "%s above maximum" % key)
    return val


def v_str(d, key, required=True, default=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if not isinstance(val, str) or val == "":
        err("ERR_VALIDATION", 400, "%s must be a non-empty string" % key)
    return val


def v_enum(d, key, allowed, required=True, default=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if not isinstance(val, str) or val not in allowed:
        err("ERR_VALIDATION", 400, "%s is not a valid value" % key)
    return val


def v_bool(d, key, required=True, default=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if not isinstance(val, bool):
        err("ERR_VALIDATION", 400, "%s must be a boolean" % key)
    return val


def v_datetime(d, key, required=True, default=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    try:
        parse_iso(val)
    except Exception:
        err("ERR_VALIDATION", 400, "%s must be a valid ISO 8601 datetime" % key)
    return val


def v_number(d, key, required=True, default=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        err("ERR_VALIDATION", 400, "%s must be a number" % key)
    return val


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def get_pagination():
    lim = request.args.get("limit")
    off = request.args.get("offset")
    if lim is None:
        limit = 10
    else:
        try:
            limit = int(lim)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 400, "limit out of range")
    if off is None:
        offset = 0
    else:
        try:
            offset = int(off)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", 400, "offset out of range")
    return limit, offset


def paginate_and_respond(items, serializer, sort_key=None):
    limit, offset = get_pagination()
    if sort_key is None:
        items = sorted(items, key=lambda x: (x["created_at"], x["_seq"]))
    else:
        items = sorted(items, key=sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pagination = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": has_more}
    return respond([serializer(x) for x in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Common record helpers
# ---------------------------------------------------------------------------
def new_common():
    ts = fmt_ts(now())
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def new_event():
    ts = fmt_ts(now())
    return {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next_seq()}


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = fmt_ts(now())


def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        err("ERR_NOT_FOUND", 404, "Resource not found")
    return rec


def clean(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def s_zone(z):
    return clean(z)


def s_customer(c):
    return clean(c)


def s_bike(b):
    return clean(b)


def s_mechanic(m):
    return clean(m)


def s_van(v):
    return clean(v)


def s_part(p):
    return clean(p)


def s_stock_item(it):
    return clean(it)


def s_movement(m):
    return clean(m)


def s_tier(t):
    return clean(t)


def s_subscription(s):
    d = clean(s)
    d["allowance_remaining"] = (s["included_tunes_per_period"]
                                - s["allowance_reserved"] - s["allowance_consumed"])
    d["settled_allowance_remaining"] = (s["included_tunes_per_period"]
                                        - s["allowance_consumed"])
    return d


def s_request(r):
    return clean(r)


def active_stop_count(day_id):
    return sum(1 for st in route_stops.values()
               if st["route_day_id"] == day_id and st["status"] in ("PLANNED", "ARRIVED"))


def s_route_day(d):
    out = clean(d)
    out["active_stop_count"] = active_stop_count(d["id"])
    return out


def s_stop(st):
    return clean(st)


def s_invoice(inv):
    return clean(inv)


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------
def route_surcharge(subtotal_cents):
    if subtotal_cents < SURCHARGE_T1_MIN:
        return 0
    if subtotal_cents < SURCHARGE_T2_MIN:
        return SURCHARGE_T1_CENTS
    return SURCHARGE_T2_CENTS


def compute_quote(req):
    """Provisional quote: assumes exactly included_minutes of labor, no parts.
    CALLBACK requests price callout and labor base at zero."""
    if req["request_kind"] == "CALLBACK":
        return 0
    tier = service_tiers[req["tier_id"]]
    zone = zones[req["zone_id"]]
    labor_net = tier["base_price_cents"]
    if req["covered_by_subscription"] and req["subscription_id"] in subscriptions:
        sub = subscriptions[req["subscription_id"]]
        labor_net -= rhu(Decimal(str(sub["discount_pct"])) * tier["base_price_cents"])
    subtotal = zone["base_callout_fee_cents"] + labor_net
    surcharge = route_surcharge(subtotal)
    tax = rhu(Decimal(subtotal + surcharge) * TAX_RATE)
    return subtotal + surcharge + tax


def outstanding_reserved(request_id):
    """Per (van_id, part_id) units still reserved for this request."""
    out = {}
    for m in stock_movements.values():
        if m["service_request_id"] != request_id:
            continue
        key = (m["van_id"], m["part_id"])
        if m["reason"] == "RESERVE":
            out[key] = out.get(key, 0) + m["quantity"]
        elif m["reason"] in ("RELEASE", "CONSUME"):
            out[key] = out.get(key, 0) - m["quantity"]
    return {k: v for k, v in out.items() if v > 0}


def consumed_parts(request_id):
    """Aggregate CONSUME movements by part, ordered by first consumption."""
    agg = {}
    order = {}
    for m in sorted(stock_movements.values(), key=lambda x: x["_seq"]):
        if m["service_request_id"] == request_id and m["reason"] == "CONSUME":
            if m["part_id"] not in agg:
                agg[m["part_id"]] = 0
                order[m["part_id"]] = m["_seq"]
            agg[m["part_id"]] += m["quantity"]
    return sorted(((pid, q) for pid, q in agg.items()), key=lambda t: order[t[0]])


def get_stock_item(van_id, part_id, create=False):
    key = (van_id, part_id)
    it = truck_stock.get(key)
    if it is None and create:
        it = new_common()
        it.update({"van_id": van_id, "part_id": part_id, "on_hand": 0, "reserved": 0})
        truck_stock[key] = it
    return it


def append_movement(van_id, part_id, request_id, quantity, delta, reason, note=None):
    m = new_event()
    m.update({
        "van_id": van_id,
        "part_id": part_id,
        "service_request_id": request_id,
        "quantity": quantity,
        "quantity_delta": delta,
        "reason": reason,
        "note": note,
    })
    stock_movements[m["id"]] = m
    return m


def active_stop_for_request(request_id):
    for st in route_stops.values():
        if st["service_request_id"] == request_id and st["status"] in ("PLANNED", "ARRIVED"):
            return st
    return None


def recompute_day_and_maybe_unlock(day):
    """Bump route day version after stop-count changes; auto-unlock a LOCKED
    day whose active stop count has fallen to zero (PRD §2.9)."""
    bump(day)
    if day["status"] == "LOCKED" and active_stop_count(day["id"]) == 0:
        day["status"] = "OPEN"


def check_window_shape(window_start, window_end):
    ws = parse_iso(window_start)
    we = parse_iso(window_end)
    dur = (we - ws).total_seconds()
    if dur < 30 * 60 or dur > 4 * 3600:
        err("ERR_INVALID_WINDOW", 422, "Window must be between 30 minutes and 4 hours")
    if ws < now():
        err("ERR_INVALID_WINDOW", 422, "window_start must not precede the current time")


def check_customer_overlap(customer_id, window_start, window_end, exclude_id=None):
    ws = parse_iso(window_start)
    we = parse_iso(window_end)
    for r in service_requests.values():
        if r["customer_id"] != customer_id:
            continue
        if r["id"] == exclude_id:
            continue
        if r["work_status"] not in LIVE_WORK_STATUSES:
            continue
        ews = parse_iso(r["window_start"])
        ewe = parse_iso(r["window_end"])
        # Closed intervals, no buffer: touching endpoints conflict.
        if ws <= ewe and ews <= we:
            err("ERR_CUSTOMER_WINDOW_OVERLAP", 409,
                "Window overlaps another live request of this customer")


def non_void_invoice_for(request_id):
    for inv in invoices.values():
        if inv["service_request_id"] == request_id and inv["status"] != "VOID":
            return inv
    return None


def create_fee_invoice(req, is_no_show):
    """Cancellation-fee / no-show invoice: callout + tax only, no surcharge."""
    zone = zones[req["zone_id"]]
    callout = zone["base_callout_fee_cents"]
    tax = rhu(Decimal(callout) * TAX_RATE)
    inv = new_common()
    inv.update({
        "service_request_id": req["id"],
        "status": "DRAFT",
        "callout_cents": callout,
        "labor_cents": 0,
        "parts_gross_cents": 0,
        "discount_cents": 0,
        "subtotal_cents": callout,
        "surcharge_cents": 0,
        "tax_cents": tax,
        "total_cents": callout + tax,
        "credit_applied_cents": 0,
        "amount_paid_cents": 0,
        "line_items": [],
        "is_no_show_fee": is_no_show,
    })
    invoices[inv["id"]] = inv
    return inv


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    d = get_body({"to_iso8601"})
    ts = v_datetime(d, "to_iso8601")
    CLOCK["now"] = parse_iso(ts)
    return respond({"current_utc": fmt_ts(CLOCK["now"])}, "object", 200)


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------
@app.route("/v1/zones", methods=["POST"])
def create_zone():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    d = get_body({"name", "base_callout_fee_cents", "active"})
    name = v_str(d, "name")
    fee = v_int(d, "base_callout_fee_cents", minimum=0)
    active = v_bool(d, "active", required=False, default=True)
    z = new_common()
    z.update({"name": name, "base_callout_fee_cents": fee, "active": active})
    zones[z["id"]] = z
    return respond(s_zone(z), "object", 201)


@app.route("/v1/zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    z = get_or_404(zones, zone_id)
    return respond(s_zone(z), "object", 200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@app.route("/v1/customers", methods=["POST"])
def create_customer():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "Dispatcher"})
    d = get_body({"name", "email", "account_kind", "phone"})
    name = v_str(d, "name")
    email = v_str(d, "email")
    kind = v_enum(d, "account_kind", ACCOUNT_KINDS)
    phone = v_str(d, "phone", required=False, default=None)
    for c in customers.values():
        if c["email"] == email:
            err("ERR_EMAIL_EXISTS", 409, "Customer email already exists")
    c = new_common()
    c.update({"name": name, "email": email, "account_kind": kind,
              "phone": phone, "account_credit_cents": 0})
    customers[c["id"]] = c
    return respond(s_customer(c), "object", 201)


@app.route("/v1/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    c = get_or_404(customers, customer_id)
    return respond(s_customer(c), "object", 200)


@app.route("/v1/customers/<customer_id>/bikes", methods=["GET"])
def list_customer_bikes(customer_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    get_or_404(customers, customer_id)
    items = [b for b in bikes.values() if b["customer_id"] == customer_id]
    return paginate_and_respond(items, s_bike)


@app.route("/v1/customers/<customer_id>/credit-adjustments", methods=["POST"])
def credit_adjustment(customer_id):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    c = get_or_404(customers, customer_id)
    d = get_body({"amount_cents", "reason"})
    amount = v_int(d, "amount_cents")
    v_str(d, "reason")
    if c["account_credit_cents"] + amount < 0:
        err("ERR_VALIDATION", 400, "Credit balance may not go below zero")
    c["account_credit_cents"] += amount
    bump(c)
    return respond(s_customer(c), "object", 201)


# ---------------------------------------------------------------------------
# Bikes
# ---------------------------------------------------------------------------
@app.route("/v1/bikes", methods=["POST"])
def create_bike():
    uid, role = authenticate()
    authorize(role, {"Customer", "Dispatcher"})
    d = get_body({"customer_id", "bike_type", "brand", "battery_wh",
                  "battery_certified", "battery_health_pct"})
    customer_id = v_str(d, "customer_id")
    bike_type = v_enum(d, "bike_type", BIKE_TYPES)
    brand = v_str(d, "brand", required=False, default=None)
    battery_wh = d.get("battery_wh")
    battery_certified = v_bool(d, "battery_certified", required=False, default=True)
    battery_health = v_int(d, "battery_health_pct", required=False, default=100,
                           minimum=0, maximum=100)
    if bike_type == "EBIKE":
        if battery_wh is None:
            err("ERR_VALIDATION", 400, "battery_wh is required for EBIKE")
        if isinstance(battery_wh, bool) or not isinstance(battery_wh, int):
            err("ERR_VALIDATION", 400, "battery_wh must be an integer")
    else:
        if battery_wh is not None:
            err("ERR_VALIDATION", 400, "battery_wh must be null for MECHANICAL")
    get_or_404(customers, customer_id)
    if role == "Customer" and uid != customer_id:
        err("ERR_FORBIDDEN", 403, "Customers may only register bikes for themselves")
    b = new_common()
    b.update({"customer_id": customer_id, "bike_type": bike_type, "brand": brand,
              "battery_wh": battery_wh if bike_type == "EBIKE" else None,
              "battery_certified": battery_certified,
              "battery_health_pct": battery_health})
    bikes[b["id"]] = b
    return respond(s_bike(b), "object", 201)


@app.route("/v1/bikes/<bike_id>", methods=["GET"])
def get_bike(bike_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    b = get_or_404(bikes, bike_id)
    return respond(s_bike(b), "object", 200)


# ---------------------------------------------------------------------------
# Mechanics
# ---------------------------------------------------------------------------
@app.route("/v1/mechanics", methods=["POST"])
def create_mechanic():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    d = get_body({"name", "ebike_certified", "home_zone_id"})
    name = v_str(d, "name")
    cert = v_bool(d, "ebike_certified")
    home_zone_id = v_str(d, "home_zone_id")
    get_or_404(zones, home_zone_id)
    m = new_common()
    m.update({"name": name, "ebike_certified": cert,
              "home_zone_id": home_zone_id, "status": "ACTIVE"})
    mechanics[m["id"]] = m
    return respond(s_mechanic(m), "object", 201)


@app.route("/v1/mechanics/<mechanic_id>", methods=["GET"])
def get_mechanic(mechanic_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    m = get_or_404(mechanics, mechanic_id)
    return respond(s_mechanic(m), "object", 200)


@app.route("/v1/mechanics", methods=["GET"])
def list_mechanics():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(mechanics.values())
    hz = request.args.get("home_zone_id")
    st = request.args.get("status")
    if hz is not None:
        items = [m for m in items if m["home_zone_id"] == hz]
    if st is not None:
        items = [m for m in items if m["status"] == st]
    return paginate_and_respond(items, s_mechanic)


@app.route("/v1/mechanics/<mechanic_id>/events", methods=["POST"])
def mechanic_events(mechanic_id):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "Dispatcher"})
    m = get_or_404(mechanics, mechanic_id)
    d = get_body({"event_type", "reason"})
    event = v_enum(d, "event_type", {"SUSPEND", "REINSTATE"})
    if event == "SUSPEND":
        if m["status"] != "ACTIVE":
            err("ERR_INVALID_STATE", 409, "Mechanic is not ACTIVE")
        m["status"] = "SUSPENDED"
        bump(m)
        # Cascade: PLANNED stops on non-CLOSED route days of this mechanic's vans
        affected_days = set()
        for st in route_stops.values():
            if st["status"] != "PLANNED":
                continue
            day = route_days.get(st["route_day_id"])
            if day is None or day["status"] == "CLOSED":
                continue
            van = vans.get(day["van_id"])
            if van is None or van["mechanic_id"] != mechanic_id:
                continue
            st["status"] = "UNASSIGNED"
            bump(st)
            req = service_requests.get(st["service_request_id"])
            if req is not None and req["work_status"] == "DISPATCHED":
                req["work_status"] = "QUOTED"
                req["scheduled_mechanic_id"] = None
                bump(req)
            affected_days.add(day["id"])
        for day_id in affected_days:
            recompute_day_and_maybe_unlock(route_days[day_id])
    else:  # REINSTATE
        if m["status"] != "SUSPENDED":
            err("ERR_INVALID_STATE", 409, "Mechanic is not SUSPENDED")
        m["status"] = "ACTIVE"
        bump(m)
    return respond(s_mechanic(m), "object", 200)


# ---------------------------------------------------------------------------
# Vans
# ---------------------------------------------------------------------------
@app.route("/v1/vans", methods=["POST"])
def create_van():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    d = get_body({"plate", "zone_id", "mechanic_id", "max_stops_per_day"})
    plate = v_str(d, "plate")
    zone_id = v_str(d, "zone_id")
    mechanic_id = v_str(d, "mechanic_id", required=False, default=None)
    max_stops = v_int(d, "max_stops_per_day", minimum=1)
    get_or_404(zones, zone_id)
    if mechanic_id is not None:
        get_or_404(mechanics, mechanic_id)
    v = new_common()
    v.update({"plate": plate, "zone_id": zone_id, "mechanic_id": mechanic_id,
              "max_stops_per_day": max_stops, "status": "ACTIVE"})
    vans[v["id"]] = v
    return respond(s_van(v), "object", 201)


@app.route("/v1/vans/<van_id>", methods=["GET"])
def get_van(van_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    v = get_or_404(vans, van_id)
    return respond(s_van(v), "object", 200)


@app.route("/v1/vans", methods=["GET"])
def list_vans():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(vans.values())
    zid = request.args.get("zone_id")
    mid = request.args.get("mechanic_id")
    st = request.args.get("status")
    if zid is not None:
        items = [v for v in items if v["zone_id"] == zid]
    if mid is not None:
        items = [v for v in items if v["mechanic_id"] == mid]
    if st is not None:
        items = [v for v in items if v["status"] == st]
    return paginate_and_respond(items, s_van)


@app.route("/v1/vans/<van_id>/events", methods=["POST"])
def van_events(van_id):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "Dispatcher"})
    v = get_or_404(vans, van_id)
    d = get_body({"event_type", "mechanic_id"})
    event = v_enum(d, "event_type",
                   {"ASSIGN_MECHANIC", "TAKE_OUT_OF_SERVICE", "RETURN_TO_SERVICE"})
    if event == "ASSIGN_MECHANIC":
        mech_id = v_str(d, "mechanic_id")
        mech = get_or_404(mechanics, mech_id)
        if v["status"] != "ACTIVE":
            err("ERR_INVALID_STATE", 409, "Van is not ACTIVE")
        if mech["status"] != "ACTIVE":
            err("ERR_MECHANIC_SUSPENDED", 409, "Mechanic is SUSPENDED")
        v["mechanic_id"] = mech_id
        bump(v)
    elif event == "TAKE_OUT_OF_SERVICE":
        if v["status"] != "ACTIVE":
            err("ERR_INVALID_STATE", 409, "Van is not ACTIVE")
        v["status"] = "OUT_OF_SERVICE"
        bump(v)
    else:  # RETURN_TO_SERVICE
        if v["status"] != "OUT_OF_SERVICE":
            err("ERR_INVALID_STATE", 409, "Van is not OUT_OF_SERVICE")
        v["status"] = "ACTIVE"
        bump(v)
    return respond(s_van(v), "object", 200)


# ---------------------------------------------------------------------------
# Parts & truck stock
# ---------------------------------------------------------------------------
@app.route("/v1/parts", methods=["POST"])
def create_part():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    d = get_body({"sku", "name", "unit_price_cents", "warranty_days", "ebike_only"})
    sku = v_str(d, "sku")
    name = v_str(d, "name")
    price = v_int(d, "unit_price_cents", minimum=0)
    warranty = v_int(d, "warranty_days", minimum=0)
    ebike_only = v_bool(d, "ebike_only", required=False, default=False)
    for p in parts.values():
        if p["sku"] == sku:
            err("ERR_DUPLICATE_SKU", 409, "Part sku already exists")
    p = new_common()
    p.update({"sku": sku, "name": name, "unit_price_cents": price,
              "warranty_days": warranty, "ebike_only": ebike_only})
    parts[p["id"]] = p
    return respond(s_part(p), "object", 201)


@app.route("/v1/parts/<part_id>", methods=["GET"])
def get_part(part_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    p = get_or_404(parts, part_id)
    return respond(s_part(p), "object", 200)


@app.route("/v1/parts/<part_id>/stock", methods=["GET"])
def list_part_stock(part_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    get_or_404(parts, part_id)
    items = [it for it in truck_stock.values() if it["part_id"] == part_id]
    return paginate_and_respond(items, s_stock_item)


@app.route("/v1/vans/<van_id>/stock", methods=["GET"])
def list_van_stock(van_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    get_or_404(vans, van_id)
    items = [it for it in truck_stock.values() if it["van_id"] == van_id]
    return paginate_and_respond(items, s_stock_item)


@app.route("/v1/vans/<van_id>/stock-movements", methods=["POST"])
def create_stock_movement(van_id):
    uid, role = authenticate()
    authorize(role, {"Dispatcher", "Mechanic"})
    v = get_or_404(vans, van_id)
    d = get_body({"part_id", "quantity", "reason", "note"})
    part_id = v_str(d, "part_id")
    quantity = v_int(d, "quantity", minimum=1)
    reason = v_enum(d, "reason", {"RECEIVE", "RETURN_TO_WAREHOUSE"})
    note = v_str(d, "note", required=False, default=None)
    get_or_404(parts, part_id)
    it = get_stock_item(van_id, part_id, create=True)
    if reason == "RECEIVE":
        it["on_hand"] += quantity
        delta = quantity
    else:  # RETURN_TO_WAREHOUSE
        if it["on_hand"] < quantity:
            err("ERR_STOCK_INSUFFICIENT", 409, "on_hand below returned quantity")
        it["on_hand"] -= quantity
        delta = -quantity
    bump(it)
    m = append_movement(van_id, part_id, None, quantity, delta, reason, note)
    return respond(s_movement(m), "object", 201)


@app.route("/v1/stock-movements/<movement_id>", methods=["GET"])
def get_movement(movement_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    m = get_or_404(stock_movements, movement_id)
    return respond(s_movement(m), "object", 200)


@app.route("/v1/stock-movements", methods=["GET"])
def list_movements():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(stock_movements.values())
    vid = request.args.get("van_id")
    pid = request.args.get("part_id")
    rid = request.args.get("service_request_id")
    rsn = request.args.get("reason")
    if vid is not None:
        items = [m for m in items if m["van_id"] == vid]
    if pid is not None:
        items = [m for m in items if m["part_id"] == pid]
    if rid is not None:
        items = [m for m in items if m["service_request_id"] == rid]
    if rsn is not None:
        items = [m for m in items if m["reason"] == rsn]
    return paginate_and_respond(items, s_movement)


# ---------------------------------------------------------------------------
# Service tiers
# ---------------------------------------------------------------------------
@app.route("/v1/service-tiers", methods=["POST"])
def create_tier():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    d = get_body({"code", "base_price_cents", "included_minutes",
                  "overage_rate_cents_per_min", "labor_warranty_days"})
    code = v_enum(d, "code", TIER_CODES)
    base = v_int(d, "base_price_cents", minimum=0)
    included = v_int(d, "included_minutes", minimum=1)
    overage = v_int(d, "overage_rate_cents_per_min", minimum=0)
    warranty = v_int(d, "labor_warranty_days", minimum=0)
    for t in service_tiers.values():
        if t["code"] == code:
            err("ERR_DUPLICATE_TIER_CODE", 409, "ServiceTier code already exists")
    t = new_common()
    t.update({"code": code, "base_price_cents": base, "included_minutes": included,
              "overage_rate_cents_per_min": overage,
              "labor_warranty_days": warranty})
    service_tiers[t["id"]] = t
    return respond(s_tier(t), "object", 201)


@app.route("/v1/service-tiers/<tier_id>", methods=["GET"])
def get_tier(tier_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    t = get_or_404(service_tiers, tier_id)
    return respond(s_tier(t), "object", 200)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------
@app.route("/v1/subscriptions", methods=["POST"])
def create_subscription():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "Dispatcher"})
    d = get_body({"customer_id", "included_tunes_per_period", "discount_pct",
                  "period_start", "period_end"})
    customer_id = v_str(d, "customer_id")
    included = v_int(d, "included_tunes_per_period", minimum=1)
    discount = v_number(d, "discount_pct")
    if not (Decimal(str(discount)) > 0 and Decimal(str(discount)) < 1):
        err("ERR_VALIDATION", 400, "discount_pct must be strictly between 0 and 1")
    period_start = v_datetime(d, "period_start")
    period_end = v_datetime(d, "period_end")
    c = get_or_404(customers, customer_id)
    for s in subscriptions.values():
        if s["customer_id"] == customer_id and s["status"] != "CANCELLED":
            err("ERR_SUBSCRIPTION_ACTIVE_EXISTS", 409,
                "Customer already has a non-CANCELLED subscription")
    if c["account_kind"] not in ("FLEET", "APARTMENT"):
        err("ERR_SUBSCRIPTION_REQUIRES_ORG_ACCOUNT", 422,
            "Subscriptions require a FLEET or APARTMENT account")
    s = new_common()
    s.update({"customer_id": customer_id,
              "included_tunes_per_period": included,
              "discount_pct": discount,
              "period_start": period_start,
              "period_end": period_end,
              "status": "ACTIVE",
              "allowance_reserved": 0,
              "allowance_consumed": 0})
    subscriptions[s["id"]] = s
    return respond(s_subscription(s), "object", 201)


@app.route("/v1/subscriptions/<subscription_id>", methods=["GET"])
def get_subscription(subscription_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    s = get_or_404(subscriptions, subscription_id)
    return respond(s_subscription(s), "object", 200)


@app.route("/v1/subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(subscriptions.values())
    cid = request.args.get("customer_id")
    st = request.args.get("status")
    if cid is not None:
        items = [s for s in items if s["customer_id"] == cid]
    if st is not None:
        items = [s for s in items if s["status"] == st]
    return paginate_and_respond(items, s_subscription)


def decouple_subscription(sub):
    """SUSPEND/CANCEL cascade: strip coverage from open covered requests,
    release their allowance reservations, recompute quotes without discount."""
    for req in service_requests.values():
        if req["subscription_id"] != sub["id"]:
            continue
        if not req["covered_by_subscription"]:
            continue
        if req["work_status"] not in LIVE_WORK_STATUSES:
            continue
        req["covered_by_subscription"] = False
        sub["allowance_reserved"] -= 1
        req["quoted_total_cents"] = compute_quote(req)
        bump(req)


@app.route("/v1/subscriptions/<subscription_id>/events", methods=["POST"])
def subscription_events(subscription_id):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "Dispatcher"})
    s = get_or_404(subscriptions, subscription_id)
    d = get_body({"event_type"})
    event = v_enum(d, "event_type",
                   {"MARK_PAST_DUE", "RECOVER", "SUSPEND", "REINSTATE", "CANCEL"})
    cur = s["status"]
    if event == "MARK_PAST_DUE":
        if cur != "ACTIVE":
            err("ERR_INVALID_STATE", 409, "Subscription is not ACTIVE")
        s["status"] = "PAST_DUE"
    elif event == "RECOVER":
        if cur != "PAST_DUE":
            err("ERR_INVALID_STATE", 409, "Subscription is not PAST_DUE")
        s["status"] = "ACTIVE"
    elif event == "SUSPEND":
        if cur not in ("ACTIVE", "PAST_DUE"):
            err("ERR_INVALID_STATE", 409, "Subscription cannot be suspended")
        s["status"] = "SUSPENDED"
        decouple_subscription(s)
    elif event == "REINSTATE":
        if cur != "SUSPENDED":
            err("ERR_INVALID_STATE", 409, "Subscription is not SUSPENDED")
        s["status"] = "ACTIVE"
    else:  # CANCEL
        if cur == "CANCELLED":
            err("ERR_INVALID_STATE", 409, "Subscription is already CANCELLED")
        if cur in ("ACTIVE", "PAST_DUE"):
            decouple_subscription(s)
        s["status"] = "CANCELLED"
    bump(s)
    return respond(s_subscription(s), "object", 200)


# ---------------------------------------------------------------------------
# Service requests
# ---------------------------------------------------------------------------
@app.route("/v1/service-requests", methods=["POST"])
def create_service_request():
    uid, role = authenticate()
    authorize(role, {"Customer", "Dispatcher"})
    d = get_body({"customer_id", "bike_id", "zone_id", "tier_id", "subscription_id",
                  "window_start", "window_end", "issue_note"})
    customer_id = v_str(d, "customer_id")
    bike_id = v_str(d, "bike_id")
    zone_id = v_str(d, "zone_id")
    tier_id = v_str(d, "tier_id")
    subscription_id = v_str(d, "subscription_id", required=False, default=None)
    window_start = v_datetime(d, "window_start")
    window_end = v_datetime(d, "window_end")
    issue_note = v_str(d, "issue_note", required=False, default=None)
    customer = get_or_404(customers, customer_id)
    bike = get_or_404(bikes, bike_id)
    zone = get_or_404(zones, zone_id)
    tier = get_or_404(service_tiers, tier_id)
    sub = None
    if subscription_id is not None:
        sub = get_or_404(subscriptions, subscription_id)
    if role == "Customer" and uid != customer_id:
        err("ERR_FORBIDDEN", 403, "Customers may only book for their own account")
    if not zone["active"]:
        err("ERR_VALIDATION", 400, "Zone is not active")
    # Battery safety
    if bike["bike_type"] == "EBIKE":
        if not bike["battery_certified"] or bike["battery_health_pct"] < BATTERY_MIN_HEALTH_PCT:
            err("ERR_BATTERY_SAFETY", 422,
                "E-bike battery is not certified or health below 70%")
    # Window shape
    check_window_shape(window_start, window_end)
    # Customer double-booking (closed intervals)
    check_customer_overlap(customer_id, window_start, window_end)
    # Ownership
    if bike["customer_id"] != customer_id:
        err("ERR_BIKE_NOT_OWNED", 403, "Bike belongs to a different customer")
    if sub is not None and sub["customer_id"] != customer_id:
        err("ERR_SUBSCRIPTION_NOT_OWNED", 403,
            "Subscription belongs to a different customer")
    # Subscription coverage checks
    if sub is not None:
        ws = parse_iso(window_start)
        if ws < parse_iso(sub["period_start"]) or ws > parse_iso(sub["period_end"]):
            err("ERR_SUBSCRIPTION_PERIOD", 422,
                "window_start outside subscription coverage period")
        if sub["status"] not in ("ACTIVE", "PAST_DUE"):
            err("ERR_SUBSCRIPTION_INACTIVE", 409,
                "Subscription is not ACTIVE or PAST_DUE")
        remaining = (sub["included_tunes_per_period"]
                     - sub["allowance_reserved"] - sub["allowance_consumed"])
        if remaining < 1:
            err("ERR_ALLOWANCE_EXHAUSTED", 422, "No subscription allowance remaining")
    r = new_common()
    r.update({
        "customer_id": customer_id,
        "bike_id": bike_id,
        "zone_id": zone_id,
        "tier_id": tier_id,
        "subscription_id": subscription_id,
        "request_kind": "STANDARD",
        "callback_of_id": None,
        "window_start": window_start,
        "window_end": window_end,
        "issue_note": issue_note,
        "work_status": "QUOTED",
        "billing_status": "ESTIMATED",
        "scheduled_mechanic_id": None,
        "quoted_total_cents": 0,
        "covered_by_subscription": sub is not None,
        "actual_labor_minutes": None,
        "completed_at": None,
        "cancel_reason": None,
    })
    service_requests[r["id"]] = r
    r["quoted_total_cents"] = compute_quote(r)
    if sub is not None:
        sub["allowance_reserved"] += 1
        bump(sub)
    return respond(s_request(r), "object", 201)


@app.route("/v1/service-requests/<request_id>", methods=["GET"])
def get_service_request(request_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    r = get_or_404(service_requests, request_id)
    return respond(s_request(r), "object", 200)


@app.route("/v1/service-requests", methods=["GET"])
def list_service_requests():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(service_requests.values())
    for f in ("customer_id", "bike_id", "zone_id", "tier_id", "subscription_id",
              "scheduled_mechanic_id", "callback_of_id", "work_status"):
        val = request.args.get(f)
        if val is not None:
            items = [r for r in items if r.get(f) == val]
    return paginate_and_respond(items, s_request)


def release_reservation_if_covered(req):
    if req["covered_by_subscription"] and req["subscription_id"] in subscriptions:
        sub = subscriptions[req["subscription_id"]]
        sub["allowance_reserved"] -= 1
        bump(sub)


def skip_linked_stop(req):
    st = active_stop_for_request(req["id"])
    if st is not None:
        st["status"] = "SKIPPED"
        bump(st)
        day = route_days.get(st["route_day_id"])
        if day is not None:
            recompute_day_and_maybe_unlock(day)


@app.route("/v1/service-requests/<request_id>/events", methods=["POST"])
def request_events(request_id):
    uid, role = authenticate()
    authorize(role, {"Customer", "Mechanic", "Dispatcher"})
    req = get_or_404(service_requests, request_id)
    d = get_body({"event_type", "labor_minutes", "cancel_reason"})
    event = v_enum(d, "event_type",
                   {"CANCEL", "START_SERVICE", "HOLD_PARTS", "RESUME",
                    "COMPLETE", "MARK_NO_SHOW"})
    if event == "CANCEL":
        if role == "Customer" and uid != req["customer_id"]:
            err("ERR_FORBIDDEN", 403, "Customers may only cancel their own requests")
        if role == "Mechanic":
            err("ERR_FORBIDDEN", 403, "Mechanics may not cancel requests")
    elif role == "Customer":
        # PRD §2.1 enumerates the customer write verbs: register bikes, book,
        # reschedule, cancel, open callbacks — mechanic-scoped work events are
        # not among them.
        err("ERR_FORBIDDEN", 403, "Customers may not perform work events")
    elif role == "Mechanic":
        # PRD §2.1: only when the role is Mechanic is X-User-ID compared against
        # the request's scheduled_mechanic_id; Dispatcher/PlatformAdmin
        # identifiers are opaque and never compared to any entity's id.
        if uid != req["scheduled_mechanic_id"]:
            err("ERR_FORBIDDEN", 403, "Event restricted to the assigned mechanic")
    if event == "COMPLETE":
        labor_minutes = v_int(d, "labor_minutes", minimum=0)
    cancel_reason = v_str(d, "cancel_reason", required=False, default=None)

    ws = req["work_status"]
    if event == "CANCEL":
        if ws == "QUOTED":
            req["work_status"] = "CANCELLED"
            req["cancel_reason"] = cancel_reason
            release_reservation_if_covered(req)
            bump(req)
        elif ws in ("DISPATCHED", "ON_SITE"):
            req["work_status"] = "CANCELLED"
            req["cancel_reason"] = cancel_reason
            skip_linked_stop(req)
            if ws == "DISPATCHED":
                req["scheduled_mechanic_id"] = None
            release_reservation_if_covered(req)
            bump(req)
            create_fee_invoice(req, is_no_show=False)
        else:
            err("ERR_INVALID_STATE", 409, "Request cannot be cancelled from %s" % ws)
    elif event == "START_SERVICE":
        if ws != "ON_SITE":
            err("ERR_INVALID_STATE", 409, "Request is not ON_SITE")
        req["work_status"] = "IN_SERVICE"
        bump(req)
    elif event == "HOLD_PARTS":
        if ws != "IN_SERVICE":
            err("ERR_INVALID_STATE", 409, "Request is not IN_SERVICE")
        req["work_status"] = "ON_HOLD_PARTS"
        bump(req)
    elif event == "RESUME":
        if ws != "ON_HOLD_PARTS":
            err("ERR_INVALID_STATE", 409, "Request is not ON_HOLD_PARTS")
        req["work_status"] = "IN_SERVICE"
        bump(req)
    elif event == "COMPLETE":
        if ws != "IN_SERVICE":
            err("ERR_INVALID_STATE", 409, "Request is not IN_SERVICE")
        req["work_status"] = "COMPLETED"
        req["actual_labor_minutes"] = labor_minutes
        req["completed_at"] = fmt_ts(now())
        # Release any units still reserved for this request
        for (van_id, part_id), qty in outstanding_reserved(req["id"]).items():
            it = get_stock_item(van_id, part_id)
            if it is not None:
                it["reserved"] -= qty
                bump(it)
            append_movement(van_id, part_id, req["id"], qty, 0, "RELEASE")
        # Settle subscription allowance
        if req["covered_by_subscription"] and req["subscription_id"] in subscriptions:
            sub = subscriptions[req["subscription_id"]]
            sub["allowance_reserved"] -= 1
            sub["allowance_consumed"] += 1
            bump(sub)
        bump(req)
    else:  # MARK_NO_SHOW
        if ws != "ON_SITE":
            err("ERR_INVALID_STATE", 409, "Request is not ON_SITE")
        req["work_status"] = "NO_SHOW"
        skip_linked_stop(req)
        release_reservation_if_covered(req)
        bump(req)
        create_fee_invoice(req, is_no_show=True)
    return respond(s_request(req), "object", 200)


@app.route("/v1/service-requests/<request_id>/reschedule", methods=["POST"])
def reschedule_request(request_id):
    uid, role = authenticate()
    authorize(role, {"Customer", "Dispatcher"})
    req = get_or_404(service_requests, request_id)
    if role == "Customer" and uid != req["customer_id"]:
        err("ERR_FORBIDDEN", 403, "Customers may only reschedule their own requests")
    d = get_body({"window_start", "window_end", "expected_service_request_version"})
    window_start = v_datetime(d, "window_start")
    window_end = v_datetime(d, "window_end")
    expected = v_int(d, "expected_service_request_version")
    if expected != req["version"]:
        err("ERR_STALE_VERSION", 412, "ServiceRequest version mismatch")
    if req["work_status"] != "QUOTED":
        err("ERR_INVALID_STATE", 409, "Only QUOTED requests may be rescheduled")
    check_window_shape(window_start, window_end)
    check_customer_overlap(req["customer_id"], window_start, window_end,
                           exclude_id=req["id"])
    req["window_start"] = window_start
    req["window_end"] = window_end
    bump(req)
    return respond(s_request(req), "object", 200)


@app.route("/v1/service-requests/<request_id>/callbacks", methods=["POST"])
def create_callback(request_id):
    uid, role = authenticate()
    authorize(role, {"Customer", "Dispatcher"})
    orig = get_or_404(service_requests, request_id)
    if role == "Customer" and uid != orig["customer_id"]:
        err("ERR_FORBIDDEN", 403, "Customers may only open callbacks on their own requests")
    d = get_body({"window_start", "window_end", "issue_note"})
    window_start = v_datetime(d, "window_start")
    window_end = v_datetime(d, "window_end")
    issue_note = v_str(d, "issue_note", required=False, default=None)
    check_window_shape(window_start, window_end)
    # Warranty eligibility (checked first)
    if orig["work_status"] != "COMPLETED":
        err("ERR_WARRANTY_EXPIRED", 409, "Original request is not COMPLETED")
    tier = service_tiers[orig["tier_id"]]
    warranty_days = tier["labor_warranty_days"]
    for pid, qty in consumed_parts(orig["id"]):
        p = parts.get(pid)
        if p is not None and p["warranty_days"] > warranty_days:
            warranty_days = p["warranty_days"]
    deadline = parse_iso(orig["completed_at"]) + timedelta(days=warranty_days)
    if now() > deadline:
        err("ERR_WARRANTY_EXPIRED", 409, "Warranty window has expired")
    # Duplicate guard (evaluated only after the warranty check)
    for r in service_requests.values():
        if r["callback_of_id"] == orig["id"] and \
                r["work_status"] not in ("CLOSED", "CANCELLED", "NO_SHOW"):
            err("ERR_CALLBACK_EXISTS", 409,
                "An open callback already exists for this request")
    r = new_common()
    r.update({
        "customer_id": orig["customer_id"],
        "bike_id": orig["bike_id"],
        "zone_id": orig["zone_id"],
        "tier_id": orig["tier_id"],
        "subscription_id": None,
        "request_kind": "CALLBACK",
        "callback_of_id": orig["id"],
        "window_start": window_start,
        "window_end": window_end,
        "issue_note": issue_note,
        "work_status": "QUOTED",
        "billing_status": "ESTIMATED",
        "scheduled_mechanic_id": None,
        "quoted_total_cents": 0,
        "covered_by_subscription": False,
        "actual_labor_minutes": None,
        "completed_at": None,
        "cancel_reason": None,
    })
    service_requests[r["id"]] = r
    r["quoted_total_cents"] = compute_quote(r)
    return respond(s_request(r), "object", 201)


@app.route("/v1/service-requests/<request_id>/part-usages", methods=["POST"])
def part_usages(request_id):
    uid, role = authenticate()
    authorize(role, {"Mechanic", "Dispatcher"})
    req = get_or_404(service_requests, request_id)
    d = get_body({"part_id", "quantity", "action"})
    part_id = v_str(d, "part_id")
    quantity = v_int(d, "quantity", minimum=1)
    action = v_enum(d, "action", {"RESERVE", "RELEASE", "CONSUME"})
    part = get_or_404(parts, part_id)
    ws = req["work_status"]
    if action == "CONSUME":
        if ws not in ("IN_SERVICE", "ON_HOLD_PARTS"):
            err("ERR_INVALID_STATE", 409,
                "CONSUME requires IN_SERVICE or ON_HOLD_PARTS")
    else:
        if ws not in ("DISPATCHED", "ON_SITE", "IN_SERVICE", "ON_HOLD_PARTS"):
            err("ERR_INVALID_STATE", 409,
                "%s not permitted from %s" % (action, ws))
    stop = active_stop_for_request(request_id)
    if stop is None:
        err("ERR_INVALID_STATE", 409, "Request has no active route stop")
    day = route_days[stop["route_day_id"]]
    van_id = day["van_id"]
    it = get_stock_item(van_id, part_id, create=True)
    per_req = outstanding_reserved(request_id).get((van_id, part_id), 0)
    if action == "RESERVE":
        if quantity > it["on_hand"] - it["reserved"]:
            err("ERR_STOCK_INSUFFICIENT", 409, "RESERVE exceeds available stock")
        it["reserved"] += quantity
    elif action == "RELEASE":
        if quantity > per_req or quantity > it["reserved"]:
            err("ERR_STOCK_INSUFFICIENT", 409, "RELEASE exceeds reserved stock")
        it["reserved"] -= quantity
    else:  # CONSUME
        if quantity > per_req or quantity > it["reserved"]:
            err("ERR_STOCK_INSUFFICIENT", 409, "CONSUME exceeds reserved stock")
        it["reserved"] -= quantity
        it["on_hand"] -= quantity
    bump(it)
    append_movement(van_id, part_id, request_id, quantity, 0, action)
    return respond(s_stock_item(it), "object", 200)


# ---------------------------------------------------------------------------
# Route days & stops
# ---------------------------------------------------------------------------
@app.route("/v1/route-days", methods=["POST"])
def create_route_day():
    uid, role = authenticate()
    authorize(role, {"Dispatcher"})
    d = get_body({"van_id", "date"})
    van_id = v_str(d, "van_id")
    date = v_str(d, "date")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        err("ERR_VALIDATION", 400, "date must be YYYY-MM-DD")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        err("ERR_VALIDATION", 400, "date must be a valid YYYY-MM-DD date")
    v = get_or_404(vans, van_id)
    if v["status"] != "ACTIVE":
        err("ERR_VAN_UNAVAILABLE", 409, "Van is not ACTIVE")
    for rd in route_days.values():
        if rd["van_id"] == van_id and rd["date"] == date:
            err("ERR_ROUTE_DAY_EXISTS", 409, "Route day already exists for van and date")
    rd = new_common()
    rd.update({"van_id": van_id, "date": date, "status": "OPEN"})
    route_days[rd["id"]] = rd
    return respond(s_route_day(rd), "object", 201)


@app.route("/v1/route-days/<route_day_id>", methods=["GET"])
def get_route_day(route_day_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    rd = get_or_404(route_days, route_day_id)
    return respond(s_route_day(rd), "object", 200)


@app.route("/v1/route-days", methods=["GET"])
def list_route_days():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(route_days.values())
    vid = request.args.get("van_id")
    dt = request.args.get("date")
    st = request.args.get("status")
    if vid is not None:
        items = [r for r in items if r["van_id"] == vid]
    if dt is not None:
        items = [r for r in items if r["date"] == dt]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    return paginate_and_respond(items, s_route_day)


@app.route("/v1/route-days/<route_day_id>/events", methods=["POST"])
def route_day_events(route_day_id):
    uid, role = authenticate()
    authorize(role, {"Dispatcher"})
    rd = get_or_404(route_days, route_day_id)
    d = get_body({"event_type"})
    event = v_enum(d, "event_type", {"LOCK", "UNLOCK", "START", "CLOSE"})
    cur = rd["status"]
    if event == "LOCK":
        if cur != "OPEN":
            err("ERR_INVALID_STATE", 409, "Route day is not OPEN")
        rd["status"] = "LOCKED"
    elif event == "UNLOCK":
        if cur != "LOCKED":
            err("ERR_INVALID_STATE", 409, "Route day is not LOCKED")
        rd["status"] = "OPEN"
    elif event == "START":
        if cur not in ("OPEN", "LOCKED"):
            err("ERR_INVALID_STATE", 409, "Route day cannot be started from %s" % cur)
        if active_stop_count(rd["id"]) < 1:
            err("ERR_INVALID_STATE", 409, "Route day has no active stops")
        rd["status"] = "IN_PROGRESS"
    else:  # CLOSE
        if cur != "IN_PROGRESS":
            err("ERR_INVALID_STATE", 409, "Route day is not IN_PROGRESS")
        for st in route_stops.values():
            if st["route_day_id"] == rd["id"] and \
                    st["status"] not in ("DONE", "SKIPPED", "UNASSIGNED"):
                err("ERR_INVALID_STATE", 409, "Route day has non-terminal stops")
        rd["status"] = "CLOSED"
    bump(rd)
    return respond(s_route_day(rd), "object", 200)


@app.route("/v1/route-days/<route_day_id>/stops", methods=["POST"])
def create_stop(route_day_id):
    uid, role = authenticate()
    authorize(role, {"Dispatcher"})
    rd = get_or_404(route_days, route_day_id)
    d = get_body({"service_request_id", "planned_start", "planned_end",
                  "travel_buffer_minutes"})
    request_id = v_str(d, "service_request_id")
    planned_start = v_datetime(d, "planned_start")
    planned_end = v_datetime(d, "planned_end")
    buffer_min = v_int(d, "travel_buffer_minutes", required=False,
                       default=DEFAULT_TRAVEL_BUFFER_MINUTES, minimum=0)
    req = get_or_404(service_requests, request_id)
    if req["work_status"] != "QUOTED":
        err("ERR_INVALID_STATE", 409, "Service request is not QUOTED")
    if rd["status"] != "OPEN":
        err("ERR_ROUTE_DAY_NOT_OPEN", 409, "Route day is not OPEN")
    van = vans[rd["van_id"]]
    if van["status"] != "ACTIVE" or van["mechanic_id"] is None:
        err("ERR_VAN_UNAVAILABLE", 409, "Van is unavailable or has no mechanic")
    mech = mechanics[van["mechanic_id"]]
    if mech["status"] != "ACTIVE":
        err("ERR_MECHANIC_SUSPENDED", 409, "Assigned mechanic is SUSPENDED")
    bike = bikes[req["bike_id"]]
    if bike["bike_type"] == "EBIKE" and not mech["ebike_certified"]:
        err("ERR_MECHANIC_NOT_EBIKE_CERTIFIED", 409,
            "E-bike job requires an e-bike certified mechanic")
    if active_stop_count(rd["id"]) >= van["max_stops_per_day"]:
        err("ERR_ROUTE_CAPACITY_EXCEEDED", 409, "Route day is at capacity")
    # Temporal checks: planned visit inside the request window, mechanic free
    ps = parse_iso(planned_start)
    pe = parse_iso(planned_end)
    if ps < parse_iso(req["window_start"]) or pe > parse_iso(req["window_end"]) or pe < ps:
        err("ERR_MECHANIC_WINDOW_OVERLAP", 409,
            "Planned stop outside the request window")
    buf = timedelta(minutes=buffer_min)
    for st in route_stops.values():
        if st["status"] not in ("PLANNED", "ARRIVED"):
            continue
        other = service_requests.get(st["service_request_id"])
        if other is None or other["scheduled_mechanic_id"] != mech["id"]:
            continue
        es = parse_iso(st["planned_start"])
        ee = parse_iso(st["planned_end"])
        # Buffered half-open intervals; exact touch at expanded boundary allowed
        if ps - buf < ee and es < pe + buf:
            err("ERR_MECHANIC_WINDOW_OVERLAP", 409,
                "Mechanic has a conflicting stop")
    st = new_common()
    st.update({
        "route_day_id": rd["id"],
        "service_request_id": req["id"],
        "seq": active_stop_count(rd["id"]) + 1,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "travel_buffer_minutes": buffer_min,
        "status": "PLANNED",
    })
    route_stops[st["id"]] = st
    req["work_status"] = "DISPATCHED"
    req["scheduled_mechanic_id"] = mech["id"]
    bump(req)
    bump(rd)
    return respond(s_stop(st), "object", 201)


@app.route("/v1/route-days/<route_day_id>/stops", methods=["GET"])
def list_day_stops(route_day_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    rd = get_or_404(route_days, route_day_id)
    items = [st for st in route_stops.values() if st["route_day_id"] == route_day_id]
    return paginate_and_respond(items, s_stop,
                                sort_key=lambda x: (x["seq"], x["_seq"]))


@app.route("/v1/route-days/<route_day_id>/resequence", methods=["POST"])
def resequence_day(route_day_id):
    uid, role = authenticate()
    authorize(role, {"Dispatcher"})
    rd = get_or_404(route_days, route_day_id)
    d = get_body({"stop_ids", "expected_route_day_version"})
    stop_ids = d.get("stop_ids")
    if not isinstance(stop_ids, list) or \
            not all(isinstance(x, str) for x in stop_ids) or \
            len(set(stop_ids)) != len(stop_ids):
        err("ERR_VALIDATION", 400, "stop_ids must be an array of unique strings")
    expected = v_int(d, "expected_route_day_version")
    if expected != rd["version"]:
        err("ERR_STALE_VERSION", 412, "RouteDay version mismatch")
    if rd["status"] != "OPEN":
        err("ERR_ROUTE_DAY_NOT_OPEN", 409, "Route day is not OPEN")
    active = {st["id"]: st for st in route_stops.values()
              if st["route_day_id"] == route_day_id
              and st["status"] in ("PLANNED", "ARRIVED")}
    if set(stop_ids) != set(active.keys()):
        err("ERR_VALIDATION", 400,
            "stop_ids must be exactly the day's PLANNED/ARRIVED stops")
    for i, sid in enumerate(stop_ids):
        st = active[sid]
        if st["seq"] != i + 1:
            st["seq"] = i + 1
            bump(st)
    bump(rd)
    return respond(s_route_day(rd), "object", 200)


@app.route("/v1/route-stops/<stop_id>", methods=["GET"])
def get_stop(stop_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    st = get_or_404(route_stops, stop_id)
    return respond(s_stop(st), "object", 200)


@app.route("/v1/route-stops", methods=["GET"])
def list_stops():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(route_stops.values())
    rid = request.args.get("service_request_id")
    st_f = request.args.get("status")
    if rid is not None:
        items = [s for s in items if s["service_request_id"] == rid]
    if st_f is not None:
        items = [s for s in items if s["status"] == st_f]
    return paginate_and_respond(items, s_stop)


@app.route("/v1/route-stops/<stop_id>/events", methods=["POST"])
def stop_events(stop_id):
    uid, role = authenticate()
    authorize(role, {"Mechanic", "Dispatcher"})
    st = get_or_404(route_stops, stop_id)
    d = get_body({"event_type"})
    event = v_enum(d, "event_type", {"ARRIVE", "DONE", "SKIP"})
    req = service_requests.get(st["service_request_id"])
    if event in ("ARRIVE", "DONE"):
        # PRD §2.1: the scheduled_mechanic_id comparison applies only when the
        # acting role is Mechanic; Dispatcher identifiers are never compared.
        if role == "Mechanic" and (req is None or uid != req["scheduled_mechanic_id"]):
            err("ERR_FORBIDDEN", 403, "Event restricted to the assigned mechanic")
    if event == "ARRIVE":
        if st["status"] != "PLANNED":
            err("ERR_INVALID_STATE", 409, "Stop is not PLANNED")
        st["status"] = "ARRIVED"
        bump(st)
        if req is not None and req["work_status"] == "DISPATCHED":
            req["work_status"] = "ON_SITE"
            bump(req)
    elif event == "DONE":
        if st["status"] != "ARRIVED":
            err("ERR_INVALID_STATE", 409, "Stop is not ARRIVED")
        if req is None or req["work_status"] != "COMPLETED":
            err("ERR_INVALID_STATE", 409, "Linked request is not COMPLETED")
        st["status"] = "DONE"
        bump(st)
        day = route_days.get(st["route_day_id"])
        if day is not None:
            recompute_day_and_maybe_unlock(day)
    else:  # SKIP
        if st["status"] != "PLANNED":
            err("ERR_INVALID_STATE", 409, "Stop is not PLANNED")
        st["status"] = "SKIPPED"
        bump(st)
        if req is not None and req["work_status"] == "DISPATCHED":
            req["work_status"] = "QUOTED"
            req["scheduled_mechanic_id"] = None
            bump(req)
        day = route_days.get(st["route_day_id"])
        if day is not None:
            recompute_day_and_maybe_unlock(day)
    return respond(s_stop(st), "object", 200)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@app.route("/v1/service-requests/<request_id>/invoices", methods=["POST"])
def generate_invoice(request_id):
    uid, role = authenticate()
    authorize(role, {"Dispatcher", "PlatformAdmin"})
    req = get_or_404(service_requests, request_id)
    get_body(set())
    if req["work_status"] not in ("COMPLETED", "NO_SHOW"):
        err("ERR_JOB_NOT_COMPLETED", 409,
            "Invoice generation requires COMPLETED or NO_SHOW")
    if non_void_invoice_for(request_id) is not None:
        err("ERR_INVOICE_EXISTS", 409,
            "A non-VOID invoice already exists for this request")
    tier = service_tiers[req["tier_id"]]
    zone = zones[req["zone_id"]]
    covered = req["covered_by_subscription"] and req["subscription_id"] in subscriptions
    discount_pct = Decimal(str(subscriptions[req["subscription_id"]]["discount_pct"])) \
        if covered else None

    is_no_show = req["work_status"] == "NO_SHOW"
    is_callback = req["request_kind"] == "CALLBACK"
    # 1. Gross labor
    if is_no_show or is_callback:
        labor_gross = 0
    else:
        overage = max(0, (req["actual_labor_minutes"] or 0) - tier["included_minutes"])
        labor_gross = tier["base_price_cents"] + overage * tier["overage_rate_cents_per_min"]
    # 2. Parts lines
    line_items = []
    parts_gross = 0
    if not is_no_show:
        for pid, qty in consumed_parts(request_id):
            p = parts[pid]
            line_total = qty * p["unit_price_cents"]
            line_discount = rhu(discount_pct * line_total) if discount_pct else 0
            parts_gross += line_total
            line_items.append({
                "part_id": pid,
                "sku": p["sku"],
                "quantity": qty,
                "unit_price_cents": p["unit_price_cents"],
                "line_total_cents": line_total,
                "line_discount_cents": line_discount,
            })
    # 3. Discounts (per line, rounded half-up before summing)
    labor_discount = rhu(discount_pct * labor_gross) if discount_pct else 0
    discount_cents = labor_discount + sum(li["line_discount_cents"] for li in line_items)
    line_items.append({
        "part_id": None,
        "sku": "LABOR",
        "quantity": 1,
        "unit_price_cents": labor_gross,
        "line_total_cents": labor_gross,
        "line_discount_cents": labor_discount,
    })
    # 4. Callout
    callout = 0 if is_callback else zone["base_callout_fee_cents"]
    if is_no_show:
        # No-show fee invoice: callout + tax only, surcharge fixed at zero
        subtotal = callout
        surcharge = 0
    else:
        # 5-6. Subtotal and surcharge bracketed on the pre-surcharge subtotal
        subtotal = callout + (labor_gross - labor_discount) \
            + (parts_gross - sum(li["line_discount_cents"] for li in line_items
                                 if li["part_id"] is not None))
        surcharge = route_surcharge(subtotal)
    # 7-8. Tax and total
    tax = rhu(Decimal(subtotal + surcharge) * TAX_RATE)
    total = subtotal + surcharge + tax
    inv = new_common()
    inv.update({
        "service_request_id": request_id,
        "status": "DRAFT",
        "callout_cents": callout,
        "labor_cents": labor_gross,
        "parts_gross_cents": parts_gross,
        "discount_cents": discount_cents,
        "subtotal_cents": subtotal,
        "surcharge_cents": surcharge,
        "tax_cents": tax,
        "total_cents": total,
        "credit_applied_cents": 0,
        "amount_paid_cents": 0,
        "line_items": line_items if not is_no_show else [],
        "is_no_show_fee": is_no_show,
    })
    invoices[inv["id"]] = inv
    return respond(s_invoice(inv), "object", 201)


@app.route("/v1/service-requests/<request_id>/invoices", methods=["GET"])
def list_request_invoices(request_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    get_or_404(service_requests, request_id)
    items = [inv for inv in invoices.values()
             if inv["service_request_id"] == request_id]
    return paginate_and_respond(items, s_invoice)


@app.route("/v1/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    inv = get_or_404(invoices, invoice_id)
    return respond(s_invoice(inv), "object", 200)


@app.route("/v1/invoices/<invoice_id>/events", methods=["POST"])
def invoice_events(invoice_id):
    uid, role = authenticate()
    authorize(role, {"Customer", "Dispatcher", "PlatformAdmin"})
    inv = get_or_404(invoices, invoice_id)
    d = get_body({"event_type", "amount_cents", "use_credit", "dispute_reason"})
    event = v_enum(d, "event_type", {"ISSUE", "PAY", "DISPUTE", "VOID"})
    req = service_requests.get(inv["service_request_id"])
    if event in ("ISSUE", "VOID"):
        if role not in ("Dispatcher", "PlatformAdmin"):
            err("ERR_FORBIDDEN", 403, "Only Dispatcher or PlatformAdmin may %s" % event)
    else:  # PAY, DISPUTE — owning customer only
        if role != "Customer" or req is None or uid != req["customer_id"]:
            err("ERR_FORBIDDEN", 403, "Only the owning customer may %s" % event)
    if event == "PAY":
        amount = v_int(d, "amount_cents")
    use_credit = v_bool(d, "use_credit", required=False, default=False)

    cur = inv["status"]
    if event == "ISSUE":
        if cur not in ("DRAFT", "DISPUTED"):
            err("ERR_INVOICE_NOT_ISSUED", 409, "Invoice cannot be issued from %s" % cur)
        inv["status"] = "ISSUED"
        bump(inv)
        if req is not None:
            req["billing_status"] = "INVOICED"
            bump(req)
    elif event == "DISPUTE":
        if cur != "ISSUED":
            err("ERR_INVOICE_NOT_ISSUED", 409, "Invoice is not ISSUED")
        inv["status"] = "DISPUTED"
        bump(inv)
        if req is not None:
            req["billing_status"] = "DISPUTED"
            bump(req)
    elif event == "VOID":
        if cur not in ("DRAFT", "DISPUTED"):
            err("ERR_INVOICE_NOT_ISSUED", 409, "Invoice cannot be voided from %s" % cur)
        was_disputed = cur == "DISPUTED"
        inv["status"] = "VOID"
        bump(inv)
        if was_disputed and req is not None:
            req["billing_status"] = "ESTIMATED"
            bump(req)
    else:  # PAY
        if cur != "ISSUED":
            err("ERR_INVOICE_NOT_ISSUED", 409, "Invoice is not ISSUED")
        customer = customers.get(req["customer_id"]) if req is not None else None
        credit_balance = customer["account_credit_cents"] if customer else 0
        credit_applied = min(credit_balance, inv["total_cents"]) if use_credit else 0
        if amount != inv["total_cents"] - credit_applied:
            err("ERR_PAYMENT_MISMATCH", 422,
                "amount_cents must equal total_cents - credit_applied_cents")
        inv["status"] = "PAID"
        inv["credit_applied_cents"] = credit_applied
        inv["amount_paid_cents"] = amount
        bump(inv)
        if customer is not None and credit_applied:
            customer["account_credit_cents"] -= credit_applied
            bump(customer)
        if req is not None:
            req["billing_status"] = "PAID"
            if req["work_status"] == "COMPLETED":
                req["work_status"] = "CLOSED"
            bump(req)
    return respond(s_invoice(inv), "object", 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import time as _time

    _port = int(os.environ.get("PORT", "10000"))
    # The harness SIGKILLs the previous server on this port right before
    # re-running start.sh; retry the bind so a lingering socket during the
    # kill window cannot abort the boot.
    for _attempt in range(50):
        try:
            app.run(host="0.0.0.0", port=_port)
            break
        except OSError:
            _time.sleep(0.2)
