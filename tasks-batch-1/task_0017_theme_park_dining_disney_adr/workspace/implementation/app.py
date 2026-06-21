"""Theme Park Dining ADR API — Flask application.

Boots empty. start.sh re-launches a fresh process per pytest test under
per-test-server isolation, so module-level state is created from scratch
on every run. There is no seeding anywhere.
"""
import os
import re
from datetime import datetime, timedelta, timezone

from flask import Flask, request

from db import store, utc_now_iso
from errors import (
    ApiError, raise_err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_FK_NOT_FOUND,
    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_GUEST_SUSPENDED,
    ERR_INVALID_ALLERGEN, ERR_OUTSIDE_BOOKING_WINDOW, ERR_PAST_DINING_DATE,
    ERR_SLOT_OUTSIDE_HOURS, ERR_SLOT_MISALIGNED, ERR_SLOT_CAPACITY_EXCEEDED,
    ERR_GUEST_DOUBLE_BOOKING, ERR_PARK_SESSION_MISMATCH,
    ERR_INSUFFICIENT_CREDITS, ERR_PLAN_NOT_COVERING, ERR_ADDON_ALREADY_EXISTS,
    ERR_PARTY_SIZE_PATCH_INFEASIBLE, ERR_INVALID_REQUEST,
)
from middleware import get_auth, require_role
from response import success_object, success_array, error_response
from calculations import (
    parse_iso_to_dt, parse_visit_date, parse_hhmm,
    reservation_window_open_utc, resort_date_of_utc, utc_to_resort_dt,
    slot_grid_offset_minutes, credit_cost,
)
import services
from services import (
    common_create, bump_version, gen_id, now_iso,
    append_ledger_entry, release_credit_hold,
    cascade_cancel_addon_for_reservation, commit_no_show,
    find_allergy_meal_for_reservation, find_lightning_lane_addon_for_reservation,
    allocate_lightning_lane,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

API_PREFIX = "/v1"

ALLOWED_PARKS = {"MAGIC_KINGDOM", "EPCOT", "ANIMAL_KINGDOM", "HOLLYWOOD_STUDIOS"}
ALLOWED_PLAN_TIERS = {"STANDARD", "PLUS", "DELUXE"}
ALLOWED_ALLERGENS = {"PEANUT", "TREE_NUT", "GLUTEN", "DAIRY", "EGG", "SHELLFISH", "SOY"}
ALLOWED_LL_TIERS = {"SINGLE_PASS", "MULTI_PASS"}

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


# ============================================================
# Global error handlers
# ============================================================

@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Path not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 400)


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", f"Internal error: {e}", 500)


# ============================================================
# Request helpers
# ============================================================

def get_json_body() -> dict:
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body: dict, fields: list):
    for f in fields:
        if f not in body:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def pagination_params() -> tuple:
    """Extract limit/offset (PRD §2.3 defaults: 10/0; limit min 1, max 100)."""
    limit_str = request.args.get("limit")
    offset_str = request.args.get("offset")
    try:
        limit = int(limit_str) if limit_str is not None else 10
        offset = int(offset_str) if offset_str is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise_err(ERR_INVALID_REQUEST, "limit must be 1..100; offset >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple:
    return items[offset:offset + limit], len(items)


def get_current_utc_dt() -> datetime:
    return parse_iso_to_dt(store.current_utc)


# ============================================================
# Existence/FK lookups
# ============================================================

def get_guest_or_404(gid: str) -> dict:
    g = store.guests.get(gid)
    if not g:
        raise_err(ERR_NOT_FOUND, f"Guest {gid} not found")
    return g


def get_restaurant_or_404(rid: str) -> dict:
    r = store.restaurants.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, f"Restaurant {rid} not found")
    return r


def get_park_session_or_404(sid: str) -> dict:
    s = store.park_sessions.get(sid)
    if not s:
        raise_err(ERR_NOT_FOUND, f"ParkSession {sid} not found")
    return s


def get_dining_plan_or_404(pid: str) -> dict:
    p = store.dining_plans.get(pid)
    if not p:
        raise_err(ERR_NOT_FOUND, f"DiningPlan {pid} not found")
    return p


def get_reservation_or_404(rid: str) -> dict:
    r = store.reservations.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, f"Reservation {rid} not found")
    return r


def get_allergy_meal_or_404(mid: str) -> dict:
    m = store.allergy_meals.get(mid)
    if not m:
        raise_err(ERR_NOT_FOUND, f"AllergyMeal {mid} not found")
    return m


def get_ll_addon_or_404(aid: str) -> dict:
    a = store.lightning_lane_addons.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, f"LightningLaneAddOn {aid} not found")
    return a


def fk_lookup(coll: dict, fk: str, label: str) -> dict:
    v = coll.get(fk)
    if not v:
        raise_err(ERR_FK_NOT_FOUND, f"{label} {fk} not found")
    return v


# ============================================================
# Ownership helpers (PRD §2.1)
# ============================================================

def own_check_guest(role: str, uid: str, guest_id: str):
    """When role is Guest, X-User-ID must equal guest_id."""
    if role == "Guest" and uid != guest_id:
        raise_err(ERR_FORBIDDEN, "Guest may only access own resources")


def own_check_restaurant(role: str, uid: str, restaurant_id: str):
    """When role is Restaurant, X-User-ID must equal restaurant_id."""
    if role == "Restaurant" and uid != restaurant_id:
        raise_err(ERR_FORBIDDEN, "Restaurant may only access own resources")


# ============================================================
# Format helpers
# ============================================================

def to_iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ============================================================
# Guests
# ============================================================

@app.route(f"{API_PREFIX}/guests", methods=["POST"])
def create_guest():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["email", "full_name", "home_timezone"])
    email = body["email"]
    full_name = body["full_name"]
    home_tz = body["home_timezone"]
    if not isinstance(email, str) or not EMAIL_RE.match(email):
        raise_err(ERR_INVALID_REQUEST, "email must be RFC 5322-ish")
    if email != email.lower():
        raise_err(ERR_INVALID_REQUEST, "email must be lowercase")
    if not isinstance(full_name, str) or not full_name.strip():
        raise_err(ERR_INVALID_REQUEST, "full_name required")
    if not isinstance(home_tz, str) or not home_tz.strip():
        raise_err(ERR_INVALID_REQUEST, "home_timezone required")
    # Uniqueness of email across Guest
    for g in store.guests.values():
        if g["email"] == email:
            raise_err(ERR_INVALID_REQUEST, "email already registered")
    g = {
        "email": email,
        "full_name": full_name,
        "home_timezone": home_tz,
        "no_show_strike_count": 0,
        "status": "ACTIVE",
    }
    common_create(g)
    store.guests[g["id"]] = g
    return success_object(g, 201)


