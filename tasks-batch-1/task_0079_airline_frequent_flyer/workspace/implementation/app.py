"""
Airline Frequent-Flyer & Upgrade Program API.

Implemented strictly from workspace/PRD.md (authoritative) and SCAFFOLD.yaml.
All state is in-memory only; every process launch starts empty. No seeding.
"""
import os
import re
import uuid
import random
import string
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from datetime import datetime, timezone
from threading import Lock

from flask import Flask, jsonify, request, g

app = Flask(__name__)
_lock = Lock()

# ---------------------------------------------------------------------------
# Constants (from PRD §3 / SCAFFOLD calculations)
# ---------------------------------------------------------------------------
ROLES = {"ProgramAdmin", "OperationsAgent", "Member"}

FARE_CLASS_MULT = {"DISCOUNT": Decimal("0.5"), "ECONOMY": Decimal("1.0"),
                   "BUSINESS": Decimal("1.5"), "FIRST": Decimal("2.0")}
TIER_BONUS_PCT = {"BASE": 0, "SILVER": 25, "GOLD": 50, "PLATINUM": 100}
MIN_MILE_RATE = Decimal("0.5")

AWARD_CHART = {"ECONOMY": 25000, "BUSINESS": 60000, "FIRST": 100000}
COMPANION_ADDON_PCT = 50

TIER_THRESHOLDS = {"BASE": 0, "SILVER": 15, "GOLD": 30, "PLATINUM": 60}
TIER_RANK = {"BASE": 0, "SILVER": 1, "GOLD": 2, "PLATINUM": 3}
TIER_BY_RANK = {v: k for k, v in TIER_RANK.items()}

FARE_WEIGHT = {"DISCOUNT": 0, "ECONOMY": 10, "BUSINESS": 20, "FIRST": 30}

EXPIRY_MONTHS = 18

FARE_CLASSES = {"DISCOUNT", "ECONOMY", "BUSINESS", "FIRST"}
AWARD_CABINS = {"ECONOMY", "BUSINESS", "FIRST"}
PRICING_MODES = {"DYNAMIC", "FIXED"}
RIVAL_TIERS = {"SILVER", "GOLD", "PLATINUM"}

# ---------------------------------------------------------------------------
# Error catalogue (PRD §5)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_POOL_VERSION": 412,
    "ERR_STALE_MEMBER_VERSION": 412,
    "ERR_STATUS_MATCH_EXHAUSTED": 409,
    "ERR_CERTIFICATE_NOT_VALID": 422,
    "ERR_GIFT_TO_SELF": 422,
    "ERR_DEPARTURE_NOT_REACHED": 422,
    "ERR_LOAD_FACTOR_REQUIRED": 422,
    "ERR_POOL_ALREADY_CLEARED": 409,
    "ERR_INSUFFICIENT_POINTS": 422,
    "ERR_VALIDATION": 400,
    "ERR_GIFT_AMOUNT_INVALID": 422,
    "ERR_POOL_CAPACITY_INVALID": 400,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_PAGINATION_INVALID": 400,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http = ERROR_HTTP[error_id]
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.members = {}
        self.segments = {}
        self.awards = {}
        self.upgrades = {}
        self.pools = {}
        self.certs = {}
        self.gifts = {}
        self.matches = {}
        self.ledger = {}  # id -> row
        self.ledger_order = []  # ids in append order
        self.seq = 0  # monotonic creation sequence for created_at tie-breaks
        # logical clock
        self.clock_id = new_id()
        self.clock_current_utc = None  # not set until first advance
        self.clock_program_year = 0
        self.clock_created_at = now_iso()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


store = Store()


def next_seq():
    store.seq += 1
    return store.seq


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 instant; return aware datetime or None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    """Authoritative 'now' = logical clock; falls back to wall time if unset."""
    if store.clock_current_utc is not None:
        return store.clock_current_utc
    return datetime.now(timezone.utc)


def add_months(dt, months):
    """Add calendar months to an aware datetime."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to month length
    import calendar
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(extra=None):
    meta = {
        "api_request_id": getattr(g, "request_id", gen_request_id()),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200, pagination=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {
        "meta": make_meta(pagination),
        "response_type": rtype,
        "data": data,
    }
    return jsonify(body), status


@app.before_request
def _assign_request_id():
    g.request_id = gen_request_id()


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http


@app.errorhandler(404)
def _handle_404(_e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(_e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, §2.10)
# ---------------------------------------------------------------------------
def auth():
    """Validate identity headers. Returns (user_id, role). Raises 401."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid identity headers.")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def valid_iata(code):
    return isinstance(code, str) and bool(re.fullmatch(r"[A-Z]{3}", code))


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common record helpers
# ---------------------------------------------------------------------------
def base_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def strip(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_PAGINATION_INVALID", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_PAGINATION_INVALID", "limit out of bounds.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_PAGINATION_INVALID", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_PAGINATION_INVALID", "offset must be non-negative.")
    items_sorted = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items_sorted)
    window = items_sorted[offset:offset + limit]
    has_more = offset + limit < total
    pg = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return window, pg


# ---------------------------------------------------------------------------
# Ledger helpers (PRD §2.6)
# ---------------------------------------------------------------------------
def add_ledger(member_id, delta, reason, source_type, source_id=None, expires_at=None):
    row = {
        "id": new_id(),
        "created_at": now_iso(),
        "member_id": member_id,
        "delta": delta,
        "reason": reason,
        "source_type": source_type,
        "source_id": source_id,
        "expires_at": expires_at,
        "_seq": next_seq(),
        "_remaining": delta if delta > 0 else 0,  # tracked for expiry sweep
    }
    store.ledger[row["id"]] = row
    store.ledger_order.append(row["id"])
    return row


