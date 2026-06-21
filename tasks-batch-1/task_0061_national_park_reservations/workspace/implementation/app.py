import os
import re
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ===========================================================================
# Constants
# ===========================================================================

ROLES = ("visitor", "ranger", "park_admin", "finance", "system")
PUBLIC_FACING_ROLES = ("visitor", "ranger", "park_admin", "finance")

HOLD_SECONDS = 15 * 60
OFFER_SECONDS = 24 * 3600
AWARD_SECONDS = 72 * 3600
VOID_WINDOW_DAYS = 30

PASS_PRICE = {
    "annual": 8000,
    "senior_annual": 2000,
    "senior_lifetime": 8000,
    "military": 0,
    "access": 0,
}
PASS_TYPES = set(PASS_PRICE.keys())
SENIOR_TYPES = ("senior_annual", "senior_lifetime")


# ===========================================================================
# In-memory store (starts empty every boot; never seeded)
# ===========================================================================

class DB:
    def __init__(self):
        self.accounts = {}
        self.parks = {}
        self.atb_passes = {}
        self.timed_entry_slots = {}
        self.timed_entry_reservations = {}
        self.lottery_draws = {}
        self.lottery_applications = {}
        self.trailheads = {}
        self.wilderness_zones = {}
        self.backcountry_permits = {}
        self.campsites = {}
        self.camp_reservations = {}
        self.waitlist_entries = {}
        self.payments = {}
        self.clock = None
        # Idempotency: key -> (body_fingerprint, response_data, status)
        self.idempotency = {}


db = DB()


# ===========================================================================
# Clock
# ===========================================================================

DEFAULT_NOW = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_utc():
    return db.clock if db.clock is not None else DEFAULT_NOW


# ===========================================================================
# Errors
# ===========================================================================

class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# ===========================================================================
# Helpers — id, time formatting
# ===========================================================================

def new_id():
    return str(uuid.uuid4())


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO-8601 datetime string into an aware UTC datetime. Raise ValueError on failure."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    """Validate and parse an ISO YYYY-MM-DD date. Raise ValueError on failure."""
    if not isinstance(s, str) or not DATE_RE.match(s):
        raise ValueError("bad date")
    return datetime.strptime(s, "%Y-%m-%d").date()


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ===========================================================================
# Response envelope
# ===========================================================================

def meta(pagination=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": iso(datetime.now(timezone.utc))}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200):
    rt = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": meta(), "response_type": rt, "data": data}), status


def ok_list(items, total, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    }
    return jsonify({"meta": meta(pagination), "response_type": "array", "data": items}), 200


def err_response(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def handle_404(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found."))


@app.errorhandler(405)
def handle_405(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found."))


# ===========================================================================
# Auth
# ===========================================================================

class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Validate X-User-Role / X-User-ID. ERR_UNAUTHORIZED if missing/unknown role.
    ERR_FORBIDDEN if role not in allowed_roles."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHORIZED", 401, "Missing or unknown role.")
    if role != "system" and user_id is None:
        raise ApiError("ERR_UNAUTHORIZED", 401, "Missing user id.")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation.")
    return Principal(user_id, role)


def acting_account(principal):
    """Return the Account record for an entity-backed principal (visitor/ranger/park_admin), else None."""
    if principal.role in ("visitor", "ranger", "park_admin"):
        return db.accounts.get(principal.user_id)
    return None


# ===========================================================================
# Body parsing & field validation
# ===========================================================================

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object.")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return data[field]


def req_str(data, field):
    v = require(data, field)
    if not isinstance(v, str) or v.strip() == "":
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a non-empty string.")
    return v


def req_int(data, field):
    v = require(data, field)
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an integer.")
    return v


# ===========================================================================
# Common fields
# ===========================================================================

_create_seq = itertools.count(1)


def stamp_new(rec):
    n = now_utc()
    rec["created_at"] = n
    rec["updated_at"] = n
    rec["version"] = 1
    rec["created_seq"] = next(_create_seq)
    return rec


def touch(rec):
    rec["updated_at"] = now_utc()
    rec["version"] = rec.get("version", 1) + 1


# ===========================================================================
# Idempotency
# ===========================================================================

def fingerprint():
    raw = request.get_data(cache=True) or b""
    return raw.decode("utf-8", errors="replace")


def idem_lookup():
    """Return a stored (data, status) for a replayed key, raise ERR_IDEMPOTENCY_CONFLICT
    when the same key arrives with a different body, or None when the key is fresh/absent."""
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None
    fp = fingerprint()
    if key in db.idempotency:
        stored_fp, data, status = db.idempotency[key]
        if stored_fp != fp:
            raise ApiError("ERR_IDEMPOTENCY_CONFLICT", 409, "Idempotency-Key reused with a different body.")
        return (data, status)
    return None


def idem_store(data, status):
    key = request.headers.get("Idempotency-Key")
    if key:
        db.idempotency[key] = (fingerprint(), data, status)


# ===========================================================================
# Park-local time helpers
# ===========================================================================

def park_local_dt(park, instant):
    """Convert a UTC instant into the park's local civil datetime (naive wall time)."""
    offset = park.get("utc_offset_minutes", 0)
    return instant + timedelta(minutes=offset)


def park_local_date(park, instant):
    return park_local_dt(park, instant).date()


def local_window_to_utc(park, date_obj, hhmm):
    """Convert a park-local date + HH:MM into a UTC datetime. local = utc + offset => utc = local - offset."""
    h, m = hhmm.split(":")
    local_naive = datetime(date_obj.year, date_obj.month, date_obj.day, int(h), int(m))
    offset = park.get("utc_offset_minutes", 0)
    return (local_naive - timedelta(minutes=offset)).replace(tzinfo=timezone.utc)


# ===========================================================================
# Payment helpers
# ===========================================================================

def create_payment(account_id, kind, ref_type, ref_id, amount_cents, capture):
    p = {
        "id": new_id(),
        "account_id": account_id,
        "kind": kind,
        "ref_type": ref_type,
        "ref_id": ref_id,
        "amount_cents": amount_cents,
        "captured_cents": amount_cents if capture else 0,
        "refunded_cents": 0,
        "status": "captured" if capture else "authorized",
    }
    stamp_new(p)
    db.payments[p["id"]] = p
    return p


def void_payment(payment_id):
    p = db.payments.get(payment_id)
    if p is None:
        return
    p["status"] = "voided"
    touch(p)


def capture_payment(payment_id):
    p = db.payments.get(payment_id)
    if p is None:
        return
    p["captured_cents"] = p["amount_cents"]
    p["status"] = "captured"
    touch(p)


def refund_payment(payment_id, amount):
    p = db.payments.get(payment_id)
    if p is None:
        return
    if p["refunded_cents"] + amount > p["captured_cents"]:
        raise ApiError("ERR_OVER_REFUND", 409, "Refund exceeds captured amount.")
    p["refunded_cents"] += amount
    if p["refunded_cents"] >= p["captured_cents"] and p["captured_cents"] > 0:
        p["status"] = "refunded"
    elif p["refunded_cents"] > 0:
        p["status"] = "partially_refunded"
    touch(p)


def credit_account(account_id, amount):
    acc = db.accounts.get(account_id)
    if acc is not None:
        acc["credit_balance_cents"] += amount
        touch(acc)


# ===========================================================================
# Calculations
# ===========================================================================

def calc_atb_valid_to(pass_type, valid_from_date):
    if pass_type == "senior_lifetime":
        return None
    return (valid_from_date + timedelta(days=365)).strftime("%Y-%m-%d")


def calc_camp_total(campsite, party_size, nights):
    if campsite["site_type"] in ("tent", "rv"):
        return campsite["base_nightly_cents"] * nights
    extra = max(0, party_size - campsite["group_included_persons"])
    per_night = campsite["group_base_cents"] + campsite["group_extra_person_cents"] * extra
    return per_night * nights


def calc_backcountry_fee(trailhead, party_size, nights):
    flat = trailhead["reservation_fee_cents"]
    variable = trailhead["per_person_per_night_cents"] * party_size * nights
    return flat, variable, flat + variable


def refund_pct(D):
    if D >= 14:
        return 100
    if 7 <= D <= 13:
        return 50
    if 2 <= D <= 6:
        return 25
    return 0


