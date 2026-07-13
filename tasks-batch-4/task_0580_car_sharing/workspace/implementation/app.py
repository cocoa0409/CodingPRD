"""
Peer-to-Peer Car Sharing API (Turo/Getaround style).

In-memory REST API server implemented with Flask.  The store starts EMPTY on
every boot; every entity is created by clients through the declared endpoints.
All money is integer cents.  Time-of-day reasoning uses a server-controlled
logical clock (default 2026-05-01T00:00:00Z) that a PlatformAdmin may advance.
"""

import json
import math
import os
import random
import string
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_FLOOR

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# In-memory store (empty on boot; keyed by id)
# ---------------------------------------------------------------------------
hosts = {}
guests = {}
plans = {}
vehicles = {}
blocks = {}
pricing_rules = {}
trips = {}
inspections = {}
claims = {}
extensions = {}
payouts = {}

_SEQ = 0

# Logical clock (raw string as supplied + parsed aware datetime for math)
CLOCK = {"raw": "2026-05-01T00:00:00Z",
         "dt": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_ROLES = {"Anonymous", "Host", "Guest", "PlatformAdmin"}
READ_ROLES = {"Host", "Guest", "PlatformAdmin"}

WEEKLY_THRESHOLD_NIGHTS = 7
MONTHLY_THRESHOLD_NIGHTS = 28
MAX_TRIP_NIGHTS = 90
MIN_PAYOUT_CENTS = 5000
MILEAGE_OVERAGE_RATE_CENTS = 50
FUEL_CHARGE_PER_PCT_CENTS = 500
LATE_FEE_MULTIPLIER = Decimal("1.5")
GRACE_SECONDS = 2 * 3600
AT_FAULT_WEIGHT = 20
LATE_WEIGHT = 5
MAX_SCORE = 100

TRIP_TERMINAL = {"COMPLETED", "CANCELLED", "DECLINED"}
CLAIM_TERMINAL = {"DENIED", "SETTLED"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def randstr(n):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def dfloor(dec):
    return int(dec.to_integral_value(rounding=ROUND_FLOOR))


def parse_date(s):
    return date.fromisoformat(s)


def date_range(start, end):
    d = parse_date(start)
    e = parse_date(end)
    while d < e:
        yield d
        d += timedelta(days=1)


def days_between(a, b):
    return (parse_date(b) - parse_date(a)).days


def parse_instant(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 400, "Invalid instant")
    t = s.strip()
    t2 = t[:-1] + "+00:00" if t.endswith("Z") else t
    try:
        dt = datetime.fromisoformat(t2)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Invalid ISO8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_common():
    ts = now_iso()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def touch(obj):
    obj["updated_at"] = now_iso()
    obj["version"] += 1


def pub(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Request / body helpers
# ---------------------------------------------------------------------------
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADER", 400,
                       "X-User-ID and X-User-Role headers required")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def body_json():
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Malformed JSON body")
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return data


def need_str(b, k):
    v = b.get(k)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, "Missing/invalid field: %s" % k)
    return v


def need_int(b, k):
    v = b.get(k)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "Missing/invalid integer field: %s" % k)
    return v


def need_num(b, k):
    v = b.get(k)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, "Missing/invalid numeric field: %s" % k)
    return v