def ledger_view(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "member_id": row["member_id"],
        "delta": row["delta"],
        "reason": row["reason"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "expires_at": row["expires_at"],
    }


# ---------------------------------------------------------------------------
# Tier recomputation (PRD §3.4)
# ---------------------------------------------------------------------------
def earned_tier_for_count(count, prior_earned_rank):
    """Highest tier whose threshold is met; monotonic ratchet within program year."""
    rank = 0
    for tier, thr in TIER_THRESHOLDS.items():
        if count >= thr and TIER_RANK[tier] > rank:
            rank = TIER_RANK[tier]
    # monotonic: never lower than prior earned rank within program year
    rank = max(rank, prior_earned_rank)
    return rank


def tier_recompute(m, allow_lower=False):
    """Recompute earned tier (ratchet), match floor, effective tier."""
    prior = 0 if allow_lower else TIER_RANK.get(m["tier"], 0)
    earned_rank = earned_tier_for_count(m["qualifying_segments_ytd"], prior)
    m["tier"] = TIER_BY_RANK[earned_rank]
    match_floor_rank = TIER_RANK[m["matched_tier"]] if m["status_match_active"] else 0
    eff_rank = max(earned_rank, match_floor_rank)
    m["effective_tier"] = TIER_BY_RANK[eff_rank]


# ---------------------------------------------------------------------------
# Member serialization
# ---------------------------------------------------------------------------
def member_view(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "email": m["email"],
        "full_name": m["full_name"],
        "home_airport": m["home_airport"],
        "points_balance": m["points_balance"],
        "qualifying_segments_ytd": m["qualifying_segments_ytd"],
        "tier": m["tier"],
        "effective_tier": m["effective_tier"],
        "status_match_active": m["status_match_active"],
        "status_match_used": m["status_match_used"],
        "last_activity_at": m["last_activity_at"],
    }


def segment_view(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "member_id": s["member_id"], "origin": s["origin"],
        "destination": s["destination"], "fare_class": s["fare_class"],
        "distance_miles": s["distance_miles"], "base_fare_usd": s["base_fare_usd"],
        "scheduled_departure": s["scheduled_departure"], "status": s["status"],
        "is_qualifying": s["is_qualifying"], "points_awarded": s["points_awarded"],
    }


def award_view(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"], "member_id": a["member_id"], "route_code": a["route_code"],
        "cabin": a["cabin"], "pricing_mode": a["pricing_mode"], "load_factor": a["load_factor"],
        "points_price": a["points_price"],
        "companion_certificate_id": a["companion_certificate_id"], "status": a["status"],
    }


def upgrade_view(u):
    return {
        "id": u["id"], "created_at": u["created_at"], "updated_at": u["updated_at"],
        "version": u["version"], "member_id": u["member_id"],
        "flight_pool_id": u["flight_pool_id"], "requested_at": u["requested_at"],
        "booked_fare_class": u["booked_fare_class"],
        "priority_score": u["priority_score"], "status": u["status"],
    }


def pool_view(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "flight_number": p["flight_number"],
        "departure_at": p["departure_at"], "premium_capacity": p["premium_capacity"],
        "seats_cleared": p["seats_cleared"], "seats_remaining": p["seats_remaining"],
        "cleared": p["cleared"],
    }


def cert_view(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"], "member_id": c["member_id"], "valid_from": c["valid_from"],
        "valid_until": c["valid_until"], "status": c["status"],
        "attached_award_id": c["attached_award_id"],
    }


def gift_view(gf):
    return {
        "id": gf["id"], "created_at": gf["created_at"], "updated_at": gf["updated_at"],
        "version": gf["version"], "sender_id": gf["sender_id"],
        "recipient_id": gf["recipient_id"], "amount": gf["amount"], "status": gf["status"],
    }


def match_view(sm):
    return {
        "id": sm["id"], "created_at": sm["created_at"], "updated_at": sm["updated_at"],
        "version": sm["version"], "member_id": sm["member_id"], "rival_tier": sm["rival_tier"],
        "matched_tier": sm["matched_tier"], "valid_until": sm["valid_until"],
        "status": sm["status"],
    }


def clock_view():
    return {
        "id": store.clock_id,
        "created_at": store.clock_created_at,
        "current_utc": (store.clock_current_utc.strftime("%Y-%m-%dT%H:%M:%S.") +
                        f"{store.clock_current_utc.microsecond // 1000:03d}Z")
        if store.clock_current_utc is not None else None,
        "program_year": store.clock_program_year,
    }


# ---------------------------------------------------------------------------
# Lookup helpers (existence -> 404)
# ---------------------------------------------------------------------------
def get_member(mid):
    m = store.members.get(mid)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", "Member not found.")
    return m


def get_segment(sid):
    s = store.segments.get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", "Flight segment not found.")
    return s


def get_award(aid):
    a = store.awards.get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Award booking not found.")
    return a


def get_upgrade(uid):
    u = store.upgrades.get(uid)
    if u is None:
        raise ApiError("ERR_NOT_FOUND", "Upgrade request not found.")
    return u


def get_pool(pid):
    p = store.pools.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Flight pool not found.")
    return p


def get_cert(cid):
    c = store.certs.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "Companion certificate not found.")
    return c


def get_gift(gid):
    gf = store.gifts.get(gid)
    if gf is None:
        raise ApiError("ERR_NOT_FOUND", "Points gift not found.")
    return gf


def get_match(smid):
    sm = store.matches.get(smid)
    if sm is None:
        raise ApiError("ERR_NOT_FOUND", "Status match not found.")
    return sm


