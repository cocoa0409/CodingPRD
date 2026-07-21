"""Fishing, Tackle & Bait Shop REST API.

Single-file Flask implementation. In-memory storage only; the store starts
empty on every boot. A server-controlled logical clock governs every temporal
rule (default 2026-07-01T00:00:00Z).
"""
import os
import re
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RECOGNIZED_ROLES = {"Anonymous", "Customer", "ShopClerk", "Guide", "ShopManager"}

SILVER_THRESHOLD = 500
GOLD_THRESHOLD = 2000
POINTS_PER_DOLLAR = 1
LICENSE_VOID_GRACE_DAYS = 7
TURNAROUND_BUFFER_MINUTES = 60
CANCEL_FULL_REFUND_HOURS = 48
CANCEL_PARTIAL_REFUND_PCT = Decimal("0.50")
TAX_RATE = Decimal("0.08")
TIER_DISCOUNT_PCT = {"BRONZE": Decimal("0"), "SILVER": Decimal("0.05"), "GOLD": Decimal("0.10")}

DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

PRODUCT_CATEGORIES = {"TACKLE", "ROD", "REEL", "LINE", "LIVE_BAIT", "MISC"}
LICENSE_CLASSES = {"RESIDENT", "NONRESIDENT"}
SERVICE_TYPES = {"REEL_REPAIR", "ROD_REPAIR", "SPOOLING"}

# ---------------------------------------------------------------------------
# Storage (reset on every boot)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.customers = {}
        self.products = {}
        self.license_types = {}
        self.license_sales = {}
        self.guides = {}
        self.charters = {}
        self.charter_bookings = {}
        self.tournaments = {}
        self.tournament_entries = {}
        self.service_orders = {}
        self.clock = DEFAULT_CLOCK
        self.seq = itertools.count(1)


db = Store()


def now_clock():
    return db.clock


def next_seq():
    return next(db.seq)


def gen_id():
    return str(uuid.uuid4())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_ts():
    return fmt_dt(now_clock())


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Errors & response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status


def _meta():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": fmt_dt(datetime.now(timezone.utc))}


def ok(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def ok_list(items, pagination):
    return ok(items, status=200, response_type="array", pagination=pagination)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.error_id},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "method not allowed"},
    }
    return jsonify(body), 405


def err(error_id, http_status):
    raise ApiError(error_id, http_status)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def guard(allowed_roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in RECOGNIZED_ROLES:
        err("ERR_UNAUTHENTICATED", 401)
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403)
    return uid, role