def need_date(b, k):
    v = need_str(b, k)
    try:
        parse_date(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Invalid date field: %s" % k)
    return v


def opt_int(b, k, default=None):
    if k not in b or b[k] is None:
        return default
    return need_int(b, k)


def opt_num(b, k, default=None):
    if k not in b or b[k] is None:
        return default
    return need_num(b, k)


def opt_str(b, k, default=None):
    if k not in b or b[k] is None:
        return default
    v = b[k]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, "Invalid string field: %s" % k)
    return v


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {"api_request_id": "req_" + randstr(20),
         "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def respond(data, status=200, is_array=False, pagination=None):
    body = {"meta": _meta(pagination),
            "response_type": "array" if is_array else "object",
            "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {"meta": _meta(),
            "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


@app.errorhandler(Exception)
def handle_uncaught(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    # Route-not-found / method-not-allowed keep their werkzeug status
    code = getattr(err, "code", 500)
    body = {"meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)}}
    return jsonify(body), code if isinstance(code, int) else 500


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_host(hid):
    o = hosts.get(hid)
    if o is None:
        raise ApiError("ERR_HOST_NOT_FOUND", 404, "Host not found")
    return o


def get_guest(gid):
    o = guests.get(gid)
    if o is None:
        raise ApiError("ERR_GUEST_NOT_FOUND", 404, "Guest not found")
    return o


def get_plan(pid):
    o = plans.get(pid)
    if o is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", 404, "Protection plan not found")
    return o


def get_vehicle(vid):
    o = vehicles.get(vid)
    if o is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND", 404, "Vehicle not found")
    return o


def get_block(bid):
    o = blocks.get(bid)
    if o is None:
        raise ApiError("ERR_BLOCK_NOT_FOUND", 404, "Availability block not found")
    return o


def get_pricing_rule(rid):
    o = pricing_rules.get(rid)
    if o is None:
        raise ApiError("ERR_PRICING_RULE_NOT_FOUND", 404, "Pricing rule not found")
    return o


def get_trip(tid):
    o = trips.get(tid)
    if o is None:
        raise ApiError("ERR_TRIP_NOT_FOUND", 404, "Trip not found")
    return o


def get_claim(cid):
    o = claims.get(cid)
    if o is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Claim not found")
    return o


def get_extension(eid):
    o = extensions.get(eid)
    if o is None:
        raise ApiError("ERR_EXTENSION_NOT_FOUND", 404, "Extension not found")
    return o


def get_payout(pid):
    o = payouts.get(pid)
    if o is None:
        raise ApiError("ERR_PAYOUT_NOT_FOUND", 404, "Payout not found")
    return o


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def price_for(veh, d):
    """Nightly price for date d: covering ACTIVE pricing rule (closed interval)
    else vehicle base price."""
    for r in pricing_rules.values():
        if r["vehicle_id"] == veh["id"] and r["status"] == "ACTIVE":
            if parse_date(r["start_date"]) <= d <= parse_date(r["end_date"]):
                return r["daily_price_cents"]
    return veh["base_daily_price_cents"]


def compute_estimate(veh, plan, start, end):
    nights = days_between(start, end)
    subtotal = 0
    for d in date_range(start, end):
        subtotal += price_for(veh, d)
    if nights >= MONTHLY_THRESHOLD_NIGHTS:
        disc = veh["monthly_discount_pct"]
    elif nights >= WEEKLY_THRESHOLD_NIGHTS:
        disc = veh["weekly_discount_pct"]
    else:
        disc = 0
    discounted = dfloor(Decimal(subtotal) * (Decimal(1) - Decimal(str(disc))))
    premium = plan["daily_premium_cents"] * nights
    total = discounted + premium
    host_earn = dfloor(Decimal(discounted) * Decimal(str(plan["host_earnings_pct"])))
    return {
        "nights": nights,
        "discounted_subtotal_cents": discounted,
        "protection_premium_cents": premium,
        "estimated_total_cents": total,
        "estimated_host_earnings_cents": host_earn,
        "deductible_snapshot_cents": plan["deductible_cents"],
    }


def overlaps_booked(veh_id, start, end, exclude_block_id=None):
    s = parse_date(start)
    e = parse_date(end)
    for blk in blocks.values():
        if blk["vehicle_id"] != veh_id:
            continue
        if blk["block_type"] != "BOOKED" or blk["status"] != "ACTIVE":
            continue
        if exclude_block_id and blk["id"] == exclude_block_id:
            continue
        bs = parse_date(blk["start_date"])
        be = parse_date(blk["end_date"])
        if s < be and bs < e:  # half-open overlap
            return True
    return False


def pricing_overlap(vehicle_id, start, end):
    s = parse_date(start)
    e = parse_date(end)
    for r in pricing_rules.values():
        if r["vehicle_id"] != vehicle_id or r["status"] != "ACTIVE":
            continue
        rs = parse_date(r["start_date"])
        re_ = parse_date(r["end_date"])
        if s <= re_ and rs <= e:  # closed-interval overlap
            return True
    return False


def find_booked_block(trip_id):
    for blk in blocks.values():
        if blk.get("trip_id") == trip_id and blk["block_type"] == "BOOKED":
            return blk
    return None


def host_owns_vehicle(uid, veh):
    return veh["host_id"] == uid


def host_owns_trip(uid, trip):
    veh = vehicles.get(trip["vehicle_id"])
    return veh is not None and veh["host_id"] == uid


def recompute_risk(guest):
    guest["driver_risk_score"] = min(
        MAX_SCORE,
        guest["at_fault_claim_count"] * AT_FAULT_WEIGHT
        + guest["late_return_count"] * LATE_WEIGHT,
    )


def require_status(obj, allowed, field="status"):
    if obj[field] not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409, "Invalid state for transition")


def paginate(items):
    l = request.args.get("limit")
    o = request.args.get("offset")
    try:
        limit = 10 if l is None else int(l)
        offset = 0 if o is None else int(o)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid pagination parameter")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    items = sorted(items, key=lambda x: x["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + limit < total}
    return [pub(x) for x in page], pagination


def list_response(items):
    data, pagination = paginate(items)
    return respond(data, 200, is_array=True, pagination=pagination)


# ===========================================================================
# HOSTS
# ===========================================================================
@app.route("/hosts", methods=["POST"])
def create_host():
    uid, role = require_auth()
    require_role(role, {"Anonymous", "PlatformAdmin"})
    b = body_json()
    name = need_str(b, "name")
    email = need_str(b, "email")
    payout_ref = opt_str(b, "payout_method_ref", None)
    h = new_common()
    h.update({
        "name": name, "email": email, "payout_method_ref": payout_ref,
        "status": "ACTIVE",
        "pending_balance_cents": 0, "available_balance_cents": 0,
        "reserved_payout_cents": 0, "lifetime_earnings_cents": 0,
        "lifetime_paid_cents": 0,
    })
    hosts[h["id"]] = h
    return respond(pub(h), 201)


@app.route("/hosts/<hid>", methods=["GET"])
def get_host_ep(hid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    return respond(pub(get_host(hid)), 200)


@app.route("/hosts/<hid>/suspend", methods=["POST"])
def suspend_host(hid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    h = get_host(hid)
    require_status(h, {"ACTIVE"})
    h["status"] = "SUSPENDED"
    touch(h)
    return respond(pub(h), 200)


@app.route("/hosts/<hid>/reinstate", methods=["POST"])
def reinstate_host(hid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    h = get_host(hid)
    require_status(h, {"SUSPENDED"})
    h["status"] = "ACTIVE"
    touch(h)
    return respond(pub(h), 200)


# ===========================================================================
# GUESTS
# ===========================================================================
@app.route("/guests", methods=["POST"])
def create_guest():
    uid, role = require_auth()
    require_role(role, {"Anonymous", "PlatformAdmin"})
    b = body_json()
    name = need_str(b, "name")
    email = need_str(b, "email")
    g = new_common()
    g.update({
        "name": name, "email": email,
        "verification_status": "UNVERIFIED",
        "license_number": None, "license_state": None,
        "license_expiry_date": None,
        "driver_risk_score": 0, "outstanding_balance_cents": 0,
        "at_fault_claim_count": 0, "late_return_count": 0,
        "completed_trip_count": 0,
    })
    guests[g["id"]] = g
    return respond(pub(g), 201)


@app.route("/guests/<gid>", methods=["GET"])
def get_guest_ep(gid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    return respond(pub(get_guest(gid)), 200)


@app.route("/guests/<gid>/submit-verification", methods=["POST"])
def submit_verification(gid):
    uid, role = require_auth()
    require_role(role, {"Guest"})
    g = get_guest(gid)
    if g["id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Guest may only act on own record")
    b = body_json()
    lic = need_str(b, "license_number")
    state = need_str(b, "license_state")
    expiry = need_date(b, "license_expiry_date")
    require_status(g, {"UNVERIFIED", "REJECTED"}, field="verification_status")
    g["license_number"] = lic
    g["license_state"] = state
    g["license_expiry_date"] = expiry
    g["verification_status"] = "PENDING_REVIEW"
    touch(g)
    return respond(pub(g), 200)


@app.route("/guests/<gid>/verify", methods=["POST"])
def verify_guest(gid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    g = get_guest(gid)
    require_status(g, {"PENDING_REVIEW"}, field="verification_status")
    g["verification_status"] = "VERIFIED"
    touch(g)
    return respond(pub(g), 200)


@app.route("/guests/<gid>/reject", methods=["POST"])
def reject_guest(gid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    g = get_guest(gid)
    body_json()  # optional reason, ignored
    require_status(g, {"PENDING_REVIEW"}, field="verification_status")
    g["verification_status"] = "REJECTED"
    touch(g)
    return respond(pub(g), 200)


# ===========================================================================
# PROTECTION PLANS
# ===========================================================================
@app.route("/protection-plans", methods=["POST"])
def create_plan():
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    b = body_json()
    tier = need_str(b, "tier")
    if tier not in {"BASIC", "STANDARD", "PREMIUM"}:
        raise ApiError("ERR_VALIDATION", 400, "Invalid tier")
    deductible = need_int(b, "deductible_cents")
    daily_premium = need_int(b, "daily_premium_cents")
    coverage = need_int(b, "coverage_limit_cents")
    host_pct = need_num(b, "host_earnings_pct")
    active = b.get("active", True)
    if not isinstance(active, bool):
        raise ApiError("ERR_VALIDATION", 400, "Invalid active flag")
    p = {"id": str(uuid.uuid4()), "created_at": now_iso(), "_seq": next_seq()}
    p.update({
        "tier": tier, "deductible_cents": deductible,
        "daily_premium_cents": daily_premium, "coverage_limit_cents": coverage,
        "host_earnings_pct": host_pct, "active": active,
    })
    plans[p["id"]] = p
    return respond(pub(p), 201)


@app.route("/protection-plans/<pid>", methods=["GET"])
def get_plan_ep(pid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    return respond(pub(get_plan(pid)), 200)


@app.route("/protection-plans", methods=["GET"])
def list_plans():
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    items = list(plans.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [p for p in items if p["active"] == want]
    return list_response(items)


# ===========================================================================
# VEHICLES
# ===========================================================================
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    uid, role = require_auth()
    require_role(role, {"Host"})
    b = body_json()
    host_id = need_str(b, "host_id")
    make = need_str(b, "make")
    model = need_str(b, "model")
    year = need_int(b, "year")
    base_price = need_int(b, "base_daily_price_cents")
    city = need_str(b, "location_city")
    mileage_limit = opt_int(b, "daily_mileage_limit", 200)
    weekly = opt_num(b, "weekly_discount_pct", 0.10)
    monthly = opt_num(b, "monthly_discount_pct", 0.25)
    odometer = opt_int(b, "odometer_current", 0)
    get_host(host_id)
    if host_id != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "host_id must equal acting host")
    v = new_common()
    v.update({
        "host_id": host_id, "make": make, "model": model, "year": year,
        "base_daily_price_cents": base_price, "location_city": city,
        "daily_mileage_limit": mileage_limit, "weekly_discount_pct": weekly,
        "monthly_discount_pct": monthly, "odometer_current": odometer,
        "status": "DRAFT", "booked_night_count": 0, "completed_trip_count": 0,
    })
    vehicles[v["id"]] = v
    return respond(pub(v), 201)


@app.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle_ep(vid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    return respond(pub(get_vehicle(vid)), 200)


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    items = list(vehicles.values())
    hid = request.args.get("host_id")
    if hid is not None:
        items = [v for v in items if v["host_id"] == hid]
    st = request.args.get("status")
    if st is not None:
        items = [v for v in items if v["status"] == st]
    return list_response(items)


@app.route("/vehicles/<vid>", methods=["PUT"])
def edit_vehicle(vid):
    uid, role = require_auth()
    require_role(role, {"Host"})
    v = get_vehicle(vid)
    if not host_owns_vehicle(uid, v):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own vehicle")
    b = body_json()
    if "base_daily_price_cents" in b and b["base_daily_price_cents"] is not None:
        v["base_daily_price_cents"] = need_int(b, "base_daily_price_cents")
    if "daily_mileage_limit" in b and b["daily_mileage_limit"] is not None:
        v["daily_mileage_limit"] = need_int(b, "daily_mileage_limit")
    if "weekly_discount_pct" in b and b["weekly_discount_pct"] is not None:
        v["weekly_discount_pct"] = need_num(b, "weekly_discount_pct")
    if "monthly_discount_pct" in b and b["monthly_discount_pct"] is not None:
        v["monthly_discount_pct"] = need_num(b, "monthly_discount_pct")
    if "location_city" in b and b["location_city"] is not None:
        v["location_city"] = need_str(b, "location_city")
    if "odometer_current" in b and b["odometer_current"] is not None:
        v["odometer_current"] = need_int(b, "odometer_current")
    touch(v)
    return respond(pub(v), 200)


@app.route("/vehicles/<vid>/list", methods=["POST"])
def list_vehicle_action(vid):
    uid, role = require_auth()
    require_role(role, {"Host"})
    v = get_vehicle(vid)
    if not host_owns_vehicle(uid, v):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own vehicle")
    require_status(v, {"DRAFT", "SNOOZED"})
    v["status"] = "LISTED"
    touch(v)
    return respond(pub(v), 200)


@app.route("/vehicles/<vid>/snooze", methods=["POST"])
def snooze_vehicle(vid):
    uid, role = require_auth()
    require_role(role, {"Host"})
    v = get_vehicle(vid)
    if not host_owns_vehicle(uid, v):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own vehicle")
    require_status(v, {"LISTED"})
    v["status"] = "SNOOZED"
    touch(v)
    return respond(pub(v), 200)


@app.route("/vehicles/<vid>/unlist", methods=["POST"])
def unlist_vehicle(vid):
    uid, role = require_auth()
    require_role(role, {"Host"})
    v = get_vehicle(vid)
    if not host_owns_vehicle(uid, v):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own vehicle")
    require_status(v, {"LISTED", "SNOOZED"})
    # precondition: no ACTIVE BOOKED block exists on the vehicle
    for blk in blocks.values():
        if (blk["vehicle_id"] == vid and blk["block_type"] == "BOOKED"
                and blk["status"] == "ACTIVE"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Cannot unlist while an active booking exists")
    v["status"] = "UNLISTED"
    touch(v)
    return respond(pub(v), 200)


# ===========================================================================
# AVAILABILITY BLOCKS
# ===========================================================================
@app.route("/vehicles/<vid>/availability-blocks", methods=["POST"])
def create_block(vid):
    uid, role = require_auth()
    require_role(role, {"Host"})
    v = get_vehicle(vid)
    b = body_json()
    start = need_date(b, "start_date")
    end = need_date(b, "end_date")
    block_type = b.get("block_type", "HOST_BLOCKED")
    if block_type is None:
        block_type = "HOST_BLOCKED"
    if block_type not in {"HOST_BLOCKED", "MAINTENANCE"}:
        raise ApiError("ERR_VALIDATION", 400, "Invalid block_type")
    if not host_owns_vehicle(uid, v):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own vehicle")
    nights = days_between(start, end)
    if nights < 1:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "end_date must be after start_date")
    if overlaps_booked(vid, start, end):
        raise ApiError("ERR_DATES_UNAVAILABLE", 409, "Window overlaps an active booking")
    blk = new_common()
    blk.update({
        "vehicle_id": vid, "trip_id": None, "block_type": block_type,
        "start_date": start, "end_date": end, "nights": nights,
        "status": "ACTIVE",
    })
    blocks[blk["id"]] = blk
    return respond(pub(blk), 201)


@app.route("/availability-blocks/<bid>", methods=["GET"])
def get_block_ep(bid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    return respond(pub(get_block(bid)), 200)


@app.route("/availability-blocks", methods=["GET"])
def list_blocks():
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    items = list(blocks.values())
    vid = request.args.get("vehicle_id")
    if vid is not None:
        items = [x for x in items if x["vehicle_id"] == vid]
    tid = request.args.get("trip_id")
    if tid is not None:
        items = [x for x in items if x.get("trip_id") == tid]
    st = request.args.get("status")
    if st is not None:
        items = [x for x in items if x["status"] == st]
    return list_response(items)


# ===========================================================================
# PRICING RULES
# ===========================================================================
@app.route("/pricing-rules", methods=["POST"])
def create_pricing_rule():
    uid, role = require_auth()
    require_role(role, {"Host"})
    b = body_json()
    vehicle_id = need_str(b, "vehicle_id")
    start = need_date(b, "start_date")
    end = need_date(b, "end_date")
    price = need_int(b, "daily_price_cents")
    v = get_vehicle(vehicle_id)
    if not host_owns_vehicle(uid, v):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own vehicle")
    if parse_date(end) < parse_date(start):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "end_date must be >= start_date")
    if pricing_overlap(vehicle_id, start, end):
        raise ApiError("ERR_PRICING_RULE_OVERLAP", 409, "Overlaps an active pricing rule")
    r = new_common()
    r.update({
        "vehicle_id": vehicle_id, "start_date": start, "end_date": end,
        "daily_price_cents": price, "status": "ACTIVE",
    })
    pricing_rules[r["id"]] = r
    return respond(pub(r), 201)


@app.route("/pricing-rules/<rid>", methods=["GET"])
def get_pricing_rule_ep(rid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    return respond(pub(get_pricing_rule(rid)), 200)


@app.route("/pricing-rules", methods=["GET"])
def list_pricing_rules():
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    items = list(pricing_rules.values())
    vid = request.args.get("vehicle_id")
    if vid is not None:
        items = [x for x in items if x["vehicle_id"] == vid]
    return list_response(items)


# ===========================================================================
# TRIPS
# ===========================================================================
@app.route("/trips", methods=["POST"])
def create_trip():
    uid, role = require_auth()
    require_role(role, {"Guest"})
    b = body_json()
    vehicle_id = need_str(b, "vehicle_id")
    guest_id = need_str(b, "guest_id")
    plan_id = need_str(b, "protection_plan_id")
    start = need_date(b, "start_date")
    end = need_date(b, "end_date")
    expected_v = need_int(b, "expected_vehicle_version")
    # existence (body left-to-right)
    veh = get_vehicle(vehicle_id)
    guest = get_guest(guest_id)
    plan = get_plan(plan_id)
    # ownership
    if guest_id != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "guest_id must equal acting guest")
    # OCC
    if expected_v != veh["version"]:
        raise ApiError("ERR_STALE_VEHICLE_VERSION", 412, "Vehicle version is stale")
    # state
    if guest["verification_status"] != "VERIFIED":
        raise ApiError("ERR_GUEST_NOT_VERIFIED", 409, "Guest is not verified")
    if veh["status"] != "LISTED":
        raise ApiError("ERR_VEHICLE_NOT_LISTED", 409, "Vehicle is not listed")
    # constraints
    nights = days_between(start, end)
    if nights < 1:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "end_date must be after start_date")
    if nights > MAX_TRIP_NIGHTS:
        raise ApiError("ERR_TRIP_TOO_LONG", 422, "Trip exceeds maximum length")
    # temporal
    if overlaps_booked(vehicle_id, start, end):
        raise ApiError("ERR_DATES_UNAVAILABLE", 409, "Window overlaps an active booking")

    est = compute_estimate(veh, plan, start, end)
    t = new_common()
    t.update({
        "vehicle_id": vehicle_id, "guest_id": guest_id,
        "protection_plan_id": plan_id, "start_date": start, "end_date": end,
        "nights": nights, "status": "REQUESTED",
        "discounted_subtotal_cents": est["discounted_subtotal_cents"],
        "protection_premium_cents": est["protection_premium_cents"],
        "estimated_total_cents": est["estimated_total_cents"],
        "estimated_host_earnings_cents": est["estimated_host_earnings_cents"],
        "deductible_snapshot_cents": est["deductible_snapshot_cents"],
        "checkin_odometer": None, "checkin_fuel_pct": None,
        "checkout_odometer": None, "checkout_fuel_pct": None,
        "scheduled_return_at": "%sT11:00:00Z" % end,
        "actual_return_at": None,
        "mileage_fee_cents": 0, "fuel_fee_cents": 0,
        "late_days": 0, "late_fee_cents": 0,
        "final_total_cents": None, "final_host_earnings_cents": None,
    })
    trips[t["id"]] = t
    # side effects: BOOKED block, vehicle booked_night_count, vehicle version bump
    blk = new_common()
    blk.update({
        "vehicle_id": vehicle_id, "trip_id": t["id"], "block_type": "BOOKED",
        "start_date": start, "end_date": end, "nights": nights, "status": "ACTIVE",
    })
    blocks[blk["id"]] = blk
    veh["booked_night_count"] += nights
    touch(veh)
    return respond(pub(t), 201)


@app.route("/trips/<tid>", methods=["GET"])
def get_trip_ep(tid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    return respond(pub(get_trip(tid)), 200)


@app.route("/trips", methods=["GET"])
def list_trips():
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    items = list(trips.values())
    for key in ("vehicle_id", "guest_id", "protection_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    return list_response(items)


@app.route("/trips/<tid>/approve", methods=["POST"])
def approve_trip(tid):
    uid, role = require_auth()
    require_role(role, {"Host"})
    t = get_trip(tid)
    if not host_owns_trip(uid, t):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own trip's vehicle")
    require_status(t, {"REQUESTED"})
    t["status"] = "CONFIRMED"
    touch(t)
    h = hosts[vehicles[t["vehicle_id"]]["host_id"]]
    h["pending_balance_cents"] += t["estimated_host_earnings_cents"]
    touch(h)
    return respond(pub(t), 200)


@app.route("/trips/<tid>/decline", methods=["POST"])
def decline_trip(tid):
    uid, role = require_auth()
    require_role(role, {"Host"})
    t = get_trip(tid)
    if not host_owns_trip(uid, t):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own trip's vehicle")
    require_status(t, {"REQUESTED"})
    t["status"] = "DECLINED"
    touch(t)
    blk = find_booked_block(tid)
    if blk and blk["status"] == "ACTIVE":
        blk["status"] = "RELEASED"
        touch(blk)
        veh = vehicles[t["vehicle_id"]]
        veh["booked_night_count"] -= t["nights"]
        touch(veh)
    return respond(pub(t), 200)


@app.route("/trips/<tid>/cancel", methods=["POST"])
def cancel_trip(tid):
    uid, role = require_auth()
    require_role(role, {"Host", "Guest"})
    t = get_trip(tid)
    if role == "Guest":
        if t["guest_id"] != uid:
            raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Guest does not own trip")
    else:  # Host
        if not host_owns_trip(uid, t):
            raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own trip's vehicle")
    body_json()  # optional reason
    prev = t["status"]
    require_status(t, {"REQUESTED", "CONFIRMED"})
    t["status"] = "CANCELLED"
    touch(t)
    blk = find_booked_block(tid)
    if blk and blk["status"] == "ACTIVE":
        blk["status"] = "RELEASED"
        touch(blk)
        veh = vehicles[t["vehicle_id"]]
        veh["booked_night_count"] -= t["nights"]
        touch(veh)
        if prev == "CONFIRMED":
            h = hosts[veh["host_id"]]
            h["pending_balance_cents"] -= t["estimated_host_earnings_cents"]
            touch(h)
    return respond(pub(t), 200)


@app.route("/trips/<tid>/check-in", methods=["POST"])
def check_in(tid):
    uid, role = require_auth()
    require_role(role, {"Guest"})
    t = get_trip(tid)
    if t["guest_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Guest does not own trip")
    b = body_json()
    odometer = need_int(b, "odometer_reading")
    fuel = need_int(b, "fuel_level_pct")
    photos = b.get("photo_refs")
    if not isinstance(photos, list):
        raise ApiError("ERR_VALIDATION", 400, "photo_refs must be an array")
    require_status(t, {"CONFIRMED"})
    veh = vehicles[t["vehicle_id"]]
    if veh["status"] == "UNLISTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Vehicle is unlisted")
    if fuel < 0 or fuel > 100:
        raise ApiError("ERR_INVALID_FUEL_LEVEL", 422, "fuel_level_pct out of range")
    rep = new_common()
    rep.update({
        "trip_id": tid, "phase": "CHECK_IN", "odometer_reading": odometer,
        "fuel_level_pct": fuel, "photo_refs": photos, "recorded_at": CLOCK["raw"],
    })
    inspections[rep["id"]] = rep
    t["checkin_odometer"] = odometer
    t["checkin_fuel_pct"] = fuel
    t["status"] = "CHECKED_IN"
    touch(t)
    return respond(pub(t), 200)


@app.route("/trips/<tid>/check-out", methods=["POST"])
def check_out(tid):
    uid, role = require_auth()
    require_role(role, {"Guest"})
    t = get_trip(tid)
    if t["guest_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Guest does not own trip")
    b = body_json()
    odometer = need_int(b, "odometer_reading")
    fuel = need_int(b, "fuel_level_pct")
    photos = b.get("photo_refs")
    if not isinstance(photos, list):
        raise ApiError("ERR_VALIDATION", 400, "photo_refs must be an array")
    require_status(t, {"CHECKED_IN"})
    if odometer < t["checkin_odometer"]:
        raise ApiError("ERR_INVALID_ODOMETER", 422, "odometer below check-in reading")
    if fuel < 0 or fuel > 100:
        raise ApiError("ERR_INVALID_FUEL_LEVEL", 422, "fuel_level_pct out of range")
    veh = vehicles[t["vehicle_id"]]

    rep = new_common()
    rep.update({
        "trip_id": tid, "phase": "CHECK_OUT", "odometer_reading": odometer,
        "fuel_level_pct": fuel, "photo_refs": photos, "recorded_at": CLOCK["raw"],
    })
    inspections[rep["id"]] = rep

    t["checkout_odometer"] = odometer
    t["checkout_fuel_pct"] = fuel
    t["actual_return_at"] = CLOCK["raw"]

    # final settlement
    miles_driven = odometer - t["checkin_odometer"]
    allowed_miles = veh["daily_mileage_limit"] * t["nights"]
    overage = max(0, miles_driven - allowed_miles)
    mileage_fee = overage * MILEAGE_OVERAGE_RATE_CENTS
    fuel_deficit = max(0, t["checkin_fuel_pct"] - fuel)
    fuel_fee = fuel_deficit * FUEL_CHARGE_PER_PCT_CENTS
    scheduled = parse_instant(t["scheduled_return_at"])
    actual = CLOCK["dt"]
    overtime = (actual - scheduled).total_seconds() - GRACE_SECONDS
    if overtime <= 0:
        late_days = 0
    else:
        late_days = int(math.ceil(overtime / 86400.0))
    late_per_day = dfloor(Decimal(veh["base_daily_price_cents"]) * LATE_FEE_MULTIPLIER)
    late_fee = late_days * late_per_day

    t["mileage_fee_cents"] = mileage_fee
    t["fuel_fee_cents"] = fuel_fee
    t["late_days"] = late_days
    t["late_fee_cents"] = late_fee
    t["final_total_cents"] = (t["discounted_subtotal_cents"] + t["protection_premium_cents"]
                              + mileage_fee + fuel_fee + late_fee)
    t["final_host_earnings_cents"] = (t["estimated_host_earnings_cents"]
                                      + mileage_fee + fuel_fee + late_fee)
    t["status"] = "CHECKED_OUT"
    touch(t)

    blk = find_booked_block(tid)
    if blk and blk["status"] == "ACTIVE":
        blk["status"] = "CONSUMED"
        touch(blk)

    if late_days > 0:
        g = guests[t["guest_id"]]
        g["late_return_count"] += 1
        touch(g)

    return respond(pub(t), 200)


@app.route("/trips/<tid>/complete", methods=["POST"])
def complete_trip(tid):
    uid, role = require_auth()
    require_role(role, {"Host"})
    t = get_trip(tid)
    if not host_owns_trip(uid, t):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own trip's vehicle")
    require_status(t, {"CHECKED_OUT"})
    t["status"] = "COMPLETED"
    touch(t)
    veh = vehicles[t["vehicle_id"]]
    h = hosts[veh["host_id"]]
    h["pending_balance_cents"] -= t["estimated_host_earnings_cents"]
    h["available_balance_cents"] += t["final_host_earnings_cents"]
    h["lifetime_earnings_cents"] += t["final_host_earnings_cents"]
    touch(h)
    veh["odometer_current"] = t["checkout_odometer"]
    veh["completed_trip_count"] += 1
    touch(veh)
    g = guests[t["guest_id"]]
    g["completed_trip_count"] += 1
    recompute_risk(g)
    touch(g)
    return respond(pub(t), 200)


@app.route("/trips/<tid>/inspections", methods=["GET"])
def list_inspections(tid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    get_trip(tid)
    items = [x for x in inspections.values() if x["trip_id"] == tid]
    return list_response(items)


# ===========================================================================
# EXTENSIONS
# ===========================================================================
@app.route("/trips/<tid>/extensions", methods=["POST"])
def create_extension(tid):
    uid, role = require_auth()
    require_role(role, {"Guest"})
    t = get_trip(tid)
    if t["guest_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Guest does not own trip")
    b = body_json()
    new_end = need_date(b, "new_end_date")
    require_status(t, {"CONFIRMED", "CHECKED_IN"})
    if parse_date(new_end) <= parse_date(t["end_date"]):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "new_end_date must be after end_date")
    for e in extensions.values():
        if e["trip_id"] == tid and e["status"] == "REQUESTED":
            raise ApiError("ERR_DUPLICATE_OPEN_EXTENSION", 409, "Trip already has an open extension")
    ext = new_common()
    ext.update({
        "trip_id": tid, "new_end_date": new_end,
        "previous_end_date": t["end_date"],
        "added_nights": days_between(t["end_date"], new_end),
        "status": "REQUESTED", "added_earnings_cents": None,
    })
    extensions[ext["id"]] = ext
    return respond(pub(ext), 201)


@app.route("/extensions/<eid>/approve", methods=["POST"])
def approve_extension(eid):
    uid, role = require_auth()
    require_role(role, {"Host"})
    ext = get_extension(eid)
    t = trips.get(ext["trip_id"])
    if not host_owns_trip(uid, t):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own trip's vehicle")
    require_status(ext, {"REQUESTED"})
    if t["status"] not in {"CONFIRMED", "CHECKED_IN"}:
        raise ApiError("ERR_INVALID_STATE", 409, "Trip not in an extendable state")
    veh = vehicles[t["vehicle_id"]]
    new_end = ext["new_end_date"]
    new_nights = days_between(t["start_date"], new_end)
    # constraint (7) before temporal (8) per §2.9
    if new_nights > MAX_TRIP_NIGHTS:
        raise ApiError("ERR_TRIP_TOO_LONG", 422, "Trip exceeds maximum length")
    blk = find_booked_block(t["id"])
    exclude = blk["id"] if blk else None
    if overlaps_booked(veh["id"], t["start_date"], new_end, exclude_block_id=exclude):
        raise ApiError("ERR_DATES_UNAVAILABLE", 409, "Extended window overlaps a booking")

    plan = plans[t["protection_plan_id"]]
    old_est_host = t["estimated_host_earnings_cents"]
    added_nights = days_between(ext["previous_end_date"], new_end)

    # cascade L1: mutate trip
    est = compute_estimate(veh, plan, t["start_date"], new_end)
    t["end_date"] = new_end
    t["nights"] = est["nights"]
    t["discounted_subtotal_cents"] = est["discounted_subtotal_cents"]
    t["protection_premium_cents"] = est["protection_premium_cents"]
    t["estimated_total_cents"] = est["estimated_total_cents"]
    t["estimated_host_earnings_cents"] = est["estimated_host_earnings_cents"]
    t["scheduled_return_at"] = "%sT11:00:00Z" % new_end
    touch(t)

    added_earnings = est["estimated_host_earnings_cents"] - old_est_host

    ext["status"] = "APPROVED"
    ext["added_earnings_cents"] = added_earnings
    touch(ext)

    # cascade L2: block
    if blk:
        blk["end_date"] = new_end
        blk["nights"] = days_between(blk["start_date"], new_end)
        touch(blk)

    # cascade L3: vehicle + host
    veh["booked_night_count"] += added_nights
    touch(veh)
    h = hosts[veh["host_id"]]
    h["pending_balance_cents"] += added_earnings
    touch(h)

    return respond(pub(ext), 200)


@app.route("/extensions/<eid>/deny", methods=["POST"])
def deny_extension(eid):
    uid, role = require_auth()
    require_role(role, {"Host"})
    ext = get_extension(eid)
    t = trips.get(ext["trip_id"])
    if not host_owns_trip(uid, t):
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own trip's vehicle")
    require_status(ext, {"REQUESTED"})
    ext["status"] = "DENIED"
    touch(ext)
    return respond(pub(ext), 200)


@app.route("/extensions/<eid>", methods=["GET"])
def get_extension_ep(eid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    return respond(pub(get_extension(eid)), 200)


@app.route("/extensions", methods=["GET"])
def list_extensions():
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    items = list(extensions.values())
    tid = request.args.get("trip_id")
    if tid is not None:
        items = [x for x in items if x["trip_id"] == tid]
    return list_response(items)


# ===========================================================================
# CLAIMS
# ===========================================================================
@app.route("/trips/<tid>/claims", methods=["POST"])
def file_claim(tid):
    uid, role = require_auth()
    require_role(role, {"Host", "Guest"})
    t = get_trip(tid)
    b = body_json()
    claimant = need_str(b, "claimant")
    if claimant not in {"HOST", "GUEST"}:
        raise ApiError("ERR_VALIDATION", 400, "Invalid claimant")
    damage = need_int(b, "damage_amount_cents")
    description = need_str(b, "description")
    # ownership: acting party is party to the trip
    if role == "Guest":
        if t["guest_id"] != uid:
            raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Guest does not own trip")
    else:
        if not host_owns_trip(uid, t):
            raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host does not own trip's vehicle")
    # state
    if t["status"] not in {"CHECKED_OUT", "COMPLETED"}:
        raise ApiError("ERR_TRIP_NOT_CLAIMABLE", 409, "Trip is not claimable")
    # constraint
    if damage <= 0:
        raise ApiError("ERR_INVALID_CLAIM_AMOUNT", 422, "damage_amount_cents must be > 0")
    # uniqueness
    for c in claims.values():
        if c["trip_id"] == tid and c["status"] not in CLAIM_TERMINAL:
            raise ApiError("ERR_DUPLICATE_OPEN_CLAIM", 409, "Trip already has an open claim")
    c = new_common()
    c.update({
        "trip_id": tid, "claimant": claimant, "damage_amount_cents": damage,
        "description": description, "status": "FILED",
        "covered_amount_cents": None, "guest_deductible_cents": None,
        "host_recovery_cents": None, "uncovered_cents": None,
        "resolution_note": None,
    })
    claims[c["id"]] = c
    return respond(pub(c), 201)


@app.route("/claims/<cid>/start-review", methods=["POST"])
def start_review(cid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_claim(cid)
    require_status(c, {"FILED"})
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return respond(pub(c), 200)


@app.route("/claims/<cid>/request-info", methods=["POST"])
def request_info(cid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_claim(cid)
    require_status(c, {"UNDER_REVIEW"})
    c["status"] = "NEEDS_INFO"
    touch(c)
    return respond(pub(c), 200)


@app.route("/claims/<cid>/provide-info", methods=["POST"])
def provide_info(cid):
    uid, role = require_auth()
    require_role(role, {"Host", "Guest"})
    c = get_claim(cid)
    t = trips.get(c["trip_id"])
    if role == "Guest":
        if t["guest_id"] != uid:
            raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Guest is not a party to the trip")
    else:
        if not host_owns_trip(uid, t):
            raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Host is not a party to the trip")
    body_json()  # optional note
    require_status(c, {"NEEDS_INFO"})
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return respond(pub(c), 200)


@app.route("/claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_claim(cid)
    b = body_json()
    note = opt_str(b, "resolution_note", None)
    require_status(c, {"UNDER_REVIEW"})
    t = trips[c["trip_id"]]
    plan = plans[t["protection_plan_id"]]
    assessed = c["damage_amount_cents"]
    covered = min(assessed, plan["coverage_limit_cents"])
    c["covered_amount_cents"] = covered
    c["guest_deductible_cents"] = min(plan["deductible_cents"], covered)
    c["host_recovery_cents"] = covered
    c["uncovered_cents"] = max(0, assessed - covered)
    if note is not None:
        c["resolution_note"] = note
    c["status"] = "APPROVED"
    touch(c)
    return respond(pub(c), 200)


@app.route("/claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_claim(cid)
    b = body_json()
    note = opt_str(b, "resolution_note", None)
    require_status(c, {"UNDER_REVIEW"})
    if note is not None:
        c["resolution_note"] = note
    c["status"] = "DENIED"
    touch(c)
    return respond(pub(c), 200)


@app.route("/claims/<cid>/settle", methods=["POST"])
def settle_claim(cid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_claim(cid)
    require_status(c, {"APPROVED"})
    t = trips[c["trip_id"]]
    veh = vehicles[t["vehicle_id"]]
    g = guests[t["guest_id"]]
    h = hosts[veh["host_id"]]
    g["outstanding_balance_cents"] += c["guest_deductible_cents"]
    h["available_balance_cents"] += c["host_recovery_cents"]
    h["lifetime_earnings_cents"] += c["host_recovery_cents"]
    touch(h)
    if c["claimant"] == "HOST":
        g["at_fault_claim_count"] += 1
        recompute_risk(g)
    touch(g)
    c["status"] = "SETTLED"
    touch(c)
    return respond(pub(c), 200)


@app.route("/claims/<cid>", methods=["GET"])
def get_claim_ep(cid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    return respond(pub(get_claim(cid)), 200)


@app.route("/claims", methods=["GET"])
def list_claims():
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    items = list(claims.values())
    tid = request.args.get("trip_id")
    if tid is not None:
        items = [x for x in items if x["trip_id"] == tid]
    return list_response(items)


# ===========================================================================
# PAYOUTS
# ===========================================================================
@app.route("/payouts", methods=["POST"])
def create_payout():
    uid, role = require_auth()
    require_role(role, {"Host"})
    b = body_json()
    host_id = need_str(b, "host_id")
    amount = need_int(b, "amount_cents")
    expected_v = need_int(b, "expected_host_version")
    trip_id = opt_str(b, "trip_id", None)
    # existence (body left-to-right: host_id then trip_id)
    h = get_host(host_id)
    if trip_id is not None:
        get_trip(trip_id)
    # ownership
    if host_id != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "host_id must equal acting host")
    # OCC
    if expected_v != h["version"]:
        raise ApiError("ERR_STALE_HOST_VERSION", 412, "Host version is stale")
    # state
    if h["status"] != "ACTIVE":
        raise ApiError("ERR_HOST_SUSPENDED", 409, "Host is suspended")
    # constraint
    if amount < MIN_PAYOUT_CENTS:
        raise ApiError("ERR_PAYOUT_BELOW_MINIMUM", 422, "Payout below minimum")
    # fiscal
    if amount > h["available_balance_cents"]:
        raise ApiError("ERR_INSUFFICIENT_BALANCE", 402, "Insufficient available balance")
    p = new_common()
    p.update({
        "host_id": host_id, "trip_id": trip_id, "amount_cents": amount,
        "status": "REQUESTED", "failure_reason": None,
    })
    payouts[p["id"]] = p
    h["available_balance_cents"] -= amount
    h["reserved_payout_cents"] += amount
    touch(h)
    return respond(pub(p), 201)


@app.route("/payouts/<pid>/mark-paid", methods=["POST"])
def mark_paid(pid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    p = get_payout(pid)
    require_status(p, {"REQUESTED"})
    p["status"] = "PAID"
    touch(p)
    h = hosts[p["host_id"]]
    h["reserved_payout_cents"] -= p["amount_cents"]
    h["lifetime_paid_cents"] += p["amount_cents"]
    touch(h)
    return respond(pub(p), 200)


@app.route("/payouts/<pid>/mark-failed", methods=["POST"])
def mark_failed(pid):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    p = get_payout(pid)
    b = body_json()
    reason = opt_str(b, "failure_reason", None)
    require_status(p, {"REQUESTED"})
    p["status"] = "FAILED"
    if reason is not None:
        p["failure_reason"] = reason
    touch(p)
    h = hosts[p["host_id"]]
    h["reserved_payout_cents"] -= p["amount_cents"]
    h["available_balance_cents"] += p["amount_cents"]
    touch(h)
    return respond(pub(p), 200)


@app.route("/payouts/<pid>", methods=["GET"])
def get_payout_ep(pid):
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    return respond(pub(get_payout(pid)), 200)


@app.route("/payouts", methods=["GET"])
def list_payouts():
    uid, role = require_auth()
    require_role(role, READ_ROLES)
    items = list(payouts.values())
    hid = request.args.get("host_id")
    if hid is not None:
        items = [x for x in items if x["host_id"] == hid]
    tid = request.args.get("trip_id")
    if tid is not None:
        items = [x for x in items if x.get("trip_id") == tid]
    return list_response(items)


# ===========================================================================
# LOGICAL CLOCK (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    b = body_json()
    to_iso = need_str(b, "to_iso8601")
    dt = parse_instant(to_iso)
    CLOCK["raw"] = to_iso
    CLOCK["dt"] = dt
    return respond({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