def calc_refund(refundable_base, D):
    pct = refund_pct(D)
    val = (Decimal(refundable_base) * Decimal(pct) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(val)


# ===========================================================================
# Pagination
# ===========================================================================

def paginate(items):
    """items: list of records sorted by created_at asc. Returns (page_items, total, limit, offset)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer.")
        if limit < 1:
            raise ApiError("ERR_VALIDATION", 400, "limit must be >= 1.")
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0.")
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset


def sorted_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))


# ===========================================================================
# Lookups
# ===========================================================================

def must_get(store, _id, label="Resource"):
    rec = store.get(_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found.")
    return rec


# ===========================================================================
# Serializers
# ===========================================================================

def ser_common(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_account(r):
    d = ser_common(r)
    d.update({
        "email": r["email"],
        "full_name": r["full_name"],
        "birth_date": r["birth_date"],
        "role": r["role"],
        "home_park_id": r["home_park_id"],
        "credit_balance_cents": r["credit_balance_cents"],
        "status": r["status"],
    })
    return d


def ser_park(r):
    d = ser_common(r)
    d.update({
        "code": r["code"],
        "name": r["name"],
        "utc_offset_minutes": r["utc_offset_minutes"],
        "timed_entry_required": r["timed_entry_required"],
        "status": r["status"],
    })
    return d


def ser_pass(r):
    d = ser_common(r)
    d.update({
        "account_id": r["account_id"],
        "pass_type": r["pass_type"],
        "price_cents": r["price_cents"],
        "valid_from": r["valid_from"],
        "valid_to": r["valid_to"],
        "status": r["status"],
        "payment_id": r["payment_id"],
    })
    return d


def ser_slot(r):
    d = ser_common(r)
    d.update({
        "park_id": r["park_id"],
        "entry_date": r["entry_date"],
        "window_start_local": r["window_start_local"],
        "window_end_local": r["window_end_local"],
        "capacity": r["capacity"],
        "held_count": r["held_count"],
        "booked_count": r["booked_count"],
        "release_at": iso(r["release_at"]),
        "entry_fee_cents": r["entry_fee_cents"],
    })
    return d


def ser_te_res(r):
    d = ser_common(r)
    d.update({
        "slot_id": r["slot_id"],
        "account_id": r["account_id"],
        "vehicle_plate": r["vehicle_plate"],
        "status": r["status"],
        "hold_expires_at": iso(r["hold_expires_at"]),
        "fee_cents": r["fee_cents"],
        "payment_id": r["payment_id"],
    })
    return d


def ser_draw(r):
    d = ser_common(r)
    d.update({
        "park_id": r["park_id"],
        "objective": r["objective"],
        "use_date": r["use_date"],
        "daily_quota": r["daily_quota"],
        "awarded_count": r["awarded_count"],
        "application_open_at": iso(r["application_open_at"]),
        "application_close_at": iso(r["application_close_at"]),
        "draw_at": iso(r["draw_at"]),
        "application_fee_cents": r["application_fee_cents"],
        "permit_fee_per_person_cents": r["permit_fee_per_person_cents"],
        "max_group_size": r["max_group_size"],
        "status": r["status"],
    })
    return d


def ser_app(r):
    d = ser_common(r)
    d.update({
        "draw_id": r["draw_id"],
        "account_id": r["account_id"],
        "party_size": r["party_size"],
        "preference_rank": r["preference_rank"],
        "status": r["status"],
        "application_fee_cents": r["application_fee_cents"],
        "application_payment_id": r["application_payment_id"],
        "permit_payment_id": r["permit_payment_id"],
        "award_accept_deadline": iso(r["award_accept_deadline"]),
    })
    return d


def ser_trailhead(r):
    d = ser_common(r)
    d.update({
        "park_id": r["park_id"],
        "name": r["name"],
        "daily_exit_quota": r["daily_exit_quota"],
        "exit_used_by_date": r["exit_used_by_date"],
        "reservation_fee_cents": r["reservation_fee_cents"],
        "per_person_per_night_cents": r["per_person_per_night_cents"],
    })
    return d


def ser_zone(r):
    d = ser_common(r)
    d.update({
        "park_id": r["park_id"],
        "name": r["name"],
        "nightly_party_quota": r["nightly_party_quota"],
        "used_by_date": r["used_by_date"],
    })
    return d


def ser_permit(r):
    d = ser_common(r)
    d.update({
        "park_id": r["park_id"],
        "account_id": r["account_id"],
        "trailhead_id": r["trailhead_id"],
        "entry_date": r["entry_date"],
        "nights": r["nights"],
        "party_size": r["party_size"],
        "zone_nights": r["zone_nights"],
        "status": r["status"],
        "hold_expires_at": iso(r["hold_expires_at"]),
        "fee_cents": r["fee_cents"],
        "refunded_cents": r["refunded_cents"],
        "payment_id": r["payment_id"],
    })
    return d


def ser_campsite(r):
    d = ser_common(r)
    d.update({
        "park_id": r["park_id"],
        "site_number": r["site_number"],
        "site_type": r["site_type"],
        "max_occupancy": r["max_occupancy"],
        "booking_window_days": r["booking_window_days"],
        "base_nightly_cents": r["base_nightly_cents"],
        "group_base_cents": r["group_base_cents"],
        "group_included_persons": r["group_included_persons"],
        "group_extra_person_cents": r["group_extra_person_cents"],
        "status": r["status"],
    })
    return d


def ser_camp_res(r):
    d = ser_common(r)
    d.update({
        "campsite_id": r["campsite_id"],
        "account_id": r["account_id"],
        "check_in": r["check_in"],
        "check_out": r["check_out"],
        "party_size": r["party_size"],
        "status": r["status"],
        "hold_expires_at": iso(r["hold_expires_at"]),
        "total_cents": r["total_cents"],
        "refunded_cents": r["refunded_cents"],
        "payment_id": r["payment_id"],
        "origin_waitlist_id": r["origin_waitlist_id"],
    })
    return d


def ser_waitlist(r):
    d = ser_common(r)
    d.update({
        "campsite_id": r["campsite_id"],
        "account_id": r["account_id"],
        "check_in": r["check_in"],
        "check_out": r["check_out"],
        "party_size": r["party_size"],
        "position": r["position"],
        "status": r["status"],
        "offer_expires_at": iso(r["offer_expires_at"]),
    })
    return d


def ser_payment(r):
    d = ser_common(r)
    d.update({
        "account_id": r["account_id"],
        "kind": r["kind"],
        "ref_type": r["ref_type"],
        "ref_id": r["ref_id"],
        "amount_cents": r["amount_cents"],
        "captured_cents": r["captured_cents"],
        "refunded_cents": r["refunded_cents"],
        "status": r["status"],
    })
    return d


def ser_clock(r):
    return {
        "id": "clock",
        "created_at": iso(r["created_at"]),
        "now_utc": iso(r["now_utc"]),
    }


# ===========================================================================
# Park-scope helper
# ===========================================================================

def require_park_scope(principal, park_id):
    """For ranger/park_admin, home_park_id must equal park_id; else ERR_FORBIDDEN."""
    if principal.role in ("ranger", "park_admin"):
        acc = acting_account(principal)
        if acc is None or acc.get("home_park_id") != park_id:
            raise ApiError("ERR_FORBIDDEN", 403, "Acting outside home park.")


def require_owner(principal, account_id):
    """Visitor may only act on own resources."""
    if principal.role == "visitor":
        if principal.user_id != account_id:
            raise ApiError("ERR_FORBIDDEN", 403, "Cannot act on another visitor's resource.")


# ===========================================================================
# Clock state singleton record
# ===========================================================================

def clock_record():
    """Return the clock record dict (always reflects current now)."""
    if not hasattr(clock_record, "_rec"):
        clock_record._rec = {"created_at": now_utc()}
    rec = clock_record._rec
    rec["now_utc"] = now_utc()
    return rec


# ===========================================================================
# Endpoints — Clock & Ops
# ===========================================================================

@app.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(("park_admin", "finance", "system"))
    data = body()
    raw = require(data, "now_utc")
    try:
        dt = parse_dt(raw)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "now_utc must be an ISO datetime.")
    db.clock = dt
    return ok(ser_clock(clock_record()), 200)


@app.route("/v1/_clock", methods=["GET"])
def get_clock():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    return ok(ser_clock(clock_record()), 200)


@app.route("/v1/_ops/run", methods=["POST"])
def ops_run():
    authenticate(("park_admin", "finance", "system"))
    n = now_utc()
    counts = {"expired_holds": 0, "expired_passes": 0, "lapsed_awards": 0,
              "advanced_offers": 0, "no_shows": 0}

    # Timed-entry held -> expired
    for r in db.timed_entry_reservations.values():
        if r["status"] == "held" and r["hold_expires_at"] is not None and n > r["hold_expires_at"]:
            r["status"] = "expired"
            slot = db.timed_entry_slots.get(r["slot_id"])
            if slot:
                slot["held_count"] -= 1
                touch(slot)
            void_payment(r["payment_id"])
            r["hold_expires_at"] = None
            touch(r)
            counts["expired_holds"] += 1

    # Backcountry held -> expired
    for r in db.backcountry_permits.values():
        if r["status"] == "held" and r["hold_expires_at"] is not None and n > r["hold_expires_at"]:
            r["status"] = "expired"
            void_payment(r["payment_id"])
            r["hold_expires_at"] = None
            touch(r)
            counts["expired_holds"] += 1

    # Camp held -> expired (void; release dates; cascade waitlist)
    for r in db.camp_reservations.values():
        if r["status"] == "held" and r["hold_expires_at"] is not None and n > r["hold_expires_at"]:
            r["status"] = "expired"
            void_payment(r["payment_id"])
            r["hold_expires_at"] = None
            touch(r)
            cascade_waitlist_offer(r["campsite_id"], r["check_in"], r["check_out"])
            counts["expired_holds"] += 1

    # AtbPass active -> expired
    for r in db.atb_passes.values():
        if r["status"] == "active" and r["valid_to"] is not None:
            if park_local_or_utc_date_gt(n, r["valid_to"]):
                r["status"] = "expired"
                touch(r)
                counts["expired_passes"] += 1

    # Lottery won -> declined past deadline
    for r in db.lottery_applications.values():
        if r["status"] == "won" and r["award_accept_deadline"] is not None and n > r["award_accept_deadline"]:
            r["status"] = "declined"
            draw = db.lottery_draws.get(r["draw_id"])
            if draw:
                draw["awarded_count"] -= r["party_size"]
                touch(draw)
            touch(r)
            counts["lapsed_awards"] += 1

    # Waitlist offered -> expired (advance)
    for r in db.waitlist_entries.values():
        if r["status"] == "offered" and r["offer_expires_at"] is not None and n > r["offer_expires_at"]:
            r["status"] = "expired"
            r["offer_expires_at"] = None
            touch(r)
            advance_waitlist_offer(r["campsite_id"], r["check_in"], r["check_out"])
            counts["advanced_offers"] += 1

    # Timed-entry confirmed -> no_show past window end
    for r in db.timed_entry_reservations.values():
        if r["status"] == "confirmed":
            slot = db.timed_entry_slots.get(r["slot_id"])
            if slot is None:
                continue
            park = db.parks.get(slot["park_id"])
            if park is None:
                continue
            try:
                edate = parse_date(slot["entry_date"])
            except ValueError:
                continue
            window_end_utc = local_window_to_utc(park, edate, slot["window_end_local"])
            if n > window_end_utc:
                r["status"] = "no_show"
                slot["booked_count"] -= 1
                touch(slot)
                touch(r)
                counts["no_shows"] += 1

    return ok(counts, 200)


def park_local_or_utc_date_gt(instant, date_str):
    """For pass expiry: now_utc date > valid_to (by date). Uses UTC date of now_utc."""
    nd = instant.astimezone(timezone.utc).date()
    return nd > datetime.strptime(date_str, "%Y-%m-%d").date()


# ===========================================================================
# Endpoints — Accounts
# ===========================================================================

@app.route("/v1/accounts", methods=["POST"])
def create_account():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()

    email = req_str(data, "email")
    full_name = req_str(data, "full_name")
    birth_date = req_str(data, "birth_date")
    try:
        parse_date(birth_date)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "birth_date must be YYYY-MM-DD.")

    role = data.get("role", "visitor")
    if role is None:
        role = "visitor"
    if role not in ("visitor", "ranger", "park_admin", "finance"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid role.")
    home_park_id = data.get("home_park_id")

    # email uniqueness
    for a in db.accounts.values():
        if a["email"] == email:
            raise ApiError("ERR_EMAIL_TAKEN", 409, "Email already in use.")

    if role in ("ranger", "park_admin") and not home_park_id:
        raise ApiError("ERR_HOME_PARK_REQUIRED", 400, "home_park_id required for staff roles.")

    if role == "visitor":
        home_park_id = None

    rec = {
        "id": new_id(),
        "email": email,
        "full_name": full_name,
        "birth_date": birth_date,
        "role": role,
        "home_park_id": home_park_id,
        "credit_balance_cents": 0,
        "status": "active",
    }
    stamp_new(rec)
    db.accounts[rec["id"]] = rec
    resp = ser_account(rec)
    payload = {"meta": meta(), "response_type": "object", "data": resp}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/accounts/<aid>", methods=["GET"])
def get_account(aid):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.accounts, aid, "Account")
    return ok(ser_account(rec), 200)


@app.route("/v1/accounts", methods=["GET"])
def list_accounts():
    authenticate(("park_admin", "finance", "system"))
    home_park_id = request.args.get("home_park_id")
    items = list(db.accounts.values())
    if home_park_id is not None:
        items = [a for a in items if a["home_park_id"] == home_park_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_account(a) for a in page], total, limit, offset)


# ===========================================================================
# Endpoints — Parks
# ===========================================================================

@app.route("/v1/parks", methods=["POST"])
def create_park():
    authenticate(("system",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    code = req_str(data, "code")
    name = req_str(data, "name")
    utc_offset_minutes = data.get("utc_offset_minutes", 0)
    if utc_offset_minutes is None:
        utc_offset_minutes = 0
    if not is_int(utc_offset_minutes):
        raise ApiError("ERR_VALIDATION", 400, "utc_offset_minutes must be an integer.")
    timed_entry_required = data.get("timed_entry_required", False)
    if timed_entry_required is None:
        timed_entry_required = False
    if not isinstance(timed_entry_required, bool):
        raise ApiError("ERR_VALIDATION", 400, "timed_entry_required must be boolean.")
    status = data.get("status", "open")
    if status is None:
        status = "open"
    if status not in ("open", "seasonal_closed"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid park status.")

    for p in db.parks.values():
        if p["code"] == code:
            raise ApiError("ERR_VALIDATION", 400, "Park code must be unique.")

    rec = {
        "id": new_id(),
        "code": code,
        "name": name,
        "utc_offset_minutes": utc_offset_minutes,
        "timed_entry_required": timed_entry_required,
        "status": status,
    }
    stamp_new(rec)
    db.parks[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_park(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/parks/<pid>", methods=["GET"])
def get_park(pid):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.parks, pid, "Park")
    return ok(ser_park(rec), 200)


# ===========================================================================
# Endpoints — ATB passes
# ===========================================================================

@app.route("/v1/atb-passes", methods=["POST"])
def create_pass():
    principal = authenticate(("visitor",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    account_id = req_str(data, "account_id")
    pass_type = require(data, "pass_type")
    valid_from = require(data, "valid_from")

    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Account not found.")
    require_owner(principal, account_id)

    if pass_type not in PASS_TYPES:
        raise ApiError("ERR_VALIDATION", 400, "Invalid pass_type.")
    try:
        valid_from_date = parse_date(valid_from)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "valid_from must be YYYY-MM-DD.")

    # Age requirement
    if pass_type in SENIOR_TYPES:
        try:
            bdate = parse_date(account["birth_date"])
        except ValueError:
            raise ApiError("ERR_AGE_REQUIREMENT", 400, "Invalid birth date for age check.")
        age = age_on(bdate, valid_from_date)
        if age < 62:
            raise ApiError("ERR_AGE_REQUIREMENT", 400, "Senior pass requires age >= 62.")

    # Overlap check
    valid_to = calc_atb_valid_to(pass_type, valid_from_date)
    new_from = valid_from_date
    new_to = None if valid_to is None else parse_date(valid_to)
    for p in db.atb_passes.values():
        if p["account_id"] != account_id or p["status"] != "active":
            continue
        ex_from = parse_date(p["valid_from"])
        ex_to = None if p["valid_to"] is None else parse_date(p["valid_to"])
        if ranges_overlap(new_from, new_to, ex_from, ex_to):
            raise ApiError("ERR_PASS_OVERLAP", 409, "Overlapping active pass exists.")

    price = PASS_PRICE[pass_type]
    rec = {
        "id": new_id(),
        "account_id": account_id,
        "pass_type": pass_type,
        "price_cents": price,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": "active",
        "payment_id": None,
    }
    stamp_new(rec)
    if price > 0:
        pay = create_payment(account_id, "atb_pass", "AtbPass", rec["id"], price, capture=True)
        rec["payment_id"] = pay["id"]
    db.atb_passes[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_pass(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


def age_on(birth_date, on_date):
    years = on_date.year - birth_date.year
    if (on_date.month, on_date.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def ranges_overlap(a_from, a_to, b_from, b_to):
    """Date ranges with possibly open-ended (None) upper bounds. Inclusive."""
    a_hi = a_to if a_to is not None else datetime.max.date()
    b_hi = b_to if b_to is not None else datetime.max.date()
    return a_from <= b_hi and b_from <= a_hi


@app.route("/v1/atb-passes/<pid>/void", methods=["POST"])
def void_pass(pid):
    authenticate(("finance",))
    rec = must_get(db.atb_passes, pid, "Pass")
    if rec["status"] != "active":
        raise ApiError("ERR_STATE_INVALID", 409, "Pass not active.")
    n = now_utc()
    deadline = rec["created_at"] + timedelta(days=VOID_WINDOW_DAYS)
    if n > deadline:
        raise ApiError("ERR_VOID_NOT_ALLOWED", 409, "Void window has passed.")
    if rec["payment_id"] is None:
        raise ApiError("ERR_VOID_NOT_ALLOWED", 409, "Free pass cannot be voided for refund.")

    rec["status"] = "voided"
    pay = db.payments.get(rec["payment_id"])
    refund_amt = pay["captured_cents"] - pay["refunded_cents"]
    refund_payment(rec["payment_id"], refund_amt)
    credit_account(rec["account_id"], refund_amt)
    touch(rec)
    return ok(ser_pass(rec), 200)


@app.route("/v1/atb-passes/<pid>", methods=["GET"])
def get_pass(pid):
    authenticate(("visitor", "finance", "park_admin", "system"))
    rec = must_get(db.atb_passes, pid, "Pass")
    return ok(ser_pass(rec), 200)


@app.route("/v1/atb-passes", methods=["GET"])
def list_passes():
    authenticate(("visitor", "finance", "park_admin", "system"))
    account_id = request.args.get("account_id")
    payment_id = request.args.get("payment_id")
    items = list(db.atb_passes.values())
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if payment_id is not None:
        items = [p for p in items if p["payment_id"] == payment_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_pass(p) for p in page], total, limit, offset)


# ===========================================================================
# Endpoints — Timed entry slots
# ===========================================================================

@app.route("/v1/timed-entry-slots", methods=["POST"])
def create_slot():
    principal = authenticate(("park_admin",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    park_id = req_str(data, "park_id")
    park = db.parks.get(park_id)
    if park is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Park not found.")
    require_park_scope(principal, park_id)

    entry_date = req_str(data, "entry_date")
    try:
        parse_date(entry_date)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "entry_date must be YYYY-MM-DD.")
    window_start_local = req_str(data, "window_start_local")
    window_end_local = req_str(data, "window_end_local")
    if not valid_hhmm(window_start_local) or not valid_hhmm(window_end_local):
        raise ApiError("ERR_VALIDATION", 400, "window times must be HH:MM.")
    capacity = req_int(data, "capacity")
    if capacity < 1:
        raise ApiError("ERR_VALIDATION", 400, "capacity must be >= 1.")
    release_at = require(data, "release_at")
    try:
        release_dt = parse_dt(release_at)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "release_at must be ISO datetime.")
    entry_fee_cents = data.get("entry_fee_cents", 200)
    if entry_fee_cents is None:
        entry_fee_cents = 200
    if not is_int(entry_fee_cents) or entry_fee_cents < 0:
        raise ApiError("ERR_VALIDATION", 400, "entry_fee_cents must be a non-negative integer.")

    rec = {
        "id": new_id(),
        "park_id": park_id,
        "entry_date": entry_date,
        "window_start_local": window_start_local,
        "window_end_local": window_end_local,
        "capacity": capacity,
        "held_count": 0,
        "booked_count": 0,
        "release_at": release_dt,
        "entry_fee_cents": entry_fee_cents,
    }
    stamp_new(rec)
    db.timed_entry_slots[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_slot(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


def valid_hhmm(s):
    return bool(re.match(r"^([01]\d|2[0-3]):[0-5]\d$", s))


@app.route("/v1/timed-entry-slots/<sid>", methods=["GET"])
def get_slot(sid):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.timed_entry_slots, sid, "Slot")
    return ok(ser_slot(rec), 200)


@app.route("/v1/timed-entry-slots", methods=["GET"])
def list_slots():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    park_id = request.args.get("park_id")
    entry_date = request.args.get("entry_date")
    items = list(db.timed_entry_slots.values())
    if park_id is not None:
        items = [s for s in items if s["park_id"] == park_id]
    if entry_date is not None:
        items = [s for s in items if s["entry_date"] == entry_date]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_slot(s) for s in page], total, limit, offset)


# ===========================================================================
# Endpoints — Timed entry reservations
# ===========================================================================

@app.route("/v1/timed-entry-reservations", methods=["POST"])
def create_te_res():
    principal = authenticate(("visitor",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    slot_id = req_str(data, "slot_id")
    account_id = req_str(data, "account_id")

    slot = db.timed_entry_slots.get(slot_id)
    if slot is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Slot not found.")
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Account not found.")
    require_owner(principal, account_id)

    vehicle_plate = require(data, "vehicle_plate")
    if not isinstance(vehicle_plate, str) or vehicle_plate.strip() == "":
        raise ApiError("ERR_VALIDATION", 400, "vehicle_plate must be non-empty.")
    expected_slot_version = require(data, "expected_slot_version")
    if not is_int(expected_slot_version):
        raise ApiError("ERR_VALIDATION", 400, "expected_slot_version must be an integer.")

    n = now_utc()
    park = db.parks.get(slot["park_id"])

    # Temporal: release
    if n < slot["release_at"]:
        raise ApiError("ERR_NOT_YET_RELEASED", 409, "Slot not yet released.")
    # Booking window (park-local dates)
    today_local = park_local_date(park, n)
    edate = parse_date(slot["entry_date"])
    diff = (edate - today_local).days
    if diff < 0 or diff > 7:
        raise ApiError("ERR_OUTSIDE_BOOKING_WINDOW", 409, "Entry date outside booking window.")

    # Duplicate reservation per (account, slot) among held/confirmed
    for r in db.timed_entry_reservations.values():
        if r["slot_id"] == slot_id and r["account_id"] == account_id and r["status"] in ("held", "confirmed"):
            raise ApiError("ERR_DUPLICATE_RESERVATION", 409, "Active reservation already exists for this slot.")

    # OCC
    if expected_slot_version != slot["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Slot version stale.")

    # Capacity
    if slot["held_count"] + slot["booked_count"] >= slot["capacity"]:
        raise ApiError("ERR_SLOT_FULL", 409, "Slot is full.")

    fee = slot["entry_fee_cents"]
    rec = {
        "id": new_id(),
        "slot_id": slot_id,
        "account_id": account_id,
        "vehicle_plate": vehicle_plate,
        "status": "held",
        "hold_expires_at": n + timedelta(seconds=HOLD_SECONDS),
        "fee_cents": fee,
        "payment_id": None,
    }
    stamp_new(rec)
    pay = create_payment(account_id, "timed_entry", "TimedEntryReservation", rec["id"], fee, capture=False)
    rec["payment_id"] = pay["id"]
    slot["held_count"] += 1
    touch(slot)  # increments version
    db.timed_entry_reservations[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_te_res(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/timed-entry-reservations/<rid>/confirm", methods=["POST"])
def confirm_te_res(rid):
    principal = authenticate(("visitor",))
    rec = must_get(db.timed_entry_reservations, rid, "Reservation")
    require_owner(principal, rec["account_id"])
    if rec["status"] != "held":
        raise ApiError("ERR_STATE_INVALID", 409, "Reservation not held.")
    if now_utc() > rec["hold_expires_at"]:
        raise ApiError("ERR_HOLD_EXPIRED", 409, "Hold expired.")
    capture_payment(rec["payment_id"])
    slot = db.timed_entry_slots.get(rec["slot_id"])
    if slot:
        slot["held_count"] -= 1
        slot["booked_count"] += 1
        touch(slot)
    rec["status"] = "confirmed"
    rec["hold_expires_at"] = None
    touch(rec)
    return ok(ser_te_res(rec), 200)


@app.route("/v1/timed-entry-reservations/<rid>/check-in", methods=["POST"])
def checkin_te_res(rid):
    principal = authenticate(("ranger",))
    rec = must_get(db.timed_entry_reservations, rid, "Reservation")
    slot = db.timed_entry_slots.get(rec["slot_id"])
    require_park_scope(principal, slot["park_id"])
    if rec["status"] != "confirmed":
        raise ApiError("ERR_STATE_INVALID", 409, "Reservation not confirmed.")
    park = db.parks.get(slot["park_id"])
    n = now_utc()
    edate = parse_date(slot["entry_date"])
    win_start = local_window_to_utc(park, edate, slot["window_start_local"])
    win_end = local_window_to_utc(park, edate, slot["window_end_local"])
    if not (win_start <= n < win_end):
        raise ApiError("ERR_STATE_INVALID", 409, "Not within check-in window.")
    rec["status"] = "checked_in"
    touch(rec)
    return ok(ser_te_res(rec), 200)


@app.route("/v1/timed-entry-reservations/<rid>/cancel", methods=["POST"])
def cancel_te_res(rid):
    principal = authenticate(("visitor",))
    rec = must_get(db.timed_entry_reservations, rid, "Reservation")
    require_owner(principal, rec["account_id"])
    slot = db.timed_entry_slots.get(rec["slot_id"])
    if rec["status"] == "held":
        if slot:
            slot["held_count"] -= 1
            touch(slot)
        void_payment(rec["payment_id"])
        rec["status"] = "cancelled"
        rec["hold_expires_at"] = None
        touch(rec)
    elif rec["status"] == "confirmed":
        if slot:
            slot["booked_count"] -= 1
            touch(slot)
        # fee non-refundable: payment stays captured
        rec["status"] = "cancelled"
        touch(rec)
    else:
        raise ApiError("ERR_STATE_INVALID", 409, "Reservation cannot be cancelled.")
    return ok(ser_te_res(rec), 200)


@app.route("/v1/timed-entry-reservations/<rid>", methods=["GET"])
def get_te_res(rid):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.timed_entry_reservations, rid, "Reservation")
    return ok(ser_te_res(rec), 200)


@app.route("/v1/timed-entry-reservations", methods=["GET"])
def list_te_res():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    slot_id = request.args.get("slot_id")
    account_id = request.args.get("account_id")
    payment_id = request.args.get("payment_id")
    items = list(db.timed_entry_reservations.values())
    if slot_id is not None:
        items = [r for r in items if r["slot_id"] == slot_id]
    if account_id is not None:
        items = [r for r in items if r["account_id"] == account_id]
    if payment_id is not None:
        items = [r for r in items if r["payment_id"] == payment_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_te_res(r) for r in page], total, limit, offset)


# ===========================================================================
# Endpoints — Lottery draws
# ===========================================================================

@app.route("/v1/lottery-draws", methods=["POST"])
def create_draw():
    principal = authenticate(("park_admin",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    park_id = req_str(data, "park_id")
    park = db.parks.get(park_id)
    if park is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Park not found.")
    require_park_scope(principal, park_id)

    objective = req_str(data, "objective")
    use_date = req_str(data, "use_date")
    try:
        parse_date(use_date)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "use_date must be YYYY-MM-DD.")
    daily_quota = req_int(data, "daily_quota")
    if daily_quota < 1:
        raise ApiError("ERR_VALIDATION", 400, "daily_quota must be >= 1.")
    try:
        application_open_at = parse_dt(require(data, "application_open_at"))
        application_close_at = parse_dt(require(data, "application_close_at"))
        draw_at = parse_dt(require(data, "draw_at"))
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "datetime fields must be ISO datetimes.")
    permit_fee_per_person_cents = req_int(data, "permit_fee_per_person_cents")
    if permit_fee_per_person_cents < 0:
        raise ApiError("ERR_VALIDATION", 400, "permit_fee_per_person_cents must be >= 0.")
    max_group_size = data.get("max_group_size", 6)
    if max_group_size is None:
        max_group_size = 6
    if not is_int(max_group_size) or max_group_size < 1:
        raise ApiError("ERR_VALIDATION", 400, "max_group_size must be a positive integer.")
    application_fee_cents = data.get("application_fee_cents", 1000)
    if application_fee_cents is None:
        application_fee_cents = 1000
    if not is_int(application_fee_cents) or application_fee_cents < 0:
        raise ApiError("ERR_VALIDATION", 400, "application_fee_cents must be a non-negative integer.")

    rec = {
        "id": new_id(),
        "park_id": park_id,
        "objective": objective,
        "use_date": use_date,
        "daily_quota": daily_quota,
        "awarded_count": 0,
        "application_open_at": application_open_at,
        "application_close_at": application_close_at,
        "draw_at": draw_at,
        "application_fee_cents": application_fee_cents,
        "permit_fee_per_person_cents": permit_fee_per_person_cents,
        "max_group_size": max_group_size,
        "status": "accepting",
    }
    stamp_new(rec)
    db.lottery_draws[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_draw(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/lottery-draws/<did>", methods=["GET"])
def get_draw(did):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.lottery_draws, did, "Draw")
    return ok(ser_draw(rec), 200)


@app.route("/v1/lottery-draws", methods=["GET"])
def list_draws():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    park_id = request.args.get("park_id")
    items = list(db.lottery_draws.values())
    if park_id is not None:
        items = [d for d in items if d["park_id"] == park_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_draw(d) for d in page], total, limit, offset)


@app.route("/v1/lottery-draws/<did>/applications", methods=["POST"])
def create_application(did):
    principal = authenticate(("visitor",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    draw = db.lottery_draws.get(did)
    if draw is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Draw not found.")
    data = body()
    account_id = req_str(data, "account_id")
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Account not found.")
    require_owner(principal, account_id)

    party_size = req_int(data, "party_size")
    preference_rank = data.get("preference_rank", 9999)
    if preference_rank is None:
        preference_rank = 9999
    if not is_int(preference_rank):
        raise ApiError("ERR_VALIDATION", 400, "preference_rank must be an integer.")

    n = now_utc()
    # Temporal window
    if not (draw["status"] == "accepting" and draw["application_open_at"] <= n < draw["application_close_at"]):
        raise ApiError("ERR_LOTTERY_CLOSED", 409, "Lottery not open.")
    # party size
    if party_size < 1 or party_size > draw["max_group_size"]:
        raise ApiError("ERR_INVALID_PARTY_SIZE", 400, "party_size out of range.")
    # duplicate non-terminal
    for a in db.lottery_applications.values():
        if a["draw_id"] == did and a["account_id"] == account_id and a["status"] in ("submitted", "won"):
            raise ApiError("ERR_DUPLICATE_APPLICATION", 409, "Active application exists for this draw.")

    rec = {
        "id": new_id(),
        "draw_id": did,
        "account_id": account_id,
        "party_size": party_size,
        "preference_rank": preference_rank,
        "status": "submitted",
        "application_fee_cents": draw["application_fee_cents"],
        "application_payment_id": None,
        "permit_payment_id": None,
        "award_accept_deadline": None,
    }
    stamp_new(rec)
    pay = create_payment(account_id, "lottery_application", "LotteryApplication", rec["id"],
                         draw["application_fee_cents"], capture=True)
    rec["application_payment_id"] = pay["id"]
    db.lottery_applications[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_app(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/lottery-draws/<did>/draw", methods=["POST"])
def run_draw(did):
    principal = authenticate(("park_admin",))
    draw = db.lottery_draws.get(did)
    if draw is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Draw not found.")
    require_park_scope(principal, draw["park_id"])
    n = now_utc()
    if not (draw["status"] == "accepting" and n >= draw["draw_at"]):
        raise ApiError("ERR_DRAW_NOT_READY", 409, "Draw not ready.")

    candidates = [a for a in db.lottery_applications.values()
                  if a["draw_id"] == did and a["status"] == "submitted"]
    candidates.sort(key=lambda a: (a["preference_rank"], a["created_at"], a["created_seq"], a["id"]))

    remaining = draw["daily_quota"]
    awarded = 0
    deadline = draw["draw_at"] + timedelta(seconds=AWARD_SECONDS)
    for a in candidates:
        if a["party_size"] <= remaining:
            a["status"] = "won"
            a["award_accept_deadline"] = deadline
            remaining -= a["party_size"]
            awarded += a["party_size"]
            touch(a)
        else:
            a["status"] = "lost"
            touch(a)
    draw["awarded_count"] = awarded
    draw["status"] = "drawn"
    touch(draw)
    return ok(ser_draw(draw), 200)


@app.route("/v1/lottery-applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    principal = authenticate(("visitor",))
    rec = must_get(db.lottery_applications, aid, "Application")
    require_owner(principal, rec["account_id"])
    if rec["status"] != "submitted":
        raise ApiError("ERR_STATE_INVALID", 409, "Application not submitted.")
    draw = db.lottery_draws.get(rec["draw_id"])
    n = now_utc()
    if not (draw["status"] == "accepting" and n < draw["application_close_at"]):
        raise ApiError("ERR_LOTTERY_CLOSED", 409, "Application window closed.")
    rec["status"] = "withdrawn"
    touch(rec)
    return ok(ser_app(rec), 200)


@app.route("/v1/lottery-applications/<aid>/accept", methods=["POST"])
def accept_application(aid):
    principal = authenticate(("visitor",))
    rec = must_get(db.lottery_applications, aid, "Application")
    require_owner(principal, rec["account_id"])
    if rec["status"] != "won":
        raise ApiError("ERR_STATE_INVALID", 409, "Application not won.")
    if now_utc() > rec["award_accept_deadline"]:
        raise ApiError("ERR_AWARD_WINDOW_CLOSED", 409, "Award window closed.")
    draw = db.lottery_draws.get(rec["draw_id"])
    amount = draw["permit_fee_per_person_cents"] * rec["party_size"]
    pay = create_payment(rec["account_id"], "lottery_permit", "LotteryApplication", rec["id"], amount, capture=True)
    rec["permit_payment_id"] = pay["id"]
    rec["status"] = "awarded"
    touch(rec)
    return ok(ser_app(rec), 200)


@app.route("/v1/lottery-applications/<aid>/decline", methods=["POST"])
def decline_application(aid):
    principal = authenticate(("visitor",))
    rec = must_get(db.lottery_applications, aid, "Application")
    require_owner(principal, rec["account_id"])
    if rec["status"] != "won":
        raise ApiError("ERR_STATE_INVALID", 409, "Application not won.")
    draw = db.lottery_draws.get(rec["draw_id"])
    if draw:
        draw["awarded_count"] -= rec["party_size"]
        touch(draw)
    rec["status"] = "declined"
    touch(rec)
    return ok(ser_app(rec), 200)


@app.route("/v1/lottery-applications/<aid>", methods=["GET"])
def get_application(aid):
    authenticate(("visitor", "park_admin", "finance", "system"))
    rec = must_get(db.lottery_applications, aid, "Application")
    return ok(ser_app(rec), 200)


@app.route("/v1/lottery-applications", methods=["GET"])
def list_applications():
    authenticate(("visitor", "park_admin", "finance", "system"))
    draw_id = request.args.get("draw_id")
    account_id = request.args.get("account_id")
    application_payment_id = request.args.get("application_payment_id")
    permit_payment_id = request.args.get("permit_payment_id")
    items = list(db.lottery_applications.values())
    if draw_id is not None:
        items = [a for a in items if a["draw_id"] == draw_id]
    if account_id is not None:
        items = [a for a in items if a["account_id"] == account_id]
    if application_payment_id is not None:
        items = [a for a in items if a["application_payment_id"] == application_payment_id]
    if permit_payment_id is not None:
        items = [a for a in items if a["permit_payment_id"] == permit_payment_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_app(a) for a in page], total, limit, offset)


# ===========================================================================
# Endpoints — Trailheads & wilderness zones
# ===========================================================================

@app.route("/v1/trailheads", methods=["POST"])
def create_trailhead():
    principal = authenticate(("park_admin",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    park_id = req_str(data, "park_id")
    park = db.parks.get(park_id)
    if park is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Park not found.")
    require_park_scope(principal, park_id)
    name = req_str(data, "name")
    daily_exit_quota = req_int(data, "daily_exit_quota")
    if daily_exit_quota < 1:
        raise ApiError("ERR_VALIDATION", 400, "daily_exit_quota must be >= 1.")
    reservation_fee_cents = data.get("reservation_fee_cents", 500)
    if reservation_fee_cents is None:
        reservation_fee_cents = 500
    if not is_int(reservation_fee_cents) or reservation_fee_cents < 0:
        raise ApiError("ERR_VALIDATION", 400, "reservation_fee_cents must be non-negative integer.")
    per_person_per_night_cents = data.get("per_person_per_night_cents", 800)
    if per_person_per_night_cents is None:
        per_person_per_night_cents = 800
    if not is_int(per_person_per_night_cents) or per_person_per_night_cents < 0:
        raise ApiError("ERR_VALIDATION", 400, "per_person_per_night_cents must be non-negative integer.")

    rec = {
        "id": new_id(),
        "park_id": park_id,
        "name": name,
        "daily_exit_quota": daily_exit_quota,
        "exit_used_by_date": {},
        "reservation_fee_cents": reservation_fee_cents,
        "per_person_per_night_cents": per_person_per_night_cents,
    }
    stamp_new(rec)
    db.trailheads[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_trailhead(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/trailheads/<tid>", methods=["GET"])
def get_trailhead(tid):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.trailheads, tid, "Trailhead")
    return ok(ser_trailhead(rec), 200)


@app.route("/v1/trailheads", methods=["GET"])
def list_trailheads():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    park_id = request.args.get("park_id")
    items = list(db.trailheads.values())
    if park_id is not None:
        items = [t for t in items if t["park_id"] == park_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_trailhead(t) for t in page], total, limit, offset)


@app.route("/v1/wilderness-zones", methods=["POST"])
def create_zone():
    principal = authenticate(("park_admin",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    park_id = req_str(data, "park_id")
    park = db.parks.get(park_id)
    if park is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Park not found.")
    require_park_scope(principal, park_id)
    name = req_str(data, "name")
    nightly_party_quota = req_int(data, "nightly_party_quota")
    if nightly_party_quota < 1:
        raise ApiError("ERR_VALIDATION", 400, "nightly_party_quota must be >= 1.")

    rec = {
        "id": new_id(),
        "park_id": park_id,
        "name": name,
        "nightly_party_quota": nightly_party_quota,
        "used_by_date": {},
    }
    stamp_new(rec)
    db.wilderness_zones[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_zone(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/wilderness-zones/<zid>", methods=["GET"])
def get_zone(zid):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.wilderness_zones, zid, "Zone")
    return ok(ser_zone(rec), 200)


@app.route("/v1/wilderness-zones", methods=["GET"])
def list_zones():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    park_id = request.args.get("park_id")
    items = list(db.wilderness_zones.values())
    if park_id is not None:
        items = [z for z in items if z["park_id"] == park_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_zone(z) for z in page], total, limit, offset)


# ===========================================================================
# Endpoints — Backcountry permits
# ===========================================================================

@app.route("/v1/backcountry-permits", methods=["POST"])
def create_permit():
    principal = authenticate(("visitor",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    park_id = req_str(data, "park_id")
    account_id = req_str(data, "account_id")
    trailhead_id = req_str(data, "trailhead_id")

    park = db.parks.get(park_id)
    if park is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Park not found.")
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Account not found.")
    trailhead = db.trailheads.get(trailhead_id)
    if trailhead is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Trailhead not found.")
    require_owner(principal, account_id)

    entry_date = req_str(data, "entry_date")
    try:
        parse_date(entry_date)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "entry_date must be YYYY-MM-DD.")
    nights = require(data, "nights")
    party_size = require(data, "party_size")
    zone_nights = require(data, "zone_nights")

    if not is_int(nights):
        raise ApiError("ERR_VALIDATION", 400, "nights must be an integer.")
    if not is_int(party_size):
        raise ApiError("ERR_VALIDATION", 400, "party_size must be an integer.")
    if not isinstance(zone_nights, list):
        raise ApiError("ERR_VALIDATION", 400, "zone_nights must be a list.")

    # zone existence (body-referenced resources) — check before itinerary validity
    for el in zone_nights:
        if isinstance(el, dict) and el.get("zone_id") is not None:
            if el["zone_id"] not in db.wilderness_zones:
                raise ApiError("ERR_NOT_FOUND", 404, "Zone not found.")

    # itinerary validity
    if nights < 1 or nights > 14 or len(zone_nights) != nights:
        raise ApiError("ERR_INVALID_ITINERARY", 400, "Invalid itinerary.")
    for el in zone_nights:
        if not isinstance(el, dict) or not el.get("zone_id") or not el.get("date"):
            raise ApiError("ERR_INVALID_ITINERARY", 400, "Each itinerary element needs zone_id and date.")
        try:
            parse_date(el["date"])
        except ValueError:
            raise ApiError("ERR_INVALID_ITINERARY", 400, "Itinerary date must be YYYY-MM-DD.")

    if party_size < 1:
        raise ApiError("ERR_INVALID_PARTY_SIZE", 400, "party_size must be >= 1.")

    # A held permit is created without touching any zone or trailhead counter;
    # capacity is verified and committed only at confirm time (PRD 3.4).

    flat, variable, fee = calc_backcountry_fee(trailhead, party_size, nights)
    n = now_utc()
    rec = {
        "id": new_id(),
        "park_id": park_id,
        "account_id": account_id,
        "trailhead_id": trailhead_id,
        "entry_date": entry_date,
        "nights": nights,
        "party_size": party_size,
        "zone_nights": zone_nights,
        "status": "held",
        "hold_expires_at": n + timedelta(seconds=HOLD_SECONDS),
        "fee_cents": fee,
        "refunded_cents": 0,
        "payment_id": None,
    }
    stamp_new(rec)
    pay = create_payment(account_id, "backcountry", "BackcountryPermit", rec["id"], fee, capture=False)
    rec["payment_id"] = pay["id"]
    db.backcountry_permits[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_permit(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/backcountry-permits/<pid>/confirm", methods=["POST"])
def confirm_permit(pid):
    principal = authenticate(("visitor",))
    rec = must_get(db.backcountry_permits, pid, "Permit")
    require_owner(principal, rec["account_id"])
    if rec["status"] != "held":
        raise ApiError("ERR_STATE_INVALID", 409, "Permit not held.")
    if now_utc() > rec["hold_expires_at"]:
        raise ApiError("ERR_HOLD_EXPIRED", 409, "Hold expired.")
    trailhead = db.trailheads.get(rec["trailhead_id"])
    # re-validate zone capacity
    for el in rec["zone_nights"]:
        zone = db.wilderness_zones.get(el["zone_id"])
        used = zone["used_by_date"].get(el["date"], 0)
        if used >= zone["nightly_party_quota"]:
            raise ApiError("ERR_ZONE_FULL", 409, "Zone full.")
    th_used = trailhead["exit_used_by_date"].get(rec["entry_date"], 0)
    if th_used >= trailhead["daily_exit_quota"]:
        raise ApiError("ERR_TRAILHEAD_FULL", 409, "Trailhead full.")

    capture_payment(rec["payment_id"])
    for el in rec["zone_nights"]:
        zone = db.wilderness_zones.get(el["zone_id"])
        zone["used_by_date"][el["date"]] = zone["used_by_date"].get(el["date"], 0) + 1
        touch(zone)
    trailhead["exit_used_by_date"][rec["entry_date"]] = trailhead["exit_used_by_date"].get(rec["entry_date"], 0) + 1
    touch(trailhead)
    rec["status"] = "confirmed"
    rec["hold_expires_at"] = None
    touch(rec)
    return ok(ser_permit(rec), 200)


@app.route("/v1/backcountry-permits/<pid>/cancel", methods=["POST"])
def cancel_permit(pid):
    principal = authenticate(("visitor",))
    rec = must_get(db.backcountry_permits, pid, "Permit")
    require_owner(principal, rec["account_id"])
    if rec["status"] == "held":
        void_payment(rec["payment_id"])
        rec["status"] = "cancelled"
        rec["hold_expires_at"] = None
        touch(rec)
    elif rec["status"] == "confirmed":
        trailhead = db.trailheads.get(rec["trailhead_id"])
        for el in rec["zone_nights"]:
            zone = db.wilderness_zones.get(el["zone_id"])
            if zone and zone["used_by_date"].get(el["date"], 0) > 0:
                zone["used_by_date"][el["date"]] -= 1
                touch(zone)
        if trailhead and trailhead["exit_used_by_date"].get(rec["entry_date"], 0) > 0:
            trailhead["exit_used_by_date"][rec["entry_date"]] -= 1
            touch(trailhead)
        # refund
        park = db.parks.get(rec["park_id"])
        today_local = park_local_date(park, now_utc())
        start = parse_date(rec["entry_date"])
        D = (start - today_local).days
        refundable_base = rec["fee_cents"] - trailhead["reservation_fee_cents"]
        refund = calc_refund(refundable_base, D)
        if refund > 0:
            refund_payment(rec["payment_id"], refund)
            credit_account(rec["account_id"], refund)
        rec["refunded_cents"] = refund
        rec["status"] = "cancelled"
        touch(rec)
    else:
        raise ApiError("ERR_STATE_INVALID", 409, "Permit cannot be cancelled.")
    return ok(ser_permit(rec), 200)


@app.route("/v1/backcountry-permits/<pid>", methods=["GET"])
def get_permit(pid):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.backcountry_permits, pid, "Permit")
    return ok(ser_permit(rec), 200)


@app.route("/v1/backcountry-permits", methods=["GET"])
def list_permits():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    account_id = request.args.get("account_id")
    trailhead_id = request.args.get("trailhead_id")
    park_id = request.args.get("park_id")
    payment_id = request.args.get("payment_id")
    items = list(db.backcountry_permits.values())
    if account_id is not None:
        items = [r for r in items if r["account_id"] == account_id]
    if trailhead_id is not None:
        items = [r for r in items if r["trailhead_id"] == trailhead_id]
    if park_id is not None:
        items = [r for r in items if r["park_id"] == park_id]
    if payment_id is not None:
        items = [r for r in items if r["payment_id"] == payment_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_permit(r) for r in page], total, limit, offset)


# ===========================================================================
# Endpoints — Campsites
# ===========================================================================

@app.route("/v1/campsites", methods=["POST"])
def create_campsite():
    principal = authenticate(("park_admin",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    park_id = req_str(data, "park_id")
    park = db.parks.get(park_id)
    if park is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Park not found.")
    require_park_scope(principal, park_id)
    site_number = req_str(data, "site_number")
    site_type = require(data, "site_type")
    if site_type not in ("tent", "rv", "group"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid site_type.")
    max_occupancy = req_int(data, "max_occupancy")
    if max_occupancy < 1:
        raise ApiError("ERR_VALIDATION", 400, "max_occupancy must be >= 1.")
    booking_window_days = data.get("booking_window_days", 180)
    if booking_window_days is None:
        booking_window_days = 180
    if not is_int(booking_window_days) or booking_window_days < 0:
        raise ApiError("ERR_VALIDATION", 400, "booking_window_days must be a non-negative integer.")
    status = data.get("status", "active")
    if status is None:
        status = "active"
    if status not in ("active", "maintenance"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid campsite status.")

    base_nightly_cents = data.get("base_nightly_cents")
    group_base_cents = data.get("group_base_cents")
    group_included_persons = data.get("group_included_persons")
    group_extra_person_cents = data.get("group_extra_person_cents")

    if site_type in ("tent", "rv"):
        if not is_int(base_nightly_cents) or base_nightly_cents < 0:
            raise ApiError("ERR_VALIDATION", 400, "base_nightly_cents must be a non-negative integer.")
        group_base_cents = None
        group_included_persons = None
        group_extra_person_cents = None
    else:  # group
        if group_base_cents is None or group_included_persons is None or group_extra_person_cents is None:
            raise ApiError("ERR_GROUP_CONFIG_MISSING", 400, "Group config fields required.")
        if not is_int(group_base_cents) or not is_int(group_included_persons) or not is_int(group_extra_person_cents):
            raise ApiError("ERR_VALIDATION", 400, "Group config fields must be integers.")
        if base_nightly_cents is not None and not is_int(base_nightly_cents):
            raise ApiError("ERR_VALIDATION", 400, "base_nightly_cents must be an integer.")

    # uniqueness of site_number per park
    for c in db.campsites.values():
        if c["park_id"] == park_id and c["site_number"] == site_number:
            raise ApiError("ERR_VALIDATION", 400, "site_number must be unique per park.")

    rec = {
        "id": new_id(),
        "park_id": park_id,
        "site_number": site_number,
        "site_type": site_type,
        "max_occupancy": max_occupancy,
        "booking_window_days": booking_window_days,
        "base_nightly_cents": base_nightly_cents,
        "group_base_cents": group_base_cents,
        "group_included_persons": group_included_persons,
        "group_extra_person_cents": group_extra_person_cents,
        "status": status,
    }
    stamp_new(rec)
    db.campsites[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_campsite(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/campsites/<cid>", methods=["GET"])
def get_campsite(cid):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.campsites, cid, "Campsite")
    return ok(ser_campsite(rec), 200)


@app.route("/v1/campsites", methods=["GET"])
def list_campsites():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    park_id = request.args.get("park_id")
    items = list(db.campsites.values())
    if park_id is not None:
        items = [c for c in items if c["park_id"] == park_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_campsite(c) for c in page], total, limit, offset)


# ===========================================================================
# Endpoints — Camp reservations
# ===========================================================================

def ranges_date_overlap(a_in, a_out, b_in, b_out):
    """Half-open [in, out) overlap on dates (strings YYYY-MM-DD)."""
    return a_in < b_out and b_in < a_out


def occupying_camp_reservations(campsite_id, statuses, exclude_id=None):
    out = []
    for r in db.camp_reservations.values():
        if r["campsite_id"] != campsite_id:
            continue
        if exclude_id and r["id"] == exclude_id:
            continue
        if r["status"] in statuses:
            out.append(r)
    return out


@app.route("/v1/camp-reservations", methods=["POST"])
def create_camp_res():
    principal = authenticate(("visitor",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    campsite_id = req_str(data, "campsite_id")
    account_id = req_str(data, "account_id")
    campsite = db.campsites.get(campsite_id)
    if campsite is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Campsite not found.")
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Account not found.")
    require_owner(principal, account_id)

    check_in = req_str(data, "check_in")
    check_out = req_str(data, "check_out")
    try:
        ci = parse_date(check_in)
        co = parse_date(check_out)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "check_in/check_out must be YYYY-MM-DD.")
    party_size = req_int(data, "party_size")

    n = now_utc()
    park = db.parks.get(campsite["park_id"])
    today_local = park_local_date(park, n)
    nights = (co - ci).days
    # booking window
    diff = (ci - today_local).days
    if not (co > ci and 0 <= diff <= campsite["booking_window_days"]):
        raise ApiError("ERR_OUTSIDE_BOOKING_WINDOW", 409, "check_in outside booking window.")
    # occupancy
    if party_size > campsite["max_occupancy"]:
        raise ApiError("ERR_OVER_OCCUPANCY", 409, "party_size exceeds max occupancy.")
    if party_size < 1:
        raise ApiError("ERR_OVER_OCCUPANCY", 409, "party_size must be >= 1.")
    # site available
    if campsite["status"] != "active":
        raise ApiError("ERR_SITE_UNAVAILABLE", 409, "Campsite not active.")

    total = calc_camp_total(campsite, party_size, nights)
    rec = {
        "id": new_id(),
        "campsite_id": campsite_id,
        "account_id": account_id,
        "check_in": check_in,
        "check_out": check_out,
        "party_size": party_size,
        "status": "held",
        "hold_expires_at": n + timedelta(seconds=HOLD_SECONDS),
        "total_cents": total,
        "refunded_cents": 0,
        "payment_id": None,
        "origin_waitlist_id": None,
    }
    stamp_new(rec)
    pay = create_payment(account_id, "campground", "CampReservation", rec["id"], total, capture=False)
    rec["payment_id"] = pay["id"]
    db.camp_reservations[rec["id"]] = rec
    payload = {"meta": meta(), "response_type": "object", "data": ser_camp_res(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/camp-reservations/<rid>/confirm", methods=["POST"])
def confirm_camp_res(rid):
    principal = authenticate(("visitor",))
    rec = must_get(db.camp_reservations, rid, "Reservation")
    require_owner(principal, rec["account_id"])
    if rec["status"] != "held":
        raise ApiError("ERR_STATE_INVALID", 409, "Reservation not held.")
    if now_utc() > rec["hold_expires_at"]:
        raise ApiError("ERR_HOLD_EXPIRED", 409, "Hold expired.")
    # date conflict against confirmed/checked_in
    for other in occupying_camp_reservations(rec["campsite_id"], ("confirmed", "checked_in"), exclude_id=rec["id"]):
        if ranges_date_overlap(rec["check_in"], rec["check_out"], other["check_in"], other["check_out"]):
            raise ApiError("ERR_DATE_CONFLICT", 409, "Dates conflict with another reservation.")
    capture_payment(rec["payment_id"])
    rec["status"] = "confirmed"
    rec["hold_expires_at"] = None
    touch(rec)
    return ok(ser_camp_res(rec), 200)


@app.route("/v1/camp-reservations/<rid>/check-in", methods=["POST"])
def checkin_camp_res(rid):
    principal = authenticate(("ranger",))
    rec = must_get(db.camp_reservations, rid, "Reservation")
    campsite = db.campsites.get(rec["campsite_id"])
    require_park_scope(principal, campsite["park_id"])
    if rec["status"] != "confirmed":
        raise ApiError("ERR_STATE_INVALID", 409, "Reservation not confirmed.")
    park = db.parks.get(campsite["park_id"])
    today_local = park_local_date(park, now_utc())
    if today_local != parse_date(rec["check_in"]):
        raise ApiError("ERR_STATE_INVALID", 409, "Not check-in date.")
    rec["status"] = "checked_in"
    touch(rec)
    return ok(ser_camp_res(rec), 200)


@app.route("/v1/camp-reservations/<rid>/complete", methods=["POST"])
def complete_camp_res(rid):
    principal = authenticate(("ranger",))
    rec = must_get(db.camp_reservations, rid, "Reservation")
    campsite = db.campsites.get(rec["campsite_id"])
    require_park_scope(principal, campsite["park_id"])
    if rec["status"] != "checked_in":
        raise ApiError("ERR_STATE_INVALID", 409, "Reservation not checked in.")
    park = db.parks.get(campsite["park_id"])
    today_local = park_local_date(park, now_utc())
    if today_local < parse_date(rec["check_out"]):
        raise ApiError("ERR_STATE_INVALID", 409, "Not yet check-out date.")
    rec["status"] = "completed"
    touch(rec)
    return ok(ser_camp_res(rec), 200)


@app.route("/v1/camp-reservations/<rid>/cancel", methods=["POST"])
def cancel_camp_res(rid):
    principal = authenticate(("visitor",))
    rec = must_get(db.camp_reservations, rid, "Reservation")
    require_owner(principal, rec["account_id"])
    if rec["status"] == "held":
        void_payment(rec["payment_id"])
        rec["status"] = "cancelled"
        rec["hold_expires_at"] = None
        touch(rec)
        cascade_waitlist_offer(rec["campsite_id"], rec["check_in"], rec["check_out"])
    elif rec["status"] == "confirmed":
        park = db.parks.get(db.campsites[rec["campsite_id"]]["park_id"])
        today_local = park_local_date(park, now_utc())
        if today_local >= parse_date(rec["check_in"]):
            raise ApiError("ERR_STATE_INVALID", 409, "Too late to cancel.")
        # refund
        D = (parse_date(rec["check_in"]) - today_local).days
        refund = calc_refund(rec["total_cents"], D)
        if refund > 0:
            refund_payment(rec["payment_id"], refund)
            credit_account(rec["account_id"], refund)
        rec["refunded_cents"] = refund
        rec["status"] = "cancelled"
        touch(rec)
        cascade_waitlist_offer(rec["campsite_id"], rec["check_in"], rec["check_out"])
    else:
        raise ApiError("ERR_STATE_INVALID", 409, "Reservation cannot be cancelled.")
    return ok(ser_camp_res(rec), 200)


@app.route("/v1/camp-reservations/<rid>", methods=["GET"])
def get_camp_res(rid):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.camp_reservations, rid, "Reservation")
    return ok(ser_camp_res(rec), 200)


@app.route("/v1/camp-reservations", methods=["GET"])
def list_camp_res():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    campsite_id = request.args.get("campsite_id")
    account_id = request.args.get("account_id")
    payment_id = request.args.get("payment_id")
    origin_waitlist_id = request.args.get("origin_waitlist_id")
    items = list(db.camp_reservations.values())
    if campsite_id is not None:
        items = [r for r in items if r["campsite_id"] == campsite_id]
    if account_id is not None:
        items = [r for r in items if r["account_id"] == account_id]
    if payment_id is not None:
        items = [r for r in items if r["payment_id"] == payment_id]
    if origin_waitlist_id is not None:
        items = [r for r in items if r["origin_waitlist_id"] == origin_waitlist_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_camp_res(r) for r in page], total, limit, offset)


# ===========================================================================
# Waitlist cascade helpers
# ===========================================================================

def make_offer_to_lowest_waiting(campsite_id, check_in, check_out):
    """Offer to the lowest-position waiting entry for the exact key. Returns the entry or None."""
    candidates = [w for w in db.waitlist_entries.values()
                  if w["campsite_id"] == campsite_id and w["check_in"] == check_in
                  and w["check_out"] == check_out and w["status"] == "waiting"]
    if not candidates:
        return None
    candidates.sort(key=lambda w: w["position"])
    entry = candidates[0]
    entry["status"] = "offered"
    entry["offer_expires_at"] = now_utc() + timedelta(seconds=OFFER_SECONDS)
    touch(entry)
    return entry


cascade_waitlist_offer = make_offer_to_lowest_waiting
advance_waitlist_offer = make_offer_to_lowest_waiting


# ===========================================================================
# Endpoints — Waitlist entries
# ===========================================================================

@app.route("/v1/waitlist-entries", methods=["POST"])
def create_waitlist():
    principal = authenticate(("visitor",))
    replay = idem_lookup()
    if replay:
        return jsonify(replay[0]), replay[1]
    data = body()
    campsite_id = req_str(data, "campsite_id")
    account_id = req_str(data, "account_id")
    campsite = db.campsites.get(campsite_id)
    if campsite is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Campsite not found.")
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Account not found.")
    require_owner(principal, account_id)

    check_in = req_str(data, "check_in")
    check_out = req_str(data, "check_out")
    try:
        ci = parse_date(check_in)
        co = parse_date(check_out)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "check_in/check_out must be YYYY-MM-DD.")
    if co <= ci:
        raise ApiError("ERR_VALIDATION", 400, "check_out must be after check_in.")
    party_size = req_int(data, "party_size")
    expected_campsite_version = require(data, "expected_campsite_version")
    if not is_int(expected_campsite_version):
        raise ApiError("ERR_VALIDATION", 400, "expected_campsite_version must be an integer.")

    # occupancy
    if party_size > campsite["max_occupancy"]:
        raise ApiError("ERR_OVER_OCCUPANCY", 409, "party_size exceeds max occupancy.")
    if party_size < 1:
        raise ApiError("ERR_OVER_OCCUPANCY", 409, "party_size must be >= 1.")

    # dates-available: must overlap an existing held/confirmed/checked_in reservation
    overlapping = False
    for r in occupying_camp_reservations(campsite_id, ("held", "confirmed", "checked_in")):
        if ranges_date_overlap(check_in, check_out, r["check_in"], r["check_out"]):
            overlapping = True
            break
    if not overlapping:
        raise ApiError("ERR_DATES_AVAILABLE", 409, "Dates are currently available; cannot waitlist.")

    # OCC
    if expected_campsite_version != campsite["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Campsite version stale.")

    # position
    pos = 1 + sum(1 for w in db.waitlist_entries.values()
                  if w["campsite_id"] == campsite_id and w["check_in"] == check_in
                  and w["check_out"] == check_out and w["status"] in ("waiting", "offered"))

    rec = {
        "id": new_id(),
        "campsite_id": campsite_id,
        "account_id": account_id,
        "check_in": check_in,
        "check_out": check_out,
        "party_size": party_size,
        "position": pos,
        "status": "waiting",
        "offer_expires_at": None,
    }
    stamp_new(rec)
    db.waitlist_entries[rec["id"]] = rec
    campsite["version"] += 1  # successful join increments campsite version
    campsite["updated_at"] = now_utc()
    payload = {"meta": meta(), "response_type": "object", "data": ser_waitlist(rec)}
    idem_store(payload, 201)
    return jsonify(payload), 201


@app.route("/v1/waitlist-entries/<wid>/claim", methods=["POST"])
def claim_waitlist(wid):
    principal = authenticate(("visitor",))
    rec = must_get(db.waitlist_entries, wid, "Waitlist entry")
    require_owner(principal, rec["account_id"])
    if rec["status"] != "offered":
        raise ApiError("ERR_STATE_INVALID", 409, "Entry not offered.")
    if now_utc() > rec["offer_expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED", 409, "Offer expired.")
    campsite = db.campsites.get(rec["campsite_id"])
    ci = parse_date(rec["check_in"])
    co = parse_date(rec["check_out"])
    nights = (co - ci).days
    total = calc_camp_total(campsite, rec["party_size"], nights)
    n = now_utc()
    new_res = {
        "id": new_id(),
        "campsite_id": rec["campsite_id"],
        "account_id": rec["account_id"],
        "check_in": rec["check_in"],
        "check_out": rec["check_out"],
        "party_size": rec["party_size"],
        "status": "confirmed",
        "hold_expires_at": None,
        "total_cents": total,
        "refunded_cents": 0,
        "payment_id": None,
        "origin_waitlist_id": rec["id"],
    }
    stamp_new(new_res)
    pay = create_payment(rec["account_id"], "campground", "CampReservation", new_res["id"], total, capture=True)
    new_res["payment_id"] = pay["id"]
    db.camp_reservations[new_res["id"]] = new_res
    rec["status"] = "claimed"
    rec["offer_expires_at"] = None
    touch(rec)
    return ok(ser_camp_res(new_res), 200)


@app.route("/v1/waitlist-entries/<wid>/cancel", methods=["POST"])
def cancel_waitlist(wid):
    principal = authenticate(("visitor",))
    rec = must_get(db.waitlist_entries, wid, "Waitlist entry")
    require_owner(principal, rec["account_id"])
    if rec["status"] == "waiting":
        rec["status"] = "cancelled"
        touch(rec)
    elif rec["status"] == "offered":
        rec["status"] = "cancelled"
        rec["offer_expires_at"] = None
        touch(rec)
        advance_waitlist_offer(rec["campsite_id"], rec["check_in"], rec["check_out"])
    else:
        raise ApiError("ERR_STATE_INVALID", 409, "Entry cannot be cancelled.")
    return ok(ser_waitlist(rec), 200)


@app.route("/v1/waitlist-entries/<wid>", methods=["GET"])
def get_waitlist(wid):
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    rec = must_get(db.waitlist_entries, wid, "Waitlist entry")
    return ok(ser_waitlist(rec), 200)


@app.route("/v1/waitlist-entries", methods=["GET"])
def list_waitlist():
    authenticate(("visitor", "ranger", "park_admin", "finance", "system"))
    campsite_id = request.args.get("campsite_id")
    account_id = request.args.get("account_id")
    items = list(db.waitlist_entries.values())
    if campsite_id is not None:
        items = [w for w in items if w["campsite_id"] == campsite_id]
    if account_id is not None:
        items = [w for w in items if w["account_id"] == account_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_waitlist(w) for w in page], total, limit, offset)


# ===========================================================================
# Endpoints — Payments
# ===========================================================================

@app.route("/v1/payments/<pid>", methods=["GET"])
def get_payment(pid):
    authenticate(("visitor", "finance", "park_admin", "system"))
    rec = must_get(db.payments, pid, "Payment")
    return ok(ser_payment(rec), 200)


@app.route("/v1/payments", methods=["GET"])
def list_payments():
    authenticate(("finance", "park_admin", "system"))
    account_id = request.args.get("account_id")
    items = list(db.payments.values())
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_payment(p) for p in page], total, limit, offset)


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
