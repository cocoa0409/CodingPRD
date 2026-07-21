"""Running & Fit Specialty Store API — single-file Flask implementation.

In-memory only. Fresh boot wipes all state. No seeding at startup.
All 51 endpoints from PRD §4 are registered below.
"""
import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD global_constants / §1.3 calculations)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-07-01T00:00:00Z"
FITTING_BUFFER_MINUTES = 15
RETURN_WINDOW_DAYS = 30
RESTOCK_FEE_PCT = Decimal("0.15")
RACE_CANCELLATION_FEE_CENTS = 500
SUBSCRIPTION_PERIOD_DAYS = 30
POINTS_PER_CENT_DIVISOR = 100
ORDER_MAX_DISCOUNT_PCT = Decimal("0.35")
FITTING_MAX_DISCOUNT_PCT = Decimal("0.30")

LOYALTY_TIER_THRESHOLDS = {"SILVER": 500, "GOLD": 1500, "PLATINUM": 3000}
LOYALTY_DISCOUNT_PCT = {
    "BRONZE": Decimal("0.00"),
    "SILVER": Decimal("0.05"),
    "GOLD": Decimal("0.10"),
    "PLATINUM": Decimal("0.15"),
}
TIER_MONTHLY_FEE_CENTS = {"CLUB_BASIC": 4000, "CLUB_PRO": 8000}
TIER_INCLUDED_FITTINGS = {"CLUB_BASIC": 1, "CLUB_PRO": 3}
TIER_GEAR_DISCOUNT_PCT = {"CLUB_BASIC": Decimal("0.10"), "CLUB_PRO": Decimal("0.20")}
TIER_TRAINING_DISCOUNT_PCT = {"CLUB_BASIC": Decimal("0.10"), "CLUB_PRO": Decimal("0.20")}
FITTING_BASE_CENTS = {"GAIT_ANALYSIS": 6000, "SHOE_FITTING": 3000, "FOLLOWUP": 2000}

ROLES = {"Anonymous", "Member", "Staff", "StoreManager"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.stores = {}
        self.staff = {}
        self.members = {}
        self.products = {}
        self.subscriptions = {}
        self.appointments = {}
        self.sessions = {}
        self.enrollments = {}
        self.events = {}
        self.registrations = {}
        self.orders = {}
        self.shoe_pairs = {}
        self.clock = parse_dt(CLOCK_DEFAULT_UTC)
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


NOT_FOUND = {
    "member": "ERR_MEMBER_NOT_FOUND",
    "store": "ERR_STORE_NOT_FOUND",
    "staff": "ERR_STAFF_NOT_FOUND",
    "product": "ERR_PRODUCT_NOT_FOUND",
    "subscription": "ERR_SUBSCRIPTION_NOT_FOUND",
    "appointment": "ERR_APPOINTMENT_NOT_FOUND",
    "session": "ERR_SESSION_NOT_FOUND",
    "enrollment": "ERR_ENROLLMENT_NOT_FOUND",
    "event": "ERR_EVENT_NOT_FOUND",
    "registration": "ERR_REGISTRATION_NOT_FOUND",
    "order": "ERR_ORDER_NOT_FOUND",
    "shoe_pair": "ERR_SHOE_PAIR_NOT_FOUND",
}


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    if not isinstance(s, str) or not s.strip():
        raise ValueError("bad datetime")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def now_dt():
    return db.clock


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _req_id(),
        "api_request_timestamp": datetime.now(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {"meta": _meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, meta_extra):
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
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
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed."},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")


def owner_guard(role, uid, owner_id):
    """Member owner-scoped check (403 if member acting on a resource they don't own)."""
    if role == "Member" and uid != owner_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Member does not own this resource.")


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object.")
    return b


def v_err(msg="Invalid request body."):
    raise ApiError("ERR_VALIDATION", 400, msg)


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        v_err(f"Field '{name}' is required and must be a non-empty string.")
    return v


def req_enum(b, name, allowed):
    v = b.get(name)
    if v not in allowed:
        v_err(f"Field '{name}' must be one of {sorted(allowed)}.")
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, name, minimum=None):
    v = b.get(name)
    if not is_int(v):
        v_err(f"Field '{name}' is required and must be an integer.")
    if minimum is not None and v < minimum:
        v_err(f"Field '{name}' must be >= {minimum}.")
    return v


def opt_int(b, name, default, minimum=None):
    if name not in b or b.get(name) is None:
        return default
    return req_int(b, name, minimum)


def req_number(b, name, minimum=None, exclusive_min=None):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        v_err(f"Field '{name}' is required and must be a number.")
    if minimum is not None and v < minimum:
        v_err(f"Field '{name}' must be >= {minimum}.")
    if exclusive_min is not None and v <= exclusive_min:
        v_err(f"Field '{name}' must be > {exclusive_min}.")
    return v


def req_dt(b, name):
    v = b.get(name)
    if not isinstance(v, str):
        v_err(f"Field '{name}' is required and must be an ISO 8601 datetime string.")
    try:
        parse_dt(v)
    except Exception:
        v_err(f"Field '{name}' must be a valid ISO 8601 datetime.")
    return v


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def base_entity():
    now = now_dt()
    return {
        "id": str(uuid.uuid4()),
        "created_at": fmt_dt(now),
        "updated_at": fmt_dt(now),
        "version": 1,
        "_seq": db.next_seq(),
        "_created_dt": now,
    }


