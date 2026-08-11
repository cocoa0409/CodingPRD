"""
Mobile Coffee-Cart & Barista Events API (Task 0996)

Single-file Flask implementation. In-memory storage only (dicts keyed by id);
the store is empty on every boot — nothing is seeded. A server-side logical
clock starts at exactly 2026-05-01T00:00:00Z and never falls back to wall
clock; all temporal rules (lead time, amend/cancel windows, notice hours,
automatic CONFIRMED -> IN_PROGRESS transitions) read that clock.

All monetary values are integer cents. Rounding follows the PRD exactly:
deposit rounded half-up before clamping, refunds floored last, cup estimates
and assignment durations ceiled.
"""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD.yaml / PRD.md)
# ---------------------------------------------------------------------------
ROLES = {"OperationsManager", "Client", "Barista"}

MIN_BOOKING_LEAD_HOURS = 24
AMEND_WINDOW_HOURS = 48
TRAVEL_BUFFER_MINUTES = 90
METERED_MAX_KM = 25
DEPOSIT_PCT = Decimal("0.30")
DEPOSIT_MIN_CENTS = 1000
DEPOSIT_MAX_CENTS = 50000
SHORT_NOTICE_FACTOR = Decimal("0.5")
LONG_NOTICE_THRESHOLD_HOURS = 168
# CUPS_PER_GUEST = 1.5, kept as an exact fraction (3/2)

BOOKING_STATUSES = {"QUOTE", "PENDING_DEPOSIT", "CONFIRMED", "IN_PROGRESS",
                    "COMPLETED", "CANCELLED", "REFUNDED"}
ASSIGNMENT_TERMINAL = {"DECLINED", "CANCELLED", "COMPLETED", "NO_SHOW"}
ASSIGNMENT_LIVE = {"OFFERED", "ACCEPTED", "CONFIRMED"}
PAYMENT_KINDS = {"DEPOSIT", "BALANCE", "REFUND"}
SKILL_LEVELS = {"JUNIOR", "SENIOR", "LEAD"}
PRICING_MODELS = {"FLAT", "PER_CUP"}

# ---------------------------------------------------------------------------
# In-memory store (empty on every boot; nothing is seeded)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}

clients = {}
carts = {}
baristas = {}
packages = {}
addons = {}
travel_zones = {}
bookings = {}
booking_addons = {}        # BookingAddOn rows (parent: EventBooking)
assignments = {}           # BaristaAssignment rows (parent: EventBooking)
inventory_items = {}
reservations = {}          # InventoryReservation rows (parent: EventBooking)
payments = {}              # Payment rows (parent: EventBooking)
cancellation_tiers = {}

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
# Time helpers (logical clock only)
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


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD §1.0 / PRD §2.2)
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