@app.route(f"{API_PREFIX}/guests/<gid>", methods=["GET"])
def get_guest(gid):
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    g = get_guest_or_404(gid)
    own_check_guest(role, uid, gid)
    return success_object(g, 200)


# ============================================================
# Restaurants
# ============================================================

@app.route(f"{API_PREFIX}/restaurants", methods=["POST"])
def create_restaurant():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, [
        "name", "park_code", "capacity_per_slot",
        "dining_plan_credit_cost", "no_show_base_fee_cents",
        "opening_local_time", "closing_local_time",
    ])
    name = body["name"]
    park = body["park_code"]
    cap = body["capacity_per_slot"]
    slot_min = body.get("slot_minutes", 30)
    is_char = body.get("is_character_dining", False)
    cost = body["dining_plan_credit_cost"]
    base_fee = body["no_show_base_fee_cents"]
    open_t = body["opening_local_time"]
    close_t = body["closing_local_time"]

    if not isinstance(name, str) or not name.strip():
        raise_err(ERR_INVALID_REQUEST, "name required")
    if park not in ALLOWED_PARKS:
        raise_err(ERR_INVALID_REQUEST, "park_code invalid")
    if not isinstance(cap, int) or not (1 <= cap <= 400):
        raise_err(ERR_INVALID_REQUEST, "capacity_per_slot must be 1..400")
    if not isinstance(slot_min, int) or slot_min != 30:
        raise_err(ERR_INVALID_REQUEST, "slot_minutes must be 30 in v1")
    if not isinstance(is_char, bool):
        raise_err(ERR_INVALID_REQUEST, "is_character_dining must be boolean")
    if not isinstance(cost, int) or not (1 <= cost <= 3):
        raise_err(ERR_INVALID_REQUEST, "dining_plan_credit_cost must be 1..3")
    if not isinstance(base_fee, int) or base_fee < 0:
        raise_err(ERR_INVALID_REQUEST, "no_show_base_fee_cents must be >= 0")
    try:
        oh, om = parse_hhmm(open_t)
        ch, cm = parse_hhmm(close_t)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "opening/closing_local_time must be HH:MM")
    # Sanity: closing is exclusive upper bound for slot start
    if (ch, cm) <= (oh, om):
        raise_err(ERR_INVALID_REQUEST,
                  "closing_local_time must be after opening_local_time")

    r = {
        "name": name,
        "park_code": park,
        "capacity_per_slot": cap,
        "slot_minutes": 30,
        "is_character_dining": is_char,
        "dining_plan_credit_cost": cost,
        "no_show_base_fee_cents": base_fee,
        "opening_local_time": open_t,
        "closing_local_time": close_t,
    }
    common_create(r)
    store.restaurants[r["id"]] = r
    return success_object(r, 201)


@app.route(f"{API_PREFIX}/restaurants/<rid>", methods=["GET"])
def get_restaurant(rid):
    _, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest", "Restaurant"])
    r = get_restaurant_or_404(rid)
    # Restaurants only see themselves
    if role == "Restaurant":
        uid, _ = get_auth()
        if uid != rid:
            raise_err(ERR_FORBIDDEN, "Restaurant may only access own row")
    return success_object(r, 200)