def touch(e):
    e["version"] += 1
    e["updated_at"] = fmt_dt(now_dt())


def serialize(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def get_or_404(coll, rid, kind):
    e = coll.get(rid)
    if e is None:
        raise ApiError(NOT_FOUND[kind], 404, f"{kind} not found.")
    return e


def sort_key(e):
    return (e["_created_dt"], e["_seq"])


def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tier_from_points(p):
    if p >= LOYALTY_TIER_THRESHOLDS["PLATINUM"]:
        return "PLATINUM"
    if p >= LOYALTY_TIER_THRESHOLDS["GOLD"]:
        return "GOLD"
    if p >= LOYALTY_TIER_THRESHOLDS["SILVER"]:
        return "SILVER"
    return "BRONZE"


def member_live_subscription(member_id):
    """The member's single non-CANCELLED subscription (PENDING/ACTIVE/PAST_DUE), if any."""
    live = [
        s
        for s in db.subscriptions.values()
        if s["member_id"] == member_id and s["status"] != "CANCELLED"
    ]
    if not live:
        return None
    live.sort(key=sort_key)
    return live[-1]


def member_active_subscription(member_id):
    s = member_live_subscription(member_id)
    if s and s["status"] == "ACTIVE":
        return s
    return None


def paginate(items):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            v_err("limit must be an integer.")
        if limit < 1 or limit > 100:
            v_err("limit must be between 1 and 100.")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            v_err("offset must be an integer.")
        if offset < 0:
            v_err("offset must be >= 0.")
    total = len(items)
    page = items[offset : offset + limit]
    has_more = offset + limit < total
    meta = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return page, meta


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def order_pricing(order):
    """Return (discount_cents, total_cents) for the current lines & member standing."""
    member = db.members[order["member_id"]]
    sub = member_active_subscription(order["member_id"])
    gear = TIER_GEAR_DISCOUNT_PCT[sub["tier"]] if sub else Decimal("0")
    loyalty = LOYALTY_DISCOUNT_PCT[member["loyalty_tier"]]
    eff = min(gear + loyalty, ORDER_MAX_DISCOUNT_PCT)
    discount = 0
    for line in order["lines"]:
        discount += round_half_up(Decimal(line["line_gross_cents"]) * eff)
    subtotal = order["subtotal_cents"]
    return discount, subtotal - discount


def fitting_fee(appt):
    member = db.members[appt["member_id"]]
    base = FITTING_BASE_CENTS[appt["service_type"]]
    sub = member_active_subscription(appt["member_id"])
    if sub and sub["fittings_used_this_period"] < sub["included_fittings_per_month"]:
        return 0, True
    if sub:
        disc = min(
            TIER_TRAINING_DISCOUNT_PCT[sub["tier"]] + LOYALTY_DISCOUNT_PCT[member["loyalty_tier"]],
            FITTING_MAX_DISCOUNT_PCT,
        )
        fee = round_half_up(Decimal(base) * (Decimal("1") - disc))
        return fee, False
    return base, False


def recompute_member_loyalty(member):
    """Recompute persisted loyalty_points & loyalty_tier from FULFILLED spend.

    Returns True if loyalty_tier changed.
    """
    fulfilled_total = sum(
        o["final_total_cents"]
        for o in db.orders.values()
        if o["member_id"] == member["id"] and o["status"] == "FULFILLED"
    )
    points = fulfilled_total // POINTS_PER_CENT_DIVISOR
    new_tier = tier_from_points(points)
    old_tier = member["loyalty_tier"]
    changed = member["loyalty_points"] != points or member["loyalty_tier"] != new_tier
    member["loyalty_points"] = points
    member["loyalty_tier"] = new_tier
    if changed:
        touch(member)
    return old_tier != new_tier


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; back-to-back touching does not overlap."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Serialized wrappers hiding private datetime fields for subscriptions
# ---------------------------------------------------------------------------

# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    b = body()
    to_iso = req_dt(b, "to_iso8601")
    db.clock = parse_dt(to_iso)
    return ok({"current_utc": fmt_dt(db.clock)}, 200)


# ===========================================================================
# STORES
# ===========================================================================
@app.route("/stores", methods=["POST"])
def create_store():
    uid, role = authenticate()
    authorize(role, {"StoreManager"})
    b = body()
    name = req_str(b, "name")
    region_code = req_str(b, "region_code")
    room = opt_int(b, "session_room_count", 1, minimum=1)
    e = base_entity()
    e.update({"name": name, "region_code": region_code, "session_room_count": room})
    db.stores[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/stores/<sid>", methods=["GET"])
def get_store(sid):
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    e = get_or_404(db.stores, sid, "store")
    return ok(serialize(e))


@app.route("/stores/<sid>/staff", methods=["GET"])
def list_store_staff(sid):
    uid, role = authenticate()
    authorize(role, {"Staff", "StoreManager"})
    get_or_404(db.stores, sid, "store")
    items = [s for s in db.staff.values() if s["store_id"] == sid]
    items.sort(key=sort_key)
    page, meta = paginate(items)
    return ok_list([serialize(x) for x in page], meta)


# ===========================================================================
# STAFF
# ===========================================================================
@app.route("/staff", methods=["POST"])
def create_staff():
    uid, role = authenticate()
    authorize(role, {"StoreManager"})
    b = body()
    store_id = req_str(b, "store_id")
    full_name = req_str(b, "full_name")
    role_type = req_enum(b, "role_type", {"FITTER", "COACH", "BOTH"})
    active = b.get("active", True)
    if not isinstance(active, bool):
        v_err("Field 'active' must be a boolean.")
    get_or_404(db.stores, store_id, "store")
    e = base_entity()
    e.update(
        {
            "store_id": store_id,
            "full_name": full_name,
            "role_type": role_type,
            "active": active,
        }
    )
    db.staff[e["id"]] = e
    return ok(serialize(e), 201)


# ===========================================================================
# MEMBERS
# ===========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    # Open registration — no auth required.
    b = body()
    email = req_str(b, "email")
    full_name = req_str(b, "full_name")
    e = base_entity()
    e.update(
        {
            "email": email,
            "full_name": full_name,
            "loyalty_points": 0,
            "loyalty_tier": "BRONZE",
            "wallet_credit_cents": 0,
        }
    )
    db.members[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    e = get_or_404(db.members, mid, "member")
    owner_guard(role, uid, mid)
    return ok(serialize(e))


@app.route("/members/<mid>/loyalty", methods=["GET"])
def member_loyalty(mid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreManager"})
    get_or_404(db.members, mid, "member")
    owner_guard(role, uid, mid)
    fulfilled = sum(
        o["final_total_cents"]
        for o in db.orders.values()
        if o["member_id"] == mid and o["status"] == "FULFILLED"
    )
    placed = sum(
        o["provisional_total_cents"]
        for o in db.orders.values()
        if o["member_id"] == mid and o["status"] == "PLACED"
    )
    earned = fulfilled // POINTS_PER_CENT_DIVISOR
    projected = (fulfilled + placed) // POINTS_PER_CENT_DIVISOR
    data = {
        "earned_points": earned,
        "current_tier": tier_from_points(earned),
        "projected_points": projected,
        "projected_tier": tier_from_points(projected),
    }
    return ok(data)


@app.route("/members/<mid>/subscriptions", methods=["GET"])
def list_member_subscriptions(mid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreManager"})
    get_or_404(db.members, mid, "member")
    owner_guard(role, uid, mid)
    items = [s for s in db.subscriptions.values() if s["member_id"] == mid]
    items.sort(key=sort_key)
    page, meta = paginate(items)
    return ok_list([serialize(x) for x in page], meta)


@app.route("/members/<mid>/subscription", methods=["POST"])
def create_subscription(mid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    owner_guard(role, uid, mid)  # member creates for self (path id == uid)
    b = body()
    tier = req_enum(b, "tier", {"CLUB_BASIC", "CLUB_PRO"})
    expected = b.get("expected_member_version")
    if not is_int(expected):
        v_err("Field 'expected_member_version' is required and must be an integer.")
    member = get_or_404(db.members, mid, "member")
    if expected != member["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Member version has advanced.")
    # supersede prior non-cancelled subscriptions
    for s in db.subscriptions.values():
        if s["member_id"] == mid and s["status"] != "CANCELLED":
            s["status"] = "CANCELLED"
            touch(s)
    e = base_entity()
    e.update(
        {
            "member_id": mid,
            "tier": tier,
            "status": "PENDING",
            "monthly_fee_cents": TIER_MONTHLY_FEE_CENTS[tier],
            "included_fittings_per_month": TIER_INCLUDED_FITTINGS[tier],
            "fittings_used_this_period": 0,
            "started_at": None,
            "current_period_end": None,
            "_period_end_dt": None,
        }
    )
    db.subscriptions[e["id"]] = e
    touch(member)  # version increments on supersede create
    return ok(serialize(e), 201)


# ===========================================================================
# SUBSCRIPTIONS
# ===========================================================================
@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreManager"})
    e = get_or_404(db.subscriptions, sid, "subscription")
    owner_guard(role, uid, e["member_id"])
    return ok(serialize(e))


@app.route("/subscriptions/<sid>/activate", methods=["POST"])
def activate_subscription(sid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    e = get_or_404(db.subscriptions, sid, "subscription")
    owner_guard(role, uid, e["member_id"])
    if e["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is not PENDING.")
    now = now_dt()
    e["status"] = "ACTIVE"
    e["started_at"] = fmt_dt(now)
    end = now + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)
    e["_period_end_dt"] = end
    e["current_period_end"] = fmt_dt(end)
    e["fittings_used_this_period"] = 0
    touch(e)
    return ok(serialize(e))


@app.route("/subscriptions/<sid>/renew", methods=["POST"])
def renew_subscription(sid):
    uid, role = authenticate()
    authorize(role, {"StoreManager"})
    b = body()
    outcome = req_enum(b, "payment_outcome", {"SUCCEEDED", "FAILED"})
    e = get_or_404(db.subscriptions, sid, "subscription")
    if outcome == "FAILED":
        if e["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Renewal FAILED requires an ACTIVE subscription.")
        e["status"] = "PAST_DUE"
    else:  # SUCCEEDED
        if e["status"] != "PAST_DUE":
            raise ApiError("ERR_INVALID_STATE", 409, "Renewal SUCCEEDED requires a PAST_DUE subscription.")
        e["status"] = "ACTIVE"
        base = e["_period_end_dt"] or now_dt()
        end = base + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)
        e["_period_end_dt"] = end
        e["current_period_end"] = fmt_dt(end)
        e["fittings_used_this_period"] = 0
    touch(e)
    return ok(serialize(e))


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    e = get_or_404(db.subscriptions, sid, "subscription")
    owner_guard(role, uid, e["member_id"])
    if e["status"] not in ("ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription cannot be cancelled from its current state.")
    e["status"] = "CANCELLED"
    touch(e)
    return ok(serialize(e))


# ===========================================================================
# PRODUCTS
# ===========================================================================
@app.route("/products", methods=["POST"])
def create_product():
    uid, role = authenticate()
    authorize(role, {"StoreManager"})
    b = body()
    sku = req_str(b, "sku")
    category = req_enum(b, "category", {"SHOE", "NUTRITION", "GEAR", "APPAREL"})
    name = req_str(b, "name")
    price_cents = req_int(b, "price_cents", minimum=0)
    stock_on_hand = opt_int(b, "stock_on_hand", 0, minimum=0)
    max_mileage = b.get("max_mileage_km", None)
    if max_mileage is not None and not is_int(max_mileage):
        v_err("Field 'max_mileage_km' must be an integer or null.")
    e = base_entity()
    e.update(
        {
            "sku": sku,
            "category": category,
            "name": name,
            "price_cents": price_cents,
            "stock_on_hand": stock_on_hand,
            "stock_reserved": 0,
            "max_mileage_km": max_mileage,
        }
    )
    db.products[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    e = get_or_404(db.products, pid, "product")
    return ok(serialize(e))


@app.route("/products/<pid>/inventory-adjustments", methods=["POST"])
def adjust_inventory(pid):
    uid, role = authenticate()
    authorize(role, {"StoreManager"})
    b = body()
    delta = b.get("delta")
    if not is_int(delta):
        v_err("Field 'delta' is required and must be an integer.")
    e = get_or_404(db.products, pid, "product")
    if e["stock_on_hand"] + delta < 0:
        v_err("Adjustment would drive stock_on_hand below zero.")
    e["stock_on_hand"] += delta
    touch(e)
    return ok(serialize(e))


# ===========================================================================
# FITTING APPOINTMENTS
# ===========================================================================
@app.route("/fitting-appointments", methods=["POST"])
def create_appointment():
    uid, role = authenticate()
    authorize(role, {"Member"})
    b = body()
    member_id = req_str(b, "member_id")
    fitter_id = req_str(b, "fitter_id")
    service_type = req_enum(b, "service_type", {"GAIT_ANALYSIS", "SHOE_FITTING", "FOLLOWUP"})
    start_at = req_dt(b, "start_at")
    end_at = req_dt(b, "end_at")
    if parse_dt(end_at) <= parse_dt(start_at):
        v_err("end_at must be strictly after start_at.")
    owner_guard(role, uid, member_id)
    get_or_404(db.members, member_id, "member")
    get_or_404(db.staff, fitter_id, "staff")
    s_dt = parse_dt(start_at)
    e_dt = parse_dt(end_at)
    # temporal: no past-dated bookings
    if s_dt < now_dt():
        raise ApiError("ERR_APPOINTMENT_IN_PAST", 422, "Appointment start_at is in the past.")
    # fitter buffer
    buf = timedelta(minutes=FITTING_BUFFER_MINUTES)
    for other in db.appointments.values():
        if other["fitter_id"] == fitter_id and other["status"] == "SCHEDULED":
            o_s = parse_dt(other["start_at"])
            o_e = parse_dt(other["end_at"])
            if s_dt < o_e + buf and o_s < e_dt + buf:
                raise ApiError("ERR_FITTER_UNAVAILABLE", 409, "Fitter is unavailable in that window.")
    e = base_entity()
    e.update(
        {
            "member_id": member_id,
            "fitter_id": fitter_id,
            "service_type": service_type,
            "start_at": start_at,
            "end_at": end_at,
            "status": "SCHEDULED",
            "gait_result": None,
            "fee_cents": None,
        }
    )
    db.appointments[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/fitting-appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    e = get_or_404(db.appointments, aid, "appointment")
    owner_guard(role, uid, e["member_id"])
    return ok(serialize(e))


@app.route("/fitting-appointments", methods=["GET"])
def list_appointments():
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    f_member = request.args.get("member_id")
    f_fitter = request.args.get("fitter_id")
    if role == "Member":
        f_member = uid
    items = list(db.appointments.values())
    if f_member is not None:
        items = [x for x in items if x["member_id"] == f_member]
    if f_fitter is not None:
        items = [x for x in items if x["fitter_id"] == f_fitter]
    items.sort(key=sort_key)
    page, meta = paginate(items)
    return ok_list([serialize(x) for x in page], meta)


@app.route("/fitting-appointments/<aid>/complete", methods=["POST"])
def complete_appointment(aid):
    uid, role = authenticate()
    authorize(role, {"Staff"})
    b = body()
    e = get_or_404(db.appointments, aid, "appointment")
    if uid != e["fitter_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Only the assigned fitter may complete this appointment.")
    if e["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Appointment is not SCHEDULED.")
    fee, included = fitting_fee(e)
    e["gait_result"] = b.get("gait_result")
    e["fee_cents"] = fee
    e["status"] = "COMPLETED"
    touch(e)
    if included:
        sub = member_active_subscription(e["member_id"])
        if sub:
            sub["fittings_used_this_period"] += 1
            touch(sub)
    return ok(serialize(e))


@app.route("/fitting-appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    e = get_or_404(db.appointments, aid, "appointment")
    owner_guard(role, uid, e["member_id"])
    if e["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Appointment is not SCHEDULED.")
    e["status"] = "CANCELLED"
    touch(e)
    return ok(serialize(e))


# ===========================================================================
# TRAINING SESSIONS
# ===========================================================================
@app.route("/training-sessions", methods=["POST"])
def create_session():
    uid, role = authenticate()
    authorize(role, {"StoreManager"})
    b = body()
    coach_id = req_str(b, "coach_id")
    store_id = req_str(b, "store_id")
    level = req_enum(b, "level", {"BEGINNER", "INTERMEDIATE", "ADVANCED"})
    start_at = req_dt(b, "start_at")
    end_at = req_dt(b, "end_at")
    capacity = req_int(b, "capacity", minimum=1)
    if parse_dt(end_at) <= parse_dt(start_at):
        v_err("end_at must be strictly after start_at.")
    get_or_404(db.staff, coach_id, "staff")
    store = get_or_404(db.stores, store_id, "store")
    s_dt = parse_dt(start_at)
    e_dt = parse_dt(end_at)
    # coach overlap (no buffer)
    for other in db.sessions.values():
        if other["coach_id"] == coach_id and other["status"] == "SCHEDULED":
            if windows_overlap(s_dt, e_dt, parse_dt(other["start_at"]), parse_dt(other["end_at"])):
                raise ApiError("ERR_COACH_UNAVAILABLE", 409, "Coach is unavailable in that window.")
    # store room aggregate capacity (no buffer)
    overlapping = 0
    for other in db.sessions.values():
        if other["store_id"] == store_id and other["status"] == "SCHEDULED":
            if windows_overlap(s_dt, e_dt, parse_dt(other["start_at"]), parse_dt(other["end_at"])):
                overlapping += 1
    if overlapping >= store["session_room_count"]:
        raise ApiError("ERR_SESSION_ROOM_CONFLICT", 409, "No coaching room available for that window.")
    e = base_entity()
    e.update(
        {
            "coach_id": coach_id,
            "store_id": store_id,
            "level": level,
            "start_at": start_at,
            "end_at": end_at,
            "capacity": capacity,
            "enrolled_count": 0,
            "status": "SCHEDULED",
        }
    )
    db.sessions[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/training-sessions/<sid>", methods=["GET"])
def get_session(sid):
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    e = get_or_404(db.sessions, sid, "session")
    return ok(serialize(e))


@app.route("/training-sessions", methods=["GET"])
def list_sessions():
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    f_coach = request.args.get("coach_id")
    f_store = request.args.get("store_id")
    items = list(db.sessions.values())
    if f_coach is not None:
        items = [x for x in items if x["coach_id"] == f_coach]
    if f_store is not None:
        items = [x for x in items if x["store_id"] == f_store]
    items.sort(key=sort_key)
    page, meta = paginate(items)
    return ok_list([serialize(x) for x in page], meta)


@app.route("/training-sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    uid, role = authenticate()
    authorize(role, {"Staff", "StoreManager"})
    e = get_or_404(db.sessions, sid, "session")
    if e["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Session is not SCHEDULED.")
    e["status"] = "CANCELLED"
    for enr in db.enrollments.values():
        if enr["session_id"] == sid and enr["status"] in ("ENROLLED", "WAITLISTED"):
            enr["status"] = "CANCELLED"
            touch(enr)
    e["enrolled_count"] = 0
    touch(e)
    return ok(serialize(e))


@app.route("/training-sessions/<sid>/enrollments", methods=["POST"])
def create_enrollment(sid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    b = body()
    member_id = req_str(b, "member_id")
    owner_guard(role, uid, member_id)
    session = get_or_404(db.sessions, sid, "session")
    get_or_404(db.members, member_id, "member")
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED", 409, "Session is not SCHEDULED.")
    # no more than one live seat per session
    for enr in db.enrollments.values():
        if enr["session_id"] == sid and enr["member_id"] == member_id and enr["status"] != "CANCELLED":
            v_err("Member already holds a live enrollment for this session.")
    e = base_entity()
    if session["enrolled_count"] < session["capacity"]:
        status = "ENROLLED"
        session["enrolled_count"] += 1
        touch(session)
    else:
        status = "WAITLISTED"
    e.update({"session_id": sid, "member_id": member_id, "status": status})
    db.enrollments[e["id"]] = e
    return ok(serialize(e), 201)


# ===========================================================================
# SESSION ENROLLMENTS
# ===========================================================================
@app.route("/session-enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    e = get_or_404(db.enrollments, eid, "enrollment")
    owner_guard(role, uid, e["member_id"])
    return ok(serialize(e))


@app.route("/session-enrollments", methods=["GET"])
def list_enrollments():
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    f_session = request.args.get("session_id")
    f_member = request.args.get("member_id")
    if role == "Member":
        f_member = uid
    items = list(db.enrollments.values())
    if f_session is not None:
        items = [x for x in items if x["session_id"] == f_session]
    if f_member is not None:
        items = [x for x in items if x["member_id"] == f_member]
    items.sort(key=sort_key)
    page, meta = paginate(items)
    return ok_list([serialize(x) for x in page], meta)


def promote_waitlist(session_id):
    """Promote earliest-created WAITLISTED enrollment of the session to ENROLLED."""
    session = db.sessions.get(session_id)
    if session is None:
        return
    if session["enrolled_count"] >= session["capacity"]:
        return
    waiting = [
        e
        for e in db.enrollments.values()
        if e["session_id"] == session_id and e["status"] == "WAITLISTED"
    ]
    if not waiting:
        return
    waiting.sort(key=sort_key)
    promoted = waiting[0]
    promoted["status"] = "ENROLLED"
    touch(promoted)
    session["enrolled_count"] += 1
    touch(session)


@app.route("/session-enrollments/<eid>/cancel", methods=["POST"])
def cancel_enrollment(eid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    e = get_or_404(db.enrollments, eid, "enrollment")
    owner_guard(role, uid, e["member_id"])
    if e["status"] not in ("ENROLLED", "WAITLISTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Enrollment cannot be cancelled from its current state.")
    was_enrolled = e["status"] == "ENROLLED"
    e["status"] = "CANCELLED"
    touch(e)
    if was_enrolled:
        session = db.sessions.get(e["session_id"])
        if session is not None:
            session["enrolled_count"] -= 1
            touch(session)
            promote_waitlist(e["session_id"])
    return ok(serialize(e))


# ===========================================================================
# RACE EVENTS
# ===========================================================================
@app.route("/race-events", methods=["POST"])
def create_event():
    uid, role = authenticate()
    authorize(role, {"StoreManager"})
    b = body()
    name = req_str(b, "name")
    event_date = req_dt(b, "event_date")
    packet_capacity = req_int(b, "packet_capacity", minimum=1)
    entry_fee_cents = req_int(b, "entry_fee_cents", minimum=0)
    e = base_entity()
    e.update(
        {
            "name": name,
            "event_date": event_date,
            "packet_capacity": packet_capacity,
            "entry_fee_cents": entry_fee_cents,
            "packets_allocated": 0,
            "active_registrations": 0,
            "status": "OPEN",
        }
    )
    db.events[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/race-events/<eid>", methods=["GET"])
def get_event(eid):
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    e = get_or_404(db.events, eid, "event")
    return ok(serialize(e))


@app.route("/race-events/<eid>/close", methods=["POST"])
def close_event(eid):
    uid, role = authenticate()
    authorize(role, {"StoreManager"})
    e = get_or_404(db.events, eid, "event")
    if e["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Event is not OPEN.")
    e["status"] = "CLOSED"
    touch(e)
    return ok(serialize(e))


@app.route("/race-events/<eid>/registrations", methods=["POST"])
def create_registration(eid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    b = body()
    member_id = req_str(b, "member_id")
    owner_guard(role, uid, member_id)
    event = get_or_404(db.events, eid, "event")
    get_or_404(db.members, member_id, "member")
    if event["status"] != "OPEN":
        raise ApiError("ERR_EVENT_CLOSED", 409, "Event is not OPEN.")
    for reg in db.registrations.values():
        if reg["event_id"] == eid and reg["member_id"] == member_id and reg["packet_status"] != "RELEASED":
            raise ApiError("ERR_ALREADY_REGISTERED", 409, "Member already registered for this event.")
    if event["active_registrations"] >= event["packet_capacity"]:
        raise ApiError("ERR_EVENT_FULL", 409, "Race packet pool is exhausted.")
    e = base_entity()
    e.update(
        {
            "event_id": eid,
            "member_id": member_id,
            "payment_status": "UNPAID",
            "packet_status": "RESERVED",
            "entry_fee_cents": event["entry_fee_cents"],
            "amount_paid_cents": 0,
            "refund_cents": 0,
        }
    )
    db.registrations[e["id"]] = e
    event["active_registrations"] += 1
    touch(event)
    return ok(serialize(e), 201)


# ===========================================================================
# RACE REGISTRATIONS
# ===========================================================================
@app.route("/race-registrations/<rid>", methods=["GET"])
def get_registration(rid):
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    e = get_or_404(db.registrations, rid, "registration")
    owner_guard(role, uid, e["member_id"])
    return ok(serialize(e))


@app.route("/race-registrations", methods=["GET"])
def list_registrations():
    uid, role = authenticate()
    authorize(role, {"Member", "Staff", "StoreManager"})
    f_event = request.args.get("event_id")
    f_member = request.args.get("member_id")
    if role == "Member":
        f_member = uid
    items = list(db.registrations.values())
    if f_event is not None:
        items = [x for x in items if x["event_id"] == f_event]
    if f_member is not None:
        items = [x for x in items if x["member_id"] == f_member]
    items.sort(key=sort_key)
    page, meta = paginate(items)
    return ok_list([serialize(x) for x in page], meta)


@app.route("/race-registrations/<rid>/pay", methods=["POST"])
def pay_registration(rid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    e = get_or_404(db.registrations, rid, "registration")
    owner_guard(role, uid, e["member_id"])
    if e["payment_status"] != "UNPAID" or e["packet_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Registration cannot be paid from its current state.")
    e["payment_status"] = "PAID"
    e["amount_paid_cents"] = e["entry_fee_cents"]
    touch(e)
    return ok(serialize(e))


@app.route("/race-registrations/<rid>/allocate", methods=["POST"])
def allocate_registration(rid):
    uid, role = authenticate()
    authorize(role, {"Staff"})
    e = get_or_404(db.registrations, rid, "registration")
    if e["packet_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Packet is not RESERVED.")
    if e["payment_status"] != "PAID":
        raise ApiError("ERR_REGISTRATION_NOT_PAID", 409, "Registration is not PAID.")
    event = db.events[e["event_id"]]
    if event["status"] != "OPEN":
        raise ApiError("ERR_EVENT_CLOSED", 409, "Event is not OPEN.")
    e["packet_status"] = "ALLOCATED"
    touch(e)
    event["packets_allocated"] += 1
    touch(event)
    return ok(serialize(e))


@app.route("/race-registrations/<rid>/cancel", methods=["POST"])
def cancel_registration(rid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    e = get_or_404(db.registrations, rid, "registration")
    owner_guard(role, uid, e["member_id"])
    if e["packet_status"] not in ("RESERVED", "ALLOCATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Registration packet is already RELEASED.")
    event = db.events[e["event_id"]]
    was_allocated = e["packet_status"] == "ALLOCATED"
    e["packet_status"] = "RELEASED"
    event["active_registrations"] -= 1
    if was_allocated:
        event["packets_allocated"] -= 1
    if e["payment_status"] == "PAID":
        e["payment_status"] = "REFUNDED"
        refund = max(e["amount_paid_cents"] - RACE_CANCELLATION_FEE_CENTS, 0)
        e["refund_cents"] = refund
        member = db.members[e["member_id"]]
        member["wallet_credit_cents"] += refund
        touch(member)
    touch(e)
    touch(event)
    return ok(serialize(e))


# ===========================================================================
# ORDERS
# ===========================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = authenticate()
    authorize(role, {"Member"})
    b = body()
    member_id = req_str(b, "member_id")
    owner_guard(role, uid, member_id)
    get_or_404(db.members, member_id, "member")
    e = base_entity()
    e.update(
        {
            "member_id": member_id,
            "status": "CART",
            "lines": [],
            "subtotal_cents": 0,
            "provisional_discount_cents": None,
            "provisional_total_cents": None,
            "final_discount_cents": None,
            "final_total_cents": None,
            "refund_cents": 0,
            "placed_at": None,
            "fulfilled_at": None,
        }
    )
    db.orders[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreManager"})
    e = get_or_404(db.orders, oid, "order")
    owner_guard(role, uid, e["member_id"])
    return ok(serialize(e))


@app.route("/orders", methods=["GET"])
def list_orders():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreManager"})
    f_member = request.args.get("member_id")
    if role == "Member":
        f_member = uid
    items = list(db.orders.values())
    if f_member is not None:
        items = [x for x in items if x["member_id"] == f_member]
    items.sort(key=sort_key)
    page, meta = paginate(items)
    return ok_list([serialize(x) for x in page], meta)


@app.route("/orders/<oid>/lines", methods=["POST"])
def add_order_line(oid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    b = body()
    product_id = req_str(b, "product_id")
    qty = req_int(b, "qty", minimum=1)
    e = get_or_404(db.orders, oid, "order")
    owner_guard(role, uid, e["member_id"])
    product = get_or_404(db.products, product_id, "product")
    if e["status"] != "CART":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not in CART.")
    unit_price = product["price_cents"]
    line = {
        "product_id": product_id,
        "qty": qty,
        "unit_price_cents": unit_price,
        "line_gross_cents": unit_price * qty,
    }
    e["lines"].append(line)
    e["subtotal_cents"] = sum(l["line_gross_cents"] for l in e["lines"])
    touch(e)
    return ok(serialize(e), 201)


@app.route("/orders/<oid>/place", methods=["POST"])
def place_order(oid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    e = get_or_404(db.orders, oid, "order")
    owner_guard(role, uid, e["member_id"])
    if e["status"] != "CART":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not in CART.")
    if len(e["lines"]) < 1:
        v_err("Order must have at least one line to place.")
    for line in e["lines"]:
        product = db.products.get(line["product_id"])
        if product is None or product["stock_on_hand"] < line["qty"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409, "Insufficient stock to place order.")
    for line in e["lines"]:
        product = db.products[line["product_id"]]
        product["stock_on_hand"] -= line["qty"]
        product["stock_reserved"] += line["qty"]
        touch(product)
    e["status"] = "PLACED"
    disc, total = order_pricing(e)
    e["provisional_discount_cents"] = disc
    e["provisional_total_cents"] = total
    e["placed_at"] = fmt_dt(now_dt())
    touch(e)
    return ok(serialize(e))


@app.route("/orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    uid, role = authenticate()
    authorize(role, {"Staff"})
    e = get_or_404(db.orders, oid, "order")
    if e["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not PLACED.")
    for line in e["lines"]:
        product = db.products.get(line["product_id"])
        if product is not None:
            product["stock_reserved"] -= line["qty"]
            touch(product)
    disc, total = order_pricing(e)
    e["final_discount_cents"] = disc
    e["final_total_cents"] = total
    e["fulfilled_at"] = fmt_dt(now_dt())
    e["status"] = "FULFILLED"
    touch(e)
    member = db.members[e["member_id"]]
    tier_changed = recompute_member_loyalty(member)
    if tier_changed:
        for other in db.orders.values():
            if other["member_id"] == member["id"] and other["status"] == "PLACED" and other["id"] != e["id"]:
                d, t = order_pricing(other)
                other["provisional_discount_cents"] = d
                other["provisional_total_cents"] = t
                touch(other)
    return ok(serialize(e))


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    e = get_or_404(db.orders, oid, "order")
    owner_guard(role, uid, e["member_id"])
    if e["status"] not in ("CART", "PLACED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order cannot be cancelled from its current state.")
    if e["status"] == "PLACED":
        for line in e["lines"]:
            product = db.products.get(line["product_id"])
            if product is not None:
                product["stock_reserved"] -= line["qty"]
                product["stock_on_hand"] += line["qty"]
                touch(product)
    e["status"] = "CANCELLED"
    touch(e)
    return ok(serialize(e))


@app.route("/orders/<oid>/return", methods=["POST"])
def return_order(oid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    b = body()
    e = get_or_404(db.orders, oid, "order")
    owner_guard(role, uid, e["member_id"])
    if e["status"] != "FULFILLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not FULFILLED.")
    deadline = parse_dt(e["fulfilled_at"]) + timedelta(days=RETURN_WINDOW_DAYS)
    if now_dt() > deadline:
        raise ApiError("ERR_RETURN_WINDOW_EXPIRED", 422, "Return window has expired.")
    restock_fee = round_half_up(Decimal(e["final_total_cents"]) * RESTOCK_FEE_PCT)
    refund = e["final_total_cents"] - restock_fee
    e["refund_cents"] = refund
    e["status"] = "RETURNED"
    touch(e)
    member = db.members[e["member_id"]]
    member["wallet_credit_cents"] += refund
    touch(member)
    for line in e["lines"]:
        product = db.products.get(line["product_id"])
        if product is not None:
            product["stock_on_hand"] += line["qty"]
            touch(product)
    return ok(serialize(e))


# ===========================================================================
# SHOE PAIRS
# ===========================================================================
@app.route("/shoe-pairs", methods=["POST"])
def create_shoe_pair():
    uid, role = authenticate()
    authorize(role, {"Member"})
    b = body()
    member_id = req_str(b, "member_id")
    product_id = req_str(b, "product_id")
    owner_guard(role, uid, member_id)
    get_or_404(db.members, member_id, "member")
    product = get_or_404(db.products, product_id, "product")
    if product["category"] != "SHOE":
        raise ApiError("ERR_PRODUCT_NOT_SHOE", 422, "Product is not a SHOE.")
    e = base_entity()
    e.update(
        {
            "member_id": member_id,
            "product_id": product_id,
            "reminder_threshold_km": product["max_mileage_km"],
            "total_mileage_km": 0,
            "run_logs": [],
            "status": "ACTIVE",
        }
    )
    db.shoe_pairs[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/shoe-pairs/<pid>", methods=["GET"])
def get_shoe_pair(pid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreManager"})
    e = get_or_404(db.shoe_pairs, pid, "shoe_pair")
    owner_guard(role, uid, e["member_id"])
    return ok(serialize(e))


@app.route("/shoe-pairs", methods=["GET"])
def list_shoe_pairs():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreManager"})
    f_member = request.args.get("member_id")
    f_product = request.args.get("product_id")
    if role == "Member":
        f_member = uid
    items = list(db.shoe_pairs.values())
    if f_member is not None:
        items = [x for x in items if x["member_id"] == f_member]
    if f_product is not None:
        items = [x for x in items if x["product_id"] == f_product]
    items.sort(key=sort_key)
    page, meta = paginate(items)
    return ok_list([serialize(x) for x in page], meta)


@app.route("/shoe-pairs/<pid>/run-logs", methods=["POST"])
def add_run_log(pid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    b = body()
    distance_km = req_number(b, "distance_km", exclusive_min=0)
    logged_at = b.get("logged_at")
    if logged_at is not None:
        if not isinstance(logged_at, str):
            v_err("Field 'logged_at' must be an ISO 8601 datetime string.")
        try:
            parse_dt(logged_at)
        except Exception:
            v_err("Field 'logged_at' must be a valid ISO 8601 datetime.")
    else:
        logged_at = fmt_dt(now_dt())
    e = get_or_404(db.shoe_pairs, pid, "shoe_pair")
    owner_guard(role, uid, e["member_id"])
    dist = float(Decimal(str(distance_km)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    e["run_logs"].append({"distance_km": dist, "logged_at": logged_at})
    total = sum(Decimal(str(entry["distance_km"])) for entry in e["run_logs"])
    total = total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    e["total_mileage_km"] = float(total)
    threshold = e["reminder_threshold_km"]
    if e["status"] == "ACTIVE" and threshold is not None and total >= Decimal(str(threshold)):
        e["status"] = "REORDER_DUE"
    touch(e)
    return ok(serialize(e), 201)


# ---------------------------------------------------------------------------
db = DB()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
