"""
Wedding-Officiant & Ceremony Service API.

Single-file Flask implementation. In-memory storage only (Python dicts); the
store starts empty on every boot and is wiped when start.sh re-launches the
process (per-test-server isolation). All time-sensitive rules are evaluated
against a controllable logical clock (default 2026-03-01T00:00:00Z).
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
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Coordinator", "Couple", "Officiant"}

STYLE_SET = {"RELIGIOUS", "SECULAR", "INTERFAITH", "SPIRITUAL"}
DENOM_SET = {"CHRISTIAN", "JEWISH", "MUSLIM", "HINDU", "BUDDHIST",
             "NONDENOMINATIONAL", "CIVIL"}
TIER_SET = {"ESSENTIAL", "CLASSIC", "PREMIUM"}
VOW_SET = {"TRADITIONAL", "PERSONAL", "MIXED"}
ADDON_SET = {"UNITY_CANDLE", "HANDFASTING", "LIVESTREAM", "SAND_CEREMONY",
             "PREMIUM_SCRIPT", "BILINGUAL_CEREMONY"}
CANCEL_REASON_SET = {"COUPLE_REQUEST", "OFFICIANT_UNAVAILABLE", "VENUE_LOST",
                     "NO_BACKUP", "OTHER"}

TRAVEL_TIER_CENTS = [(25, 0), (75, 15000), (150, 30000)]  # else 45000
TRAVEL_TIER_TOP = 45000
RUSH_THRESHOLD_DAYS = 30
RUSH_FEE_CENTS = 25000
INTERFAITH_SURCHARGE_CENTS = 20000
ADDON_PRICE_CENTS = {
    "UNITY_CANDLE": 5000, "HANDFASTING": 8000, "LIVESTREAM": 12000,
    "SAND_CEREMONY": 4000, "PREMIUM_SCRIPT": 5025, "BILINGUAL_CEREMONY": 8025,
}
GRATUITY_RATE = Decimal("0.18")
GOODWILL_PCT = Decimal("0.10")
HOLD_TTL_DAYS = 14
LICENSE_RETURN_WINDOW_DAYS = 10
SECONDS_PER_DAY = 86400

DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00Z"

# Error catalogue: error_id -> http status
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_OFFICIANT_NOT_FOUND": 404,
    "ERR_COUPLE_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_SCRIPT_NOT_FOUND": 404,
    "ERR_REHEARSAL_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_BOOKING_NOT_HOLD": 409,
    "ERR_OFFICIANT_UNAVAILABLE": 409,
    "ERR_STALE_OFFICIANT_VERSION": 412,
    "ERR_OFFICIANT_NOT_CERTIFIED": 422,
    "ERR_STYLE_MISMATCH": 422,
    "ERR_LICENSE_JURISDICTION_MISMATCH": 422,
    "ERR_HOLD_EXPIRED": 409,
    "ERR_LICENSE_EXPIRED": 409,
    "ERR_LICENSE_RETURN_OVERDUE": 409,
    "ERR_OFFICIANT_DOUBLE_BOOKED": 409,
    "ERR_VENUE_UNAVAILABLE": 409,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_NO_BACKUP_AVAILABLE": 409,
    "ERR_SCRIPT_NOT_APPROVED": 409,
    "ERR_BOOKING_NOT_CONFIRMED": 409,
    "ERR_REVIEW_NOT_ALLOWED": 409,
    "ERR_DEPOSIT_INSUFFICIENT": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store + logical clock
# ---------------------------------------------------------------------------
DB = {
    "officiants": {},
    "couples": {},
    "packages": {},
    "venues": {},
    "bookings": {},
    "dateholds": {},
    "scripts": {},
    "rehearsals": {},
    "licenses": {},
    "reviews": {},
}
STATE = {"clock": None, "seq": 0}


def _init_clock():
    STATE["clock"] = parse_iso(DEFAULT_CLOCK_ISO)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not an iso string")
    t = value.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def clock_now():
    return STATE["clock"]


def now_iso():
    return fmt_iso(clock_now())


def days_between(later_dt, earlier_dt):
    """floor((later - earlier) / 86400s)"""
    delta = (later_dt - earlier_dt).total_seconds()
    return int(delta // SECONDS_PER_DAY)


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mean_2dp(values):
    if not values:
        return None
    total = Decimal(sum(values))
    mean = total / Decimal(len(values))
    q = mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def gen_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_entity(store, fields):
    STATE["seq"] += 1
    ent = dict(fields)
    ts = now_iso()
    ent["id"] = gen_id()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = STATE["seq"]
    store[ent["id"]] = ent
    return ent


def touch(ent):
    ent["updated_at"] = now_iso()
    ent["version"] += 1


def serialize(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def make_meta(pagination=None):
    meta = {"api_request_id": gen_request_id(),
            "api_request_timestamp": now_iso()}
    if pagination:
        meta.update(pagination)
    return meta


def respond_object(data, status=200):
    return jsonify({"meta": make_meta(), "response_type": "object",
                    "data": data if data is not None else {}}), status


def respond_array(items, limit, offset, total_count):
    pagination = {"limit": limit, "offset": offset,
                  "total_count": total_count,
                  "has_more": offset + len(items) < total_count}
    return jsonify({"meta": make_meta(pagination), "response_type": "array",
                    "data": items}), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_err):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_err):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"}}
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not uid:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid auth headers")
    return role, uid


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation")


def get_or_404(store_name, ident, error_id):
    if ident is None:
        raise ApiError(error_id, "Referenced resource not found")
    ent = DB[store_name].get(ident)
    if ent is None:
        raise ApiError(error_id, "Referenced resource not found")
    return ent


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {n}")


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a non-empty string")
    return v


def require_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be an integer")
    return v


def require_number(name, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a number")
    return v


def require_enum(name, value, allowed):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", f"Field {name} not in allowed set")
    return value


def require_state_code(name, value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{2}", value):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a 2-letter state code")
    return value


# ---------------------------------------------------------------------------
# Ownership resolution
# ---------------------------------------------------------------------------
def booking_owned_by_couple(booking, uid):
    return booking.get("couple_id") == uid


def booking_owned_by_officiant(booking, uid):
    return booking.get("officiant_id") == uid or booking.get("backup_officiant_id") == uid


def ensure_couple_owns_booking(booking, uid):
    if not booking_owned_by_couple(booking, uid):
        raise ApiError("ERR_UNAUTHORIZED", "Couple does not own this booking")


def ensure_officiant_owns_booking(booking, uid):
    if not booking_owned_by_officiant(booking, uid):
        raise ApiError("ERR_UNAUTHORIZED", "Officiant is not assigned to this booking")


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(store_name, filters):
    limit, offset = parse_pagination()
    items = [e for e in DB[store_name].values() if _matches(e, filters)]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return respond_array([serialize(e) for e in page], limit, offset, total)


def _matches(ent, filters):
    for key, val in filters.items():
        if val is None:
            continue
        if key == "style":
            if val not in ent.get("styles", []):
                return False
        elif key == "jurisdiction_cert":
            if val not in ent.get("certified_jurisdictions", []):
                return False
        else:
            if str(ent.get(key)) != str(val):
                return False
    return True


# ---------------------------------------------------------------------------
# Interval / overlap helpers
# ---------------------------------------------------------------------------
def officiant_double_booked(officiant, start_dt, end_dt, exclude_hold_id=None):
    buffer = timedelta(minutes=officiant["travel_buffer_minutes"])
    cand_start = start_dt - buffer
    cand_end = end_dt + buffer
    for h in DB["dateholds"].values():
        if h["officiant_id"] != officiant["id"]:
            continue
        if h["status"] not in ("HELD", "CONFIRMED"):
            continue
        if exclude_hold_id and h["id"] == exclude_hold_id:
            continue
        ex_start = parse_iso(h["hold_start"]) - buffer
        ex_end = parse_iso(h["hold_end"]) + buffer
        # closed intervals: touching endpoints collide
        if cand_start <= ex_end and ex_start <= cand_end:
            return True
    return False


def venue_conflict(venue_id, start_dt, end_dt):
    for r in DB["rehearsals"].values():
        if r["venue_id"] != venue_id:
            continue
        if r["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        ex_start = parse_iso(r["rehearsal_start"])
        ex_end = parse_iso(r["rehearsal_end"])
        # half-open [start, end): strict overlap, adjacency allowed
        if start_dt < ex_end and ex_start < end_dt:
            return True
    return False


# ---------------------------------------------------------------------------
# Reputation
# ---------------------------------------------------------------------------
def recompute_reputation(officiant_id):
    off = DB["officiants"].get(officiant_id)
    if off is None:
        return
    published = [r["rating"] for r in DB["reviews"].values()
                 if r["officiant_id"] == officiant_id and r["status"] == "PUBLISHED"]
    internal = [r["rating"] for r in DB["reviews"].values()
                if r["officiant_id"] == officiant_id
                and r["status"] in ("SUBMITTED", "PUBLISHED")]
    off["displayed_rating"] = mean_2dp(published)
    off["internal_rating"] = mean_2dp(internal)
    off["published_review_count"] = len(published)
    touch(off)


# ---------------------------------------------------------------------------
# Booking pricing
# ---------------------------------------------------------------------------
def travel_tier(distance):
    for upper, cents in TRAVEL_TIER_CENTS:
        if distance <= upper:
            return cents
    return TRAVEL_TIER_TOP


def compute_quote(booking, package):
    base = package["base_price_cents"]
    travel = travel_tier(booking["travel_distance_km"])
    days_until = days_between(parse_iso(booking["ceremony_start"]), clock_now())
    rush = RUSH_FEE_CENTS if days_until < RUSH_THRESHOLD_DAYS else 0
    interfaith = INTERFAITH_SURCHARGE_CENTS if booking["required_style"] == "INTERFAITH" else 0
    addons = sum(ADDON_PRICE_CENTS[c] for c in booking["addon_codes"])

    subtotal = base + travel + rush + interfaith + addons

    line_items = [base, travel, rush, interfaith] + \
                 [ADDON_PRICE_CENTS[c] for c in booking["addon_codes"]]
    gratuity = sum(round_half_up(Decimal(li) * GRATUITY_RATE) for li in line_items)

    total = subtotal + gratuity
    deposit_due = round_half_up(Decimal(total) * Decimal(str(package["deposit_pct"])))

    booking["days_until_ceremony_at_quote"] = days_until
    booking["quoted_travel_cents"] = travel
    booking["quoted_rush_cents"] = rush
    booking["quoted_interfaith_cents"] = interfaith
    booking["quoted_addons_cents"] = addons
    booking["quoted_subtotal_cents"] = subtotal
    booking["quoted_gratuity_cents"] = gratuity
    booking["quoted_total_cents"] = total
    booking["deposit_due_cents"] = deposit_due


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def cascade_suspend(officiant_id):
    for b in list(DB["bookings"].values()):
        affected = False
        if b["officiant_id"] == officiant_id and b["status"] in ("CONFIRMED", "BACKUP_CONFIRMED"):
            affected = True
        elif b.get("backup_officiant_id") == officiant_id and b["status"] == "BACKUP_CONFIRMED":
            affected = True
        if not affected:
            continue
        b["status"] = "BACKUP_PENDING"
        touch(b)
        # link2: APPROVED script -> CHANGES_REQUESTED
        for s in list(DB["scripts"].values()):
            if s["booking_id"] == b["id"] and s["status"] == "APPROVED":
                s["status"] = "CHANGES_REQUESTED"
                touch(s)
                # link3: CONFIRMED rehearsal -> SCHEDULED
                for r in list(DB["rehearsals"].values()):
                    if r["booking_id"] == b["id"] and r["status"] == "CONFIRMED":
                        r["status"] = "SCHEDULED"
                        touch(r)


def cascade_cancel(booking, origin_status):
    # link1: active date hold (HELD or CONFIRMED) -> RELEASED
    for h in list(DB["dateholds"].values()):
        if h["booking_id"] == booking["id"] and h["status"] in ("HELD", "CONFIRMED"):
            h["status"] = "RELEASED"
            touch(h)
            off = DB["officiants"].get(h["officiant_id"])
            if off is not None:
                off["active_hold_count"] -= 1
                touch(off)
    # direct fan-out for CONFIRMED / BACKUP_PENDING / BACKUP_CONFIRMED origins
    if origin_status in ("CONFIRMED", "BACKUP_PENDING", "BACKUP_CONFIRMED"):
        for r in list(DB["rehearsals"].values()):
            if r["booking_id"] == booking["id"] and r["status"] in ("SCHEDULED", "CONFIRMED"):
                r["status"] = "CANCELLED"
                touch(r)
        for l in list(DB["licenses"].values()):
            if l["booking_id"] == booking["id"] and l["status"] in ("NOT_FILED", "FILED", "SIGNED"):
                l["status"] = "VOIDED"
                touch(l)


# ===========================================================================
# OFFICIANT endpoints
# ===========================================================================
@app.route("/officiants", methods=["POST"])
def create_officiant():
    role, _uid = require_auth()
    require_role(role, {"Coordinator"})
    body = get_body()

    require_fields(body, ["full_name", "email", "styles", "denomination",
                          "certified_jurisdictions"])
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")

    styles = body["styles"]
    if not isinstance(styles, list) or len(styles) == 0:
        raise ApiError("ERR_VALIDATION", "styles must be a non-empty array")
    for s in styles:
        require_enum("styles", s, STYLE_SET)

    denomination = require_enum("denomination", body["denomination"], DENOM_SET)

    juris = body["certified_jurisdictions"]
    if not isinstance(juris, list) or len(juris) == 0:
        raise ApiError("ERR_VALIDATION", "certified_jurisdictions must be non-empty")
    for j in juris:
        require_state_code("certified_jurisdictions", j)

    travel_buffer = body.get("travel_buffer_minutes", 180)
    if isinstance(travel_buffer, bool) or not isinstance(travel_buffer, int) or travel_buffer < 0:
        raise ApiError("ERR_VALIDATION", "travel_buffer_minutes must be a non-negative integer")

    max_holds = body.get("max_active_holds", 5)
    if isinstance(max_holds, bool) or not isinstance(max_holds, int) or max_holds < 1:
        raise ApiError("ERR_VALIDATION", "max_active_holds must be an integer >= 1")

    ent = new_entity(DB["officiants"], {
        "full_name": full_name,
        "email": email,
        "styles": list(styles),
        "denomination": denomination,
        "certified_jurisdictions": list(juris),
        "travel_buffer_minutes": travel_buffer,
        "max_active_holds": max_holds,
        "status": "PENDING_REVIEW",
        "active_hold_count": 0,
        "escrow_balance_cents": 0,
        "displayed_rating": None,
        "internal_rating": None,
        "published_review_count": 0,
    })
    return respond_object(serialize(ent), 201)


@app.route("/officiants/<oid>", methods=["GET"])
def get_officiant(oid):
    role, _uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    ent = get_or_404("officiants", oid, "ERR_OFFICIANT_NOT_FOUND")
    return respond_object(serialize(ent))


@app.route("/officiants", methods=["GET"])
def list_officiants():
    role, _uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    args = request.args
    filters = {
        "style": args.get("style"),
        "denomination": args.get("denomination"),
        "jurisdiction_cert": args.get("jurisdiction"),
        "status": args.get("status"),
    }
    return list_response("officiants", filters)


@app.route("/officiants/<oid>/transition", methods=["POST"])
def transition_officiant(oid):
    role, _uid = require_auth()
    require_role(role, {"Coordinator"})
    off = get_or_404("officiants", oid, "ERR_OFFICIANT_NOT_FOUND")
    body = get_body()
    require_fields(body, ["to_state"])
    to_state = require_enum("to_state", body["to_state"],
                            {"PENDING_REVIEW", "ACTIVE", "SUSPENDED"})

    cur = off["status"]
    valid = {("PENDING_REVIEW", "ACTIVE"), ("ACTIVE", "SUSPENDED"),
             ("SUSPENDED", "ACTIVE")}
    if (cur, to_state) not in valid:
        raise ApiError("ERR_INVALID_STATE", "Invalid officiant transition")

    off["status"] = to_state
    touch(off)
    if to_state == "SUSPENDED":
        cascade_suspend(off["id"])
    return respond_object(serialize(off))


# ===========================================================================
# COUPLE endpoints
# ===========================================================================
@app.route("/couples", methods=["POST"])
def create_couple():
    role, _uid = require_auth()
    require_role(role, {"Coordinator", "Couple"})
    body = get_body()
    require_fields(body, ["partner_one_name", "partner_two_name", "email", "phone"])
    ent = new_entity(DB["couples"], {
        "partner_one_name": require_str(body, "partner_one_name"),
        "partner_two_name": require_str(body, "partner_two_name"),
        "email": require_str(body, "email"),
        "phone": require_str(body, "phone"),
        "paid_total_cents": 0,
        "refund_credit_cents": 0,
    })
    return respond_object(serialize(ent), 201)


@app.route("/couples/<cid>", methods=["GET"])
def get_couple(cid):
    role, uid = require_auth()
    require_role(role, {"Coordinator", "Couple"})
    ent = get_or_404("couples", cid, "ERR_COUPLE_NOT_FOUND")
    if role == "Couple" and ent["id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Couple may only read its own record")
    return respond_object(serialize(ent))


# ===========================================================================
# PACKAGE endpoints
# ===========================================================================
@app.route("/packages", methods=["POST"])
def create_package():
    role, _uid = require_auth()
    require_role(role, {"Coordinator"})
    body = get_body()
    require_fields(body, ["name", "tier", "base_price_cents", "deposit_pct"])
    name = require_str(body, "name")
    tier = require_enum("tier", body["tier"], TIER_SET)
    base_price = require_int(body, "base_price_cents")
    if base_price <= 0:
        raise ApiError("ERR_VALIDATION", "base_price_cents must be > 0")
    deposit_pct = body["deposit_pct"]
    require_number("deposit_pct", deposit_pct)
    if not (0 < deposit_pct <= 1):
        raise ApiError("ERR_VALIDATION", "deposit_pct must be in (0, 1]")
    ent = new_entity(DB["packages"], {
        "name": name, "tier": tier,
        "base_price_cents": base_price, "deposit_pct": deposit_pct,
    })
    return respond_object(serialize(ent), 201)


# ===========================================================================
# VENUE endpoints
# ===========================================================================
@app.route("/venues", methods=["POST"])
def create_venue():
    role, _uid = require_auth()
    require_role(role, {"Coordinator"})
    body = get_body()
    require_fields(body, ["name", "jurisdiction", "address"])
    ent = new_entity(DB["venues"], {
        "name": require_str(body, "name"),
        "jurisdiction": require_state_code("jurisdiction", body["jurisdiction"]),
        "address": require_str(body, "address"),
    })
    return respond_object(serialize(ent), 201)


# ===========================================================================
# BOOKING endpoints
# ===========================================================================
@app.route("/bookings", methods=["POST"])
def create_booking():
    role, uid = require_auth()
    require_role(role, {"Coordinator", "Couple"})
    body = get_body()

    # Existence (left-to-right: officiant, couple, package, venue) for present FKs
    if body.get("officiant_id") is not None:
        get_or_404("officiants", body["officiant_id"], "ERR_OFFICIANT_NOT_FOUND")
    if body.get("couple_id") is not None:
        get_or_404("couples", body["couple_id"], "ERR_COUPLE_NOT_FOUND")
    if body.get("package_id") is not None:
        get_or_404("packages", body["package_id"], "ERR_PACKAGE_NOT_FOUND")
    if body.get("venue_id") is not None:
        get_or_404("venues", body["venue_id"], "ERR_VENUE_NOT_FOUND")

    # Ownership: couple creates only its own bookings
    if role == "Couple" and body.get("couple_id") is not None and body["couple_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Couple may only create its own bookings")

    # Body shape validation
    require_fields(body, ["officiant_id", "couple_id", "package_id", "venue_id",
                          "ceremony_start", "ceremony_end", "travel_distance_km",
                          "required_style"])
    try:
        cs = parse_iso(body["ceremony_start"])
        ce = parse_iso(body["ceremony_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "ceremony_start/ceremony_end must be ISO8601")
    if not (ce > cs):
        raise ApiError("ERR_VALIDATION", "ceremony_end must be after ceremony_start")

    distance = require_number("travel_distance_km", body["travel_distance_km"])
    if distance < 0:
        raise ApiError("ERR_VALIDATION", "travel_distance_km must be >= 0")

    required_style = require_enum("required_style", body["required_style"], STYLE_SET)

    addon_codes = body.get("addon_codes", [])
    if addon_codes is None:
        addon_codes = []
    if not isinstance(addon_codes, list):
        raise ApiError("ERR_VALIDATION", "addon_codes must be an array")
    for c in addon_codes:
        require_enum("addon_codes", c, ADDON_SET)

    package = DB["packages"][body["package_id"]]

    ent = new_entity(DB["bookings"], {
        "officiant_id": body["officiant_id"],
        "couple_id": body["couple_id"],
        "package_id": body["package_id"],
        "venue_id": body["venue_id"],
        "backup_officiant_id": None,
        "ceremony_start": body["ceremony_start"],
        "ceremony_end": body["ceremony_end"],
        "travel_distance_km": distance,
        "required_style": required_style,
        "addon_codes": list(addon_codes),
        "status": "INQUIRY",
        "deposit_captured_cents": 0,
        "refund_issued_cents": 0,
        "forfeit_retained_cents": 0,
        "cancel_initiator": None,
        "cancel_reason": None,
    })
    compute_quote(ent, package)
    return respond_object(serialize(ent), 201)


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    role, uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    b = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND")
    if role == "Couple":
        ensure_couple_owns_booking(b, uid)
    elif role == "Officiant":
        ensure_officiant_owns_booking(b, uid)
    return respond_object(serialize(b))


@app.route("/bookings", methods=["GET"])
def list_bookings():
    role, _uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    args = request.args
    filters = {
        "officiant_id": args.get("officiant_id"),
        "backup_officiant_id": args.get("backup_officiant_id"),
        "couple_id": args.get("couple_id"),
        "package_id": args.get("package_id"),
        "venue_id": args.get("venue_id"),
        "status": args.get("status"),
    }
    return list_response("bookings", filters)


@app.route("/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    role, uid = require_auth()
    require_role(role, {"Couple"})
    b = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND")
    ensure_couple_owns_booking(b, uid)
    body = get_body()
    require_fields(body, ["deposit_amount_cents"])
    deposit_amount = require_int(body, "deposit_amount_cents")

    # Dedicated confirm state gate (outranks fiscal deposit check)
    if b["status"] != "HOLD":
        raise ApiError("ERR_BOOKING_NOT_HOLD", "Booking is not in HOLD")

    off = DB["officiants"][b["officiant_id"]]
    if off["status"] != "ACTIVE":
        raise ApiError("ERR_OFFICIANT_UNAVAILABLE", "Assigned officiant is not ACTIVE")

    hold = _find_active_hold(b["id"], ("HELD",))
    if hold is not None:
        if not (clock_now() < parse_iso(hold["expires_at"])):
            raise ApiError("ERR_HOLD_EXPIRED", "Date hold has expired")

    if deposit_amount < b["deposit_due_cents"]:
        raise ApiError("ERR_DEPOSIT_INSUFFICIENT", "Deposit amount is insufficient")

    captured = b["deposit_due_cents"]
    b["deposit_captured_cents"] = captured
    b["status"] = "CONFIRMED"
    touch(b)

    couple = DB["couples"][b["couple_id"]]
    couple["paid_total_cents"] += captured
    touch(couple)

    off["escrow_balance_cents"] += captured
    touch(off)

    if hold is not None:
        hold["status"] = "CONFIRMED"
        touch(hold)

    return respond_object(serialize(b))


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    role, uid = require_auth()
    require_role(role, {"Couple", "Coordinator"})
    b = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND")
    if role == "Couple":
        ensure_couple_owns_booking(b, uid)
    body = get_body()
    require_fields(body, ["cancel_reason"])
    cancel_reason = require_enum("cancel_reason", body["cancel_reason"], CANCEL_REASON_SET)

    origin = b["status"]
    if origin not in ("HOLD", "CONFIRMED", "BACKUP_PENDING", "BACKUP_CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "Booking cannot be cancelled from this state")

    # Determine initiator
    if origin == "BACKUP_PENDING":
        initiator = "SERVICE" if (cancel_reason == "NO_BACKUP" or role == "Coordinator") else "COUPLE"
    else:
        initiator = "COUPLE" if role == "Couple" else "SERVICE"

    captured = b["deposit_captured_cents"]
    if origin == "HOLD":
        refund = 0
        forfeit = 0
    else:
        if initiator == "COUPLE":
            days_left = days_between(parse_iso(b["ceremony_start"]), clock_now())
            if days_left >= 90:
                pct = Decimal("1.0")
            elif days_left >= 30:
                pct = Decimal("0.5")
            else:
                pct = Decimal("0.0")
            refund = round_half_up(Decimal(captured) * pct)
            forfeit = captured - refund
        else:  # SERVICE
            goodwill = round_half_up(Decimal(b["quoted_subtotal_cents"]) * GOODWILL_PCT)
            refund = captured + goodwill
            forfeit = 0

    b["status"] = "CANCELLED"
    b["cancel_initiator"] = initiator
    b["cancel_reason"] = cancel_reason
    b["refund_issued_cents"] = refund
    b["forfeit_retained_cents"] = forfeit
    touch(b)

    if origin != "HOLD":
        couple = DB["couples"][b["couple_id"]]
        couple["refund_credit_cents"] += refund
        touch(couple)

        off = DB["officiants"].get(b["officiant_id"])
        if off is not None:
            off["escrow_balance_cents"] -= (captured - forfeit)
            touch(off)

    cascade_cancel(b, origin)
    return respond_object(serialize(b))


@app.route("/bookings/<bid>/assign-backup", methods=["POST"])
def assign_backup(bid):
    role, _uid = require_auth()
    require_role(role, {"Coordinator"})
    b = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND")
    get_body()

    if b["status"] != "BACKUP_PENDING":
        raise ApiError("ERR_INVALID_STATE", "Booking is not BACKUP_PENDING")

    venue = DB["venues"][b["venue_id"]]
    cs = parse_iso(b["ceremony_start"])
    ce = parse_iso(b["ceremony_end"])

    candidates = []
    for o in DB["officiants"].values():
        if o["id"] == b["officiant_id"]:
            continue
        if o["status"] != "ACTIVE":
            continue
        if b["required_style"] not in o["styles"]:
            continue
        if venue["jurisdiction"] not in o["certified_jurisdictions"]:
            continue
        if o["active_hold_count"] >= o["max_active_holds"]:
            continue
        if officiant_double_booked(o, cs, ce):
            continue
        candidates.append(o)

    if not candidates:
        raise ApiError("ERR_NO_BACKUP_AVAILABLE", "No eligible backup officiant")

    def rank_key(o):
        rating = o["displayed_rating"]
        rating = rating if rating is not None else -1
        return (-rating, o["created_at"], o["_seq"])

    candidates.sort(key=rank_key)
    selected = candidates[0]

    b["backup_officiant_id"] = selected["id"]
    b["status"] = "BACKUP_CONFIRMED"
    touch(b)

    selected["active_hold_count"] += 1
    touch(selected)

    return respond_object(serialize(b))


@app.route("/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    role, uid = require_auth()
    require_role(role, {"Officiant"})
    b = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND")
    ensure_officiant_owns_booking(b, uid)
    get_body()

    if b["status"] not in ("CONFIRMED", "BACKUP_CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "Booking cannot be completed from this state")
    if clock_now() < parse_iso(b["ceremony_start"]):
        raise ApiError("ERR_INVALID_STATE", "Ceremony has not started yet")

    b["status"] = "COMPLETED"
    touch(b)
    return respond_object(serialize(b))


def _find_active_hold(booking_id, statuses):
    for h in DB["dateholds"].values():
        if h["booking_id"] == booking_id and h["status"] in statuses:
            return h
    return None


# ===========================================================================
# DATE HOLD endpoints
# ===========================================================================
@app.route("/date-holds", methods=["POST"])
def create_date_hold():
    role, uid = require_auth()
    require_role(role, {"Couple", "Coordinator"})
    body = get_body()

    # Existence: booking
    if body.get("booking_id") is not None:
        b = get_or_404("bookings", body["booking_id"], "ERR_BOOKING_NOT_FOUND")
    else:
        b = None

    # Ownership
    if role == "Couple" and b is not None:
        ensure_couple_owns_booking(b, uid)

    # Body validation
    require_fields(body, ["booking_id", "expected_officiant_version"])
    expected = require_int(body, "expected_officiant_version")

    off = DB["officiants"][b["officiant_id"]]
    venue = DB["venues"][b["venue_id"]]

    # Ordered gauntlet (PRD 3.3)
    if b["status"] != "INQUIRY":
        raise ApiError("ERR_INVALID_STATE", "Booking is not in INQUIRY")
    if off["status"] != "ACTIVE":
        raise ApiError("ERR_OFFICIANT_UNAVAILABLE", "Assigned officiant is not ACTIVE")
    if venue["jurisdiction"] not in off["certified_jurisdictions"]:
        raise ApiError("ERR_OFFICIANT_NOT_CERTIFIED", "Officiant not certified for venue jurisdiction")
    if b["required_style"] not in off["styles"]:
        raise ApiError("ERR_STYLE_MISMATCH", "Required style not offered by officiant")
    if expected != off["version"]:
        raise ApiError("ERR_STALE_OFFICIANT_VERSION", "Stale officiant version")
    cs = parse_iso(b["ceremony_start"])
    ce = parse_iso(b["ceremony_end"])
    if officiant_double_booked(off, cs, ce):
        raise ApiError("ERR_OFFICIANT_DOUBLE_BOOKED", "Officiant double-booked")
    if off["active_hold_count"] >= off["max_active_holds"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", "Officiant hold capacity exceeded")

    expires_at = fmt_iso(clock_now() + timedelta(days=HOLD_TTL_DAYS))
    hold = new_entity(DB["dateholds"], {
        "booking_id": b["id"],
        "officiant_id": off["id"],
        "hold_start": b["ceremony_start"],
        "hold_end": b["ceremony_end"],
        "expires_at": expires_at,
        "status": "HELD",
    })

    b["status"] = "HOLD"
    touch(b)

    off["active_hold_count"] += 1
    touch(off)

    return respond_object(serialize(hold), 201)


@app.route("/date-holds/<hid>", methods=["GET"])
def get_date_hold(hid):
    role, uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    h = get_or_404("dateholds", hid, "ERR_HOLD_NOT_FOUND")
    if role in ("Couple", "Officiant"):
        b = DB["bookings"].get(h["booking_id"])
        if b is not None:
            if role == "Couple":
                ensure_couple_owns_booking(b, uid)
            else:
                ensure_officiant_owns_booking(b, uid)
    return respond_object(serialize(h))


@app.route("/date-holds", methods=["GET"])
def list_date_holds():
    role, _uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    args = request.args
    filters = {
        "officiant_id": args.get("officiant_id"),
        "booking_id": args.get("booking_id"),
        "status": args.get("status"),
    }
    return list_response("dateholds", filters)


# ===========================================================================
# CEREMONY SCRIPT endpoints
# ===========================================================================
@app.route("/ceremony-scripts", methods=["POST"])
def create_script():
    role, uid = require_auth()
    require_role(role, {"Couple"})
    body = get_body()

    if body.get("booking_id") is not None:
        b = get_or_404("bookings", body["booking_id"], "ERR_BOOKING_NOT_FOUND")
    else:
        b = None
    if b is not None:
        ensure_couple_owns_booking(b, uid)

    require_fields(body, ["booking_id", "opening_remarks", "vow_format", "closing_blessing"])
    vow_format = require_enum("vow_format", body["vow_format"], VOW_SET)

    readings = body.get("readings", [])
    if readings is None:
        readings = []
    if not isinstance(readings, list):
        raise ApiError("ERR_VALIDATION", "readings must be an array")
    ritual = body.get("ritual_elements", [])
    if ritual is None:
        ritual = []
    if not isinstance(ritual, list):
        raise ApiError("ERR_VALIDATION", "ritual_elements must be an array")

    ent = new_entity(DB["scripts"], {
        "booking_id": b["id"],
        "opening_remarks": require_str(body, "opening_remarks"),
        "vow_format": vow_format,
        "readings": list(readings),
        "ritual_elements": list(ritual),
        "closing_blessing": require_str(body, "closing_blessing"),
        "officiant_notes": None,
        "revision_count": 0,
        "status": "DRAFT",
    })
    return respond_object(serialize(ent), 201)


@app.route("/ceremony-scripts/<sid>", methods=["GET"])
def get_script(sid):
    role, uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    s = get_or_404("scripts", sid, "ERR_SCRIPT_NOT_FOUND")
    _script_ownership_read(role, uid, s)
    return respond_object(serialize(s))


@app.route("/ceremony-scripts", methods=["GET"])
def list_scripts():
    role, _uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    args = request.args
    filters = {"booking_id": args.get("booking_id"), "status": args.get("status")}
    return list_response("scripts", filters)


@app.route("/ceremony-scripts/<sid>", methods=["PATCH"])
def edit_script(sid):
    role, uid = require_auth()
    require_role(role, {"Couple"})
    s = get_or_404("scripts", sid, "ERR_SCRIPT_NOT_FOUND")
    b = DB["bookings"].get(s["booking_id"])
    if b is not None:
        ensure_couple_owns_booking(b, uid)
    body = get_body()

    if s["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", "Script may only be edited in DRAFT or CHANGES_REQUESTED")

    if "opening_remarks" in body and body["opening_remarks"] is not None:
        s["opening_remarks"] = require_str(body, "opening_remarks")
    if "closing_blessing" in body and body["closing_blessing"] is not None:
        s["closing_blessing"] = require_str(body, "closing_blessing")
    if "vow_format" in body and body["vow_format"] is not None:
        s["vow_format"] = require_enum("vow_format", body["vow_format"], VOW_SET)
    if "readings" in body and body["readings"] is not None:
        if not isinstance(body["readings"], list):
            raise ApiError("ERR_VALIDATION", "readings must be an array")
        s["readings"] = list(body["readings"])
    if "ritual_elements" in body and body["ritual_elements"] is not None:
        if not isinstance(body["ritual_elements"], list):
            raise ApiError("ERR_VALIDATION", "ritual_elements must be an array")
        s["ritual_elements"] = list(body["ritual_elements"])

    touch(s)
    return respond_object(serialize(s))


@app.route("/ceremony-scripts/<sid>/submit", methods=["POST"])
def submit_script(sid):
    role, uid = require_auth()
    require_role(role, {"Couple"})
    s = get_or_404("scripts", sid, "ERR_SCRIPT_NOT_FOUND")
    b = DB["bookings"].get(s["booking_id"])
    if b is not None:
        ensure_couple_owns_booking(b, uid)
    get_body()

    if s["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", "Script cannot be submitted from this state")
    if s["status"] == "CHANGES_REQUESTED":
        s["revision_count"] += 1
    s["status"] = "SUBMITTED"
    touch(s)
    return respond_object(serialize(s))


@app.route("/ceremony-scripts/<sid>/decision", methods=["POST"])
def decide_script(sid):
    role, uid = require_auth()
    require_role(role, {"Officiant"})
    s = get_or_404("scripts", sid, "ERR_SCRIPT_NOT_FOUND")
    b = DB["bookings"].get(s["booking_id"])
    if b is not None:
        ensure_officiant_owns_booking(b, uid)
    body = get_body()
    require_fields(body, ["decision"])
    decision = require_enum("decision", body["decision"], {"APPROVE", "REQUEST_CHANGES"})

    if s["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Script is not SUBMITTED")

    s["status"] = "APPROVED" if decision == "APPROVE" else "CHANGES_REQUESTED"
    s["officiant_notes"] = body.get("notes")
    touch(s)
    return respond_object(serialize(s))


def _script_ownership_read(role, uid, s):
    b = DB["bookings"].get(s["booking_id"])
    if b is None:
        return
    if role == "Couple":
        ensure_couple_owns_booking(b, uid)
    elif role == "Officiant":
        ensure_officiant_owns_booking(b, uid)


# ===========================================================================
# REHEARSAL endpoints
# ===========================================================================
@app.route("/rehearsals", methods=["POST"])
def create_rehearsal():
    role, uid = require_auth()
    require_role(role, {"Couple"})
    body = get_body()

    # Existence order: venue (4) before booking (5)
    if body.get("venue_id") is not None:
        venue = get_or_404("venues", body["venue_id"], "ERR_VENUE_NOT_FOUND")
    else:
        venue = None
    if body.get("booking_id") is not None:
        b = get_or_404("bookings", body["booking_id"], "ERR_BOOKING_NOT_FOUND")
    else:
        b = None
    if b is not None:
        ensure_couple_owns_booking(b, uid)

    require_fields(body, ["booking_id", "venue_id", "rehearsal_start", "rehearsal_end"])
    try:
        rs = parse_iso(body["rehearsal_start"])
        re_ = parse_iso(body["rehearsal_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "rehearsal_start/rehearsal_end must be ISO8601")
    if not (re_ > rs):
        raise ApiError("ERR_VALIDATION", "rehearsal_end must be after rehearsal_start")

    if venue_conflict(venue["id"], rs, re_):
        raise ApiError("ERR_VENUE_UNAVAILABLE", "Venue unavailable for the rehearsal window")

    ent = new_entity(DB["rehearsals"], {
        "booking_id": b["id"],
        "venue_id": venue["id"],
        "rehearsal_start": body["rehearsal_start"],
        "rehearsal_end": body["rehearsal_end"],
        "status": "SCHEDULED",
    })
    return respond_object(serialize(ent), 201)


@app.route("/rehearsals/<rid>", methods=["GET"])
def get_rehearsal(rid):
    role, uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    r = get_or_404("rehearsals", rid, "ERR_REHEARSAL_NOT_FOUND")
    b = DB["bookings"].get(r["booking_id"])
    if b is not None:
        if role == "Couple":
            ensure_couple_owns_booking(b, uid)
        elif role == "Officiant":
            ensure_officiant_owns_booking(b, uid)
    return respond_object(serialize(r))


@app.route("/rehearsals", methods=["GET"])
def list_rehearsals():
    role, _uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    args = request.args
    filters = {
        "booking_id": args.get("booking_id"),
        "venue_id": args.get("venue_id"),
        "status": args.get("status"),
    }
    return list_response("rehearsals", filters)


@app.route("/rehearsals/<rid>/transition", methods=["POST"])
def transition_rehearsal(rid):
    role, uid = require_auth()
    require_role(role, {"Officiant", "Couple", "Coordinator"})
    r = get_or_404("rehearsals", rid, "ERR_REHEARSAL_NOT_FOUND")
    body = get_body()
    require_fields(body, ["to_state"])
    to_state = require_enum("to_state", body["to_state"],
                            {"SCHEDULED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED"})

    b = DB["bookings"].get(r["booking_id"])

    # Per-target role + ownership
    if to_state in ("CONFIRMED", "COMPLETED", "NO_SHOW"):
        if role != "Officiant":
            raise ApiError("ERR_UNAUTHORIZED", "Only the officiant may perform this transition")
        if b is not None:
            ensure_officiant_owns_booking(b, uid)
    elif to_state == "CANCELLED":
        if role not in ("Couple", "Coordinator"):
            raise ApiError("ERR_UNAUTHORIZED", "Only couple or coordinator may cancel a rehearsal")
        if role == "Couple" and b is not None:
            ensure_couple_owns_booking(b, uid)
    else:
        raise ApiError("ERR_INVALID_STATE", "Unsupported rehearsal transition")

    cur = r["status"]
    valid = {
        ("SCHEDULED", "CONFIRMED"),
        ("CONFIRMED", "COMPLETED"),
        ("CONFIRMED", "NO_SHOW"),
        ("SCHEDULED", "CANCELLED"),
        ("CONFIRMED", "CANCELLED"),
    }
    if (cur, to_state) not in valid:
        raise ApiError("ERR_INVALID_STATE", "Invalid rehearsal transition")

    if to_state == "CONFIRMED":
        approved = any(s["booking_id"] == r["booking_id"] and s["status"] == "APPROVED"
                       for s in DB["scripts"].values())
        if not approved:
            raise ApiError("ERR_SCRIPT_NOT_APPROVED", "Ceremony script is not APPROVED")

    r["status"] = to_state
    touch(r)
    return respond_object(serialize(r))


# ===========================================================================
# MARRIAGE LICENSE endpoints
# ===========================================================================
@app.route("/marriage-licenses", methods=["POST"])
def create_license():
    role, uid = require_auth()
    require_role(role, {"Couple"})
    body = get_body()

    if body.get("booking_id") is not None:
        b = get_or_404("bookings", body["booking_id"], "ERR_BOOKING_NOT_FOUND")
    else:
        b = None
    if b is not None:
        ensure_couple_owns_booking(b, uid)

    require_fields(body, ["booking_id", "jurisdiction", "license_number",
                          "issued_date", "expiry_date"])
    jurisdiction = require_state_code("jurisdiction", body["jurisdiction"])
    license_number = require_str(body, "license_number")
    try:
        issued = parse_iso(body["issued_date"])
        expiry = parse_iso(body["expiry_date"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "issued_date/expiry_date must be ISO8601")
    if not (expiry > issued):
        raise ApiError("ERR_VALIDATION", "expiry_date must be after issued_date")

    ent = new_entity(DB["licenses"], {
        "booking_id": b["id"],
        "jurisdiction": jurisdiction,
        "license_number": license_number,
        "issued_date": body["issued_date"],
        "expiry_date": body["expiry_date"],
        "signed_at": None,
        "return_deadline": None,
        "recorded_at": None,
        "status": "NOT_FILED",
    })
    return respond_object(serialize(ent), 201)


@app.route("/marriage-licenses/<lid>", methods=["GET"])
def get_license(lid):
    role, uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    l = get_or_404("licenses", lid, "ERR_LICENSE_NOT_FOUND")
    b = DB["bookings"].get(l["booking_id"])
    if b is not None:
        if role == "Couple":
            ensure_couple_owns_booking(b, uid)
        elif role == "Officiant":
            ensure_officiant_owns_booking(b, uid)
    return respond_object(serialize(l))


@app.route("/marriage-licenses", methods=["GET"])
def list_licenses():
    role, _uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    args = request.args
    filters = {"booking_id": args.get("booking_id"), "status": args.get("status")}
    return list_response("licenses", filters)


@app.route("/marriage-licenses/<lid>/transition", methods=["POST"])
def transition_license(lid):
    role, uid = require_auth()
    require_role(role, {"Couple", "Officiant", "Coordinator"})
    l = get_or_404("licenses", lid, "ERR_LICENSE_NOT_FOUND")
    body = get_body()
    require_fields(body, ["to_state"])
    to_state = require_enum("to_state", body["to_state"],
                            {"FILED", "SIGNED", "RECORDED", "REJECTED"})

    b = DB["bookings"].get(l["booking_id"])

    # Per-target role + ownership
    if to_state == "FILED":
        if role != "Couple":
            raise ApiError("ERR_UNAUTHORIZED", "Only the couple may file a license")
        if b is not None:
            ensure_couple_owns_booking(b, uid)
    elif to_state == "SIGNED":
        if role != "Officiant":
            raise ApiError("ERR_UNAUTHORIZED", "Only the officiant may sign a license")
        if b is not None:
            ensure_officiant_owns_booking(b, uid)
    else:  # RECORDED, REJECTED
        if role != "Coordinator":
            raise ApiError("ERR_UNAUTHORIZED", "Only a coordinator may record/reject a license")

    cur = l["status"]

    if to_state == "FILED":
        if cur not in ("NOT_FILED", "REJECTED"):
            raise ApiError("ERR_INVALID_STATE", "License cannot be filed from this state")
        if b is None or b["status"] not in ("CONFIRMED", "BACKUP_CONFIRMED"):
            raise ApiError("ERR_BOOKING_NOT_CONFIRMED", "Backing booking is not confirmed")
        if cur == "NOT_FILED":
            venue = DB["venues"][b["venue_id"]]
            if l["jurisdiction"] != venue["jurisdiction"]:
                raise ApiError("ERR_LICENSE_JURISDICTION_MISMATCH",
                               "License jurisdiction does not match venue")
            l["status"] = "FILED"
        else:  # refile from REJECTED
            l["status"] = "FILED"
            l["signed_at"] = None
            l["return_deadline"] = None

    elif to_state == "SIGNED":
        if cur != "FILED":
            raise ApiError("ERR_INVALID_STATE", "License cannot be signed from this state")
        if clock_now() > parse_iso(l["expiry_date"]):
            raise ApiError("ERR_LICENSE_EXPIRED", "License has expired")
        l["status"] = "SIGNED"
        l["signed_at"] = now_iso()
        l["return_deadline"] = fmt_iso(clock_now() + timedelta(days=LICENSE_RETURN_WINDOW_DAYS))

    elif to_state == "RECORDED":
        if cur != "SIGNED":
            raise ApiError("ERR_INVALID_STATE", "License cannot be recorded from this state")
        if clock_now() > parse_iso(l["return_deadline"]):
            raise ApiError("ERR_LICENSE_RETURN_OVERDUE", "License return window elapsed")
        l["status"] = "RECORDED"
        l["recorded_at"] = now_iso()

    elif to_state == "REJECTED":
        if cur != "SIGNED":
            raise ApiError("ERR_INVALID_STATE", "License cannot be rejected from this state")
        l["status"] = "REJECTED"

    touch(l)
    return respond_object(serialize(l))


# ===========================================================================
# REVIEW endpoints
# ===========================================================================
@app.route("/reviews", methods=["POST"])
def create_review():
    role, uid = require_auth()
    require_role(role, {"Couple"})
    body = get_body()

    if body.get("booking_id") is not None:
        b = get_or_404("bookings", body["booking_id"], "ERR_BOOKING_NOT_FOUND")
    else:
        b = None
    if b is not None:
        ensure_couple_owns_booking(b, uid)

    require_fields(body, ["booking_id", "rating", "text"])
    rating = require_int(body, "rating")
    if rating < 1 or rating > 5:
        raise ApiError("ERR_VALIDATION", "rating must be an integer 1..5")
    text = require_str(body, "text")

    if b["status"] != "COMPLETED":
        raise ApiError("ERR_REVIEW_NOT_ALLOWED", "Booking is not COMPLETED")

    ent = new_entity(DB["reviews"], {
        "booking_id": b["id"],
        "officiant_id": b["officiant_id"],
        "rating": rating,
        "text": text,
        "status": "SUBMITTED",
    })
    recompute_reputation(b["officiant_id"])
    return respond_object(serialize(ent), 201)


@app.route("/reviews/<rvid>", methods=["GET"])
def get_review(rvid):
    role, uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    rv = get_or_404("reviews", rvid, "ERR_REVIEW_NOT_FOUND")
    b = DB["bookings"].get(rv["booking_id"])
    if b is not None:
        if role == "Couple":
            ensure_couple_owns_booking(b, uid)
        elif role == "Officiant":
            ensure_officiant_owns_booking(b, uid)
    return respond_object(serialize(rv))


@app.route("/reviews", methods=["GET"])
def list_reviews():
    role, _uid = require_auth()
    require_role(role, {"Coordinator", "Couple", "Officiant"})
    args = request.args
    filters = {
        "officiant_id": args.get("officiant_id"),
        "booking_id": args.get("booking_id"),
        "status": args.get("status"),
    }
    return list_response("reviews", filters)


@app.route("/reviews/<rvid>/moderate", methods=["POST"])
def moderate_review(rvid):
    role, _uid = require_auth()
    require_role(role, {"Coordinator"})
    rv = get_or_404("reviews", rvid, "ERR_REVIEW_NOT_FOUND")
    body = get_body()
    require_fields(body, ["decision"])
    decision = require_enum("decision", body["decision"], {"PUBLISH", "REMOVE"})

    cur = rv["status"]
    if decision == "PUBLISH":
        if cur != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Review is not SUBMITTED")
        rv["status"] = "PUBLISHED"
    else:  # REMOVE
        if cur not in ("SUBMITTED", "PUBLISHED"):
            raise ApiError("ERR_INVALID_STATE", "Review cannot be removed from this state")
        rv["status"] = "REMOVED"

    touch(rv)
    recompute_reputation(rv["officiant_id"])
    return respond_object(serialize(rv))


# ===========================================================================
# SYSTEM / test-driving endpoints
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, _uid = require_auth()
    require_role(role, {"Coordinator"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        STATE["clock"] = parse_iso(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be an ISO8601 instant")
    return respond_object({})


@app.route("/_expiry/run", methods=["POST"])
def run_expiry():
    role, _uid = require_auth()
    require_role(role, {"Coordinator"})
    get_body()
    now = clock_now()

    # Expire HELD date holds whose expires_at is at/before now
    for h in list(DB["dateholds"].values()):
        if h["status"] == "HELD" and now >= parse_iso(h["expires_at"]):
            h["status"] = "EXPIRED"
            touch(h)
            off = DB["officiants"].get(h["officiant_id"])
            if off is not None:
                off["active_hold_count"] -= 1
                touch(off)
            b = DB["bookings"].get(h["booking_id"])
            if b is not None and b["status"] == "HOLD":
                b["status"] = "EXPIRED"
                touch(b)

    # Expire FILED licenses whose expiry_date is at/before now
    for l in list(DB["licenses"].values()):
        if l["status"] == "FILED" and now >= parse_iso(l["expiry_date"]):
            l["status"] = "EXPIRED"
            touch(l)

    return respond_object({})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
_init_clock()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