# ===========================================================================
# MEMBER ENDPOINTS
# ===========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    _uid, role = auth()
    require_role(role, {"ProgramAdmin"})
    data = body()
    email = data.get("email")
    full_name = data.get("full_name")
    home_airport = data.get("home_airport")

    if not isinstance(email, str) or email.strip() == "":
        raise ApiError("ERR_VALIDATION", "email is required and non-empty.")
    if not isinstance(full_name, str) or full_name.strip() == "":
        raise ApiError("ERR_VALIDATION", "full_name is required and non-empty.")
    if not valid_iata(home_airport):
        raise ApiError("ERR_VALIDATION", "home_airport must be 3 uppercase letters.")

    with _lock:
        for existing in store.members.values():
            if existing["email"] == email:
                raise ApiError("ERR_DUPLICATE_EMAIL", "Email already registered.")
        rec = base_record()
        rec.update({
            "email": email, "full_name": full_name, "home_airport": home_airport,
            "points_balance": 0, "qualifying_segments_ytd": 0,
            "tier": "BASE", "effective_tier": "BASE",
            "status_match_active": False, "status_match_used": False,
            "last_activity_at": None,
            "_program_year": store.clock_program_year,
        })
        store.members[rec["id"]] = rec
    return ok(member_view(rec), 201)


@app.route("/members/<mid>", methods=["GET"])
def fetch_member(mid):
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    m = get_member(mid)
    if role == "Member" and uid != m["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the resource owner.")
    return ok(member_view(m), 200)


@app.route("/members", methods=["GET"])
def list_members():
    _uid, role = auth()
    require_role(role, {"ProgramAdmin"})
    tier = request.args.get("tier")
    items = list(store.members.values())
    if tier is not None:
        items = [m for m in items if m["tier"] == tier]
    window, pg = paginate(items)
    return ok([member_view(m) for m in window], 200, pg)


@app.route("/members/<mid>/ledger", methods=["GET"])
def list_member_ledger(mid):
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    m = get_member(mid)
    if role == "Member" and uid != m["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the resource owner.")
    rows = [store.ledger[i] for i in store.ledger_order if store.ledger[i]["member_id"] == mid]
    window, pg = paginate(rows)
    return ok([ledger_view(r) for r in window], 200, pg)


@app.route("/members/<mid>/segments", methods=["GET"])
def list_member_segments(mid):
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    m = get_member(mid)
    if role == "Member" and uid != m["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the resource owner.")
    rows = [s for s in store.segments.values() if s["member_id"] == mid]
    window, pg = paginate(rows)
    return ok([segment_view(s) for s in window], 200, pg)


# ===========================================================================
# FLIGHT SEGMENT ENDPOINTS
# ===========================================================================
@app.route("/flight-segments", methods=["POST"])
def create_segment():
    _uid, role = auth()
    require_role(role, {"OperationsAgent"})
    data = body()
    member_id = data.get("member_id")
    origin = data.get("origin")
    destination = data.get("destination")
    fare_class = data.get("fare_class")
    distance_miles = data.get("distance_miles")
    base_fare_usd = data.get("base_fare_usd")
    scheduled_departure = data.get("scheduled_departure")

    # existence (FK) before domain validation per ordering
    if not isinstance(member_id, str):
        raise ApiError("ERR_VALIDATION", "member_id is required.")
    get_member(member_id)

    if not valid_iata(origin):
        raise ApiError("ERR_VALIDATION", "origin must be 3 uppercase letters.")
    if not valid_iata(destination):
        raise ApiError("ERR_VALIDATION", "destination must be 3 uppercase letters.")
    if destination == origin:
        raise ApiError("ERR_VALIDATION", "destination must differ from origin.")
    if fare_class not in FARE_CLASSES:
        raise ApiError("ERR_VALIDATION", "invalid fare_class.")
    if not is_int(distance_miles) or distance_miles < 1:
        raise ApiError("ERR_VALIDATION", "distance_miles must be an integer >= 1.")
    if not is_num(base_fare_usd) or base_fare_usd < 0:
        raise ApiError("ERR_VALIDATION", "base_fare_usd must be a number >= 0.")
    if parse_dt(scheduled_departure) is None:
        raise ApiError("ERR_VALIDATION", "scheduled_departure must be ISO 8601.")

    with _lock:
        rec = base_record()
        rec.update({
            "member_id": member_id, "origin": origin, "destination": destination,
            "fare_class": fare_class, "distance_miles": distance_miles,
            "base_fare_usd": base_fare_usd,
            "scheduled_departure": scheduled_departure,
            "status": "BOOKED", "is_qualifying": False, "points_awarded": 0,
        })
        store.segments[rec["id"]] = rec
    return ok(segment_view(rec), 201)


@app.route("/flight-segments/<sid>", methods=["GET"])
def fetch_segment(sid):
    _uid, role = auth()
    require_role(role, {"ProgramAdmin", "OperationsAgent", "Member"})
    s = get_segment(sid)
    return ok(segment_view(s), 200)


@app.route("/flight-segments/<sid>/fly", methods=["POST"])
def fly_segment(sid):
    _uid, role = auth()
    require_role(role, {"OperationsAgent"})
    with _lock:
        s = get_segment(sid)
        if s["status"] != "BOOKED":
            raise ApiError("ERR_INVALID_STATE", "Segment is not BOOKED.")
        dep = parse_dt(s["scheduled_departure"])
        if clock_now() < dep:
            raise ApiError("ERR_DEPARTURE_NOT_REACHED", "Departure not yet reached.")
        s["status"] = "FLOWN"
        touch(s)
    return ok(segment_view(s), 200)