def error_body(error_id, message):
    return {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return jsonify(error_body("ERR_RESOURCE_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify(error_body("ERR_RESOURCE_NOT_FOUND", "Method not allowed")), 405


@app.errorhandler(Exception)
def handle_generic(e):
    return jsonify(error_body("ERR_INTERNAL", "Internal server error")), 500


# ---------------------------------------------------------------------------
# Auth (PRD §2.1)
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers are required and role must be a declared role")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")


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


def v_int(d, key, required=True, default=None, minimum=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if isinstance(val, bool) or not isinstance(val, int):
        err("ERR_VALIDATION", 400, "%s must be an integer" % key)
    if minimum is not None and val < minimum:
        err("ERR_VALIDATION", 400, "%s is below its minimum" % key)
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
# Pagination (PRD §2.3: limit/offset, defaults 10/0, limit in [1,100])
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
            err("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if off is None:
        offset = 0
    else:
        try:
            offset = int(off)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", 400, "offset must be non-negative")
    return limit, offset


def paginate_and_respond(items, serializer):
    limit, offset = get_pagination()
    items = sorted(items, key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pagination = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": has_more}
    return respond([serializer(x) for x in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_common():
    ts = fmt_ts(now())
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def new_join():
    """BookingAddOn / Payment carry only id + created_at (PRD §2.4)."""
    ts = fmt_ts(now())
    return {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next_seq()}


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = fmt_ts(now())


def touch(rec):
    rec["updated_at"] = fmt_ts(now())


def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        err("ERR_RESOURCE_NOT_FOUND", 404, "Resource not found: %s" % rid)
    return rec


def clean(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Derived (computed-on-read) values
# ---------------------------------------------------------------------------
def assignment_duration(a):
    """ceil((event_end - event_start)/3600) against the parent booking window."""
    b = bookings[a["booking_id"]]
    secs = int((b["_ee"] - b["_es"]).total_seconds())
    if secs <= 0:
        return 0
    return (secs + 3599) // 3600


def barista_committed_hours(barista_id):
    total = 0
    for a in assignments.values():
        if a["barista_id"] == barista_id and a["status"] in ("ACCEPTED", "CONFIRMED"):
            total += assignment_duration(a)
    return total


def cart_committed_event_count(cart_id):
    return sum(1 for b in bookings.values()
               if b["cart_id"] == cart_id and b["status"] in ("CONFIRMED", "IN_PROGRESS"))


def item_reserved_units(item_id):
    return sum(r["qty_units"] for r in reservations.values()
               if r["item_id"] == item_id and r["status"] in ("RESERVED", "COMMITTED"))


def item_consumed_units(item_id):
    return sum(r["qty_consumed"] for r in reservations.values()
               if r["item_id"] == item_id
               and r["status"] in ("PARTIALLY_CONSUMED", "RECONCILED"))


def booking_paid(booking_id, kind):
    return sum(p["amount_cents"] for p in payments.values()
               if p["booking_id"] == booking_id and p["kind"] == kind
               and p["status"] == "SUCCEEDED")


def booking_balance_due(b):
    if b["balance_waived_flag"]:
        return 0
    return (b["quoted_total_cents"] - booking_paid(b["id"], "DEPOSIT")
            - booking_paid(b["id"], "BALANCE"))


def booking_addons_of(booking_id):
    return [ba for ba in booking_addons.values() if ba["booking_id"] == booking_id]


def assignments_of(booking_id):
    return [a for a in assignments.values() if a["booking_id"] == booking_id]


def reservations_of(booking_id):
    return [r for r in reservations.values() if r["booking_id"] == booking_id]


def live_assignments_of(booking_id):
    return [a for a in assignments_of(booking_id) if a["status"] in ASSIGNMENT_LIVE]


# ---------------------------------------------------------------------------
# Pricing engine (SCAFFOLD §1.3 / PRD §3.3)
# ---------------------------------------------------------------------------
def compute_quote(b):
    """Returns (subtotal, travel_fee, total, deposit_due, pricing_variant,
    travel_variant). Raises ERR_SUBTOTAL_BELOW_ZONE_MINIMUM after the subtotal
    is known and before any fee math (pinned evaluation order)."""
    pkg = packages[b["package_id"]]
    addon_sum = sum(ba["applied_price_cents"] for ba in booking_addons_of(b["id"]))
    if pkg["pricing_model"] == "FLAT":
        pricing_variant = "FLAT_PACKAGE"
        subtotal = pkg["flat_price_cents"] + addon_sum
    else:
        pricing_variant = "PER_CUP_METERED"
        # ceil(guest_count * 1.5) with exact integer arithmetic
        estimated_cups = (b["guest_count"] * 3 + 1) // 2
        metered = estimated_cups * pkg["per_cup_price_cents"]
        subtotal = max(metered, pkg["per_cup_minimum_cents"]) + addon_sum

    zone = travel_zones[b["travel_zone_id"]]
    if subtotal < zone["min_booking_subtotal_cents"]:
        err("ERR_SUBTOTAL_BELOW_ZONE_MINIMUM", 422,
            "quoted_subtotal_cents is below the travel zone minimum")

    if b["distance_km"] <= METERED_MAX_KM:
        travel_variant = "METERED"
        travel_fee = b["distance_km"] * zone["per_km_rate_cents"]
    else:
        travel_variant = "BANDED"
        travel_fee = zone["banded_fee_cents"]

    total = subtotal + travel_fee
    raw = (Decimal(total) * DEPOSIT_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    deposit_due = int(min(max(raw, DEPOSIT_MIN_CENTS), DEPOSIT_MAX_CENTS))
    return subtotal, travel_fee, total, deposit_due, pricing_variant, travel_variant


# ---------------------------------------------------------------------------
# Overlap / scheduling guards (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def cart_double_booked(b):
    bs = b["_es"] - timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    be = b["_ee"] + timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    for o in bookings.values():
        if o["id"] == b["id"] or o["cart_id"] != b["cart_id"]:
            continue
        if o["status"] not in ("PENDING_DEPOSIT", "CONFIRMED", "IN_PROGRESS"):
            continue
        os_ = o["_es"] - timedelta(minutes=TRAVEL_BUFFER_MINUTES)
        oe = o["_ee"] + timedelta(minutes=TRAVEL_BUFFER_MINUTES)
        if bs < oe and os_ < be:
            return True
    return False


def barista_double_booked(a):
    b = bookings[a["booking_id"]]
    for o in assignments.values():
        if o["id"] == a["id"] or o["barista_id"] != a["barista_id"]:
            continue
        if o["status"] not in ("ACCEPTED", "CONFIRMED"):
            continue
        ob = bookings[o["booking_id"]]
        # half-open [start, end) overlap; adjacency (end == start) is allowed
        if b["_es"] < ob["_ee"] and ob["_es"] < b["_ee"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def s_client(c):
    return clean(c)


def s_cart(c):
    d = clean(c)
    d["committed_event_count"] = cart_committed_event_count(c["id"])
    return d


def s_barista(r):
    d = clean(r)
    d["committed_hours_this_week"] = barista_committed_hours(r["id"])
    return d


def s_package(p):
    return clean(p)


def s_addon(a):
    return clean(a)


def s_zone(z):
    return clean(z)


def s_booking(b):
    d = clean(b)
    d["deposit_paid_cents"] = booking_paid(b["id"], "DEPOSIT")
    d["balance_paid_cents"] = booking_paid(b["id"], "BALANCE")
    d["refund_paid_cents"] = booking_paid(b["id"], "REFUND")
    d["balance_due_cents"] = booking_balance_due(b)
    return d


def s_booking_addon(ba):
    return clean(ba)


def s_assignment(a):
    d = clean(a)
    d["duration_hours"] = assignment_duration(a)
    return d


def s_item(it):
    d = clean(it)
    d["reserved_units"] = item_reserved_units(it["id"])
    d["consumed_units_lifetime"] = item_consumed_units(it["id"])
    return d


def s_reservation(r):
    return clean(r)


def s_payment(p):
    return clean(p)


def s_tier(t):
    return clean(t)


# ---------------------------------------------------------------------------
# Shared validation blocks
# ---------------------------------------------------------------------------
def check_event_window(es_dt, ee_dt):
    if not (es_dt < ee_dt):
        err("ERR_EVENT_WINDOW_INVALID", 422, "event_end must be later than event_start")
    if es_dt < now() + timedelta(hours=MIN_BOOKING_LEAD_HOURS):
        err("ERR_EVENT_WINDOW_INVALID", 422,
            "event_start must be at least %d hours ahead of the current time"
            % MIN_BOOKING_LEAD_HOURS)


def check_venue_hookup(cart, provides_power, provides_water):
    if cart["requires_power_hookup"] and not provides_power:
        err("ERR_VENUE_HOOKUP_MISMATCH", 422,
            "Cart requires a power hookup but the venue does not provide power")
    if cart["requires_water_hookup"] and not provides_water:
        err("ERR_VENUE_HOOKUP_MISMATCH", 422,
            "Cart requires a water hookup but the venue does not provide water")


def check_guest_count(pkg, guest_count):
    if guest_count < 1 or guest_count > pkg["max_guests"]:
        err("ERR_GUEST_COUNT_OUT_OF_RANGE", 422,
            "guest_count must be between 1 and the package max_guests")


def require_active(rec, error_id, label):
    if rec["status"] != "ACTIVE":
        err(error_id, 409, "%s is not ACTIVE" % label)


def require_booking_owner(b, uid, role):
    if role == "Client" and b["client_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Clients may only act on their own bookings")


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def cascade_confirm_booking(b):
    """PENDING_DEPOSIT -> CONFIRMED side effects."""
    b["status"] = "CONFIRMED"
    bump(b)
    for a in assignments_of(b["id"]):
        if a["status"] in ("OFFERED", "ACCEPTED"):
            a["status"] = "CONFIRMED"
            bump(a)
    for r in reservations_of(b["id"]):
        if r["status"] == "RESERVED":
            r["status"] = "COMMITTED"
            bump(r)


def create_payment_row(booking_id, kind, amount_cents, idempotency_key):
    p = new_join()
    p.update({"booking_id": booking_id, "kind": kind, "amount_cents": amount_cents,
              "status": "PENDING", "idempotency_key": idempotency_key})
    payments[p["id"]] = p
    return p


def run_automatic_transitions():
    """Clock-driven transitions: CONFIRMED -> IN_PROGRESS once the clock
    reaches event_start."""
    for b in bookings.values():
        if b["status"] == "CONFIRMED" and now() >= b["_es"]:
            b["status"] = "IN_PROGRESS"
            bump(b)


# ---------------------------------------------------------------------------
# Logical clock endpoint
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    d = get_body({"to_iso8601"})
    raw = v_datetime(d, "to_iso8601")
    CLOCK["now"] = parse_iso(raw)
    run_automatic_transitions()
    return respond({"current_utc": fmt_ts(CLOCK["now"])}, "object", 200)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/clients", methods=["POST"])
def create_client():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    d = get_body({"company_name", "contact_email"})
    company_name = v_str(d, "company_name")
    contact_email = v_str(d, "contact_email")
    c = new_common()
    c.update({"company_name": company_name, "contact_email": contact_email,
              "status": "ACTIVE"})
    clients[c["id"]] = c
    return respond(s_client(c), "object", 201)


@app.route("/coffee-cart/clients", methods=["GET"])
def list_clients():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    items = list(clients.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate_and_respond(items, s_client)


@app.route("/coffee-cart/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    c = get_or_404(clients, client_id)
    return respond(s_client(c), "object", 200)


# ---------------------------------------------------------------------------
# Coffee carts
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/carts", methods=["POST"])
def create_cart():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    d = get_body({"cart_code", "max_drinks_per_hour", "requires_power_hookup",
                  "requires_water_hookup", "home_base_lat", "home_base_lng"})
    c = new_common()
    c.update({
        "cart_code": v_str(d, "cart_code"),
        "status": "ACTIVE",
        "max_drinks_per_hour": v_int(d, "max_drinks_per_hour"),
        "requires_power_hookup": v_bool(d, "requires_power_hookup"),
        "requires_water_hookup": v_bool(d, "requires_water_hookup"),
        "home_base_lat": v_number(d, "home_base_lat"),
        "home_base_lng": v_number(d, "home_base_lng"),
    })
    carts[c["id"]] = c
    return respond(s_cart(c), "object", 201)


@app.route("/coffee-cart/carts", methods=["GET"])
def list_carts():
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    items = list(carts.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate_and_respond(items, s_cart)


@app.route("/coffee-cart/carts/<cart_id>", methods=["GET"])
def get_cart(cart_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    c = get_or_404(carts, cart_id)
    return respond(s_cart(c), "object", 200)


# ---------------------------------------------------------------------------
# Baristas
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/baristas", methods=["POST"])
def create_barista():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    d = get_body({"full_name", "skill_level", "latte_art_certified",
                  "hourly_rate_cents", "weekly_hour_cap"})
    r = new_common()
    r.update({
        "full_name": v_str(d, "full_name"),
        "status": "ACTIVE",
        "skill_level": v_enum(d, "skill_level", SKILL_LEVELS),
        "latte_art_certified": v_bool(d, "latte_art_certified"),
        "hourly_rate_cents": v_int(d, "hourly_rate_cents"),
        "weekly_hour_cap": v_int(d, "weekly_hour_cap"),
    })
    baristas[r["id"]] = r
    return respond(s_barista(r), "object", 201)


@app.route("/coffee-cart/baristas", methods=["GET"])
def list_baristas():
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Barista"})
    items = list(baristas.values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    skill = request.args.get("skill_level")
    if skill is not None:
        items = [r for r in items if r["skill_level"] == skill]
    return paginate_and_respond(items, s_barista)


@app.route("/coffee-cart/baristas/<barista_id>", methods=["GET"])
def get_barista(barista_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Barista", "Client"})
    r = get_or_404(baristas, barista_id)
    return respond(s_barista(r), "object", 200)


@app.route("/coffee-cart/baristas/<barista_id>/assignments", methods=["GET"])
def list_barista_assignments(barista_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Barista"})
    get_or_404(baristas, barista_id)
    items = [a for a in assignments.values() if a["barista_id"] == barista_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate_and_respond(items, s_assignment)


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/packages", methods=["POST"])
def create_package():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    d = get_body({"package_code", "pricing_model", "base_hours", "included_drinks",
                  "flat_price_cents", "per_cup_price_cents", "per_cup_minimum_cents",
                  "max_guests"})
    p = new_common()
    p.update({
        "package_code": v_str(d, "package_code"),
        "status": "ACTIVE",
        "pricing_model": v_enum(d, "pricing_model", PRICING_MODELS),
        "base_hours": v_int(d, "base_hours"),
        "included_drinks": v_int(d, "included_drinks"),
        "flat_price_cents": v_int(d, "flat_price_cents"),
        "per_cup_price_cents": v_int(d, "per_cup_price_cents"),
        "per_cup_minimum_cents": v_int(d, "per_cup_minimum_cents"),
        "max_guests": v_int(d, "max_guests"),
    })
    packages[p["id"]] = p
    return respond(s_package(p), "object", 201)


@app.route("/coffee-cart/packages", methods=["GET"])
def list_packages():
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    items = list(packages.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    model = request.args.get("pricing_model")
    if model is not None:
        items = [p for p in items if p["pricing_model"] == model]
    return paginate_and_respond(items, s_package)


@app.route("/coffee-cart/packages/<package_id>", methods=["GET"])
def get_package(package_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    p = get_or_404(packages, package_id)
    return respond(s_package(p), "object", 200)


# ---------------------------------------------------------------------------
# Add-ons
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/addons", methods=["POST"])
def create_addon():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    d = get_body({"addon_code", "price_cents", "requires_lead_barista",
                  "requires_latte_art_cert"})
    a = new_common()
    a.update({
        "addon_code": v_str(d, "addon_code"),
        "status": "ACTIVE",
        "price_cents": v_int(d, "price_cents"),
        "requires_lead_barista": v_bool(d, "requires_lead_barista"),
        "requires_latte_art_cert": v_bool(d, "requires_latte_art_cert"),
    })
    addons[a["id"]] = a
    return respond(s_addon(a), "object", 201)


@app.route("/coffee-cart/addons", methods=["GET"])
def list_addons():
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    items = list(addons.values())
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate_and_respond(items, s_addon)


@app.route("/coffee-cart/addons/<addon_id>", methods=["GET"])
def get_addon(addon_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    a = get_or_404(addons, addon_id)
    return respond(s_addon(a), "object", 200)


@app.route("/coffee-cart/addons/<addon_id>/booking-addons", methods=["GET"])
def list_addon_booking_addons(addon_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    get_or_404(addons, addon_id)
    items = [ba for ba in booking_addons.values() if ba["addon_id"] == addon_id]
    return paginate_and_respond(items, s_booking_addon)


# ---------------------------------------------------------------------------
# Travel zones
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/travel-zones", methods=["POST"])
def create_zone():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    d = get_body({"zone_code", "max_distance_km", "banded_fee_cents",
                  "per_km_rate_cents", "min_booking_subtotal_cents"})
    z = new_common()
    z.update({
        "zone_code": v_str(d, "zone_code"),
        "status": "ACTIVE",
        "max_distance_km": v_int(d, "max_distance_km"),
        "banded_fee_cents": v_int(d, "banded_fee_cents"),
        "per_km_rate_cents": v_int(d, "per_km_rate_cents"),
        "min_booking_subtotal_cents": v_int(d, "min_booking_subtotal_cents"),
    })
    travel_zones[z["id"]] = z
    return respond(s_zone(z), "object", 201)


@app.route("/coffee-cart/travel-zones", methods=["GET"])
def list_zones():
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    items = list(travel_zones.values())
    status = request.args.get("status")
    if status is not None:
        items = [z for z in items if z["status"] == status]
    return paginate_and_respond(items, s_zone)


@app.route("/coffee-cart/travel-zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    z = get_or_404(travel_zones, zone_id)
    return respond(s_zone(z), "object", 200)


# ---------------------------------------------------------------------------
# Inventory items
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/inventory-items", methods=["POST"])
def create_item():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    d = get_body({"sku", "on_hand_units", "reorder_threshold_units"})
    it = new_common()
    it.update({
        "sku": v_str(d, "sku"),
        "status": "ACTIVE",
        "on_hand_units": v_int(d, "on_hand_units"),
        "reorder_threshold_units": v_int(d, "reorder_threshold_units"),
    })
    inventory_items[it["id"]] = it
    return respond(s_item(it), "object", 201)


@app.route("/coffee-cart/inventory-items", methods=["GET"])
def list_items():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    items = list(inventory_items.values())
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return paginate_and_respond(items, s_item)


@app.route("/coffee-cart/inventory-items/<item_id>", methods=["GET"])
def get_item(item_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    it = get_or_404(inventory_items, item_id)
    return respond(s_item(it), "object", 200)


@app.route("/coffee-cart/inventory-items/<item_id>/reservations", methods=["GET"])
def list_item_reservations(item_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    get_or_404(inventory_items, item_id)
    items = [r for r in reservations.values() if r["item_id"] == item_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate_and_respond(items, s_reservation)


# ---------------------------------------------------------------------------
# Cancellation policy tiers
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/cancellation-tiers", methods=["POST"])
def create_tier():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    d = get_body({"tier_code", "min_notice_hours", "max_notice_hours",
                  "deposit_refund_pct", "balance_waived"})
    pct = v_number(d, "deposit_refund_pct")
    if pct < 0 or pct > 1:
        err("ERR_VALIDATION", 400, "deposit_refund_pct must be between 0 and 1")
    t = new_common()
    t.update({
        "tier_code": v_str(d, "tier_code"),
        "min_notice_hours": v_int(d, "min_notice_hours"),
        "max_notice_hours": v_int(d, "max_notice_hours"),
        "deposit_refund_pct": pct,
        "balance_waived": v_bool(d, "balance_waived"),
        "status": "ACTIVE",
    })
    cancellation_tiers[t["id"]] = t
    return respond(s_tier(t), "object", 201)


@app.route("/coffee-cart/cancellation-tiers", methods=["GET"])
def list_tiers():
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    items = list(cancellation_tiers.values())
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return paginate_and_respond(items, s_tier)


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------
BOOKING_FIELDS = {"client_id", "package_id", "cart_id", "travel_zone_id",
                  "event_start", "event_end", "guest_count",
                  "venue_provides_power", "venue_provides_water", "distance_km"}


@app.route("/coffee-cart/bookings", methods=["POST"])
def create_booking():
    uid, role = authenticate()
    authorize(role, {"Client"})
    d = get_body(BOOKING_FIELDS)
    client_id = v_str(d, "client_id")
    package_id = v_str(d, "package_id")
    cart_id = v_str(d, "cart_id")
    travel_zone_id = v_str(d, "travel_zone_id")
    event_start = v_datetime(d, "event_start")
    event_end = v_datetime(d, "event_end")
    guest_count = v_int(d, "guest_count")
    venue_provides_power = v_bool(d, "venue_provides_power")
    venue_provides_water = v_bool(d, "venue_provides_water")
    distance_km = v_int(d, "distance_km", minimum=0)

    # body-FK existence (§2.10 priority 4)
    get_or_404(clients, client_id)
    pkg = get_or_404(packages, package_id)
    cart = get_or_404(carts, cart_id)
    zone = get_or_404(travel_zones, travel_zone_id)

    # ownership: a client books only for their own account
    if client_id != uid:
        err("ERR_UNAUTHORIZED", 403, "Clients may only create bookings for their own account")

    # catalog liveness (§2.9)
    require_active(pkg, "ERR_PACKAGE_NOT_ACTIVE", "Package")
    require_active(cart, "ERR_CART_NOT_ACTIVE", "CoffeeCart")
    require_active(zone, "ERR_ZONE_NOT_ACTIVE", "TravelZone")

    es_dt = parse_iso(event_start)
    ee_dt = parse_iso(event_end)
    check_event_window(es_dt, ee_dt)
    check_venue_hookup(cart, venue_provides_power, venue_provides_water)
    check_guest_count(pkg, guest_count)

    b = new_common()
    b.update({
        "client_id": client_id,
        "package_id": package_id,
        "cart_id": cart_id,
        "travel_zone_id": travel_zone_id,
        "status": "QUOTE",
        "event_start": event_start,
        "event_end": event_end,
        "guest_count": guest_count,
        "venue_provides_power": venue_provides_power,
        "venue_provides_water": venue_provides_water,
        "distance_km": distance_km,
        "quoted_subtotal_cents": 0,
        "quoted_travel_fee_cents": 0,
        "quoted_total_cents": 0,
        "deposit_due_cents": 0,
        "pricing_variant_used": None,
        "travel_variant_used": None,
        "cancellation_reason": None,
        "cancelled_at": None,
        "balance_waived_flag": False,
        "_es": es_dt,
        "_ee": ee_dt,
        "_refund_cents": None,
    })
    bookings[b["id"]] = b
    return respond(s_booking(b), "object", 201)


@app.route("/coffee-cart/bookings", methods=["GET"])
def list_bookings():
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    items = list(bookings.values())
    if role == "Client":
        # own scope only
        items = [b for b in items if b["client_id"] == uid]
    for f in ("status", "client_id", "cart_id", "package_id", "travel_zone_id"):
        v = request.args.get(f)
        if v is not None:
            items = [b for b in items if b[f] == v]
    return paginate_and_respond(items, s_booking)


@app.route("/coffee-cart/bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client", "Barista"})
    b = get_or_404(bookings, booking_id)
    return respond(s_booking(b), "object", 200)


# --- Booking add-ons -------------------------------------------------------
@app.route("/coffee-cart/bookings/<booking_id>/addons", methods=["POST"])
def attach_addon(booking_id):
    uid, role = authenticate()
    authorize(role, {"Client"})
    b = get_or_404(bookings, booking_id)
    require_booking_owner(b, uid, role)
    d = get_body({"addon_id"})
    addon_id = v_str(d, "addon_id")
    addon = get_or_404(addons, addon_id)
    if b["status"] != "QUOTE":
        err("ERR_INVALID_STATE", 409, "Add-ons may only be attached while the booking is in QUOTE")
    require_active(addon, "ERR_ADDON_NOT_ACTIVE", "AddOn")
    ba = new_join()
    ba.update({"booking_id": b["id"], "addon_id": addon_id,
               "applied_price_cents": addon["price_cents"]})
    booking_addons[ba["id"]] = ba
    touch(b)  # attach refreshes the booking's updated_at
    return respond(s_booking_addon(ba), "object", 201)


@app.route("/coffee-cart/bookings/<booking_id>/addons", methods=["GET"])
def list_booking_addons(booking_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    b = get_or_404(bookings, booking_id)
    require_booking_owner(b, uid, role)
    return paginate_and_respond(booking_addons_of(booking_id), s_booking_addon)


# --- Booking assignments (offers) ------------------------------------------
@app.route("/coffee-cart/bookings/<booking_id>/assignments", methods=["POST"])
def offer_assignment(booking_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    b = get_or_404(bookings, booking_id)
    d = get_body({"barista_id", "is_primary"})
    barista_id = v_str(d, "barista_id")
    is_primary = v_bool(d, "is_primary")
    get_or_404(baristas, barista_id)
    if b["status"] not in ("QUOTE", "PENDING_DEPOSIT", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409,
            "Assignments may only be offered while the booking is QUOTE, PENDING_DEPOSIT or CONFIRMED")
    if is_primary:
        for a in assignments_of(booking_id):
            if a["is_primary"] and a["status"] in ASSIGNMENT_LIVE:
                err("ERR_VALIDATION", 400,
                    "The booking already has a primary barista assignment")
    a = new_common()
    a.update({"booking_id": booking_id, "barista_id": barista_id,
              "status": "OFFERED", "is_primary": is_primary,
              "decline_reason": None})
    assignments[a["id"]] = a
    return respond(s_assignment(a), "object", 201)


@app.route("/coffee-cart/bookings/<booking_id>/assignments", methods=["GET"])
def list_booking_assignments(booking_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client", "Barista"})
    b = get_or_404(bookings, booking_id)
    require_booking_owner(b, uid, role)
    items = assignments_of(booking_id)
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate_and_respond(items, s_assignment)


# --- Booking inventory reservations ----------------------------------------
@app.route("/coffee-cart/bookings/<booking_id>/reservations", methods=["POST"])
def create_reservation(booking_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    b = get_or_404(bookings, booking_id)
    d = get_body({"item_id", "qty_units"})
    item_id = v_str(d, "item_id")
    qty_units = v_int(d, "qty_units", minimum=1)
    item = get_or_404(inventory_items, item_id)
    if b["status"] != "QUOTE":
        err("ERR_INVALID_STATE", 409,
            "Reservations may only be created while the booking is in QUOTE")
    require_active(item, "ERR_ITEM_NOT_ACTIVE", "InventoryItem")
    available = item["on_hand_units"] - item_reserved_units(item_id)
    if qty_units > available:
        err("ERR_INSUFFICIENT_INVENTORY", 422,
            "Requested units exceed available inventory")
    r = new_common()
    r.update({"booking_id": booking_id, "item_id": item_id,
              "qty_units": qty_units, "qty_consumed": 0, "status": "RESERVED"})
    reservations[r["id"]] = r
    return respond(s_reservation(r), "object", 201)


@app.route("/coffee-cart/bookings/<booking_id>/reservations", methods=["GET"])
def list_booking_reservations(booking_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    b = get_or_404(bookings, booking_id)
    require_booking_owner(b, uid, role)
    items = reservations_of(booking_id)
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate_and_respond(items, s_reservation)


# --- Booking lifecycle actions ----------------------------------------------
@app.route("/coffee-cart/bookings/<booking_id>/submit", methods=["POST"])
def submit_booking(booking_id):
    uid, role = authenticate()
    authorize(role, {"Client"})
    b = get_or_404(bookings, booking_id)
    require_booking_owner(b, uid, role)
    d = get_body({"expected_cart_version", "expected_primary_barista_version"})
    expected_cart_version = v_int(d, "expected_cart_version")
    expected_barista_version = v_int(d, "expected_primary_barista_version")

    # 1. booking state
    if b["status"] != "QUOTE":
        err("ERR_INVALID_STATE", 409, "Only a QUOTE booking may be submitted")
    # 2. catalog liveness of everything the booking references
    pkg = packages[b["package_id"]]
    require_active(pkg, "ERR_PACKAGE_NOT_ACTIVE", "Package")
    cart = carts[b["cart_id"]]
    require_active(cart, "ERR_CART_NOT_ACTIVE", "CoffeeCart")
    zone = travel_zones[b["travel_zone_id"]]
    require_active(zone, "ERR_ZONE_NOT_ACTIVE", "TravelZone")
    for ba in booking_addons_of(booking_id):
        require_active(addons[ba["addon_id"]], "ERR_ADDON_NOT_ACTIVE", "AddOn")
    for r in reservations_of(booking_id):
        if r["status"] in ("RESERVED", "COMMITTED"):
            require_active(inventory_items[r["item_id"]], "ERR_ITEM_NOT_ACTIVE",
                           "InventoryItem")
    # 3. cart schedule (buffered)
    if cart_double_booked(b):
        err("ERR_CART_DOUBLE_BOOKED", 409,
            "The cart is already committed to an overlapping booking window")
    # 4. add-on skill gate
    live = live_assignments_of(booking_id)
    for ba in booking_addons_of(booking_id):
        addon = addons[ba["addon_id"]]
        if addon["requires_latte_art_cert"]:
            if not any(baristas[a["barista_id"]]["latte_art_certified"] for a in live):
                err("ERR_ADDON_SKILL_MISSING", 422,
                    "No assigned barista holds the required latte-art certification")
        if addon["requires_lead_barista"]:
            if not any(baristas[a["barista_id"]]["skill_level"] == "LEAD" for a in live):
                err("ERR_ADDON_SKILL_MISSING", 422,
                    "No assigned barista holds the required LEAD skill level")
    # 5. staffing presence
    if not live:
        err("ERR_NO_BARISTA_ASSIGNED", 422,
            "The booking has no non-terminal barista assignment")
    # 6. recompute quote (subtotal -> zone tier gate -> travel fee -> total -> deposit)
    subtotal, fee, total, deposit_due, pv, tv = compute_quote(b)
    # 7. optimistic concurrency on the two parent entities
    if cart["version"] != expected_cart_version:
        err("ERR_STALE_VERSION", 412, "expected_cart_version does not match the cart's current version")
    primary = next((a for a in live if a["is_primary"]), None)
    primary_barista = None
    if primary is not None:
        primary_barista = baristas[primary["barista_id"]]
        if primary_barista["version"] != expected_barista_version:
            err("ERR_STALE_VERSION", 412,
                "expected_primary_barista_version does not match the barista's current version")
    # commit: reprice, pin variants, transition
    b["quoted_subtotal_cents"] = subtotal
    b["quoted_travel_fee_cents"] = fee
    b["quoted_total_cents"] = total
    b["deposit_due_cents"] = deposit_due
    b["pricing_variant_used"] = pv
    b["travel_variant_used"] = tv
    b["status"] = "PENDING_DEPOSIT"
    bump(b)
    bump(cart)
    if primary_barista is not None:
        bump(primary_barista)
    return respond(s_booking(b), "object", 200)


@app.route("/coffee-cart/bookings/<booking_id>/reopen", methods=["POST"])
def reopen_booking(booking_id):
    uid, role = authenticate()
    authorize(role, {"Client"})
    b = get_or_404(bookings, booking_id)
    require_booking_owner(b, uid, role)
    get_body(set())
    if b["status"] != "PENDING_DEPOSIT":
        err("ERR_INVALID_STATE", 409, "Only a PENDING_DEPOSIT booking may be reopened")
    if booking_paid(booking_id, "DEPOSIT") > 0:
        err("ERR_DEPOSIT_ALREADY_PAID", 409,
            "A succeeded deposit exists; the booking must travel the refund path")
    b["status"] = "QUOTE"
    b["pricing_variant_used"] = None
    b["travel_variant_used"] = None
    bump(b)
    return respond(s_booking(b), "object", 200)


AMEND_FIELDS = {"package_id", "cart_id", "travel_zone_id", "event_start",
                "event_end", "guest_count", "venue_provides_power",
                "venue_provides_water", "distance_km"}


@app.route("/coffee-cart/bookings/<booking_id>/amend", methods=["POST"])
def amend_booking(booking_id):
    uid, role = authenticate()
    authorize(role, {"Client"})
    b = get_or_404(bookings, booking_id)
    require_booking_owner(b, uid, role)
    d = get_body(AMEND_FIELDS)
    # validate types of any provided fields
    new_package_id = v_str(d, "package_id", required=False)
    new_cart_id = v_str(d, "cart_id", required=False)
    new_zone_id = v_str(d, "travel_zone_id", required=False)
    new_start = v_datetime(d, "event_start", required=False)
    new_end = v_datetime(d, "event_end", required=False)
    new_guests = v_int(d, "guest_count", required=False)
    new_power = v_bool(d, "venue_provides_power", required=False)
    new_water = v_bool(d, "venue_provides_water", required=False)
    new_distance = v_int(d, "distance_km", required=False, minimum=0)
    # body-FK existence (priority 4)
    if new_package_id is not None:
        get_or_404(packages, new_package_id)
    if new_cart_id is not None:
        get_or_404(carts, new_cart_id)
    if new_zone_id is not None:
        get_or_404(travel_zones, new_zone_id)
    # state
    if b["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409, "Only a CONFIRMED booking may be amended")
    # amend window: the event must remain more than 48h ahead of the clock
    if not (b["_es"] > now() + timedelta(hours=AMEND_WINDOW_HOURS)):
        err("ERR_AMEND_WINDOW_CLOSED", 409,
            "Amendments are closed within %d hours of event_start" % AMEND_WINDOW_HOURS)

    # merged candidate values
    m_package_id = new_package_id if new_package_id is not None else b["package_id"]
    m_cart_id = new_cart_id if new_cart_id is not None else b["cart_id"]
    m_zone_id = new_zone_id if new_zone_id is not None else b["travel_zone_id"]
    m_start = new_start if new_start is not None else b["event_start"]
    m_end = new_end if new_end is not None else b["event_end"]
    m_guests = new_guests if new_guests is not None else b["guest_count"]
    m_power = new_power if new_power is not None else b["venue_provides_power"]
    m_water = new_water if new_water is not None else b["venue_provides_water"]
    m_distance = new_distance if new_distance is not None else b["distance_km"]

    m_pkg = packages[m_package_id]
    m_cart = carts[m_cart_id]
    m_zone = travel_zones[m_zone_id]
    require_active(m_pkg, "ERR_PACKAGE_NOT_ACTIVE", "Package")
    require_active(m_cart, "ERR_CART_NOT_ACTIVE", "CoffeeCart")
    require_active(m_zone, "ERR_ZONE_NOT_ACTIVE", "TravelZone")

    # re-run the creation-time validations on the merged values
    es_dt = parse_iso(m_start)
    ee_dt = parse_iso(m_end)
    check_event_window(es_dt, ee_dt)
    check_venue_hookup(m_cart, m_power, m_water)
    check_guest_count(m_pkg, m_guests)
    probe = {"id": b["id"], "cart_id": m_cart_id, "_es": es_dt, "_ee": ee_dt}
    if cart_double_booked(probe):
        err("ERR_CART_DOUBLE_BOOKED", 409,
            "The cart is already committed to an overlapping booking window")

    cart_changed = m_cart_id != b["cart_id"]
    old_cart = carts[b["cart_id"]]

    # unwind: assignments CONFIRMED -> OFFERED (re-offer loop), reservations
    # COMMITTED -> RESERVED; deposit payments stay SUCCEEDED (credit carried).
    affected_baristas = set()
    for a in assignments_of(booking_id):
        if a["status"] == "CONFIRMED":
            a["status"] = "OFFERED"
            bump(a)
            affected_baristas.add(a["barista_id"])
    for r in reservations_of(booking_id):
        if r["status"] == "COMMITTED":
            r["status"] = "RESERVED"
            bump(r)

    b.update({
        "package_id": m_package_id,
        "cart_id": m_cart_id,
        "travel_zone_id": m_zone_id,
        "event_start": m_start,
        "event_end": m_end,
        "guest_count": m_guests,
        "venue_provides_power": m_power,
        "venue_provides_water": m_water,
        "distance_km": m_distance,
        "status": "QUOTE",
        "pricing_variant_used": None,
        "travel_variant_used": None,
        "_es": es_dt,
        "_ee": ee_dt,
    })
    bump(b)
    if cart_changed:
        bump(old_cart)
        bump(m_cart)
    for bid in affected_baristas:
        bump(baristas[bid])
    return respond(s_booking(b), "object", 200)


@app.route("/coffee-cart/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    uid, role = authenticate()
    authorize(role, {"Client"})
    b = get_or_404(bookings, booking_id)
    require_booking_owner(b, uid, role)
    d = get_body({"cancellation_reason"})
    reason = d.get("cancellation_reason")
    if reason is not None and not isinstance(reason, str):
        err("ERR_VALIDATION", 400, "cancellation_reason must be a string")

    if b["status"] not in ("QUOTE", "PENDING_DEPOSIT", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409,
            "Only QUOTE, PENDING_DEPOSIT or CONFIRMED bookings may be cancelled")
    if b["status"] == "CONFIRMED" and now() >= b["_es"]:
        err("ERR_CANCEL_WINDOW_CLOSED", 409,
            "Cannot cancel after service has started")

    was_confirmed = b["status"] == "CONFIRMED"
    if reason is not None:
        b["cancellation_reason"] = reason
    b["cancelled_at"] = fmt_ts(now())

    for a in assignments_of(booking_id):
        if a["status"] in ("OFFERED", "ACCEPTED", "CONFIRMED"):
            a["status"] = "CANCELLED"
            bump(a)
    for r in reservations_of(booking_id):
        if r["status"] in ("RESERVED", "COMMITTED"):
            r["status"] = "RELEASED"
            bump(r)

    if was_confirmed:
        # price the refund by notice hours against ACTIVE tiers (creation order)
        notice_hours = int((b["_es"] - now()).total_seconds() // 3600)
        tier = None
        for t in sorted(cancellation_tiers.values(), key=lambda x: x["_seq"]):
            if t["status"] != "ACTIVE":
                continue
            if notice_hours < t["min_notice_hours"]:
                continue
            if t["max_notice_hours"] != -1 and notice_hours >= t["max_notice_hours"]:
                continue
            tier = t
            break
        refund = 0
        if tier is not None:
            base = Decimal(booking_paid(booking_id, "DEPOSIT")) * Decimal(str(tier["deposit_refund_pct"]))
            if notice_hours < LONG_NOTICE_THRESHOLD_HOURS:
                base = base * SHORT_NOTICE_FACTOR
            refund = int(base.to_integral_value(rounding=ROUND_FLOOR))
            if tier["balance_waived"]:
                b["balance_waived_flag"] = True
        b["_refund_cents"] = refund
        if refund > 0:
            create_payment_row(booking_id, "REFUND", refund,
                               "auto-refund-%s" % booking_id)

    b["status"] = "CANCELLED"
    bump(b)
    return respond(s_booking(b), "object", 200)


@app.route("/coffee-cart/bookings/<booking_id>/complete", methods=["POST"])
def complete_booking(booking_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    b = get_or_404(bookings, booking_id)
    get_body(set())
    if b["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", 409, "Only an IN_PROGRESS booking may be completed")
    if now() < b["_ee"]:
        err("ERR_INVALID_STATE", 409, "The booking cannot be completed before event_end")
    for a in assignments_of(booking_id):
        if a["status"] in ("ACCEPTED", "CONFIRMED"):
            err("ERR_UNRESOLVED_ASSIGNMENTS", 409,
                "All assignments must be resolved before completing the booking")
    b["status"] = "COMPLETED"
    bump(b)
    due = booking_balance_due(b)
    if due > 0:
        create_payment_row(booking_id, "BALANCE", due,
                           "auto-balance-%s" % booking_id)
    return respond(s_booking(b), "object", 200)


# ---------------------------------------------------------------------------
# Assignment actions
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Barista", "Client"})
    a = get_or_404(assignments, assignment_id)
    return respond(s_assignment(a), "object", 200)


def require_assignment_owner(a, uid, role):
    if role == "Barista" and a["barista_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Baristas may only act on their own assignments")


@app.route("/coffee-cart/assignments/<assignment_id>/accept", methods=["POST"])
def accept_assignment(assignment_id):
    uid, role = authenticate()
    authorize(role, {"Barista"})
    a = get_or_404(assignments, assignment_id)
    require_assignment_owner(a, uid, role)
    get_body(set())
    if a["status"] != "OFFERED":
        err("ERR_INVALID_STATE", 409, "Only an OFFERED assignment may be accepted")
    barista = baristas[a["barista_id"]]
    if barista["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "The barista is not ACTIVE")
    b = bookings[a["booking_id"]]
    if b["status"] not in ("QUOTE", "PENDING_DEPOSIT", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409,
            "The parent booking does not permit accepting assignments")
    # scheduling guards, in order: double-booking first, weekly cap second
    if barista_double_booked(a):
        err("ERR_BARISTA_DOUBLE_BOOKED", 409,
            "The barista already has an overlapping accepted/confirmed assignment")
    projected = barista_committed_hours(a["barista_id"]) + assignment_duration(a)
    if projected > barista["weekly_hour_cap"]:
        err("ERR_WEEKLY_CAP_EXCEEDED", 422,
            "Accepting would exceed the barista's weekly hour cap")
    a["status"] = "ACCEPTED"
    bump(a)
    bump(barista)
    return respond(s_assignment(a), "object", 200)


@app.route("/coffee-cart/assignments/<assignment_id>/decline", methods=["POST"])
def decline_assignment(assignment_id):
    uid, role = authenticate()
    authorize(role, {"Barista"})
    a = get_or_404(assignments, assignment_id)
    require_assignment_owner(a, uid, role)
    d = get_body({"decline_reason"})
    reason = d.get("decline_reason")
    if reason is not None and not isinstance(reason, str):
        err("ERR_VALIDATION", 400, "decline_reason must be a string")
    if a["status"] != "OFFERED":
        err("ERR_INVALID_STATE", 409, "Only an OFFERED assignment may be declined")
    a["status"] = "DECLINED"
    if reason is not None:
        a["decline_reason"] = reason
    bump(a)
    return respond(s_assignment(a), "object", 200)


@app.route("/coffee-cart/assignments/<assignment_id>/withdraw", methods=["POST"])
def withdraw_assignment(assignment_id):
    uid, role = authenticate()
    authorize(role, {"Barista"})
    a = get_or_404(assignments, assignment_id)
    require_assignment_owner(a, uid, role)
    get_body(set())
    if a["status"] != "ACCEPTED":
        err("ERR_INVALID_STATE", 409, "Only an ACCEPTED assignment may be withdrawn")
    b = bookings[a["booking_id"]]
    if b["status"] == "IN_PROGRESS":
        err("ERR_INVALID_STATE", 409, "Cannot withdraw mid-event")
    a["status"] = "CANCELLED"
    bump(a)
    bump(baristas[a["barista_id"]])
    return respond(s_assignment(a), "object", 200)


@app.route("/coffee-cart/assignments/<assignment_id>/resolve", methods=["POST"])
def resolve_assignment(assignment_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    a = get_or_404(assignments, assignment_id)
    d = get_body({"attended"})
    attended = v_bool(d, "attended")
    if a["status"] not in ("ACCEPTED", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409,
            "Only an ACCEPTED or CONFIRMED assignment may be resolved")
    b = bookings[a["booking_id"]]
    if b["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", 409, "The parent booking is not IN_PROGRESS")
    if now() < b["_ee"]:
        err("ERR_INVALID_STATE", 409, "Assignments may only be resolved at or after event_end")
    if attended:
        a["status"] = "COMPLETED"
    else:
        a["status"] = "NO_SHOW"
    bump(a)
    if not attended:
        bump(baristas[a["barista_id"]])
    return respond(s_assignment(a), "object", 200)


# ---------------------------------------------------------------------------
# Inventory reservation actions
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    r = get_or_404(reservations, reservation_id)
    return respond(s_reservation(r), "object", 200)


@app.route("/coffee-cart/reservations/<reservation_id>/record-consumption", methods=["POST"])
def record_consumption(reservation_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    r = get_or_404(reservations, reservation_id)
    d = get_body({"qty_consumed"})
    qty_consumed = v_int(d, "qty_consumed")
    if r["status"] != "COMMITTED":
        err("ERR_INVALID_STATE", 409,
            "Only a COMMITTED reservation may record consumption")
    b = bookings[r["booking_id"]]
    if b["status"] not in ("IN_PROGRESS", "COMPLETED"):
        err("ERR_INVALID_STATE", 409,
            "Consumption may only be recorded while the booking is IN_PROGRESS or COMPLETED")
    if qty_consumed < 0 or qty_consumed > r["qty_units"]:
        err("ERR_CONSUMPTION_OUT_OF_RANGE", 422,
            "qty_consumed must lie between 0 and qty_units inclusive")
    item = inventory_items[r["item_id"]]
    r["qty_consumed"] = qty_consumed
    r["status"] = "PARTIALLY_CONSUMED"
    bump(r)
    item["on_hand_units"] -= qty_consumed
    bump(item)
    return respond(s_reservation(r), "object", 200)


@app.route("/coffee-cart/reservations/<reservation_id>/reconcile", methods=["POST"])
def reconcile_reservation(reservation_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    r = get_or_404(reservations, reservation_id)
    get_body(set())
    if r["status"] != "PARTIALLY_CONSUMED":
        err("ERR_INVALID_STATE", 409,
            "Only a PARTIALLY_CONSUMED reservation may be reconciled")
    b = bookings[r["booking_id"]]
    if b["status"] != "COMPLETED":
        err("ERR_INVALID_STATE", 409,
            "The parent booking must be COMPLETED before reconciliation")
    r["status"] = "RECONCILED"
    bump(r)
    return respond(s_reservation(r), "object", 200)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@app.route("/coffee-cart/bookings/<booking_id>/payments", methods=["POST"])
def create_payment(booking_id):
    uid, role = authenticate()
    authorize(role, {"Client", "OperationsManager"})
    b = get_or_404(bookings, booking_id)
    require_booking_owner(b, uid, role)
    d = get_body({"kind", "amount_cents", "idempotency_key"})
    kind = v_enum(d, "kind", PAYMENT_KINDS)
    amount = v_int(d, "amount_cents", minimum=1)
    key = v_str(d, "idempotency_key")

    # idempotency, scoped per booking + kind + key
    for p in payments.values():
        if (p["booking_id"] == booking_id and p["kind"] == kind
                and p["idempotency_key"] == key and p["status"] != "FAILED"):
            if p["amount_cents"] != amount:
                err("ERR_IDEMPOTENCY_CONFLICT", 409,
                    "idempotency_key was already used with a different payload")
            # SUCCEEDED (or still PENDING): return the existing row unchanged
            return respond(s_payment(p), "object", 201)

    # amount discipline
    if kind == "DEPOSIT":
        remaining = b["deposit_due_cents"] - booking_paid(booking_id, "DEPOSIT")
        if amount < remaining:
            err("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                "DEPOSIT amount must be at least the outstanding deposit due")
    elif kind == "BALANCE":
        if amount != booking_balance_due(b):
            err("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                "BALANCE amount must equal the current balance_due_cents")
    else:  # REFUND
        if b["_refund_cents"] is not None and amount != b["_refund_cents"]:
            err("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                "REFUND amount must equal the computed cancellation refund")

    p = create_payment_row(booking_id, kind, amount, key)
    return respond(s_payment(p), "object", 201)


@app.route("/coffee-cart/bookings/<booking_id>/payments", methods=["GET"])
def list_booking_payments(booking_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    b = get_or_404(bookings, booking_id)
    require_booking_owner(b, uid, role)
    items = [p for p in payments.values() if p["booking_id"] == booking_id]
    kind = request.args.get("kind")
    if kind is not None:
        items = [p for p in items if p["kind"] == kind]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate_and_respond(items, s_payment)


@app.route("/coffee-cart/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "Client"})
    p = get_or_404(payments, payment_id)
    return respond(s_payment(p), "object", 200)


@app.route("/coffee-cart/payments/<payment_id>/mark-succeeded", methods=["POST"])
def mark_payment_succeeded(payment_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    p = get_or_404(payments, payment_id)
    get_body(set())
    if p["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Only a PENDING payment may be marked succeeded")
    b = bookings[p["booking_id"]]
    if p["kind"] == "DEPOSIT" and b["status"] != "PENDING_DEPOSIT":
        err("ERR_BOOKING_NOT_AWAITING_DEPOSIT", 409,
            "The booking is not awaiting a deposit")
    if p["kind"] == "BALANCE" and b["status"] not in ("CONFIRMED", "IN_PROGRESS", "COMPLETED"):
        err("ERR_INVALID_STATE", 409,
            "The booking status does not permit settling a balance payment")
    if p["kind"] == "REFUND" and b["status"] != "CANCELLED":
        err("ERR_INVALID_STATE", 409,
            "The booking status does not permit settling a refund payment")
    # amount re-validation at settlement time
    if p["kind"] == "DEPOSIT":
        remaining = b["deposit_due_cents"] - booking_paid(b["id"], "DEPOSIT")
        if p["amount_cents"] < remaining:
            err("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                "DEPOSIT amount must be at least the outstanding deposit due")
    elif p["kind"] == "BALANCE":
        if p["amount_cents"] != booking_balance_due(b):
            err("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                "BALANCE amount must equal the current balance_due_cents")
    else:
        if b["_refund_cents"] is not None and p["amount_cents"] != b["_refund_cents"]:
            err("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                "REFUND amount must equal the computed cancellation refund")

    p["status"] = "SUCCEEDED"
    if p["kind"] == "DEPOSIT" and booking_paid(b["id"], "DEPOSIT") >= b["deposit_due_cents"]:
        cascade_confirm_booking(b)  # includes the booking version bump
    if p["kind"] == "REFUND" and b["status"] == "CANCELLED":
        b["status"] = "REFUNDED"
        bump(b)
    return respond(s_payment(p), "object", 200)


@app.route("/coffee-cart/payments/<payment_id>/mark-failed", methods=["POST"])
def mark_payment_failed(payment_id):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    p = get_or_404(payments, payment_id)
    get_body(set())
    if p["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Only a PENDING payment may be marked failed")
    p["status"] = "FAILED"
    return respond(s_payment(p), "object", 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