def guard_public_or(allowed_roles):
    """For customer self-registration: anonymous public allowed without auth."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None and uid is None:
        return None, "Anonymous"
    if not role or not uid or role not in RECOGNIZED_ROLES:
        err("ERR_UNAUTHENTICATED", 401)
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403)
    return uid, role


def get_body():
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None or not isinstance(data, dict):
        err("ERR_VALIDATION", 400)
    return data


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------
def base_common(with_version=True):
    fields = {"id": gen_id(), "created_at": clock_ts(), "_seq": next_seq()}
    if with_version:
        fields["updated_at"] = clock_ts()
        fields["version"] = 1
    return fields


def touch(entity):
    entity["updated_at"] = clock_ts()
    entity["version"] = entity.get("version", 1) + 1


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            err("ERR_VALIDATION", 400)


def as_int(value, allow_none=False):
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        err("ERR_VALIDATION", 400)
    if not isinstance(value, int):
        err("ERR_VALIDATION", 400)
    return value


def as_str(value):
    if not isinstance(value, str) or value == "":
        err("ERR_VALIDATION", 400)
    return value


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400)
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 400)
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400)
        if offset < 0:
            err("ERR_VALIDATION", 400)
    return limit, offset


def paginate(items):
    """items: list already sorted by creation order."""
    limit, offset = parse_pagination()
    total = len(items)
    window = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, pagination


def sorted_by_seq(values):
    return sorted(values, key=lambda x: x["_seq"])


# ---------------------------------------------------------------------------
# Loyalty helpers
# ---------------------------------------------------------------------------
def recompute_tier(customer):
    lifetime = customer["lifetime_points_earned"]
    if lifetime >= GOLD_THRESHOLD:
        customer["loyalty_tier"] = "GOLD"
    elif lifetime >= SILVER_THRESHOLD:
        customer["loyalty_tier"] = "SILVER"
    else:
        customer["loyalty_tier"] = "BRONZE"


def credit_points(customer, points):
    customer["loyalty_points_balance"] += points
    customer["lifetime_points_earned"] += points
    recompute_tier(customer)
    touch(customer)


def reverse_points(customer, points):
    customer["loyalty_points_balance"] -= points
    customer["lifetime_points_earned"] -= points
    recompute_tier(customer)
    touch(customer)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_customer(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "date_of_birth": c["date_of_birth"],
        "residency_state": c["residency_state"],
        "loyalty_points_balance": c["loyalty_points_balance"],
        "lifetime_points_earned": c["lifetime_points_earned"],
        "loyalty_tier": c["loyalty_tier"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_product(p):
    return {
        "id": p["id"],
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "unit_price_cents": p["unit_price_cents"],
        "stock_qty": p["stock_qty"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_license_type(lt):
    return {
        "id": lt["id"],
        "code": lt["code"],
        "state_code": lt["state_code"],
        "license_class": lt["license_class"],
        "base_price_cents": lt["base_price_cents"],
        "youth_max_age": lt["youth_max_age"],
        "youth_price_cents": lt["youth_price_cents"],
        "senior_min_age": lt["senior_min_age"],
        "senior_price_cents": lt["senior_price_cents"],
        "peak_surcharge_cents": lt["peak_surcharge_cents"],
        "peak_start_month": lt["peak_start_month"],
        "peak_end_month": lt["peak_end_month"],
        "min_age": lt["min_age"],
        "season_start_date": lt["season_start_date"],
        "season_end_date": lt["season_end_date"],
        "validity_days": lt["validity_days"],
        "created_at": lt["created_at"],
    }


def ser_license_sale(s):
    return {
        "id": s["id"],
        "customer_id": s["customer_id"],
        "license_type_id": s["license_type_id"],
        "issued_at": s["issued_at"],
        "valid_from": s["valid_from"],
        "valid_until": s["valid_until"],
        "price_paid_cents": s["price_paid_cents"],
        "points_earned": s["points_earned"],
        "refund_amount_cents": s["refund_amount_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_guide(g):
    return {
        "id": g["id"],
        "name": g["name"],
        "license_no": g["license_no"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_charter(ch):
    return {
        "id": ch["id"],
        "guide_id": ch["guide_id"],
        "title": ch["title"],
        "start_at": ch["start_at"],
        "end_at": ch["end_at"],
        "capacity": ch["capacity"],
        "booked_seats": ch["booked_seats"],
        "price_per_seat_cents": ch["price_per_seat_cents"],
        "fuel_surcharge_cents": ch["fuel_surcharge_cents"],
        "status": ch["status"],
        "created_at": ch["created_at"],
        "updated_at": ch["updated_at"],
        "version": ch["version"],
    }


def ser_booking(b):
    return {
        "id": b["id"],
        "charter_id": b["charter_id"],
        "customer_id": b["customer_id"],
        "seats": b["seats"],
        "waitlist_requested": b["waitlist_requested"],
        "booking_status": b["booking_status"],
        "payment_status": b["payment_status"],
        "provisional_total_cents": b["provisional_total_cents"],
        "final_total_cents": b["final_total_cents"],
        "amount_paid_cents": b["amount_paid_cents"],
        "refund_amount_cents": b["refund_amount_cents"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_tournament(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "species": t["species"],
        "start_at": t["start_at"],
        "end_at": t["end_at"],
        "entry_fee_cents": t["entry_fee_cents"],
        "min_qualifying_weight_grams": t["min_qualifying_weight_grams"],
        "prize_points": t["prize_points"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_entry(e):
    return {
        "id": e["id"],
        "tournament_id": e["tournament_id"],
        "customer_id": e["customer_id"],
        "status": e["status"],
        "weigh_ins": [
            {"species": w["species"], "weight_grams": w["weight_grams"], "recorded_at": w["recorded_at"]}
            for w in e["weigh_ins"]
        ],
        "best_weight_grams": e["best_weight_grams"],
        "final_rank": e["final_rank"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_service_order(o):
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "product_id": o["product_id"],
        "service_type": o["service_type"],
        "base_service_cents": o["base_service_cents"],
        "line_price_cents_per_meter": o["line_price_cents_per_meter"],
        "estimated_line_meters": o["estimated_line_meters"],
        "actual_line_meters": o["actual_line_meters"],
        "line_units": o["line_units"],
        "parts_cents": o["parts_cents"],
        "quoted_cents": o["quoted_cents"],
        "final_subtotal_cents": o["final_subtotal_cents"],
        "grand_total_cents": o["grand_total_cents"],
        "points_earned": o["points_earned"],
        "stock_consumed": o["stock_consumed"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        err("ERR_CUSTOMER_NOT_FOUND", 404)
    return c


def get_product(pid):
    p = db.products.get(pid)
    if p is None:
        err("ERR_PRODUCT_NOT_FOUND", 404)
    return p


def get_license_type(lid):
    lt = db.license_types.get(lid)
    if lt is None:
        err("ERR_LICENSE_TYPE_NOT_FOUND", 404)
    return lt


def get_license_sale(sid):
    s = db.license_sales.get(sid)
    if s is None:
        err("ERR_LICENSE_SALE_NOT_FOUND", 404)
    return s


def get_guide(gid):
    g = db.guides.get(gid)
    if g is None:
        err("ERR_GUIDE_NOT_FOUND", 404)
    return g


def get_charter(cid):
    ch = db.charters.get(cid)
    if ch is None:
        err("ERR_CHARTER_NOT_FOUND", 404)
    return ch


def get_booking(bid):
    b = db.charter_bookings.get(bid)
    if b is None:
        err("ERR_BOOKING_NOT_FOUND", 404)
    return b


def get_tournament(tid):
    t = db.tournaments.get(tid)
    if t is None:
        err("ERR_TOURNAMENT_NOT_FOUND", 404)
    return t


def get_entry(eid):
    e = db.tournament_entries.get(eid)
    if e is None:
        err("ERR_ENTRY_NOT_FOUND", 404)
    return e


def get_service_order(oid):
    o = db.service_orders.get(oid)
    if o is None:
        err("ERR_SERVICE_ORDER_NOT_FOUND", 404)
    return o


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def whole_years(dob, ref):
    years = ref.year - dob.year
    if (ref.month, ref.day) < (dob.month, dob.day):
        years -= 1
    return years


def compute_license_price(lt, age, valid_from_date):
    if lt["youth_max_age"] is not None and age <= lt["youth_max_age"]:
        tier_price = lt["youth_price_cents"]
    elif lt["senior_min_age"] is not None and age >= lt["senior_min_age"]:
        tier_price = lt["senior_price_cents"]
    else:
        tier_price = lt["base_price_cents"]
    surcharge = 0
    if (
        lt["peak_start_month"] is not None
        and lt["peak_end_month"] is not None
        and lt["peak_start_month"] <= valid_from_date.month <= lt["peak_end_month"]
    ):
        surcharge = lt["peak_surcharge_cents"]
    return tier_price + surcharge


def compute_void_refund(sale, lt):
    valid_from = parse_date(sale["valid_from"])
    elapsed_days = (now_clock().date() - valid_from).days
    if elapsed_days < 0:
        elapsed_days = 0
    validity = lt["validity_days"]
    if elapsed_days <= LICENSE_VOID_GRACE_DAYS:
        return sale["price_paid_cents"]
    remaining = max(0, validity - elapsed_days)
    return round_half_up(Decimal(sale["price_paid_cents"]) * Decimal(remaining) / Decimal(validity))


def provisional_total(charter, seats):
    return seats * charter["price_per_seat_cents"] + seats * charter["fuel_surcharge_cents"]


def final_total(charter, seats, tier):
    gross = provisional_total(charter, seats)
    disc = TIER_DISCOUNT_PCT[tier]
    return round_half_up(Decimal(gross) * (Decimal(1) - disc))


def compute_cancellation_refund(booking, charter, initiated_by):
    amount = booking["amount_paid_cents"]
    if initiated_by == "guide":
        return amount
    hours_before = (charter["_start_dt"] - now_clock()).total_seconds() / 3600.0
    if hours_before >= CANCEL_FULL_REFUND_HOURS:
        return amount
    if hours_before > 0:
        return round_half_up(Decimal(amount) * CANCEL_PARTIAL_REFUND_PCT)
    return 0


def compute_grand_total(subtotal, tier):
    disc = TIER_DISCOUNT_PCT[tier]
    discount_cents = round_half_up(Decimal(subtotal) * disc)
    discounted = subtotal - discount_cents
    tax_cents = round_half_up(Decimal(discounted) * TAX_RATE)
    return discounted + tax_cents


# ---------------------------------------------------------------------------
# Charter / booking seat helpers
# ---------------------------------------------------------------------------
def bookings_of_charter(charter_id):
    return [b for b in db.charter_bookings.values() if b["charter_id"] == charter_id]


def promote_waitlist(charter):
    if charter["status"] != "OPEN":
        return
    remaining = charter["capacity"] - charter["booked_seats"]
    if remaining <= 0:
        return
    candidates = [
        b for b in bookings_of_charter(charter["id"])
        if b["booking_status"] == "WAITLISTED" and b["seats"] <= remaining
    ]
    if not candidates:
        return
    b = sorted(candidates, key=lambda x: x["_seq"])[0]
    b["booking_status"] = "RESERVED"
    charter["booked_seats"] += b["seats"]
    b["provisional_total_cents"] = provisional_total(charter, b["seats"])
    touch(b)
    if charter["booked_seats"] >= charter["capacity"]:
        charter["status"] = "FULL"
    touch(charter)


def release_seats(charter):
    """Called after booked_seats has been decremented on an active charter."""
    flipped = False
    if charter["status"] == "FULL" and charter["booked_seats"] < charter["capacity"]:
        charter["status"] = "OPEN"
        flipped = True
    touch(charter)
    if flipped:
        promote_waitlist(charter)


def refund_if_paid(booking, charter, initiated_by):
    if booking["payment_status"] == "PAID":
        booking["refund_amount_cents"] = compute_cancellation_refund(booking, charter, initiated_by)
        booking["payment_status"] = "REFUNDED"


def cancel_booking_cascade(booking, initiated_by):
    """Cancel a booking as part of a cascade (customer suspend / charter cancel).
    Handles seat release for charters that remain active."""
    charter = db.charters[booking["charter_id"]]
    st = booking["booking_status"]
    if st == "RESERVED":
        charter["booked_seats"] -= booking["seats"]
        booking["booking_status"] = "CANCELLED"
        refund_if_paid(booking, charter, initiated_by)
        touch(booking)
        release_seats(charter)
    elif st == "WAITLISTED":
        booking["booking_status"] = "CANCELLED"
        refund_if_paid(booking, charter, initiated_by)
        touch(booking)
    elif st == "CHECKED_IN":
        charter["booked_seats"] -= booking["seats"]
        booking["booking_status"] = "CANCELLED"
        refund_if_paid(booking, charter, initiated_by)
        touch(booking)
        release_seats(charter)


def cancel_charter_cascade(charter):
    """Cancel a charter (terminal). Cancels active bookings with full refund."""
    charter["status"] = "CANCELLED"
    for b in sorted_by_seq(bookings_of_charter(charter["id"])):
        if b["booking_status"] in ("RESERVED", "WAITLISTED", "CHECKED_IN"):
            b["booking_status"] = "CANCELLED"
            refund_if_paid(b, charter, "guide")
            touch(b)
    charter["booked_seats"] = 0
    touch(charter)


def guide_schedule_conflict(guide_id, start_dt, end_dt, exclude_charter_id=None):
    buffer = timedelta(minutes=TURNAROUND_BUFFER_MINUTES)
    for ch in db.charters.values():
        if ch["guide_id"] != guide_id:
            continue
        if ch["status"] == "CANCELLED":
            continue
        if exclude_charter_id is not None and ch["id"] == exclude_charter_id:
            continue
        os_, oe = ch["_start_dt"], ch["_end_dt"]
        # overlap
        if start_dt < oe and os_ < end_dt:
            return True
        # gap
        if end_dt <= os_:
            gap = os_ - end_dt
        else:
            gap = start_dt - oe
        if gap < buffer:
            return True
    return False


ACTIVE_BOOKING_STATUSES = ("RESERVED", "WAITLISTED", "CHECKED_IN")


def angler_schedule_conflict(customer_id, start_dt, end_dt):
    for b in db.charter_bookings.values():
        if b["customer_id"] != customer_id:
            continue
        if b["booking_status"] not in ACTIVE_BOOKING_STATUSES:
            continue
        ch = db.charters.get(b["charter_id"])
        if ch is None:
            continue
        if start_dt < ch["_end_dt"] and ch["_start_dt"] < end_dt:
            return True
    return False


def customer_has_valid_license(customer_id, charter_start_dt):
    target_date = charter_start_dt.date()
    for s in db.license_sales.values():
        if s["customer_id"] != customer_id:
            continue
        if s["status"] != "ACTIVE":
            continue
        vf = parse_date(s["valid_from"])
        vu = parse_date(s["valid_until"])
        if vf <= target_date <= vu:
            return True
    return False


# ===========================================================================
# ROUTES
# ===========================================================================

# ---- Logical clock ----
@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    guard({"ShopManager", "ShopClerk"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        dt = parse_dt(body["to_iso8601"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400)
    db.clock = dt
    return ok({}, status=200)


# ---- Customers ----
@app.route("/api/customers", methods=["POST"])
def create_customer():
    guard_public_or({"Anonymous", "ShopClerk", "ShopManager"})
    body = get_body()
    require_fields(body, ["full_name", "email", "date_of_birth", "residency_state"])
    full_name = as_str(body["full_name"])
    email = as_str(body["email"])
    residency_state = as_str(body["residency_state"])
    try:
        parse_date(body["date_of_birth"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400)
    dob = body["date_of_birth"]
    for c in db.customers.values():
        if c["email"] == email:
            err("ERR_VALIDATION", 400)
    c = base_common()
    c.update({
        "full_name": full_name,
        "email": email,
        "date_of_birth": dob,
        "residency_state": residency_state,
        "loyalty_points_balance": 0,
        "lifetime_points_earned": 0,
        "loyalty_tier": "BRONZE",
        "status": "ACTIVE",
    })
    db.customers[c["id"]] = c
    return ok(ser_customer(c), status=201)


@app.route("/api/customers/<cid>", methods=["GET"])
def get_customer_route(cid):
    uid, role = guard({"Customer", "ShopClerk", "ShopManager"})
    c = get_customer(cid)
    if role == "Customer" and c["id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    return ok(ser_customer(c))


@app.route("/api/customers/<cid>/status", methods=["POST"])
def customer_status(cid):
    guard({"ShopManager"})
    body = get_body()
    require_fields(body, ["status"])
    target = body["status"]
    if target not in ("ACTIVE", "SUSPENDED"):
        err("ERR_VALIDATION", 400)
    c = get_customer(cid)
    if target == "SUSPENDED":
        if c["status"] != "ACTIVE":
            err("ERR_INVALID_STATE", 409)
        c["status"] = "SUSPENDED"
        touch(c)
        targets = [
            b for b in sorted_by_seq(list(db.charter_bookings.values()))
            if b["customer_id"] == cid and b["booking_status"] in ("RESERVED", "WAITLISTED")
        ]
        for b in targets:
            if b["booking_status"] in ("RESERVED", "WAITLISTED"):
                cancel_booking_cascade(b, "customer")
    else:  # ACTIVE
        if c["status"] != "SUSPENDED":
            err("ERR_INVALID_STATE", 409)
        c["status"] = "ACTIVE"
        touch(c)
    return ok(ser_customer(c))


@app.route("/api/customers/<cid>/loyalty-adjustments", methods=["POST"])
def loyalty_adjustment(cid):
    guard({"ShopManager"})
    body = get_body()
    require_fields(body, ["points_delta", "reason"])
    delta = as_int(body["points_delta"])
    as_str(body["reason"])
    c = get_customer(cid)
    if c["loyalty_points_balance"] + delta < 0:
        err("ERR_INSUFFICIENT_POINTS", 402)
    c["loyalty_points_balance"] += delta
    if delta > 0:
        c["lifetime_points_earned"] += delta
    recompute_tier(c)
    touch(c)
    return ok(ser_customer(c))


# ---- Products ----
@app.route("/api/products", methods=["POST"])
def create_product():
    guard({"ShopManager", "ShopClerk"})
    body = get_body()
    require_fields(body, ["sku", "name", "category", "unit_price_cents", "stock_qty"])
    sku = as_str(body["sku"])
    name = as_str(body["name"])
    category = body["category"]
    if category not in PRODUCT_CATEGORIES:
        err("ERR_VALIDATION", 400)
    unit_price = as_int(body["unit_price_cents"])
    stock_qty = as_int(body["stock_qty"])
    if unit_price < 0 or stock_qty < 0:
        err("ERR_VALIDATION", 400)
    for p in db.products.values():
        if p["sku"] == sku:
            err("ERR_VALIDATION", 400)
    p = base_common()
    p.update({
        "sku": sku,
        "name": name,
        "category": category,
        "unit_price_cents": unit_price,
        "stock_qty": stock_qty,
        "status": "ACTIVE",
    })
    db.products[p["id"]] = p
    return ok(ser_product(p), status=201)


@app.route("/api/products/<pid>", methods=["GET"])
def get_product_route(pid):
    guard({"Customer", "ShopClerk", "ShopManager"})
    p = get_product(pid)
    return ok(ser_product(p))


@app.route("/api/products/<pid>/restock", methods=["POST"])
def restock_product(pid):
    guard({"ShopClerk", "ShopManager"})
    body = get_body()
    require_fields(body, ["add_qty"])
    add_qty = as_int(body["add_qty"])
    if add_qty < 0:
        err("ERR_VALIDATION", 400)
    p = get_product(pid)
    p["stock_qty"] += add_qty
    touch(p)
    return ok(ser_product(p))


# ---- License Types ----
@app.route("/api/license-types", methods=["POST"])
def create_license_type():
    guard({"ShopManager"})
    body = get_body()
    require_fields(body, ["code", "state_code", "license_class", "base_price_cents",
                          "season_start_date", "season_end_date", "validity_days"])
    code = as_str(body["code"])
    state_code = as_str(body["state_code"])
    license_class = body["license_class"]
    if license_class not in LICENSE_CLASSES:
        err("ERR_VALIDATION", 400)
    base_price = as_int(body["base_price_cents"])
    if base_price < 0:
        err("ERR_VALIDATION", 400)
    validity_days = as_int(body["validity_days"])
    if validity_days <= 0:
        err("ERR_VALIDATION", 400)
    try:
        parse_date(body["season_start_date"])
        parse_date(body["season_end_date"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400)

    youth_max_age = as_int(body.get("youth_max_age"), allow_none=True)
    youth_price = as_int(body.get("youth_price_cents"), allow_none=True)
    senior_min_age = as_int(body.get("senior_min_age"), allow_none=True)
    senior_price = as_int(body.get("senior_price_cents"), allow_none=True)
    peak_surcharge = as_int(body.get("peak_surcharge_cents"), allow_none=True)
    if peak_surcharge is None:
        peak_surcharge = 0
    peak_start_month = as_int(body.get("peak_start_month"), allow_none=True)
    peak_end_month = as_int(body.get("peak_end_month"), allow_none=True)
    min_age = as_int(body.get("min_age"), allow_none=True)
    if min_age is None:
        min_age = 0

    for v in (youth_price, senior_price, peak_surcharge):
        if v is not None and v < 0:
            err("ERR_VALIDATION", 400)
    if min_age < 0:
        err("ERR_VALIDATION", 400)
    for m in (peak_start_month, peak_end_month):
        if m is not None and not (1 <= m <= 12):
            err("ERR_VALIDATION", 400)

    lt = base_common(with_version=False)
    lt.update({
        "code": code,
        "state_code": state_code,
        "license_class": license_class,
        "base_price_cents": base_price,
        "youth_max_age": youth_max_age,
        "youth_price_cents": youth_price,
        "senior_min_age": senior_min_age,
        "senior_price_cents": senior_price,
        "peak_surcharge_cents": peak_surcharge,
        "peak_start_month": peak_start_month,
        "peak_end_month": peak_end_month,
        "min_age": min_age,
        "season_start_date": body["season_start_date"],
        "season_end_date": body["season_end_date"],
        "validity_days": validity_days,
    })
    db.license_types[lt["id"]] = lt
    return ok(ser_license_type(lt), status=201)


@app.route("/api/license-types/<lid>", methods=["GET"])
def get_license_type_route(lid):
    guard({"Customer", "ShopClerk", "ShopManager"})
    lt = get_license_type(lid)
    return ok(ser_license_type(lt))


# ---- License Sales ----
@app.route("/api/license-sales", methods=["POST"])
def create_license_sale():
    uid, role = guard({"Customer", "ShopClerk", "ShopManager"})
    body = get_body()
    require_fields(body, ["customer_id", "license_type_id"])
    customer_id = as_str(body["customer_id"])
    license_type_id = as_str(body["license_type_id"])
    # existence left-to-right
    c = get_customer(customer_id)
    lt = get_license_type(license_type_id)
    # ownership
    if role == "Customer" and c["id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    # state: suspended
    if c["status"] == "SUSPENDED":
        err("ERR_CUSTOMER_SUSPENDED", 409)
    # business: age then season
    valid_from_date = now_clock().date()
    dob = parse_date(c["date_of_birth"])
    age = whole_years(dob, valid_from_date)
    if age < lt["min_age"]:
        err("ERR_AGE_REQUIREMENT_NOT_MET", 422)
    season_start = parse_date(lt["season_start_date"])
    season_end = parse_date(lt["season_end_date"])
    if not (season_start <= valid_from_date <= season_end):
        err("ERR_LICENSE_OUT_OF_SEASON", 422)

    price = compute_license_price(lt, age, valid_from_date)
    valid_until_date = valid_from_date + timedelta(days=lt["validity_days"] - 1)
    points = (price // 100) * POINTS_PER_DOLLAR

    s = base_common()
    s.update({
        "customer_id": customer_id,
        "license_type_id": license_type_id,
        "issued_at": clock_ts(),
        "valid_from": valid_from_date.isoformat(),
        "valid_until": valid_until_date.isoformat(),
        "price_paid_cents": price,
        "points_earned": points,
        "refund_amount_cents": None,
        "status": "ACTIVE",
    })
    db.license_sales[s["id"]] = s
    credit_points(c, points)
    return ok(ser_license_sale(s), status=201)


@app.route("/api/license-sales/<sid>", methods=["GET"])
def get_license_sale_route(sid):
    uid, role = guard({"Customer", "ShopClerk", "ShopManager"})
    s = get_license_sale(sid)
    if role == "Customer" and s["customer_id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    return ok(ser_license_sale(s))


@app.route("/api/license-sales", methods=["GET"])
def list_license_sales():
    uid, role = guard({"Customer", "ShopClerk", "ShopManager"})
    items = list(db.license_sales.values())
    if role == "Customer":
        items = [s for s in items if s["customer_id"] == uid]
    cf = request.args.get("customer_id")
    if cf is not None:
        items = [s for s in items if s["customer_id"] == cf]
    lf = request.args.get("license_type_id")
    if lf is not None:
        items = [s for s in items if s["license_type_id"] == lf]
    items = sorted_by_seq(items)
    window, pagination = paginate(items)
    return ok_list([ser_license_sale(s) for s in window], pagination)


@app.route("/api/license-sales/<sid>/void", methods=["POST"])
def void_license_sale(sid):
    guard({"ShopClerk", "ShopManager"})
    s = get_license_sale(sid)
    if s["status"] != "ACTIVE":
        err("ERR_ALREADY_VOIDED", 409)
    lt = db.license_types.get(s["license_type_id"])
    s["refund_amount_cents"] = compute_void_refund(s, lt)
    s["status"] = "VOIDED"
    touch(s)
    c = db.customers.get(s["customer_id"])
    if c is not None:
        reverse_points(c, s["points_earned"])
    return ok(ser_license_sale(s))


# ---- Guides ----
@app.route("/api/guides", methods=["POST"])
def create_guide():
    guard({"ShopManager"})
    body = get_body()
    require_fields(body, ["name", "license_no"])
    name = as_str(body["name"])
    license_no = as_str(body["license_no"])
    g = base_common()
    g.update({"name": name, "license_no": license_no, "status": "AVAILABLE"})
    db.guides[g["id"]] = g
    return ok(ser_guide(g), status=201)


@app.route("/api/guides/<gid>", methods=["GET"])
def get_guide_route(gid):
    uid, role = guard({"Guide", "ShopClerk", "ShopManager"})
    g = get_guide(gid)
    if role == "Guide" and g["id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    return ok(ser_guide(g))


@app.route("/api/guides/<gid>/status", methods=["POST"])
def guide_status(gid):
    guard({"ShopManager"})
    body = get_body()
    require_fields(body, ["status"])
    target = body["status"]
    if target not in ("AVAILABLE", "SUSPENDED"):
        err("ERR_VALIDATION", 400)
    g = get_guide(gid)
    if target == "SUSPENDED":
        if g["status"] != "AVAILABLE":
            err("ERR_INVALID_STATE", 409)
        g["status"] = "SUSPENDED"
        touch(g)
        charters = [
            ch for ch in sorted_by_seq(list(db.charters.values()))
            if ch["guide_id"] == gid and ch["status"] in ("OPEN", "FULL")
        ]
        for ch in charters:
            cancel_charter_cascade(ch)
    else:
        if g["status"] != "SUSPENDED":
            err("ERR_INVALID_STATE", 409)
        g["status"] = "AVAILABLE"
        touch(g)
    return ok(ser_guide(g))


# ---- Charters ----
@app.route("/api/charters", methods=["POST"])
def create_charter():
    uid, role = guard({"Guide", "ShopManager"})
    body = get_body()
    require_fields(body, ["guide_id", "title", "start_at", "end_at", "capacity", "price_per_seat_cents"])
    guide_id = as_str(body["guide_id"])
    title = as_str(body["title"])
    try:
        start_dt = parse_dt(body["start_at"])
        end_dt = parse_dt(body["end_at"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400)
    if end_dt <= start_dt:
        err("ERR_VALIDATION", 400)
    capacity = as_int(body["capacity"])
    if capacity <= 0:
        err("ERR_VALIDATION", 400)
    price_per_seat = as_int(body["price_per_seat_cents"])
    if price_per_seat < 0:
        err("ERR_VALIDATION", 400)
    fuel = as_int(body.get("fuel_surcharge_cents"), allow_none=True)
    if fuel is None:
        fuel = 0
    if fuel < 0:
        err("ERR_VALIDATION", 400)
    # existence
    g = get_guide(guide_id)
    # ownership
    if role == "Guide" and g["id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    # business: guide schedule conflict
    if guide_schedule_conflict(guide_id, start_dt, end_dt):
        err("ERR_GUIDE_SCHEDULE_CONFLICT", 409)
    ch = base_common()
    ch.update({
        "guide_id": guide_id,
        "title": title,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "capacity": capacity,
        "booked_seats": 0,
        "price_per_seat_cents": price_per_seat,
        "fuel_surcharge_cents": fuel,
        "status": "OPEN",
    })
    db.charters[ch["id"]] = ch
    return ok(ser_charter(ch), status=201)


@app.route("/api/charters/<cid>", methods=["GET"])
def get_charter_route(cid):
    guard({"Customer", "Guide", "ShopClerk", "ShopManager"})
    ch = get_charter(cid)
    return ok(ser_charter(ch))


@app.route("/api/charters", methods=["GET"])
def list_charters():
    guard({"Customer", "Guide", "ShopClerk", "ShopManager"})
    items = list(db.charters.values())
    gf = request.args.get("guide_id")
    if gf is not None:
        items = [ch for ch in items if ch["guide_id"] == gf]
    items = sorted_by_seq(items)
    window, pagination = paginate(items)
    return ok_list([ser_charter(ch) for ch in window], pagination)


@app.route("/api/charters/<cid>", methods=["PUT"])
def reschedule_charter(cid):
    uid, role = guard({"Guide", "ShopManager"})
    body = get_body()
    require_fields(body, ["expected_charter_version"])
    expected_version = as_int(body["expected_charter_version"])
    # optional fields validation
    new_start_raw = body.get("start_at")
    new_end_raw = body.get("end_at")
    start_dt = None
    end_dt = None
    if new_start_raw is not None:
        try:
            start_dt = parse_dt(new_start_raw)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400)
    if new_end_raw is not None:
        try:
            end_dt = parse_dt(new_end_raw)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400)
    capacity = as_int(body.get("capacity"), allow_none=True)
    if capacity is not None and capacity <= 0:
        err("ERR_VALIDATION", 400)
    price_per_seat = as_int(body.get("price_per_seat_cents"), allow_none=True)
    if price_per_seat is not None and price_per_seat < 0:
        err("ERR_VALIDATION", 400)
    fuel = as_int(body.get("fuel_surcharge_cents"), allow_none=True)
    if fuel is not None and fuel < 0:
        err("ERR_VALIDATION", 400)
    # existence
    ch = get_charter(cid)
    # ownership
    if role == "Guide" and ch["guide_id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    # OCC
    if expected_version != ch["version"]:
        err("ERR_STALE_VERSION", 412)
    # compute effective window
    eff_start = start_dt if start_dt is not None else ch["_start_dt"]
    eff_end = end_dt if end_dt is not None else ch["_end_dt"]
    if eff_end <= eff_start:
        err("ERR_VALIDATION", 400)
    # business: guide conflict against new window
    if guide_schedule_conflict(ch["guide_id"], eff_start, eff_end, exclude_charter_id=ch["id"]):
        err("ERR_GUIDE_SCHEDULE_CONFLICT", 409)
    if start_dt is not None:
        ch["start_at"] = new_start_raw
        ch["_start_dt"] = start_dt
    if end_dt is not None:
        ch["end_at"] = new_end_raw
        ch["_end_dt"] = end_dt
    if capacity is not None:
        ch["capacity"] = capacity
        if ch["status"] != "CANCELLED":
            if ch["booked_seats"] >= ch["capacity"]:
                ch["status"] = "FULL"
            else:
                ch["status"] = "OPEN"
    if price_per_seat is not None:
        ch["price_per_seat_cents"] = price_per_seat
    if fuel is not None:
        ch["fuel_surcharge_cents"] = fuel
    touch(ch)
    return ok(ser_charter(ch))


@app.route("/api/charters/<cid>/cancel", methods=["POST"])
def cancel_charter(cid):
    uid, role = guard({"Guide", "ShopManager"})
    ch = get_charter(cid)
    if role == "Guide" and ch["guide_id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    if ch["status"] not in ("OPEN", "FULL"):
        err("ERR_INVALID_STATE", 409)
    cancel_charter_cascade(ch)
    return ok(ser_charter(ch))


# ---- Charter Bookings ----
@app.route("/api/charter-bookings", methods=["POST"])
def create_booking():
    uid, role = guard({"Customer", "ShopClerk"})
    body = get_body()
    require_fields(body, ["charter_id", "customer_id", "seats"])
    charter_id = as_str(body["charter_id"])
    customer_id = as_str(body["customer_id"])
    seats = as_int(body["seats"])
    if seats <= 0:
        err("ERR_VALIDATION", 400)
    waitlist_requested = body.get("waitlist_requested", False)
    if not isinstance(waitlist_requested, bool):
        err("ERR_VALIDATION", 400)
    # existence left-to-right
    ch = get_charter(charter_id)
    c = get_customer(customer_id)
    # ownership
    if role == "Customer" and c["id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    # state: customer suspended, then charter open
    if c["status"] == "SUSPENDED":
        err("ERR_CUSTOMER_SUSPENDED", 409)
    if ch["status"] not in ("OPEN", "FULL"):
        err("ERR_CHARTER_NOT_OPEN", 409)
    # business: angler conflict
    if angler_schedule_conflict(customer_id, ch["_start_dt"], ch["_end_dt"]):
        err("ERR_ANGLER_SCHEDULE_CONFLICT", 409)
    # business: license required
    if not customer_has_valid_license(customer_id, ch["_start_dt"]):
        err("ERR_LICENSE_REQUIRED", 422)
    # business: seats
    remaining = ch["capacity"] - ch["booked_seats"]
    if seats > remaining:
        if not waitlist_requested:
            err("ERR_INSUFFICIENT_SEATS", 409)
        booking_status = "WAITLISTED"
    else:
        booking_status = "RESERVED"

    b = base_common()
    b.update({
        "charter_id": charter_id,
        "customer_id": customer_id,
        "seats": seats,
        "waitlist_requested": waitlist_requested,
        "booking_status": booking_status,
        "payment_status": "UNPAID",
        "provisional_total_cents": provisional_total(ch, seats),
        "final_total_cents": None,
        "amount_paid_cents": 0,
        "refund_amount_cents": None,
    })
    db.charter_bookings[b["id"]] = b
    if booking_status == "RESERVED":
        ch["booked_seats"] += seats
        if ch["booked_seats"] >= ch["capacity"]:
            ch["status"] = "FULL"
        touch(ch)
    return ok(ser_booking(b), status=201)


@app.route("/api/charter-bookings/<bid>", methods=["GET"])
def get_booking_route(bid):
    uid, role = guard({"Customer", "ShopClerk", "Guide", "ShopManager"})
    b = get_booking(bid)
    if role == "Customer" and b["customer_id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    return ok(ser_booking(b))


@app.route("/api/charter-bookings", methods=["GET"])
def list_bookings():
    uid, role = guard({"Customer", "ShopClerk", "Guide", "ShopManager"})
    items = list(db.charter_bookings.values())
    if role == "Customer":
        items = [b for b in items if b["customer_id"] == uid]
    cf = request.args.get("charter_id")
    if cf is not None:
        items = [b for b in items if b["charter_id"] == cf]
    custf = request.args.get("customer_id")
    if custf is not None:
        items = [b for b in items if b["customer_id"] == custf]
    items = sorted_by_seq(items)
    window, pagination = paginate(items)
    return ok_list([ser_booking(b) for b in window], pagination)


@app.route("/api/charter-bookings/<bid>/pay", methods=["POST"])
def pay_booking(bid):
    uid, role = guard({"Customer", "ShopClerk"})
    b = get_booking(bid)
    if role == "Customer" and b["customer_id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    if b["payment_status"] != "UNPAID":
        err("ERR_INVALID_STATE", 409)
    if b["booking_status"] not in ("RESERVED", "CHECKED_IN"):
        err("ERR_INVALID_STATE", 409)
    b["payment_status"] = "PAID"
    b["amount_paid_cents"] = b["provisional_total_cents"]
    touch(b)
    return ok(ser_booking(b))


@app.route("/api/charter-bookings/<bid>/check-in", methods=["POST"])
def checkin_booking(bid):
    uid, role = guard({"ShopClerk", "Guide"})
    b = get_booking(bid)
    ch = db.charters.get(b["charter_id"])
    if role == "Guide" and (ch is None or ch["guide_id"] != uid):
        err("ERR_UNAUTHORIZED", 403)
    if b["booking_status"] != "RESERVED":
        err("ERR_INVALID_STATE", 409)
    if b["payment_status"] != "PAID":
        err("ERR_PAYMENT_REQUIRED", 409)
    if ch is None or ch["status"] not in ("OPEN", "FULL"):
        err("ERR_INVALID_STATE", 409)
    b["booking_status"] = "CHECKED_IN"
    touch(b)
    return ok(ser_booking(b))


@app.route("/api/charter-bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    uid, role = guard({"Guide", "ShopClerk"})
    b = get_booking(bid)
    ch = db.charters.get(b["charter_id"])
    if role == "Guide" and (ch is None or ch["guide_id"] != uid):
        err("ERR_UNAUTHORIZED", 403)
    if b["booking_status"] != "CHECKED_IN":
        err("ERR_INVALID_STATE", 409)
    c = db.customers.get(b["customer_id"])
    tier = c["loyalty_tier"] if c else "BRONZE"
    b["booking_status"] = "COMPLETED"
    b["final_total_cents"] = final_total(ch, b["seats"], tier)
    touch(b)
    return ok(ser_booking(b))


@app.route("/api/charter-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = guard({"Customer", "ShopClerk", "ShopManager"})
    b = get_booking(bid)
    if role == "Customer" and b["customer_id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    if b["booking_status"] not in ("RESERVED", "WAITLISTED"):
        err("ERR_INVALID_STATE", 409)
    cancel_booking_cascade(b, "customer")
    return ok(ser_booking(b))


# ---- Tournaments ----
@app.route("/api/tournaments", methods=["POST"])
def create_tournament():
    guard({"ShopManager", "ShopClerk"})
    body = get_body()
    require_fields(body, ["name", "species", "start_at", "end_at", "min_qualifying_weight_grams"])
    name = as_str(body["name"])
    species = as_str(body["species"])
    try:
        start_dt = parse_dt(body["start_at"])
        end_dt = parse_dt(body["end_at"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400)
    if end_dt <= start_dt:
        err("ERR_VALIDATION", 400)
    min_qual = as_int(body["min_qualifying_weight_grams"])
    if min_qual < 0:
        err("ERR_VALIDATION", 400)
    entry_fee = as_int(body.get("entry_fee_cents"), allow_none=True)
    if entry_fee is None:
        entry_fee = 0
    if entry_fee < 0:
        err("ERR_VALIDATION", 400)
    prize_points = as_int(body.get("prize_points"), allow_none=True)
    if prize_points is None:
        prize_points = 0
    if prize_points < 0:
        err("ERR_VALIDATION", 400)
    t = base_common()
    t.update({
        "name": name,
        "species": species,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "entry_fee_cents": entry_fee,
        "min_qualifying_weight_grams": min_qual,
        "prize_points": prize_points,
        "status": "SCHEDULED",
    })
    db.tournaments[t["id"]] = t
    return ok(ser_tournament(t), status=201)


@app.route("/api/tournaments/<tid>", methods=["GET"])
def get_tournament_route(tid):
    guard({"Customer", "ShopClerk", "ShopManager"})
    t = get_tournament(tid)
    return ok(ser_tournament(t))


def entry_best_weight(entry, tournament):
    best = 0
    for w in entry["weigh_ins"]:
        if w["species"] != tournament["species"]:
            continue
        if w["weight_grams"] < tournament["min_qualifying_weight_grams"]:
            continue
        if not (tournament["_start_dt"] <= w["_recorded_dt"] <= tournament["_end_dt"]):
            continue
        if w["weight_grams"] > best:
            best = w["weight_grams"]
    return best


def earliest_qualifying_recorded(entry, tournament):
    times = [
        w["_recorded_dt"] for w in entry["weigh_ins"]
        if w["species"] == tournament["species"]
        and w["weight_grams"] >= tournament["min_qualifying_weight_grams"]
        and tournament["_start_dt"] <= w["_recorded_dt"] <= tournament["_end_dt"]
    ]
    return min(times) if times else None


@app.route("/api/tournaments/<tid>/status", methods=["POST"])
def tournament_status(tid):
    guard({"ShopManager", "ShopClerk"})
    body = get_body()
    require_fields(body, ["status"])
    target = body["status"]
    if target not in ("OPEN", "IN_PROGRESS", "FINALIZED", "CANCELLED"):
        err("ERR_VALIDATION", 400)
    t = get_tournament(tid)
    cur = t["status"]
    entries = [e for e in db.tournament_entries.values() if e["tournament_id"] == tid]

    if target == "OPEN":
        if cur != "SCHEDULED":
            err("ERR_INVALID_STATE", 409)
        t["status"] = "OPEN"
        touch(t)
    elif target == "IN_PROGRESS":
        if cur != "OPEN":
            err("ERR_INVALID_STATE", 409)
        t["status"] = "IN_PROGRESS"
        touch(t)
    elif target == "FINALIZED":
        if cur != "IN_PROGRESS":
            err("ERR_INVALID_STATE", 409)
        qualifying = [
            e for e in entries
            if e["status"] in ("CHECKED_IN", "WEIGHED")
            and e["best_weight_grams"] >= t["min_qualifying_weight_grams"]
        ]
        if not qualifying:
            err("ERR_NO_QUALIFIED_ENTRIES", 409)
        t["status"] = "FINALIZED"
        touch(t)

        def sort_key(e):
            eq = earliest_qualifying_recorded(e, t)
            return (-e["best_weight_grams"], eq, e["_seq"])

        ranked = sorted(qualifying, key=sort_key)
        for idx, e in enumerate(ranked, start=1):
            e["final_rank"] = idx
            touch(e)
        winner = ranked[0]
        winner["status"] = "WINNER"
        touch(winner)
        c = db.customers.get(winner["customer_id"])
        if c is not None and t["prize_points"] > 0:
            credit_points(c, t["prize_points"])
    else:  # CANCELLED
        if cur == "SCHEDULED":
            t["status"] = "CANCELLED"
            touch(t)
        elif cur == "OPEN":
            t["status"] = "CANCELLED"
            touch(t)
            for e in entries:
                if e["status"] in ("REGISTERED", "CHECKED_IN", "WEIGHED"):
                    e["status"] = "WITHDRAWN"
                    touch(e)
        else:
            err("ERR_INVALID_STATE", 409)
    return ok(ser_tournament(t))


# ---- Tournament Entries ----
@app.route("/api/tournament-entries", methods=["POST"])
def create_entry():
    uid, role = guard({"Customer", "ShopClerk"})
    body = get_body()
    require_fields(body, ["tournament_id", "customer_id"])
    tournament_id = as_str(body["tournament_id"])
    customer_id = as_str(body["customer_id"])
    # existence
    t = get_tournament(tournament_id)
    c = get_customer(customer_id)
    # ownership
    if role == "Customer" and c["id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    # state: tournament must be OPEN for registration
    if t["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409)
    # business: duplicate entry
    for e in db.tournament_entries.values():
        if e["tournament_id"] == tournament_id and e["customer_id"] == customer_id \
                and e["status"] in ("REGISTERED", "CHECKED_IN", "WEIGHED", "WINNER"):
            err("ERR_DUPLICATE_ENTRY", 409)
    e = base_common()
    e.update({
        "tournament_id": tournament_id,
        "customer_id": customer_id,
        "status": "REGISTERED",
        "weigh_ins": [],
        "best_weight_grams": 0,
        "final_rank": None,
    })
    db.tournament_entries[e["id"]] = e
    return ok(ser_entry(e), status=201)


@app.route("/api/tournament-entries/<eid>", methods=["GET"])
def get_entry_route(eid):
    uid, role = guard({"Customer", "ShopClerk", "ShopManager"})
    e = get_entry(eid)
    if role == "Customer" and e["customer_id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    return ok(ser_entry(e))


@app.route("/api/tournament-entries", methods=["GET"])
def list_entries():
    uid, role = guard({"Customer", "ShopClerk", "ShopManager"})
    items = list(db.tournament_entries.values())
    if role == "Customer":
        items = [e for e in items if e["customer_id"] == uid]
    tf = request.args.get("tournament_id")
    if tf is not None:
        items = [e for e in items if e["tournament_id"] == tf]
    cf = request.args.get("customer_id")
    if cf is not None:
        items = [e for e in items if e["customer_id"] == cf]
    items = sorted_by_seq(items)
    window, pagination = paginate(items)
    return ok_list([ser_entry(e) for e in window], pagination)


@app.route("/api/tournament-entries/<eid>/status", methods=["POST"])
def entry_status(eid):
    uid, role = guard({"Customer", "ShopClerk"})
    body = get_body()
    require_fields(body, ["status"])
    target = body["status"]
    if target not in ("CHECKED_IN", "WITHDRAWN"):
        err("ERR_VALIDATION", 400)
    e = get_entry(eid)
    if role == "Customer" and e["customer_id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    t = db.tournaments.get(e["tournament_id"])
    if target == "CHECKED_IN":
        if e["status"] != "REGISTERED":
            err("ERR_INVALID_STATE", 409)
        if t is None or t["status"] != "IN_PROGRESS":
            err("ERR_TOURNAMENT_NOT_IN_PROGRESS", 409)
        e["status"] = "CHECKED_IN"
        touch(e)
    else:  # WITHDRAWN
        if e["status"] not in ("REGISTERED", "CHECKED_IN"):
            err("ERR_INVALID_STATE", 409)
        e["status"] = "WITHDRAWN"
        touch(e)
    return ok(ser_entry(e))


@app.route("/api/tournament-entries/<eid>/weigh-in", methods=["POST"])
def weigh_in(eid):
    guard({"ShopClerk"})
    body = get_body()
    require_fields(body, ["species", "weight_grams"])
    species = as_str(body["species"])
    weight_grams = as_int(body["weight_grams"])
    if weight_grams < 0:
        err("ERR_VALIDATION", 400)
    e = get_entry(eid)
    t = db.tournaments.get(e["tournament_id"])
    if t is None or t["status"] != "IN_PROGRESS":
        err("ERR_TOURNAMENT_NOT_IN_PROGRESS", 409)
    if e["status"] not in ("CHECKED_IN", "WEIGHED"):
        err("ERR_INVALID_STATE", 409)
    recorded_dt = now_clock()
    e["weigh_ins"].append({
        "species": species,
        "weight_grams": weight_grams,
        "recorded_at": fmt_dt(recorded_dt),
        "_recorded_dt": recorded_dt,
    })
    # first qualifying weigh-in advances CHECKED_IN -> WEIGHED
    e["best_weight_grams"] = entry_best_weight(e, t)
    if e["status"] == "CHECKED_IN" and e["best_weight_grams"] > 0:
        e["status"] = "WEIGHED"
    touch(e)
    return ok(ser_entry(e))


# ---- Service Orders ----
@app.route("/api/service-orders", methods=["POST"])
def create_service_order():
    uid, role = guard({"Customer", "ShopClerk"})
    body = get_body()
    require_fields(body, ["customer_id", "service_type", "base_service_cents"])
    customer_id = as_str(body["customer_id"])
    service_type = body["service_type"]
    if service_type not in SERVICE_TYPES:
        err("ERR_VALIDATION", 400)
    base_service = as_int(body["base_service_cents"])
    if base_service < 0:
        err("ERR_VALIDATION", 400)
    product_id = body.get("product_id")
    if product_id is not None and not isinstance(product_id, str):
        err("ERR_VALIDATION", 400)
    line_price = as_int(body.get("line_price_cents_per_meter"), allow_none=True)
    if line_price is None:
        line_price = 0
    if line_price < 0:
        err("ERR_VALIDATION", 400)
    estimated = as_int(body.get("estimated_line_meters"), allow_none=True)
    if estimated is None:
        estimated = 0
    if estimated < 0:
        err("ERR_VALIDATION", 400)
    # existence left-to-right
    c = get_customer(customer_id)
    if product_id is not None:
        get_product(product_id)
    # ownership
    if role == "Customer" and c["id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    # state: suspended
    if c["status"] == "SUSPENDED":
        err("ERR_CUSTOMER_SUSPENDED", 409)
    o = base_common()
    o.update({
        "customer_id": customer_id,
        "product_id": product_id,
        "service_type": service_type,
        "base_service_cents": base_service,
        "line_price_cents_per_meter": line_price,
        "estimated_line_meters": estimated,
        "actual_line_meters": 0,
        "line_units": 0,
        "parts_cents": 0,
        "quoted_cents": None,
        "final_subtotal_cents": None,
        "grand_total_cents": None,
        "points_earned": 0,
        "stock_consumed": False,
        "status": "INTAKE",
    })
    db.service_orders[o["id"]] = o
    return ok(ser_service_order(o), status=201)


@app.route("/api/service-orders/<oid>", methods=["GET"])
def get_service_order_route(oid):
    uid, role = guard({"Customer", "ShopClerk", "ShopManager"})
    o = get_service_order(oid)
    if role == "Customer" and o["customer_id"] != uid:
        err("ERR_UNAUTHORIZED", 403)
    return ok(ser_service_order(o))


@app.route("/api/service-orders", methods=["GET"])
def list_service_orders():
    uid, role = guard({"Customer", "ShopClerk", "ShopManager"})
    items = list(db.service_orders.values())
    if role == "Customer":
        items = [o for o in items if o["customer_id"] == uid]
    cf = request.args.get("customer_id")
    if cf is not None:
        items = [o for o in items if o["customer_id"] == cf]
    pf = request.args.get("product_id")
    if pf is not None:
        items = [o for o in items if o["product_id"] == pf]
    items = sorted_by_seq(items)
    window, pagination = paginate(items)
    return ok_list([ser_service_order(o) for o in window], pagination)


SERVICE_TRANSITIONS = {
    "INTAKE": {"DIAGNOSED", "CANCELLED"},
    "DIAGNOSED": {"IN_PROGRESS", "INTAKE", "CANCELLED"},
    "IN_PROGRESS": {"DIAGNOSED", "READY", "CANCELLED"},
    "READY": {"PICKED_UP", "CANCELLED"},
    "PICKED_UP": set(),
    "CANCELLED": set(),
}


@app.route("/api/service-orders/<oid>/transition", methods=["POST"])
def transition_service_order(oid):
    guard({"ShopClerk"})
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    valid_targets = {"INTAKE", "DIAGNOSED", "IN_PROGRESS", "READY", "PICKED_UP", "CANCELLED"}
    if to_status not in valid_targets:
        err("ERR_VALIDATION", 400)
    o = get_service_order(oid)
    cur = o["status"]
    if to_status not in SERVICE_TRANSITIONS.get(cur, set()):
        err("ERR_INVALID_STATE", 409)

    if to_status == "DIAGNOSED":
        # INTAKE->DIAGNOSED or IN_PROGRESS->DIAGNOSED : (re)quote
        o["quoted_cents"] = o["base_service_cents"] + o["estimated_line_meters"] * o["line_price_cents_per_meter"]
        o["status"] = "DIAGNOSED"
        touch(o)
    elif to_status == "IN_PROGRESS":
        o["status"] = "IN_PROGRESS"
        touch(o)
    elif to_status == "INTAKE":
        o["quoted_cents"] = None
        o["status"] = "INTAKE"
        touch(o)
    elif to_status == "READY":
        actual = as_int(body.get("actual_line_meters"), allow_none=True)
        if actual is None:
            actual = 0
        if actual < 0:
            err("ERR_VALIDATION", 400)
        parts = as_int(body.get("parts_cents"), allow_none=True)
        if parts is None:
            parts = 0
        if parts < 0:
            err("ERR_VALIDATION", 400)
        line_units = as_int(body.get("line_units"), allow_none=True)
        if line_units is None:
            line_units = 0
        if line_units < 0:
            err("ERR_VALIDATION", 400)
        product = None
        if line_units > 0:
            if o["product_id"] is None:
                err("ERR_VALIDATION", 400)
            product = db.products.get(o["product_id"])
            if product is None:
                err("ERR_PRODUCT_NOT_FOUND", 404)
            if product["stock_qty"] < line_units:
                err("ERR_INSUFFICIENT_STOCK", 409)
        o["actual_line_meters"] = actual
        o["parts_cents"] = parts
        o["line_units"] = line_units
        o["final_subtotal_cents"] = (
            o["base_service_cents"] + actual * o["line_price_cents_per_meter"] + parts
        )
        if line_units > 0:
            product["stock_qty"] -= line_units
            o["stock_consumed"] = True
            touch(product)
        o["status"] = "READY"
        touch(o)
    elif to_status == "PICKED_UP":
        c = db.customers.get(o["customer_id"])
        tier = c["loyalty_tier"] if c else "BRONZE"
        grand = compute_grand_total(o["final_subtotal_cents"], tier)
        o["grand_total_cents"] = grand
        points = (grand // 100) * POINTS_PER_DOLLAR
        o["points_earned"] = points
        o["status"] = "PICKED_UP"
        touch(o)
        if c is not None:
            credit_points(c, points)
    elif to_status == "CANCELLED":
        if cur == "READY" and o["stock_consumed"]:
            product = db.products.get(o["product_id"])
            if product is not None:
                product["stock_qty"] += o["line_units"]
                touch(product)
            o["stock_consumed"] = False
        o["status"] = "CANCELLED"
        touch(o)
    return ok(ser_service_order(o))


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