@app.route("/flight-segments/<sid>/accrue", methods=["POST"])
def accrue_segment(sid):
    _uid, role = auth()
    require_role(role, {"OperationsAgent"})
    with _lock:
        s = get_segment(sid)
        if s["status"] != "FLOWN":
            raise ApiError("ERR_INVALID_STATE", "Segment is not FLOWN.")
        m = store.members.get(s["member_id"])
        if m is None:
            raise ApiError("ERR_NOT_FOUND", "Member not found.")

        # segment_accrual using member.effective_tier BEFORE this segment counts
        class_mult = FARE_CLASS_MULT[s["fare_class"]]
        tier_bonus_pct = TIER_BONUS_PCT[m["effective_tier"]]
        base_points = Decimal(str(s["base_fare_usd"])) * class_mult
        distance_floor = int((Decimal(s["distance_miles"]) * MIN_MILE_RATE)
                             .to_integral_value(rounding=ROUND_CEILING))
        earned = max(base_points, Decimal(distance_floor))
        points_awarded = round_half_up(earned * (Decimal(1) + Decimal(tier_bonus_pct) / Decimal(100)))

        s["points_awarded"] = points_awarded
        s["is_qualifying"] = (s["fare_class"] != "DISCOUNT")
        s["status"] = "ACCRUED"
        touch(s)

        now = clock_now()
        exp = add_months(now, EXPIRY_MONTHS)
        add_ledger(m["id"], points_awarded, "ACCRUAL", "FlightSegment",
                   source_id=s["id"], expires_at=iso_z(exp))
        m["points_balance"] += points_awarded
        m["last_activity_at"] = iso_z(now)
        if s["is_qualifying"]:
            m["qualifying_segments_ytd"] += 1
            tier_recompute(m)
        touch(m)
    return ok(segment_view(s), 200)


@app.route("/flight-segments/<sid>/cancel", methods=["POST"])
def cancel_segment(sid):
    _uid, role = auth()
    require_role(role, {"OperationsAgent"})
    with _lock:
        s = get_segment(sid)
        if s["status"] != "BOOKED":
            raise ApiError("ERR_INVALID_STATE", "Only BOOKED segments may be cancelled.")
        s["status"] = "CANCELLED"
        touch(s)
    return ok(segment_view(s), 200)