@app.route(f"{API_PREFIX}/restaurants", methods=["GET"])
def list_restaurants():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest", "Restaurant"])
    limit, offset = pagination_params()
    park = request.args.get("park_code")
    items = list(store.restaurants.values())
    if park:
        if park not in ALLOWED_PARKS:
            raise_err(ERR_INVALID_REQUEST, "park_code invalid")
        items = [r for r in items if r["park_code"] == park]
    items.sort(key=lambda r: r["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


# ============================================================
# Park Sessions
# ============================================================

@app.route(f"{API_PREFIX}/park-sessions", methods=["POST"])
def create_park_session():
    uid, role = get_auth()
    require_role(role, ["Guest", "PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["guest_id", "park_code", "visit_date"])
    guest_id = body["guest_id"]
    park = body["park_code"]
    visit_date = body["visit_date"]
    # FK check
    fk_lookup(store.guests, guest_id, "Guest")
    # Ownership: if Guest role, must own
    own_check_guest(role, uid, guest_id)
    if park not in ALLOWED_PARKS:
        raise_err(ERR_INVALID_REQUEST, "park_code invalid")
    try:
        parse_visit_date(visit_date)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "visit_date must be YYYY-MM-DD")

    s = {
        "guest_id": guest_id,
        "park_code": park,
        "visit_date": visit_date,
        "status": "NOT_STARTED",
        "activated_at": None,
        "closed_at": None,
    }
    common_create(s)
    store.park_sessions[s["id"]] = s
    return success_object(s, 201)


@app.route(f"{API_PREFIX}/park-sessions/<sid>", methods=["GET"])
def get_park_session(sid):
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    s = get_park_session_or_404(sid)
    own_check_guest(role, uid, s["guest_id"])
    return success_object(s, 200)


@app.route(f"{API_PREFIX}/park-sessions", methods=["GET"])
def list_park_sessions():
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    limit, offset = pagination_params()
    guest_id = request.args.get("guest_id")
    items = list(store.park_sessions.values())
    if guest_id:
        items = [s for s in items if s["guest_id"] == guest_id]
    if role == "Guest":
        items = [s for s in items if s["guest_id"] == uid]
    items.sort(key=lambda s: s["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


@app.route(f"{API_PREFIX}/park-sessions/<sid>/activate", methods=["POST"])
def activate_park_session(sid):
    uid, role = get_auth()
    require_role(role, ["Guest"])
    s = get_park_session_or_404(sid)
    own_check_guest(role, uid, s["guest_id"])
    if s["status"] != "NOT_STARTED":
        raise_err(ERR_INVALID_STATE, f"ParkSession is {s['status']}, must be NOT_STARTED")
    # Precondition: resort-projected current date == visit_date
    today_resort = resort_date_of_utc(get_current_utc_dt())
    vd = parse_visit_date(s["visit_date"])
    if today_resort != vd:
        raise_err(ERR_INVALID_STATE,
                  "Cannot activate: current resort date does not equal visit_date")
    s["activated_at"] = now_iso()
    s["status"] = "ACTIVE"
    bump_version(s)
    return success_object(s, 200)


@app.route(f"{API_PREFIX}/park-sessions/<sid>/close", methods=["POST"])
def close_park_session(sid):
    uid, role = get_auth()
    require_role(role, ["Guest"])
    s = get_park_session_or_404(sid)
    own_check_guest(role, uid, s["guest_id"])
    if s["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"ParkSession is {s['status']}, must be ACTIVE")
    s["closed_at"] = now_iso()
    s["status"] = "CLOSED"
    bump_version(s)
    return success_object(s, 200)


@app.route(f"{API_PREFIX}/park-sessions/<sid>/cancel", methods=["POST"])
def cancel_park_session(sid):
    uid, role = get_auth()
    require_role(role, ["Guest"])
    s = get_park_session_or_404(sid)
    own_check_guest(role, uid, s["guest_id"])
    if s["status"] != "NOT_STARTED":
        raise_err(ERR_INVALID_STATE, f"ParkSession is {s['status']}, must be NOT_STARTED")
    s["closed_at"] = now_iso()
    s["status"] = "CANCELLED"
    bump_version(s)
    # Two-hop cascade per PRD §3.2.
    # Hop 1: every Reservation with park_session_id == sid and status in
    # {PENDING, CONFIRMED} -> CANCELLED; for CONFIRMED ones release credits.
    for r in list(store.reservations.values()):
        if r["park_session_id"] != sid:
            continue
        if r["status"] not in ("PENDING", "CONFIRMED"):
            continue
        was_confirmed = r["status"] == "CONFIRMED"
        if was_confirmed:
            release_credit_hold(r)
        r["status"] = "CANCELLED"
        bump_version(r)
        # Hop 2: cascade attached LL add-on
        cascade_cancel_addon_for_reservation(r["id"])
    return success_object(s, 200)


# ============================================================
# Dining Plans
# ============================================================

@app.route(f"{API_PREFIX}/dining-plans", methods=["POST"])
def create_dining_plan():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["guest_id", "tier", "table_service_credits_initial",
                          "valid_from", "valid_until"])
    guest_id = body["guest_id"]
    tier = body["tier"]
    init_credits = body["table_service_credits_initial"]
    valid_from = body["valid_from"]
    valid_until = body["valid_until"]
    fk_lookup(store.guests, guest_id, "Guest")
    if tier not in ALLOWED_PLAN_TIERS:
        raise_err(ERR_INVALID_REQUEST, "tier invalid")
    if not isinstance(init_credits, int) or init_credits < 0:
        raise_err(ERR_INVALID_REQUEST, "table_service_credits_initial must be >= 0")
    try:
        vf = parse_iso_to_dt(valid_from)
        vu = parse_iso_to_dt(valid_until)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "valid_from/valid_until must be ISO 8601")
    if vu <= vf:
        raise_err(ERR_INVALID_REQUEST, "valid_until must be > valid_from")
    p = {
        "guest_id": guest_id,
        "tier": tier,
        "table_service_credits_initial": init_credits,
        "table_service_credits_remaining": init_credits,
        "table_service_credits_held": 0,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ACTIVE",
    }
    common_create(p)
    store.dining_plans[p["id"]] = p
    return success_object(p, 201)


@app.route(f"{API_PREFIX}/dining-plans/<pid>", methods=["GET"])
def get_dining_plan(pid):
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    p = get_dining_plan_or_404(pid)
    own_check_guest(role, uid, p["guest_id"])
    return success_object(p, 200)


@app.route(f"{API_PREFIX}/dining-plans", methods=["GET"])
def list_dining_plans():
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    limit, offset = pagination_params()
    guest_id = request.args.get("guest_id")
    items = list(store.dining_plans.values())
    if guest_id:
        items = [p for p in items if p["guest_id"] == guest_id]
    if role == "Guest":
        items = [p for p in items if p["guest_id"] == uid]
    items.sort(key=lambda p: p["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


# ============================================================
# Reservations
# ============================================================

def _slot_overlap(a_start: datetime, a_end: datetime,
                  b_start: datetime, b_end: datetime) -> bool:
    """Two half-open intervals [a_start, a_end) and [b_start, b_end) overlap."""
    return a_start < b_end and b_start < a_end


@app.route(f"{API_PREFIX}/reservations", methods=["POST"])
def create_reservation():
    uid, role = get_auth()
    require_role(role, ["Guest"])
    body = get_json_body()
    require_fields(body, ["guest_id", "restaurant_id", "park_session_id",
                          "dining_plan_id", "slot_start_utc", "party_size"])
    guest_id = body["guest_id"]
    restaurant_id = body["restaurant_id"]
    park_session_id = body["park_session_id"]
    dining_plan_id = body["dining_plan_id"]
    slot_start_str = body["slot_start_utc"]
    party_size = body["party_size"]

    # Priority 4 — FK existence (body-level)
    guest = fk_lookup(store.guests, guest_id, "Guest")
    restaurant = fk_lookup(store.restaurants, restaurant_id, "Restaurant")
    session = fk_lookup(store.park_sessions, park_session_id, "ParkSession")
    plan = fk_lookup(store.dining_plans, dining_plan_id, "DiningPlan")

    # Ownership: Guest must own the guest_id
    own_check_guest(role, uid, guest_id)

    # Basic type / range validation (before the §1.4 business ladder)
    if not isinstance(party_size, int) or not (1 <= party_size <= 12):
        raise_err(ERR_INVALID_REQUEST, "party_size must be integer in [1, 12]")
    try:
        slot_start = parse_iso_to_dt(slot_start_str)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "slot_start_utc must be ISO 8601")
    slot_end = slot_start + timedelta(minutes=int(restaurant["slot_minutes"]))

    # Priority 7 — Guest suspension check
    if guest["status"] == "SUSPENDED":
        raise_err(ERR_GUEST_SUSPENDED,
                  "Suspended guest may not create reservations")

    # Priority 9 — booking window open
    window_open = reservation_window_open_utc(
        # The window is computed off resort-date of slot_start
        utc_to_resort_dt(slot_start).date().isoformat()
    )
    now_utc = get_current_utc_dt()
    if now_utc < window_open:
        raise_err(ERR_OUTSIDE_BOOKING_WINDOW,
                  f"Window opens at {to_iso_z(window_open)}; now {to_iso_z(now_utc)}")

    # Priority 10 — past date
    today_resort = resort_date_of_utc(now_utc)
    visit_resort = utc_to_resort_dt(slot_start).date()
    if visit_resort < today_resort:
        raise_err(ERR_PAST_DINING_DATE, "Visit date is in the past")
    if visit_resort == today_resort and slot_start <= now_utc:
        # Same-day but slot has already started/ended in the past
        raise_err(ERR_PAST_DINING_DATE, "Slot has already begun")

    # Priority 11 — slot inside [opening, closing) wall-clock
    slot_resort = utc_to_resort_dt(slot_start)
    oh, om = parse_hhmm(restaurant["opening_local_time"])
    ch, cm = parse_hhmm(restaurant["closing_local_time"])
    slot_minute = slot_resort.hour * 60 + slot_resort.minute
    open_minute = oh * 60 + om
    close_minute = ch * 60 + cm
    if not (open_minute <= slot_minute < close_minute):
        raise_err(ERR_SLOT_OUTSIDE_HOURS,
                  "slot_start outside restaurant hours")

    # Priority 12 — 30-minute grid alignment
    offset_min = slot_grid_offset_minutes(slot_resort, (oh, om),
                                          int(restaurant["slot_minutes"]))
    if offset_min < 0 or (offset_min % int(restaurant["slot_minutes"])) != 0:
        raise_err(ERR_SLOT_MISALIGNED, "slot_start not on the 30-minute grid")
    # Also: seconds and microseconds must be zero for proper alignment
    if slot_start.second != 0 or slot_start.microsecond != 0:
        raise_err(ERR_SLOT_MISALIGNED, "slot_start must be aligned to a 30-minute boundary")

    # Priority 13 — restaurant slot capacity
    active_statuses = ("PENDING", "CONFIRMED", "CHECKED_IN", "SEATED")
    used = 0
    for r in store.reservations.values():
        if r["restaurant_id"] != restaurant_id:
            continue
        if r["status"] not in active_statuses:
            continue
        other_start = parse_iso_to_dt(r["slot_start_utc"])
        other_end = parse_iso_to_dt(r["slot_end_utc"])
        if _slot_overlap(slot_start, slot_end, other_start, other_end):
            used += int(r["party_size"])
    if used + int(party_size) > int(restaurant["capacity_per_slot"]):
        raise_err(ERR_SLOT_CAPACITY_EXCEEDED,
                  f"Capacity {restaurant['capacity_per_slot']} exceeded "
                  f"(currently {used}, requested {party_size})")

    # Priority 14 — guest double-booking with 60-min padded buffer (cross-park)
    pad = timedelta(minutes=60)
    for r in store.reservations.values():
        if r["guest_id"] != guest_id:
            continue
        if r["status"] not in active_statuses:
            continue
        other_start = parse_iso_to_dt(r["slot_start_utc"]) - pad
        other_end = parse_iso_to_dt(r["slot_end_utc"]) + pad
        if _slot_overlap(slot_start, slot_end, other_start, other_end):
            raise_err(ERR_GUEST_DOUBLE_BOOKING,
                      "Guest already has an overlapping reservation within 60-min buffer")

    # Priority 15 — park session referential consistency
    if (session["status"] not in ("NOT_STARTED", "ACTIVE")
            or session["park_code"] != restaurant["park_code"]
            or parse_visit_date(session["visit_date"]) != visit_resort):
        raise_err(ERR_PARK_SESSION_MISMATCH,
                  "ParkSession status/park_code/visit_date do not match candidate")

    # Note: at booking, the plan is NOT credit-checked. That happens at /confirm.
    r = {
        "guest_id": guest_id,
        "restaurant_id": restaurant_id,
        "park_session_id": park_session_id,
        "dining_plan_id": dining_plan_id,
        "slot_start_utc": slot_start_str,
        "slot_end_utc": to_iso_z(slot_end),
        "party_size": party_size,
        "credits_held": 0,
        "credits_debited": 0,
        "status": "PENDING",
        "confirmed_at": None,
        "checked_in_at": None,
        "no_show_assessed_at": None,
    }
    common_create(r)
    store.reservations[r["id"]] = r
    return success_object(r, 201)


@app.route(f"{API_PREFIX}/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest", "Restaurant"])
    r = get_reservation_or_404(rid)
    if role == "Guest":
        own_check_guest(role, uid, r["guest_id"])
    elif role == "Restaurant":
        own_check_restaurant(role, uid, r["restaurant_id"])
    return success_object(r, 200)


@app.route(f"{API_PREFIX}/reservations", methods=["GET"])
def list_reservations():
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest", "Restaurant"])
    limit, offset = pagination_params()
    guest_id = request.args.get("guest_id")
    restaurant_id = request.args.get("restaurant_id")
    park_session_id = request.args.get("park_session_id")
    dining_plan_id = request.args.get("dining_plan_id")
    status_filter = request.args.get("status")
    items = list(store.reservations.values())
    if guest_id:
        items = [r for r in items if r["guest_id"] == guest_id]
    if restaurant_id:
        items = [r for r in items if r["restaurant_id"] == restaurant_id]
    if park_session_id:
        items = [r for r in items if r["park_session_id"] == park_session_id]
    if dining_plan_id:
        items = [r for r in items if r["dining_plan_id"] == dining_plan_id]
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    if role == "Guest":
        items = [r for r in items if r["guest_id"] == uid]
    elif role == "Restaurant":
        items = [r for r in items if r["restaurant_id"] == uid]
    items.sort(key=lambda r: r["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


@app.route(f"{API_PREFIX}/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    uid, role = get_auth()
    require_role(role, ["Guest"])
    r = get_reservation_or_404(rid)
    own_check_guest(role, uid, r["guest_id"])
    if r["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, f"Reservation status is {r['status']}, must be PENDING")
    plan = store.dining_plans.get(r["dining_plan_id"])
    if plan is None:
        raise_err(ERR_FK_NOT_FOUND, "DiningPlan vanished")
    restaurant = store.restaurants.get(r["restaurant_id"])
    if restaurant is None:
        raise_err(ERR_FK_NOT_FOUND, "Restaurant vanished")
    session = store.park_sessions.get(r["park_session_id"])
    if session is None:
        raise_err(ERR_FK_NOT_FOUND, "ParkSession vanished")
    guest = store.guests.get(r["guest_id"])
    if guest is None:
        raise_err(ERR_FK_NOT_FOUND, "Guest vanished")

    # Guest must be ACTIVE
    if guest["status"] != "ACTIVE":
        raise_err(ERR_GUEST_SUSPENDED, "Suspended guest cannot confirm")
    # ParkSession must be NOT_STARTED or ACTIVE
    if session["status"] not in ("NOT_STARTED", "ACTIVE"):
        raise_err(ERR_INVALID_STATE,
                  f"ParkSession is {session['status']}, must be NOT_STARTED or ACTIVE")
    # DiningPlan coverage
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_COVERING, f"DiningPlan is {plan['status']}, not ACTIVE")
    slot_start = parse_iso_to_dt(r["slot_start_utc"])
    vf = parse_iso_to_dt(plan["valid_from"])
    vu = parse_iso_to_dt(plan["valid_until"])
    if not (vf <= slot_start < vu):
        raise_err(ERR_PLAN_NOT_COVERING,
                  "slot_start_utc not within plan validity window")
    # Credit sufficiency
    need = credit_cost(restaurant, r["party_size"])
    free = int(plan["table_service_credits_remaining"]) - int(plan["table_service_credits_held"])
    if free < need:
        raise_err(ERR_INSUFFICIENT_CREDITS,
                  f"Need {need} credits; only {free} free")
    # Commit
    r["credits_held"] = need
    plan["table_service_credits_held"] = int(plan["table_service_credits_held"]) + need
    bump_version(plan)
    append_ledger_entry(
        dining_plan_id=plan["id"], reservation_id=r["id"],
        entry_type="HOLD", credits_delta=+need,
    )
    r["confirmed_at"] = now_iso()
    r["status"] = "CONFIRMED"
    bump_version(r)
    return success_object(r, 200)


@app.route(f"{API_PREFIX}/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    uid, role = get_auth()
    require_role(role, ["Guest"])
    r = get_reservation_or_404(rid)
    own_check_guest(role, uid, r["guest_id"])
    body = get_json_body()
    if "expected_reservation_version" not in body:
        raise_err(ERR_INVALID_REQUEST,
                  "expected_reservation_version is required for cancel")
    expected = body["expected_reservation_version"]
    if not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_reservation_version must be integer")
    if r["status"] not in ("PENDING", "CONFIRMED"):
        raise_err(ERR_INVALID_STATE,
                  f"Reservation is {r['status']}, cannot cancel")
    # OCC check (priority 6)
    if expected != int(r["version"]):
        raise_err(ERR_STALE_VERSION,
                  f"Expected version {expected}, current {r['version']}")
    if r["status"] == "CONFIRMED":
        # Two-hour free-cancel window
        now_utc = get_current_utc_dt()
        slot_start = parse_iso_to_dt(r["slot_start_utc"])
        if now_utc >= slot_start - timedelta(hours=2):
            raise_err(ERR_INVALID_STATE,
                      "Free-cancel window has closed (within 2 hours of slot_start)")
        # Release credits + cascade LL add-on
        release_credit_hold(r)
    r["status"] = "CANCELLED"
    bump_version(r)
    # Cascade: any LL add-on in REQUESTED or ALLOCATED -> CANCELLED
    cascade_cancel_addon_for_reservation(r["id"])
    return success_object(r, 200)


@app.route(f"{API_PREFIX}/reservations/<rid>/check-in", methods=["POST"])
def check_in_reservation(rid):
    uid, role = get_auth()
    require_role(role, ["Guest"])
    r = get_reservation_or_404(rid)
    own_check_guest(role, uid, r["guest_id"])
    if r["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, f"Reservation is {r['status']}, must be CONFIRMED")
    session = store.park_sessions.get(r["park_session_id"])
    if session is None or session["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE,
                  "ParkSession must be ACTIVE at check-in")
    now_utc = get_current_utc_dt()
    slot_start = parse_iso_to_dt(r["slot_start_utc"])
    slot_end = parse_iso_to_dt(r["slot_end_utc"])
    if now_utc < slot_start - timedelta(minutes=15):
        raise_err(ERR_INVALID_STATE, "Too early to check in (>15 min before slot)")
    if now_utc > slot_end:
        raise_err(ERR_INVALID_STATE, "Check-in window has elapsed")
    restaurant = store.restaurants.get(r["restaurant_id"])
    plan = store.dining_plans.get(r["dining_plan_id"])
    if restaurant is None or plan is None:
        raise_err(ERR_FK_NOT_FOUND, "Restaurant or DiningPlan vanished")
    debit = credit_cost(restaurant, r["party_size"])
    held = int(r.get("credits_held", 0))
    # Adjust held bucket (reverse hold)
    plan["table_service_credits_held"] = int(plan["table_service_credits_held"]) - held
    # Debit remaining
    plan["table_service_credits_remaining"] = int(plan["table_service_credits_remaining"]) - debit
    bump_version(plan)
    append_ledger_entry(
        dining_plan_id=plan["id"], reservation_id=r["id"],
        entry_type="DEBIT", credits_delta=+debit,
    )
    r["credits_debited"] = debit
    r["credits_held"] = 0
    r["checked_in_at"] = now_iso()
    r["status"] = "CHECKED_IN"
    bump_version(r)
    return success_object(r, 200)


@app.route(f"{API_PREFIX}/reservations/<rid>/seat", methods=["POST"])
def seat_reservation(rid):
    uid, role = get_auth()
    require_role(role, ["Restaurant"])
    r = get_reservation_or_404(rid)
    own_check_restaurant(role, uid, r["restaurant_id"])
    if r["status"] != "CHECKED_IN":
        raise_err(ERR_INVALID_STATE, f"Reservation is {r['status']}, must be CHECKED_IN")
    r["status"] = "SEATED"
    bump_version(r)
    # Cascade: AllergyMeal REQUESTED -> ACKNOWLEDGED
    m = find_allergy_meal_for_reservation(r["id"])
    if m is not None and m["status"] == "REQUESTED":
        m["status"] = "ACKNOWLEDGED"
        bump_version(m)
    return success_object(r, 200)


@app.route(f"{API_PREFIX}/reservations/<rid>/complete", methods=["POST"])
def complete_reservation(rid):
    uid, role = get_auth()
    require_role(role, ["Restaurant"])
    r = get_reservation_or_404(rid)
    own_check_restaurant(role, uid, r["restaurant_id"])
    if r["status"] != "SEATED":
        raise_err(ERR_INVALID_STATE, f"Reservation is {r['status']}, must be SEATED")
    r["status"] = "COMPLETED"
    bump_version(r)
    # Cascade: AllergyMeal PREPARED -> SERVED
    m = find_allergy_meal_for_reservation(r["id"])
    if m is not None and m["status"] == "PREPARED":
        m["status"] = "SERVED"
        bump_version(m)
    # Cascade: LightningLaneAddOn ALLOCATED -> REDEEMED if still within window
    a = find_lightning_lane_addon_for_reservation(r["id"])
    if a is not None and a["status"] == "ALLOCATED":
        now_utc = get_current_utc_dt()
        if a.get("redemption_window_end_utc"):
            end = parse_iso_to_dt(a["redemption_window_end_utc"])
            if now_utc <= end:
                a["status"] = "REDEEMED"
                bump_version(a)
    return success_object(r, 200)


@app.route(f"{API_PREFIX}/reservations/<rid>/mark-no-show", methods=["POST"])
def mark_no_show(rid):
    uid, role = get_auth()
    require_role(role, ["Restaurant", "PlatformAdmin"])
    r = get_reservation_or_404(rid)
    if role == "Restaurant":
        own_check_restaurant(role, uid, r["restaurant_id"])
    if r["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, f"Reservation is {r['status']}, must be CONFIRMED")
    now_utc = get_current_utc_dt()
    slot_end = parse_iso_to_dt(r["slot_end_utc"])
    if not (now_utc > slot_end):
        raise_err(ERR_INVALID_STATE,
                  "Cannot mark no-show before slot_end_utc has fully elapsed")
    commit_no_show(r)
    return success_object(r, 200)


@app.route(f"{API_PREFIX}/reservations/<rid>/party-size", methods=["POST"])
def patch_party_size(rid):
    uid, role = get_auth()
    require_role(role, ["Guest"])
    r = get_reservation_or_404(rid)
    own_check_guest(role, uid, r["guest_id"])
    body = get_json_body()
    require_fields(body, ["party_size"])
    new_size = body["party_size"]
    if not isinstance(new_size, int) or not (1 <= new_size <= 12):
        raise_err(ERR_INVALID_REQUEST, "party_size must be integer in [1, 12]")
    if r["status"] not in ("PENDING", "CONFIRMED"):
        raise_err(ERR_INVALID_STATE, f"Reservation is {r['status']}, cannot patch")
    restaurant = store.restaurants.get(r["restaurant_id"])
    if restaurant is None:
        raise_err(ERR_FK_NOT_FOUND, "Restaurant vanished")
    # Re-check capacity excluding self
    slot_start = parse_iso_to_dt(r["slot_start_utc"])
    slot_end = parse_iso_to_dt(r["slot_end_utc"])
    active_statuses = ("PENDING", "CONFIRMED", "CHECKED_IN", "SEATED")
    used = 0
    for other in store.reservations.values():
        if other["id"] == r["id"]:
            continue
        if other["restaurant_id"] != restaurant["id"]:
            continue
        if other["status"] not in active_statuses:
            continue
        o_start = parse_iso_to_dt(other["slot_start_utc"])
        o_end = parse_iso_to_dt(other["slot_end_utc"])
        if _slot_overlap(slot_start, slot_end, o_start, o_end):
            used += int(other["party_size"])
    if used + new_size > int(restaurant["capacity_per_slot"]):
        raise_err(ERR_PARTY_SIZE_PATCH_INFEASIBLE,
                  "Patch exceeds slot capacity")
    # If CONFIRMED, also check credit budget
    if r["status"] == "CONFIRMED":
        plan = store.dining_plans.get(r["dining_plan_id"])
        if plan is None:
            raise_err(ERR_FK_NOT_FOUND, "DiningPlan vanished")
        new_hold = credit_cost(restaurant, new_size)
        delta = new_hold - int(r.get("credits_held", 0))
        # Free budget excludes the current hold (which already counts)
        free_excluding_self = (int(plan["table_service_credits_remaining"])
                                - int(plan["table_service_credits_held"]))
        # delta could be negative (releasing credits) or positive (holding more).
        # If positive, we need free_excluding_self to cover the delta.
        if delta > 0 and free_excluding_self < delta:
            raise_err(ERR_PARTY_SIZE_PATCH_INFEASIBLE,
                      "Patch exceeds plan credit budget")
        # Commit credit delta
        if delta != 0:
            plan["table_service_credits_held"] = int(plan["table_service_credits_held"]) + delta
            bump_version(plan)
            r["credits_held"] = new_hold
            entry_type = "HOLD" if delta > 0 else "RELEASE"
            append_ledger_entry(
                dining_plan_id=plan["id"], reservation_id=r["id"],
                entry_type=entry_type,
                credits_delta=delta,
            )
    r["party_size"] = new_size
    bump_version(r)
    return success_object(r, 200)


# ============================================================
# Allergy Meals
# ============================================================

@app.route(f"{API_PREFIX}/allergy-meals", methods=["POST"])
def create_allergy_meal():
    uid, role = get_auth()
    require_role(role, ["Guest"])
    body = get_json_body()
    require_fields(body, ["reservation_id", "allergen_codes"])
    reservation_id = body["reservation_id"]
    codes = body["allergen_codes"]
    notes = body.get("notes", "")
    r = fk_lookup(store.reservations, reservation_id, "Reservation")
    own_check_guest(role, uid, r["guest_id"])
    # priority 18: uniqueness
    if find_allergy_meal_for_reservation(reservation_id) is not None:
        raise_err(ERR_ADDON_ALREADY_EXISTS, "AllergyMeal already exists for this Reservation")
    # priority 8: allergen validation
    if not isinstance(codes, list) or len(codes) == 0:
        raise_err(ERR_INVALID_ALLERGEN, "allergen_codes must be non-empty array")
    for c in codes:
        if c not in ALLOWED_ALLERGENS:
            raise_err(ERR_INVALID_ALLERGEN, f"Allergen {c!r} not allowed")
    if not isinstance(notes, str):
        raise_err(ERR_INVALID_REQUEST, "notes must be string")
    m = {
        "reservation_id": reservation_id,
        "allergen_codes": list(codes),
        "notes": notes,
        "status": "REQUESTED",
        "declined_reason": None,
    }
    common_create(m)
    store.allergy_meals[m["id"]] = m
    return success_object(m, 201)


@app.route(f"{API_PREFIX}/allergy-meals/<mid>", methods=["GET"])
def get_allergy_meal(mid):
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest", "Restaurant"])
    m = get_allergy_meal_or_404(mid)
    if role in ("Guest", "Restaurant"):
        r = store.reservations.get(m["reservation_id"])
        if r is None:
            raise_err(ERR_NOT_FOUND, "Parent reservation not found")
        if role == "Guest":
            own_check_guest(role, uid, r["guest_id"])
        else:
            own_check_restaurant(role, uid, r["restaurant_id"])
    return success_object(m, 200)


@app.route(f"{API_PREFIX}/allergy-meals", methods=["GET"])
def list_allergy_meals():
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest", "Restaurant"])
    limit, offset = pagination_params()
    reservation_id = request.args.get("reservation_id")
    items = list(store.allergy_meals.values())
    if reservation_id:
        items = [m for m in items if m["reservation_id"] == reservation_id]
    if role in ("Guest", "Restaurant"):
        own_items = []
        for m in items:
            r = store.reservations.get(m["reservation_id"])
            if r is None:
                continue
            if role == "Guest" and r["guest_id"] == uid:
                own_items.append(m)
            elif role == "Restaurant" and r["restaurant_id"] == uid:
                own_items.append(m)
        items = own_items
    items.sort(key=lambda m: m["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


def _allergy_transition(mid: str, expected_from: str, to: str,
                        require_reservation_status: set,
                        body_extra=None):
    uid, role = get_auth()
    require_role(role, ["Restaurant"])
    m = get_allergy_meal_or_404(mid)
    r = store.reservations.get(m["reservation_id"])
    if r is None:
        raise_err(ERR_NOT_FOUND, "Parent reservation not found")
    own_check_restaurant(role, uid, r["restaurant_id"])
    if m["status"] != expected_from:
        raise_err(ERR_INVALID_STATE, f"AllergyMeal is {m['status']}, must be {expected_from}")
    if require_reservation_status is not None and r["status"] not in require_reservation_status:
        raise_err(ERR_INVALID_STATE,
                  f"Parent reservation is {r['status']}, must be one of {sorted(require_reservation_status)}")
    if body_extra:
        body_extra(m)
    m["status"] = to
    bump_version(m)
    return m


@app.route(f"{API_PREFIX}/allergy-meals/<mid>/acknowledge", methods=["POST"])
def ack_allergy_meal(mid):
    m = _allergy_transition(mid, "REQUESTED", "ACKNOWLEDGED",
                            {"CONFIRMED", "CHECKED_IN", "SEATED"})
    return success_object(m, 200)


@app.route(f"{API_PREFIX}/allergy-meals/<mid>/prepare", methods=["POST"])
def prepare_allergy_meal(mid):
    m = _allergy_transition(mid, "ACKNOWLEDGED", "PREPARED", {"SEATED"})
    return success_object(m, 200)


@app.route(f"{API_PREFIX}/allergy-meals/<mid>/serve", methods=["POST"])
def serve_allergy_meal(mid):
    m = _allergy_transition(mid, "PREPARED", "SERVED", {"SEATED", "COMPLETED"})
    return success_object(m, 200)


@app.route(f"{API_PREFIX}/allergy-meals/<mid>/revert-to-requested", methods=["POST"])
def revert_allergy_meal(mid):
    m = _allergy_transition(mid, "ACKNOWLEDGED", "REQUESTED",
                            {"CONFIRMED", "CHECKED_IN"})
    return success_object(m, 200)


@app.route(f"{API_PREFIX}/allergy-meals/<mid>/decline", methods=["POST"])
def decline_allergy_meal(mid):
    body = get_json_body()
    if "reason" not in body or not isinstance(body["reason"], str) or not body["reason"].strip():
        raise_err(ERR_INVALID_REQUEST, "reason is required for decline")
    def setter(m):
        m["declined_reason"] = body["reason"]
    # Decline is valid from REQUESTED with no constraint on parent reservation status
    m = _allergy_transition(mid, "REQUESTED", "DECLINED", None, body_extra=setter)
    return success_object(m, 200)


# ============================================================
# Lightning Lane Add-Ons
# ============================================================

@app.route(f"{API_PREFIX}/lightning-lane-addons", methods=["POST"])
def create_ll_addon():
    uid, role = get_auth()
    require_role(role, ["Guest"])
    body = get_json_body()
    require_fields(body, ["reservation_id", "tier"])
    reservation_id = body["reservation_id"]
    tier = body["tier"]
    r = fk_lookup(store.reservations, reservation_id, "Reservation")
    own_check_guest(role, uid, r["guest_id"])
    guest = store.guests.get(r["guest_id"])
    if guest and guest["status"] == "SUSPENDED":
        raise_err(ERR_GUEST_SUSPENDED, "Suspended guest may not create add-ons")
    if tier not in ALLOWED_LL_TIERS:
        raise_err(ERR_INVALID_REQUEST, "tier must be SINGLE_PASS or MULTI_PASS")
    if find_lightning_lane_addon_for_reservation(reservation_id) is not None:
        raise_err(ERR_ADDON_ALREADY_EXISTS, "LightningLaneAddOn already exists")
    a = {
        "reservation_id": reservation_id,
        "tier": tier,
        "fee_cents": 0,
        "status": "REQUESTED",
        "allocated_at": None,
        "redemption_window_end_utc": None,
    }
    common_create(a)
    store.lightning_lane_addons[a["id"]] = a
    return success_object(a, 201)


@app.route(f"{API_PREFIX}/lightning-lane-addons/<aid>", methods=["GET"])
def get_ll_addon(aid):
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    a = get_ll_addon_or_404(aid)
    if role == "Guest":
        r = store.reservations.get(a["reservation_id"])
        if r is None:
            raise_err(ERR_NOT_FOUND, "Parent reservation not found")
        own_check_guest(role, uid, r["guest_id"])
    return success_object(a, 200)


@app.route(f"{API_PREFIX}/lightning-lane-addons", methods=["GET"])
def list_ll_addons():
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    limit, offset = pagination_params()
    reservation_id = request.args.get("reservation_id")
    items = list(store.lightning_lane_addons.values())
    if reservation_id:
        items = [a for a in items if a["reservation_id"] == reservation_id]
    if role == "Guest":
        own = []
        for a in items:
            r = store.reservations.get(a["reservation_id"])
            if r is not None and r["guest_id"] == uid:
                own.append(a)
        items = own
    items.sort(key=lambda a: a["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


@app.route(f"{API_PREFIX}/lightning-lane-addons/<aid>/allocate", methods=["POST"])
def allocate_ll_addon(aid):
    uid, role = get_auth()
    require_role(role, ["Guest"])
    a = get_ll_addon_or_404(aid)
    r = store.reservations.get(a["reservation_id"])
    if r is None:
        raise_err(ERR_NOT_FOUND, "Parent reservation not found")
    own_check_guest(role, uid, r["guest_id"])
    body = get_json_body()
    if "expected_reservation_version" not in body:
        raise_err(ERR_INVALID_REQUEST,
                  "expected_reservation_version is required for allocate")
    expected = body["expected_reservation_version"]
    if not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_reservation_version must be integer")
    # State checks come before OCC per priority table (5 < 6)
    if a["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, f"AddOn is {a['status']}, must be REQUESTED")
    if r["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE,
                  f"Parent reservation is {r['status']}, must be CONFIRMED")
    if expected != int(r["version"]):
        raise_err(ERR_STALE_VERSION,
                  f"Expected version {expected}, current {r['version']}")
    restaurant = store.restaurants.get(r["restaurant_id"])
    if restaurant is None:
        raise_err(ERR_FK_NOT_FOUND, "Restaurant vanished")
    allocate_lightning_lane(a, r, restaurant)
    # Per scaffold §1.2.1 side-effect note: "increments Reservation.version by 1"
    bump_version(r)
    return success_object(a, 200)


@app.route(f"{API_PREFIX}/lightning-lane-addons/<aid>/redeem", methods=["POST"])
def redeem_ll_addon(aid):
    uid, role = get_auth()
    require_role(role, ["Guest", "Restaurant"])
    a = get_ll_addon_or_404(aid)
    r = store.reservations.get(a["reservation_id"])
    if r is None:
        raise_err(ERR_NOT_FOUND, "Parent reservation not found")
    if role == "Guest":
        own_check_guest(role, uid, r["guest_id"])
    elif role == "Restaurant":
        own_check_restaurant(role, uid, r["restaurant_id"])
    if a["status"] != "ALLOCATED":
        raise_err(ERR_INVALID_STATE, f"AddOn is {a['status']}, must be ALLOCATED")
    now_utc = get_current_utc_dt()
    if a.get("redemption_window_end_utc"):
        end = parse_iso_to_dt(a["redemption_window_end_utc"])
        if now_utc > end:
            raise_err(ERR_INVALID_STATE, "Redemption window has elapsed")
    a["status"] = "REDEEMED"
    bump_version(a)
    return success_object(a, 200)


@app.route(f"{API_PREFIX}/lightning-lane-addons/<aid>/cancel", methods=["POST"])
def cancel_ll_addon(aid):
    uid, role = get_auth()
    require_role(role, ["Guest"])
    a = get_ll_addon_or_404(aid)
    r = store.reservations.get(a["reservation_id"])
    if r is None:
        raise_err(ERR_NOT_FOUND, "Parent reservation not found")
    own_check_guest(role, uid, r["guest_id"])
    if a["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, f"AddOn is {a['status']}, must be REQUESTED")
    a["status"] = "CANCELLED"
    bump_version(a)
    return success_object(a, 200)


# ============================================================
# Read-only views: NoShowFeeAssessment, CreditLedgerEntry
# ============================================================

@app.route(f"{API_PREFIX}/no-show-fee-assessments/<aid>", methods=["GET"])
def get_no_show_assessment(aid):
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    a = store.no_show_fee_assessments.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, f"NoShowFeeAssessment {aid} not found")
    own_check_guest(role, uid, a["guest_id"])
    return success_object(a, 200)


@app.route(f"{API_PREFIX}/no-show-fee-assessments", methods=["GET"])
def list_no_show_assessments():
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    limit, offset = pagination_params()
    guest_id = request.args.get("guest_id")
    reservation_id = request.args.get("reservation_id")
    items = list(store.no_show_fee_assessments.values())
    if guest_id:
        items = [a for a in items if a["guest_id"] == guest_id]
    if reservation_id:
        items = [a for a in items if a["reservation_id"] == reservation_id]
    if role == "Guest":
        items = [a for a in items if a["guest_id"] == uid]
    items.sort(key=lambda a: a["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


@app.route(f"{API_PREFIX}/credit-ledger-entries/<eid>", methods=["GET"])
def get_ledger_entry(eid):
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    e = store.credit_ledger_entries.get(eid)
    if not e:
        raise_err(ERR_NOT_FOUND, f"CreditLedgerEntry {eid} not found")
    if role == "Guest":
        # Ownership via parent reservation -> guest
        r = store.reservations.get(e["reservation_id"])
        if r is None or r["guest_id"] != uid:
            raise_err(ERR_FORBIDDEN, "Not owner of related reservation")
    return success_object(e, 200)


@app.route(f"{API_PREFIX}/credit-ledger-entries", methods=["GET"])
def list_ledger_entries():
    uid, role = get_auth()
    require_role(role, ["PlatformAdmin", "Guest"])
    limit, offset = pagination_params()
    dining_plan_id = request.args.get("dining_plan_id")
    reservation_id = request.args.get("reservation_id")
    items = list(store.credit_ledger_entries.values())
    if dining_plan_id:
        items = [e for e in items if e["dining_plan_id"] == dining_plan_id]
    if reservation_id:
        items = [e for e in items if e["reservation_id"] == reservation_id]
    if role == "Guest":
        own = []
        for e in items:
            r = store.reservations.get(e["reservation_id"])
            if r is not None and r["guest_id"] == uid:
                own.append(e)
        items = own
    items.sort(key=lambda e: e["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


# ============================================================
# Test-driving clock and ops sweeps
# ============================================================

@app.route(f"{API_PREFIX}/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    to_iso = body["to_iso8601"]
    try:
        dt = parse_iso_to_dt(to_iso)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601")
    # Normalise to the canonical 3-fractional-digit Z form for consistency.
    store.current_utc = to_iso_z(dt)
    return success_object({"current_utc": store.current_utc}, 200)


@app.route(f"{API_PREFIX}/_ops/no-show-sweep", methods=["POST"])
def no_show_sweep():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    now_utc = get_current_utc_dt()
    swept_ids = []
    # Iterate over a snapshot to avoid mutation-during-iter pitfalls.
    for r in list(store.reservations.values()):
        if r["status"] != "CONFIRMED":
            continue
        slot_end = parse_iso_to_dt(r["slot_end_utc"])
        if not (now_utc > slot_end):
            continue
        commit_no_show(r)
        swept_ids.append(r["id"])
    return success_object({"swept_count": len(swept_ids),
                           "swept_reservation_ids": swept_ids}, 200)


@app.route(f"{API_PREFIX}/_ops/lightning-lane-expiry-sweep", methods=["POST"])
def ll_expiry_sweep():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    now_utc = get_current_utc_dt()
    expired_ids = []
    for a in list(store.lightning_lane_addons.values()):
        if a["status"] != "ALLOCATED":
            continue
        end_str = a.get("redemption_window_end_utc")
        if not end_str:
            continue
        end = parse_iso_to_dt(end_str)
        if not (now_utc > end):
            continue
        a["status"] = "EXPIRED"
        bump_version(a)
        expired_ids.append(a["id"])
    return success_object({"expired_count": len(expired_ids),
                           "expired_addon_ids": expired_ids}, 200)


# ============================================================
# Health
# ============================================================

@app.route("/", methods=["GET"])
def root():
    return success_object({"service": "theme-park-dining-adr"}, 200)


@app.route("/healthz", methods=["GET"])
def healthz():
    return success_object({"ok": True}, 200)


# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