def iso_z(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ===========================================================================
# AWARD BOOKING ENDPOINTS
# ===========================================================================
@app.route("/award-bookings", methods=["POST"])
def create_award():
    uid, role = auth()
    require_role(role, {"Member"})
    data = body()
    member_id = data.get("member_id")
    route_code = data.get("route_code")
    cabin = data.get("cabin")
    pricing_mode = data.get("pricing_mode")
    load_factor = data.get("load_factor", None)
    cert_id = data.get("companion_certificate_id", None)

    # ownership (member acting on own): X-User-ID must equal member_id
    if not isinstance(member_id, str):
        raise ApiError("ERR_VALIDATION", "member_id is required.")
    if uid != member_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Member may only act on own resources.")
    # existence
    m = get_member(member_id)
    cert = None
    if cert_id is not None:
        cert = get_cert(cert_id)

    # state precedence is N/A on create; OCC N/A; business rules:
    # certificate validity (priority 8) before load_factor (priority 11)
    # but field-domain validation (priority 14) is the final fallback.
    # We validate enums/route as domain checks; certificate & load_factor are
    # specific business rules ordered ahead of generic ERR_VALIDATION.

    if not isinstance(route_code, str) or route_code.strip() == "":
        raise ApiError("ERR_VALIDATION", "route_code is required and non-empty.")
    if cabin not in AWARD_CABINS:
        raise ApiError("ERR_VALIDATION", "invalid cabin.")
    if pricing_mode not in PRICING_MODES:
        raise ApiError("ERR_VALIDATION", "invalid pricing_mode.")

    # companion certificate validity (priority 8)
    if cert is not None:
        if cert["member_id"] != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Certificate not owned by member.")
        if cert["status"] != "ISSUED":
            raise ApiError("ERR_CERTIFICATE_NOT_VALID", "Certificate is not ISSUED.")
        vf = parse_dt(cert["valid_from"])
        vu = parse_dt(cert["valid_until"])
        now = clock_now()
        if not (vf <= now <= vu):
            raise ApiError("ERR_CERTIFICATE_NOT_VALID",
                           "Current instant outside certificate validity window.")

    # load_factor (priority 11)
    if pricing_mode == "DYNAMIC":
        if not is_num(load_factor):
            raise ApiError("ERR_LOAD_FACTOR_REQUIRED", "DYNAMIC requires load_factor.")
        if load_factor < 0 or load_factor > 1:
            raise ApiError("ERR_LOAD_FACTOR_REQUIRED", "load_factor must be in [0,1].")
    else:  # FIXED
        if load_factor is not None:
            raise ApiError("ERR_LOAD_FACTOR_REQUIRED", "FIXED must omit load_factor.")

    # award_pricing
    base_chart = AWARD_CHART[cabin]
    if pricing_mode == "FIXED":
        cabin_price = base_chart
    else:
        cabin_price = round_half_up(
            Decimal(base_chart) * (Decimal("0.8") + Decimal("0.8") * Decimal(str(load_factor)))
        )
    if cert is not None:
        companion_addon = round_half_up(Decimal(cabin_price) * Decimal(COMPANION_ADDON_PCT) / Decimal(100))
    else:
        companion_addon = 0
    points_price = cabin_price + companion_addon

    with _lock:
        rec = base_record()
        rec.update({
            "member_id": member_id, "route_code": route_code, "cabin": cabin,
            "pricing_mode": pricing_mode, "load_factor": load_factor,
            "points_price": points_price, "companion_certificate_id": cert_id,
            "status": "QUOTED",
        })
        store.awards[rec["id"]] = rec
        if cert is not None:
            cert["status"] = "RESERVED"
            cert["attached_award_id"] = rec["id"]
            touch(cert)
    return ok(award_view(rec), 201)


@app.route("/award-bookings/<aid>", methods=["GET"])
def fetch_award(aid):
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    a = get_award(aid)
    if role == "Member" and uid != a["member_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the resource owner.")
    return ok(award_view(a), 200)


@app.route("/award-bookings", methods=["GET"])
def list_awards():
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    items = list(store.awards.values())
    member_id = request.args.get("member_id")
    cert_id = request.args.get("companion_certificate_id")
    if role == "Member":
        items = [a for a in items if a["member_id"] == uid]
    if member_id is not None:
        items = [a for a in items if a["member_id"] == member_id]
    if cert_id is not None:
        items = [a for a in items if a["companion_certificate_id"] == cert_id]
    window, pg = paginate(items)
    return ok([award_view(a) for a in window], 200, pg)


@app.route("/award-bookings/<aid>/issue", methods=["POST"])
def issue_award(aid):
    uid, role = auth()
    require_role(role, {"Member"})
    with _lock:
        a = get_award(aid)
        if uid != a["member_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the resource owner.")
        if a["status"] != "QUOTED":
            raise ApiError("ERR_INVALID_STATE", "Award is not QUOTED.")
        m = store.members.get(a["member_id"])
        if m is None:
            raise ApiError("ERR_NOT_FOUND", "Member not found.")
        if m["points_balance"] < a["points_price"]:
            raise ApiError("ERR_INSUFFICIENT_POINTS", "Insufficient points.")

        now = clock_now()
        add_ledger(m["id"], -a["points_price"], "REDEMPTION", "AwardBooking", source_id=a["id"])
        m["points_balance"] -= a["points_price"]
        m["last_activity_at"] = iso_z(now)
        touch(m)

        if a["companion_certificate_id"]:
            cert = store.certs.get(a["companion_certificate_id"])
            if cert is not None and cert["status"] == "RESERVED":
                cert["status"] = "REDEEMED"
                touch(cert)

        a["status"] = "ISSUED"
        touch(a)
    return ok(award_view(a), 200)


@app.route("/award-bookings/<aid>/cancel", methods=["POST"])
def cancel_award(aid):
    uid, role = auth()
    require_role(role, {"Member"})
    with _lock:
        a = get_award(aid)
        if uid != a["member_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the resource owner.")
        if a["status"] not in ("QUOTED", "ISSUED"):
            raise ApiError("ERR_INVALID_STATE", "Award not cancellable from current state.")

        if a["status"] == "QUOTED":
            # no refund; release cert RESERVED -> ISSUED
            if a["companion_certificate_id"]:
                cert = store.certs.get(a["companion_certificate_id"])
                if cert is not None and cert["status"] == "RESERVED":
                    cert["status"] = "ISSUED"
                    cert["attached_award_id"] = None
                    touch(cert)
            a["status"] = "CANCELLED"
            touch(a)
        else:  # ISSUED
            m = store.members.get(a["member_id"])
            now = clock_now()
            add_ledger(m["id"], a["points_price"], "REDEMPTION_REFUND", "AwardBooking",
                       source_id=a["id"])
            m["points_balance"] += a["points_price"]
            m["last_activity_at"] = iso_z(now)
            touch(m)
            if a["companion_certificate_id"]:
                cert = store.certs.get(a["companion_certificate_id"])
                if cert is not None and cert["status"] == "REDEEMED":
                    cert["status"] = "ISSUED"
                    cert["attached_award_id"] = None
                    touch(cert)
            a["status"] = "CANCELLED"
            touch(a)
    return ok(award_view(a), 200)


@app.route("/award-bookings/<aid>/fly", methods=["POST"])
def fly_award(aid):
    _uid, role = auth()
    require_role(role, {"OperationsAgent"})
    with _lock:
        a = get_award(aid)
        if a["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", "Award is not ISSUED.")
        a["status"] = "FLOWN"
        touch(a)
    return ok(award_view(a), 200)


# ===========================================================================
# FLIGHT POOL & UPGRADE ENDPOINTS
# ===========================================================================
@app.route("/flight-pools", methods=["POST"])
def create_pool():
    _uid, role = auth()
    require_role(role, {"OperationsAgent"})
    data = body()
    flight_number = data.get("flight_number")
    departure_at = data.get("departure_at")
    premium_capacity = data.get("premium_capacity")

    if not isinstance(flight_number, str) or flight_number.strip() == "":
        raise ApiError("ERR_VALIDATION", "flight_number is required.")
    if parse_dt(departure_at) is None:
        raise ApiError("ERR_VALIDATION", "departure_at must be ISO 8601.")
    if not is_int(premium_capacity):
        raise ApiError("ERR_VALIDATION", "premium_capacity must be an integer.")
    if premium_capacity < 0:
        raise ApiError("ERR_POOL_CAPACITY_INVALID", "premium_capacity must be non-negative.")

    with _lock:
        rec = base_record()
        rec.update({
            "flight_number": flight_number, "departure_at": departure_at,
            "premium_capacity": premium_capacity, "seats_cleared": 0,
            "seats_remaining": premium_capacity, "cleared": False,
        })
        store.pools[rec["id"]] = rec
    return ok(pool_view(rec), 201)


@app.route("/flight-pools/<pid>", methods=["GET"])
def fetch_pool(pid):
    _uid, role = auth()
    require_role(role, {"ProgramAdmin", "OperationsAgent", "Member"})
    p = get_pool(pid)
    return ok(pool_view(p), 200)


@app.route("/flight-pools/<pid>/upgrade-requests", methods=["GET"])
def list_pool_upgrades(pid):
    _uid, role = auth()
    require_role(role, {"ProgramAdmin", "OperationsAgent", "Member"})
    get_pool(pid)
    items = [u for u in store.upgrades.values() if u["flight_pool_id"] == pid]
    window, pg = paginate(items)
    return ok([upgrade_view(u) for u in window], 200, pg)


@app.route("/upgrade-requests", methods=["POST"])
def create_upgrade():
    uid, role = auth()
    require_role(role, {"Member"})
    data = body()
    member_id = data.get("member_id")
    flight_pool_id = data.get("flight_pool_id")
    booked_fare_class = data.get("booked_fare_class")
    expected_version = data.get("expected_flightpool_version")

    if not isinstance(member_id, str):
        raise ApiError("ERR_VALIDATION", "member_id is required.")
    if uid != member_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Member may only act on own resources.")
    m = get_member(member_id)
    if not isinstance(flight_pool_id, str):
        raise ApiError("ERR_VALIDATION", "flight_pool_id is required.")
    pool = get_pool(flight_pool_id)

    # OCC (priority 6) before remaining business/domain checks
    if is_int(expected_version):
        if expected_version != pool["version"]:
            raise ApiError("ERR_STALE_POOL_VERSION", "Pool version is stale.")
    elif expected_version is not None:
        raise ApiError("ERR_VALIDATION", "expected_flightpool_version must be an integer.")

    if booked_fare_class not in FARE_CLASSES:
        raise ApiError("ERR_VALIDATION", "invalid booked_fare_class.")

    priority_score = TIER_RANK[m["effective_tier"]] * 1000 + FARE_WEIGHT[booked_fare_class]

    with _lock:
        rec = base_record()
        rec.update({
            "member_id": member_id, "flight_pool_id": flight_pool_id,
            "requested_at": now_iso(), "booked_fare_class": booked_fare_class,
            "priority_score": priority_score, "status": "WAITLISTED",
        })
        store.upgrades[rec["id"]] = rec
        touch(pool)  # joining increments pool version
    return ok(upgrade_view(rec), 201)


@app.route("/upgrade-requests/<uid_>", methods=["GET"])
def fetch_upgrade(uid_):
    _uid, role = auth()
    require_role(role, {"ProgramAdmin", "OperationsAgent", "Member"})
    u = get_upgrade(uid_)
    return ok(upgrade_view(u), 200)


@app.route("/upgrade-requests", methods=["GET"])
def list_upgrades():
    _uid, role = auth()
    require_role(role, {"ProgramAdmin", "OperationsAgent", "Member"})
    items = list(store.upgrades.values())
    member_id = request.args.get("member_id")
    flight_pool_id = request.args.get("flight_pool_id")
    if member_id is not None:
        items = [u for u in items if u["member_id"] == member_id]
    if flight_pool_id is not None:
        items = [u for u in items if u["flight_pool_id"] == flight_pool_id]
    window, pg = paginate(items)
    return ok([upgrade_view(u) for u in window], 200, pg)


@app.route("/upgrade-requests/<uid_>/withdraw", methods=["POST"])
def withdraw_upgrade(uid_):
    uid, role = auth()
    require_role(role, {"Member"})
    with _lock:
        u = get_upgrade(uid_)
        if uid != u["member_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the resource owner.")
        if u["status"] != "WAITLISTED":
            raise ApiError("ERR_INVALID_STATE", "Request is not WAITLISTED.")
        pool = store.pools.get(u["flight_pool_id"])
        if pool is not None and pool["cleared"]:
            raise ApiError("ERR_INVALID_STATE", "Pool already cleared.")
        u["status"] = "WITHDRAWN"
        touch(u)
    return ok(upgrade_view(u), 200)


@app.route("/flight-pools/<pid>/clear-waitlist", methods=["POST"])
def clear_waitlist(pid):
    _uid, role = auth()
    require_role(role, {"OperationsAgent"})
    with _lock:
        pool = get_pool(pid)
        if pool["cleared"]:
            raise ApiError("ERR_POOL_ALREADY_CLEARED", "Pool already cleared.")
        if clock_now() < parse_dt(pool["departure_at"]):
            raise ApiError("ERR_POOL_ALREADY_CLEARED", "Clearing before departure.")

        waitlisted = [u for u in store.upgrades.values()
                      if u["flight_pool_id"] == pid and u["status"] == "WAITLISTED"]
        # sort: priority_score desc, requested_at asc, created_at asc
        waitlisted.sort(key=lambda u: (-u["priority_score"], u["requested_at"],
                                       u["created_at"], u["_seq"]))
        for u in waitlisted:
            if pool["seats_remaining"] > 0:
                u["status"] = "CLEARED"
                pool["seats_cleared"] += 1
                pool["seats_remaining"] -= 1
            else:
                u["status"] = "DENIED"
            touch(u)
        pool["cleared"] = True
        touch(pool)
    return ok(pool_view(pool), 200)


# ===========================================================================
# COMPANION CERTIFICATE ENDPOINTS
# ===========================================================================
@app.route("/companion-certificates", methods=["POST"])
def create_cert():
    _uid, role = auth()
    require_role(role, {"ProgramAdmin"})
    data = body()
    member_id = data.get("member_id")
    valid_from = data.get("valid_from")
    valid_until = data.get("valid_until")

    if not isinstance(member_id, str):
        raise ApiError("ERR_VALIDATION", "member_id is required.")
    get_member(member_id)
    vf = parse_dt(valid_from)
    vu = parse_dt(valid_until)
    if vf is None or vu is None:
        raise ApiError("ERR_VALIDATION", "valid_from/valid_until must be ISO 8601.")
    if not (vu > vf):
        raise ApiError("ERR_VALIDATION", "valid_until must be after valid_from.")

    with _lock:
        rec = base_record()
        rec.update({
            "member_id": member_id, "valid_from": valid_from, "valid_until": valid_until,
            "status": "ISSUED", "attached_award_id": None,
        })
        store.certs[rec["id"]] = rec
    return ok(cert_view(rec), 201)


@app.route("/companion-certificates/<cid>", methods=["GET"])
def fetch_cert(cid):
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    c = get_cert(cid)
    if role == "Member" and uid != c["member_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the resource owner.")
    return ok(cert_view(c), 200)


@app.route("/companion-certificates", methods=["GET"])
def list_certs():
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    items = list(store.certs.values())
    member_id = request.args.get("member_id")
    attached_award_id = request.args.get("attached_award_id")
    if role == "Member":
        items = [c for c in items if c["member_id"] == uid]
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if attached_award_id is not None:
        items = [c for c in items if c["attached_award_id"] == attached_award_id]
    window, pg = paginate(items)
    return ok([cert_view(c) for c in window], 200, pg)


# ===========================================================================
# POINTS GIFT ENDPOINTS
# ===========================================================================
@app.route("/points-gifts", methods=["POST"])
def create_gift():
    uid, role = auth()
    require_role(role, {"Member"})
    data = body()
    sender_id = data.get("sender_id")
    recipient_id = data.get("recipient_id")
    amount = data.get("amount")

    if not isinstance(sender_id, str):
        raise ApiError("ERR_VALIDATION", "sender_id is required.")
    if uid != sender_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Member may only gift as themselves.")
    get_member(sender_id)
    if not isinstance(recipient_id, str):
        raise ApiError("ERR_VALIDATION", "recipient_id is required.")
    get_member(recipient_id)

    if recipient_id == sender_id:
        raise ApiError("ERR_GIFT_TO_SELF", "Recipient must differ from sender.")
    if not is_int(amount) or amount < 1:
        raise ApiError("ERR_GIFT_AMOUNT_INVALID", "amount must be an integer >= 1.")

    with _lock:
        rec = base_record()
        rec.update({
            "sender_id": sender_id, "recipient_id": recipient_id, "amount": amount,
            "status": "PENDING",
        })
        store.gifts[rec["id"]] = rec
    return ok(gift_view(rec), 201)


@app.route("/points-gifts/<gid>", methods=["GET"])
def fetch_gift(gid):
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    gf = get_gift(gid)
    if role == "Member" and uid not in (gf["sender_id"], gf["recipient_id"]):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not party to this gift.")
    return ok(gift_view(gf), 200)


@app.route("/points-gifts", methods=["GET"])
def list_gifts():
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    items = list(store.gifts.values())
    sender_id = request.args.get("sender_id")
    recipient_id = request.args.get("recipient_id")
    if role == "Member":
        items = [g_ for g_ in items if uid in (g_["sender_id"], g_["recipient_id"])]
    if sender_id is not None:
        items = [g_ for g_ in items if g_["sender_id"] == sender_id]
    if recipient_id is not None:
        items = [g_ for g_ in items if g_["recipient_id"] == recipient_id]
    window, pg = paginate(items)
    return ok([gift_view(g_) for g_ in window], 200, pg)


@app.route("/points-gifts/<gid>/settle", methods=["POST"])
def settle_gift(gid):
    uid, role = auth()
    require_role(role, {"Member"})
    data = body()
    expected_version = data.get("expected_member_version")
    with _lock:
        gf = get_gift(gid)
        if uid != gf["sender_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the sender may settle.")
        if gf["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Gift is not PENDING.")
        sender = store.members.get(gf["sender_id"])
        recipient = store.members.get(gf["recipient_id"])
        if sender is None or recipient is None:
            raise ApiError("ERR_NOT_FOUND", "Member not found.")

        # OCC (priority 6)
        if is_int(expected_version):
            if expected_version != sender["version"]:
                raise ApiError("ERR_STALE_MEMBER_VERSION", "Sender version is stale.")
        elif expected_version is not None:
            raise ApiError("ERR_VALIDATION", "expected_member_version must be an integer.")

        if sender["points_balance"] < gf["amount"]:
            raise ApiError("ERR_INSUFFICIENT_POINTS", "Insufficient sender points.")

        now = clock_now()
        add_ledger(sender["id"], -gf["amount"], "GIFT_OUT", "PointsGift", source_id=gf["id"])
        sender["points_balance"] -= gf["amount"]
        sender["last_activity_at"] = iso_z(now)
        touch(sender)

        exp = add_months(now, EXPIRY_MONTHS)
        add_ledger(recipient["id"], gf["amount"], "GIFT_IN", "PointsGift",
                   source_id=gf["id"], expires_at=iso_z(exp))
        recipient["points_balance"] += gf["amount"]
        recipient["last_activity_at"] = iso_z(now)
        touch(recipient)

        gf["status"] = "SETTLED"
        touch(gf)
    return ok(gift_view(gf), 200)


@app.route("/points-gifts/<gid>/reverse", methods=["POST"])
def reverse_gift(gid):
    uid, role = auth()
    require_role(role, {"Member"})
    with _lock:
        gf = get_gift(gid)
        if uid != gf["sender_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the sender may reverse.")
        if gf["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Gift is not PENDING.")
        gf["status"] = "REVERSED"
        touch(gf)
    return ok(gift_view(gf), 200)


# ===========================================================================
# STATUS MATCH ENDPOINTS
# ===========================================================================
@app.route("/status-matches", methods=["POST"])
def create_match():
    _uid, role = auth()
    require_role(role, {"ProgramAdmin"})
    data = body()
    member_id = data.get("member_id")
    rival_tier = data.get("rival_tier")
    valid_until = data.get("valid_until")

    if not isinstance(member_id, str):
        raise ApiError("ERR_VALIDATION", "member_id is required.")
    m = get_member(member_id)

    # state precedence: lifetime exhaustion (priority 7) before domain validation
    if m["status_match_used"]:
        raise ApiError("ERR_STATUS_MATCH_EXHAUSTED", "Lifetime status match used.")

    if rival_tier not in RIVAL_TIERS:
        raise ApiError("ERR_VALIDATION", "invalid rival_tier.")
    if parse_dt(valid_until) is None:
        raise ApiError("ERR_VALIDATION", "valid_until must be ISO 8601.")

    # matched_tier = one rung below rival_tier
    matched_rank = TIER_RANK[rival_tier] - 1
    matched_tier = TIER_BY_RANK[matched_rank]

    with _lock:
        rec = base_record()
        rec.update({
            "member_id": member_id, "rival_tier": rival_tier, "matched_tier": matched_tier,
            "valid_until": valid_until, "status": "GRANTED",
        })
        store.matches[rec["id"]] = rec
        m["matched_tier"] = matched_tier
        m["status_match_active"] = True
        m["status_match_used"] = True
        tier_recompute(m)
        touch(m)
    return ok(match_view(rec), 201)


@app.route("/status-matches/<smid>", methods=["GET"])
def fetch_match(smid):
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    sm = get_match(smid)
    if role == "Member" and uid != sm["member_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the resource owner.")
    return ok(match_view(sm), 200)


@app.route("/status-matches", methods=["GET"])
def list_matches():
    uid, role = auth()
    require_role(role, {"ProgramAdmin", "Member"})
    items = list(store.matches.values())
    member_id = request.args.get("member_id")
    if role == "Member":
        items = [sm for sm in items if sm["member_id"] == uid]
    if member_id is not None:
        items = [sm for sm in items if sm["member_id"] == member_id]
    window, pg = paginate(items)
    return ok([match_view(sm) for sm in window], 200, pg)


# ===========================================================================
# CLOCK & INJECTION ENDPOINTS
# ===========================================================================
@app.route("/_clock/advance", methods=["POST"])
def clock_advance():
    _uid, role = auth()
    require_role(role, {"ProgramAdmin"})
    data = body()
    current_utc = data.get("current_utc")
    new_now = parse_dt(current_utc)
    if new_now is None:
        raise ApiError("ERR_VALIDATION", "current_utc must be ISO 8601 UTC.")

    with _lock:
        store.clock_current_utc = new_now
        store.clock_program_year = new_now.year
        now = new_now

        # Sweep 1: points expiration
        for m in store.members.values():
            if m["last_activity_at"] is None:
                continue
            last = parse_dt(m["last_activity_at"])
            if last is None:
                continue
            # inactive beyond 18 months?
            threshold = add_months(last, EXPIRY_MONTHS)
            if now <= threshold:
                continue
            # expire positive lots with expires_at <= now, oldest first
            lots = []
            for lid in store.ledger_order:
                r = store.ledger[lid]
                if r["member_id"] != m["id"]:
                    continue
                if r["_remaining"] <= 0 or r["expires_at"] is None:
                    continue
                exp = parse_dt(r["expires_at"])
                if exp is not None and exp <= now:
                    lots.append(r)
            lots.sort(key=lambda r: (r["expires_at"], r["_seq"]))
            for lot in lots:
                if m["points_balance"] <= 0:
                    break
                burn = min(lot["_remaining"], m["points_balance"])
                if burn <= 0:
                    continue
                add_ledger(m["id"], -burn, "EXPIRY", "System", source_id=None)
                m["points_balance"] -= burn
                lot["_remaining"] -= burn
            touch(m)

        # Sweep 2: status-match expiration + companion certificate expiration
        for sm in store.matches.values():
            if sm["status"] == "GRANTED":
                vu = parse_dt(sm["valid_until"])
                if vu is not None and now > vu:
                    sm["status"] = "EXPIRED"
                    touch(sm)
                    m = store.members.get(sm["member_id"])
                    if m is not None:
                        m["status_match_active"] = False
                        tier_recompute(m)
                        touch(m)
        for c in store.certs.values():
            if c["status"] == "ISSUED":
                vu = parse_dt(c["valid_until"])
                if vu is not None and now > vu:
                    c["status"] = "EXPIRED"
                    touch(c)

        # Sweep 3: year-end run
        for m in store.members.values():
            if store.clock_program_year > m["_program_year"]:
                m["qualifying_segments_ytd"] = 0
                m["_program_year"] = store.clock_program_year
                tier_recompute(m, allow_lower=True)
                touch(m)

    return ok(clock_view(), 200)


@app.route("/_clock", methods=["GET"])
def clock_read():
    _uid, role = auth()
    require_role(role, {"ProgramAdmin", "OperationsAgent", "Member"})
    return ok(clock_view(), 200)


@app.route("/_inject/points", methods=["POST"])
def inject_points():
    _uid, role = auth()
    require_role(role, {"ProgramAdmin"})
    data = body()
    member_id = data.get("member_id")
    amount = data.get("amount")
    if not isinstance(member_id, str):
        raise ApiError("ERR_VALIDATION", "member_id is required.")
    m = get_member(member_id)
    if not is_int(amount) or amount < 1:
        raise ApiError("ERR_VALIDATION", "amount must be an integer >= 1.")
    with _lock:
        now = clock_now()
        exp = add_months(now, EXPIRY_MONTHS)
        add_ledger(m["id"], amount, "ACCRUAL", "System", source_id=None, expires_at=iso_z(exp))
        m["points_balance"] += amount
        m["last_activity_at"] = iso_z(now)
        touch(m)
    return ok(member_view(m), 200)


@app.route("/_inject/qualifying_segments", methods=["POST"])
def inject_segments():
    _uid, role = auth()
    require_role(role, {"ProgramAdmin"})
    data = body()
    member_id = data.get("member_id")
    count = data.get("count")
    if not isinstance(member_id, str):
        raise ApiError("ERR_VALIDATION", "member_id is required.")
    m = get_member(member_id)
    if not is_int(count) or count < 0:
        raise ApiError("ERR_VALIDATION", "count must be a non-negative integer.")
    with _lock:
        m["qualifying_segments_ytd"] = count
        tier_recompute(m)
        touch(m)
    return ok(member_view(m), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
