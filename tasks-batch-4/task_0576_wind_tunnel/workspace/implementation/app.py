import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
ROLES = {"Flyer", "Instructor", "FrontDesk", "Manager"}

MIN_SESSION_MINUTES = 15
WAIVER_VALID_DAYS = 90
SENIOR_UPGRADE_THRESHOLD = 2

VIDEO_PRICE_CENTS = 3335
COACHING_RATE_PER_MIN_CENTS = 1245

MEMBER_DISCOUNT = {
    "NONE": Decimal("0.00"),
    "STANDARD": Decimal("0.10"),
    "PRO": Decimal("0.15"),
}

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# =============================================================================
# In-memory store (fresh on every process boot — NO seeding)
# =============================================================================
tunnels = {}
instructors = {}
members = {}
memberships = {}
packages = {}
bookings = {}
sessions = {}
flights = {}
waivers = {}
coachings = {}

_seq_counter = [0]
_clock = [DEFAULT_CLOCK]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def clock_now():
    return _clock[0]


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


NOT_FOUND = {
    "tunnel": "ERR_TUNNEL_NOT_FOUND",
    "instructor": "ERR_INSTRUCTOR_NOT_FOUND",
    "member": "ERR_MEMBER_NOT_FOUND",
    "membership": "ERR_MEMBERSHIP_NOT_FOUND",
    "package": "ERR_PACKAGE_NOT_FOUND",
    "booking": "ERR_BOOKING_NOT_FOUND",
    "session": "ERR_SESSION_NOT_FOUND",
    "flight": "ERR_FLIGHT_NOT_FOUND",
    "waiver": "ERR_WAIVER_NOT_FOUND",
    "coaching": "ERR_COACHING_NOT_FOUND",
}


# =============================================================================
# Time / formatting helpers
# =============================================================================
def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def now_iso():
    return iso(datetime.now(timezone.utc))


def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def rhu(x):
    """Round-half-up to whole integer cents."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# Response envelope
# =============================================================================
def meta_base(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def success(data, response_type="object", status=200, list_meta=None):
    body = {
        "meta": meta_base(list_meta),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "method not allowed"},
    }
    return jsonify(body), 405


# =============================================================================
# Auth / RBAC
# =============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or unrecognized credentials")
    return uid, role


def require(allowed_roles):
    uid, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "role %s not permitted" % role)
    return uid, role


# =============================================================================
# Body parsing / validation helpers
# =============================================================================
def get_body():
    body = request.get_json(force=True, silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "body must be an object")
    return body


def req_str(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", 400, "missing field: %s" % key)
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, "invalid string: %s" % key)
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid string: %s" % key)
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", 400, "missing field: %s" % key)
    v = body[key]
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", 400, "invalid integer: %s" % key)
    return v


def opt_int(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", 400, "invalid integer: %s" % key)
    return v


def req_num(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", 400, "missing field: %s" % key)
    v = body[key]
    if not is_num(v):
        raise ApiError("ERR_VALIDATION", 400, "invalid number: %s" % key)
    return v


def req_bool(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", 400, "missing field: %s" % key)
    v = body[key]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, "invalid boolean: %s" % key)
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "invalid enum: %s" % key)
    return v


def opt_enum(body, key, allowed, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "invalid enum: %s" % key)
    return v


# =============================================================================
# Common resource lifecycle
# =============================================================================
def new_common():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# =============================================================================
# Existence helpers
# =============================================================================
def must_exist(store, key, kind):
    if key not in store:
        raise ApiError(NOT_FOUND[kind], 404, "%s not found" % kind)
    return store[key]


# =============================================================================
# Waiver status (dynamic from logical clock)
# =============================================================================
def waiver_status(w):
    return "SIGNED" if clock_now() <= w["_expires_dt"] else "EXPIRED"


def public_waiver(w):
    d = public(w)
    d["status"] = waiver_status(w)
    return d


# =============================================================================
# Minutes / seats / booking-status helpers
# =============================================================================
def refund_minutes(booking, amount):
    booking["minutes_remaining"] += amount
    touch(booking)
    if booking["status"] == "EXHAUSTED" and booking["minutes_remaining"] > 0:
        booking["status"] = "CONFIRMED"
        m = members.get(booking["member_id"])
        if m:
            m["confirmed_booking_count"] += 1
            touch(m)


def consume_minutes(booking, amount):
    booking["minutes_remaining"] -= amount
    touch(booking)
    if booking["minutes_remaining"] == 0 and booking["status"] == "CONFIRMED":
        booking["status"] = "EXHAUSTED"
        m = members.get(booking["member_id"])
        if m:
            m["confirmed_booking_count"] -= 1
            touch(m)


def recompute_seats(session_id):
    s = sessions.get(session_id)
    if not s:
        return
    taken = sum(
        1
        for f in flights.values()
        if f["session_id"] == session_id and f["status"] in ("SCHEDULED", "CHECKED_IN", "FLOWN")
    )
    avail = s["capacity"] - taken
    if avail < 0:
        avail = 0
    if s["seats_taken"] != taken or s["seats_available"] != avail:
        s["seats_taken"] = taken
        s["seats_available"] = avail
        touch(s)


def recompute_outstanding(member_id):
    m = members.get(member_id)
    if not m:
        return
    v = sum(
        f["video_charge_cents"]
        for f in flights.values()
        if f["member_id"] == member_id and f["video_addon_purchased"]
    )
    c = sum(
        cb["charge_cents"]
        for cb in coachings.values()
        if flights.get(cb["flight_id"], {}).get("member_id") == member_id
        and cb["status"] != "CANCELLED"
    )
    total = v + c
    if m["outstanding_addon_cents"] != total:
        m["outstanding_addon_cents"] = total
        touch(m)


def cancel_flight_coaching(flight_id):
    for cb in coachings.values():
        if cb["flight_id"] == flight_id and cb["status"] == "REQUESTED":
            cb["status"] = "CANCELLED"
            touch(cb)
    f = flights.get(flight_id)
    if f:
        recompute_outstanding(f["member_id"])


# =============================================================================
# Pagination + listing
# =============================================================================
def get_pagination():
    q = request.args
    limit_raw = q.get("limit")
    offset_raw = q.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "invalid limit")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "invalid offset")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(items, serializer):
    items = sorted(items, key=lambda e: e["_seq"])
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    list_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    data = [serializer(e) for e in page]
    return success(data, response_type="array", status=200, list_meta=list_meta)


# =============================================================================
# Pricing
# =============================================================================
def compute_booking_price(base_price_cents, booking_type, party_size, lead_days, membership_tier):
    per = Decimal(base_price_cents)
    if party_size <= 2:
        party_mult = Decimal("1.00")
    elif party_size <= 4:
        party_mult = Decimal("0.95")
    else:
        party_mult = Decimal("0.90")
    subtotal = per * Decimal(party_size) * party_mult
    if booking_type == "WALK_IN":
        typed = subtotal * Decimal("1.20")
    else:
        if lead_days < 3:
            lead_disc = Decimal("0.00")
        elif lead_days < 7:
            lead_disc = Decimal("0.05")
        else:
            lead_disc = Decimal("0.10")
        typed = subtotal * (Decimal("1") - lead_disc)
    member_disc = MEMBER_DISCOUNT[membership_tier]
    return rhu(typed * (Decimal("1") - member_disc))


def video_line(member):
    return rhu(Decimal(VIDEO_PRICE_CENTS) * (Decimal("1") - MEMBER_DISCOUNT[member["membership_tier"]]))


def coaching_line(member, minutes):
    return rhu(
        Decimal(COACHING_RATE_PER_MIN_CENTS) * Decimal(minutes)
        * (Decimal("1") - MEMBER_DISCOUNT[member["membership_tier"]])
    )


# =============================================================================
# TUNNELS
# =============================================================================
@app.route("/tunnels", methods=["POST"])
def create_tunnel():
    require({"Manager"})
    body = get_body()
    name = req_str(body, "name")
    max_weight_kg = req_num(body, "max_weight_kg")
    default_capacity = req_int(body, "default_capacity")
    turnaround_minutes = req_int(body, "turnaround_minutes")
    t = new_common()
    t.update({
        "name": name,
        "max_weight_kg": max_weight_kg,
        "default_capacity": default_capacity,
        "turnaround_minutes": turnaround_minutes,
        "status": "OPERATIONAL",
    })
    tunnels[t["id"]] = t
    return success(public(t), status=201)


@app.route("/tunnels/<tid>", methods=["GET"])
def get_tunnel(tid):
    require({"Manager", "FrontDesk"})
    t = must_exist(tunnels, tid, "tunnel")
    return success(public(t))


@app.route("/tunnels/<tid>/maintenance", methods=["POST"])
def tunnel_maintenance(tid):
    require({"Manager"})
    t = must_exist(tunnels, tid, "tunnel")
    body = get_body()
    mode = req_enum(body, "mode", {"OPERATIONAL", "MAINTENANCE"})
    if t["status"] != mode:
        t["status"] = mode
        touch(t)
    return success(public(t))


# =============================================================================
# INSTRUCTORS
# =============================================================================
@app.route("/instructors", methods=["POST"])
def create_instructor():
    require({"Manager"})
    body = get_body()
    name = req_str(body, "name")
    cert_level = req_enum(body, "cert_level", {"L1", "L2", "L3"})
    status = opt_enum(body, "status", {"ACTIVE", "OFF"}, "ACTIVE")
    i = new_common()
    i.update({
        "name": name,
        "cert_level": cert_level,
        "tier": "JUNIOR",
        "sessions_completed": 0,
        "status": status,
    })
    instructors[i["id"]] = i
    return success(public(i), status=201)


@app.route("/instructors/<iid>", methods=["GET"])
def get_instructor(iid):
    require({"Manager", "FrontDesk"})
    i = must_exist(instructors, iid, "instructor")
    return success(public(i))


# =============================================================================
# MEMBERS
# =============================================================================
@app.route("/members", methods=["POST"])
def create_member():
    require({"Flyer", "FrontDesk"})
    body = get_body()
    name = req_str(body, "name")
    weight_kg = req_num(body, "weight_kg")
    experience_status = opt_enum(body, "experience_status", {"FIRST_TIME", "RETURNING"}, "FIRST_TIME")
    health_flags = body.get("health_flags", [])
    if health_flags is None:
        health_flags = []
    if not isinstance(health_flags, list):
        raise ApiError("ERR_VALIDATION", 400, "invalid health_flags")
    m = new_common()
    m.update({
        "name": name,
        "weight_kg": weight_kg,
        "experience_status": experience_status,
        "health_flags": health_flags,
        "membership_tier": "NONE",
        "reflight_credit_minutes": 0,
        "total_credits_minted": 0,
        "total_credits_consumed": 0,
        "wallet_cents": 0,
        "confirmed_booking_count": 0,
        "outstanding_addon_cents": 0,
    })
    members[m["id"]] = m
    return success(public(m), status=201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    require({"Flyer", "FrontDesk", "Manager"})
    m = must_exist(members, mid, "member")
    return success(public(m))


@app.route("/members/<mid>/statement", methods=["GET"])
def member_statement(mid):
    require({"Flyer", "FrontDesk", "Manager"})
    must_exist(members, mid, "member")
    video = sum(
        f["video_charge_cents"]
        for f in flights.values()
        if f["member_id"] == mid and f["video_addon_purchased"]
    )
    coaching = sum(
        cb["charge_cents"]
        for cb in coachings.values()
        if flights.get(cb["flight_id"], {}).get("member_id") == mid and cb["status"] != "CANCELLED"
    )
    data = {
        "statement_total_cents": video + coaching,
        "video_charges_cents": video,
        "coaching_charges_cents": coaching,
    }
    return success(data)


# =============================================================================
# WAIVERS
# =============================================================================
@app.route("/waivers", methods=["POST"])
def create_waiver():
    require({"Flyer", "FrontDesk"})
    body = get_body()
    member_id = req_str(body, "member_id")
    weight_kg_declared = req_num(body, "weight_kg_declared")
    health_ok = req_bool(body, "health_ok")
    must_exist(members, member_id, "member")
    signed_dt = clock_now()
    expires_dt = signed_dt + timedelta(days=WAIVER_VALID_DAYS)
    w = new_common()
    w.update({
        "member_id": member_id,
        "weight_kg_declared": weight_kg_declared,
        "health_ok": health_ok,
        "signed_at": iso(signed_dt),
        "expires_at": iso(expires_dt),
        "status": "SIGNED",
        "_expires_dt": expires_dt,
    })
    waivers[w["id"]] = w
    return success(public_waiver(w), status=201)


@app.route("/waivers/<wid>", methods=["GET"])
def get_waiver(wid):
    require({"Flyer", "FrontDesk", "Manager"})
    w = must_exist(waivers, wid, "waiver")
    return success(public_waiver(w))


@app.route("/waivers", methods=["GET"])
def list_waivers():
    require({"Flyer", "FrontDesk", "Manager"})
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = []
    for w in waivers.values():
        if member_id is not None and w["member_id"] != member_id:
            continue
        if status is not None and waiver_status(w) != status:
            continue
        items.append(w)
    return list_response(items, public_waiver)


# =============================================================================
# MEMBERSHIPS
# =============================================================================
@app.route("/memberships", methods=["POST"])
def create_membership():
    require({"FrontDesk", "Manager"})
    body = get_body()
    member_id = req_str(body, "member_id")
    tier = req_enum(body, "tier", {"STANDARD", "PRO"})
    m = must_exist(members, member_id, "member")
    discount_pct = float(MEMBER_DISCOUNT[tier])
    ms = new_common()
    ms.update({
        "member_id": member_id,
        "tier": tier,
        "discount_pct": discount_pct,
        "status": "ACTIVE",
    })
    memberships[ms["id"]] = ms
    m["membership_tier"] = tier
    touch(m)
    return success(public(ms), status=201)


@app.route("/memberships/<msid>", methods=["GET"])
def get_membership(msid):
    require({"Flyer", "FrontDesk", "Manager"})
    ms = must_exist(memberships, msid, "membership")
    return success(public(ms))


@app.route("/memberships", methods=["GET"])
def list_memberships():
    require({"FrontDesk", "Manager"})
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = []
    for ms in memberships.values():
        if member_id is not None and ms["member_id"] != member_id:
            continue
        if status is not None and ms["status"] != status:
            continue
        items.append(ms)
    return list_response(items, public)


@app.route("/memberships/<msid>/cancel", methods=["POST"])
def cancel_membership(msid):
    require({"FrontDesk", "Manager"})
    ms = must_exist(memberships, msid, "membership")
    if ms["status"] != "CANCELLED":
        ms["status"] = "CANCELLED"
        touch(ms)
        m = members.get(ms["member_id"])
        if m:
            m["membership_tier"] = "NONE"
            touch(m)
    return success(public(ms))


# =============================================================================
# PACKAGES
# =============================================================================
@app.route("/packages", methods=["POST"])
def create_package():
    require({"Manager"})
    body = get_body()
    name = req_str(body, "name")
    included_minutes = req_int(body, "included_minutes")
    base_price_cents = req_int(body, "base_price_cents")
    min_experience = opt_enum(body, "min_experience", {"FIRST_TIME", "RETURNING"}, "FIRST_TIME")
    active = body.get("active", True)
    if active is None:
        active = True
    if not isinstance(active, bool):
        raise ApiError("ERR_VALIDATION", 400, "invalid active")
    p = new_common()
    p.update({
        "name": name,
        "included_minutes": included_minutes,
        "base_price_cents": base_price_cents,
        "min_experience": min_experience,
        "active": active,
    })
    packages[p["id"]] = p
    return success(public(p), status=201)


@app.route("/packages/<pid>", methods=["GET"])
def get_package(pid):
    require({"Flyer", "FrontDesk", "Manager"})
    p = must_exist(packages, pid, "package")
    return success(public(p))


# =============================================================================
# BOOKINGS
# =============================================================================
@app.route("/bookings", methods=["POST"])
def create_booking():
    require({"Flyer", "FrontDesk"})
    body = get_body()
    member_id = req_str(body, "member_id")
    package_id = req_str(body, "package_id")
    booking_type = req_enum(body, "booking_type", {"WALK_IN", "RESERVATION"})
    party_size = req_int(body, "party_size")
    lead_days = opt_int(body, "lead_days", 0)
    # existence: member_id then package_id
    m = must_exist(members, member_id, "member")
    p = must_exist(packages, package_id, "package")
    # eligibility (priority 5)
    if p["min_experience"] == "RETURNING" and m["experience_status"] != "RETURNING":
        raise ApiError("ERR_EXPERIENCE_NOT_ELIGIBLE", 409, "member not eligible for package")
    # structural (priority 8)
    if party_size < 1:
        raise ApiError("ERR_INVALID_PARTY_SIZE", 422, "party_size must be >= 1")
    total_price = compute_booking_price(
        p["base_price_cents"], booking_type, party_size, lead_days, m["membership_tier"]
    )
    minutes_included = party_size * p["included_minutes"]
    b = new_common()
    b.update({
        "member_id": member_id,
        "package_id": package_id,
        "booking_type": booking_type,
        "party_size": party_size,
        "lead_days": lead_days,
        "minutes_included": minutes_included,
        "minutes_remaining": minutes_included,
        "total_price_cents": total_price,
        "refunded_cents": 0,
        "status": "CONFIRMED",
    })
    bookings[b["id"]] = b
    m["confirmed_booking_count"] += 1
    touch(m)
    return success(public(b), status=201)


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    require({"Flyer", "FrontDesk", "Manager"})
    b = must_exist(bookings, bid, "booking")
    return success(public(b))


@app.route("/bookings", methods=["GET"])
def list_bookings():
    require({"Flyer", "FrontDesk", "Manager"})
    member_id = request.args.get("member_id")
    package_id = request.args.get("package_id")
    status = request.args.get("status")
    items = []
    for b in bookings.values():
        if member_id is not None and b["member_id"] != member_id:
            continue
        if package_id is not None and b["package_id"] != package_id:
            continue
        if status is not None and b["status"] != status:
            continue
        items.append(b)
    return list_response(items, public)


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    require({"Flyer", "FrontDesk"})
    b = must_exist(bookings, bid, "booking")
    if b["status"] not in ("CONFIRMED", "EXHAUSTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "booking not cancellable")
    booking_flights = [f for f in flights.values() if f["booking_id"] == bid]
    if any(f["status"] == "FLOWN" for f in booking_flights):
        raise ApiError("ERR_BOOKING_HAS_FLOWN_FLIGHT", 409, "booking has a flown flight")
    was_confirmed = b["status"] == "CONFIRMED"
    affected_sessions = set()
    for f in booking_flights:
        if f["status"] in ("SCHEDULED", "CHECKED_IN"):
            f["status"] = "CANCELLED"
            touch(f)
            affected_sessions.add(f["session_id"])
            cancel_flight_coaching(f["id"])
    for sid in affected_sessions:
        recompute_seats(sid)
    m = members.get(b["member_id"])
    if m:
        m["wallet_cents"] += b["total_price_cents"]
    b["refunded_cents"] = b["total_price_cents"]
    b["status"] = "CANCELLED"
    touch(b)
    if m:
        if was_confirmed:
            m["confirmed_booking_count"] -= 1
        touch(m)
    return success(public(b))


# =============================================================================
# SESSIONS
# =============================================================================
def intervals_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end); adjacency (touching) is NOT overlap
    return a_start < b_end and b_start < a_end


@app.route("/sessions", methods=["POST"])
def create_session():
    require({"FrontDesk", "Manager"})
    body = get_body()
    tunnel_id = req_str(body, "tunnel_id")
    start_raw = req_str(body, "start_utc")
    end_raw = req_str(body, "end_utc")
    t = must_exist(tunnels, tunnel_id, "tunnel")
    capacity = opt_int(body, "capacity", None)
    if capacity is None:
        capacity = t["default_capacity"]
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    # window validation (priority 7)
    if end_dt <= start_dt or (end_dt - start_dt) < timedelta(minutes=MIN_SESSION_MINUTES):
        raise ApiError("ERR_INVALID_SESSION_WINDOW", 422, "invalid session window")
    # tunnel conflict + turnaround buffer (priority 7)
    buffer = timedelta(minutes=t["turnaround_minutes"])
    for s in sessions.values():
        if s["tunnel_id"] != tunnel_id:
            continue
        if s["op_status"] == "CANCELLED":
            continue
        e_start = parse_dt(s["start_utc"])
        e_end = parse_dt(s["end_utc"])
        if start_dt < e_end + buffer and e_start < end_dt + buffer:
            raise ApiError("ERR_SESSION_TIME_CONFLICT", 409, "session time conflict")
    s = new_common()
    s.update({
        "tunnel_id": tunnel_id,
        "instructor_id": None,
        "start_utc": iso(start_dt),
        "end_utc": iso(end_dt),
        "capacity": capacity,
        "op_status": "OPEN",
        "staffing_status": "UNSTAFFED",
        "seats_taken": 0,
        "seats_available": capacity,
    })
    sessions[s["id"]] = s
    return success(public(s), status=201)


@app.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    require({"Flyer", "FrontDesk", "Manager", "Instructor"})
    s = must_exist(sessions, sid, "session")
    return success(public(s))


@app.route("/sessions", methods=["GET"])
def list_sessions():
    require({"Flyer", "FrontDesk", "Manager", "Instructor"})
    tunnel_id = request.args.get("tunnel_id")
    instructor_id = request.args.get("instructor_id")
    op_status = request.args.get("op_status")
    items = []
    for s in sessions.values():
        if tunnel_id is not None and s["tunnel_id"] != tunnel_id:
            continue
        if instructor_id is not None and s["instructor_id"] != instructor_id:
            continue
        if op_status is not None and s["op_status"] != op_status:
            continue
        items.append(s)
    return list_response(items, public)


@app.route("/sessions/<sid>/assign-instructor", methods=["POST"])
def assign_instructor(sid):
    require({"FrontDesk", "Manager"})
    body = get_body()
    instructor_id = req_str(body, "instructor_id")
    expected_version = req_int(body, "expected_session_version")
    # existence: path (session) then body FK (instructor)
    s = must_exist(sessions, sid, "session")
    inst = must_exist(instructors, instructor_id, "instructor")
    # OCC
    if expected_version != s["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale session version")
    # instructor conflict over [start, end)
    s_start = parse_dt(s["start_utc"])
    s_end = parse_dt(s["end_utc"])
    for other in sessions.values():
        if other["id"] == sid:
            continue
        if other["instructor_id"] != instructor_id:
            continue
        if other["op_status"] == "CANCELLED":
            continue
        o_start = parse_dt(other["start_utc"])
        o_end = parse_dt(other["end_utc"])
        if intervals_overlap(s_start, s_end, o_start, o_end):
            raise ApiError("ERR_INSTRUCTOR_TIME_CONFLICT", 409, "instructor time conflict")
    s["instructor_id"] = instructor_id
    s["staffing_status"] = "STAFFED"
    touch(s)
    return success(public(s))


@app.route("/sessions/<sid>/start", methods=["POST"])
def start_session(sid):
    require({"Instructor", "FrontDesk"})
    s = must_exist(sessions, sid, "session")
    # state (priority 4)
    if s["op_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "session not OPEN")
    # eligibility gates (priority 5): staffed first, then tunnel operational
    if s["staffing_status"] != "STAFFED":
        raise ApiError("ERR_SESSION_NOT_STAFFED", 409, "session not staffed")
    t = tunnels.get(s["tunnel_id"])
    if t is None or t["status"] != "OPERATIONAL":
        raise ApiError("ERR_TUNNEL_NOT_OPERATIONAL", 409, "tunnel not operational")
    s["op_status"] = "RUNNING"
    touch(s)
    return success(public(s))


@app.route("/sessions/<sid>/close", methods=["POST"])
def close_session(sid):
    require({"Instructor", "FrontDesk"})
    s = must_exist(sessions, sid, "session")
    if s["op_status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "session not RUNNING")
    # instructor seniority
    inst = instructors.get(s["instructor_id"])
    if inst:
        inst["sessions_completed"] += 1
        if inst["sessions_completed"] >= SENIOR_UPGRADE_THRESHOLD:
            inst["tier"] = "SENIOR"
        touch(inst)
    session_flights = [f for f in flights.values() if f["session_id"] == sid]
    for f in session_flights:
        if f["status"] in ("SCHEDULED", "CHECKED_IN"):
            # auto no-show: minutes forfeited (no refund)
            f["status"] = "NO_SHOW"
            touch(f)
        elif f["status"] == "ABORTED":
            # reconcile provisional -> final reflight credit
            final = f["scheduled_minutes"] - f["flown_minutes"]
            delta = final - f["reflight_credit_granted"]
            f["reflight_credit_granted"] = final
            touch(f)
            m = members.get(f["member_id"])
            if m and delta != 0:
                m["reflight_credit_minutes"] += delta
                m["total_credits_minted"] += delta
                touch(m)
        elif f["status"] == "FLOWN":
            # finalize (already scheduled_minutes; no-op if unchanged)
            if f["minutes_charged"] != f["scheduled_minutes"]:
                f["minutes_charged"] = f["scheduled_minutes"]
                touch(f)
    # deliver REQUESTED coaching on this session's flights
    flight_ids = {f["id"] for f in session_flights}
    for cb in coachings.values():
        if cb["flight_id"] in flight_ids and cb["status"] == "REQUESTED":
            cb["status"] = "DELIVERED"
            touch(cb)
    s["op_status"] = "CLOSED"
    touch(s)
    recompute_seats(sid)
    return success(public(s))


@app.route("/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    require({"FrontDesk", "Manager"})
    s = must_exist(sessions, sid, "session")
    if s["op_status"] not in ("OPEN", "RUNNING"):
        raise ApiError("ERR_INVALID_STATE", 409, "session not cancellable")
    for f in flights.values():
        if f["session_id"] == sid and f["status"] in ("SCHEDULED", "CHECKED_IN"):
            f["status"] = "CANCELLED"
            touch(f)
            b = bookings.get(f["booking_id"])
            if b:
                refund_minutes(b, f["scheduled_minutes"])
            cancel_flight_coaching(f["id"])
    s["op_status"] = "CANCELLED"
    touch(s)
    recompute_seats(sid)
    return success(public(s))


# =============================================================================
# FLIGHTS
# =============================================================================
@app.route("/flights", methods=["POST"])
def create_flight():
    require({"Flyer", "FrontDesk"})
    body = get_body()
    booking_id = req_str(body, "booking_id")
    session_id = req_str(body, "session_id")
    member_id = req_str(body, "member_id")
    scheduled_minutes = req_int(body, "scheduled_minutes")
    # existence order: member_id, booking_id, session_id
    must_exist(members, member_id, "member")
    b = must_exist(bookings, booking_id, "booking")
    s = must_exist(sessions, session_id, "session")
    # state (priority 4)
    if s["op_status"] not in ("OPEN", "RUNNING"):
        raise ApiError("ERR_INVALID_STATE", 409, "session not open for flights")
    if b["status"] not in ("CONFIRMED", "EXHAUSTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "booking not active")
    # eligibility (priority 5): staffed
    if s["staffing_status"] != "STAFFED":
        raise ApiError("ERR_SESSION_NOT_STAFFED", 409, "session not staffed")
    # structural (priority 8): seat available
    if s["seats_available"] < 1:
        raise ApiError("ERR_SESSION_FULL", 422, "session full")
    # fiscal (priority 9): sufficient minutes
    if b["minutes_remaining"] < scheduled_minutes:
        raise ApiError("ERR_INSUFFICIENT_MINUTES", 422, "insufficient minutes")
    f = new_common()
    f.update({
        "booking_id": booking_id,
        "session_id": session_id,
        "member_id": member_id,
        "scheduled_minutes": scheduled_minutes,
        "status": "SCHEDULED",
        "minutes_charged": 0,
        "flown_minutes": 0,
        "reflight_credit_granted": 0,
        "video_addon_purchased": False,
        "video_charge_cents": 0,
    })
    flights[f["id"]] = f
    consume_minutes(b, scheduled_minutes)
    recompute_seats(session_id)
    return success(public(f), status=201)


@app.route("/flights/<fid>", methods=["GET"])
def get_flight(fid):
    require({"Flyer", "FrontDesk", "Manager", "Instructor"})
    f = must_exist(flights, fid, "flight")
    return success(public(f))


@app.route("/flights", methods=["GET"])
def list_flights():
    require({"Flyer", "FrontDesk", "Manager", "Instructor"})
    booking_id = request.args.get("booking_id")
    session_id = request.args.get("session_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = []
    for f in flights.values():
        if booking_id is not None and f["booking_id"] != booking_id:
            continue
        if session_id is not None and f["session_id"] != session_id:
            continue
        if member_id is not None and f["member_id"] != member_id:
            continue
        if status is not None and f["status"] != status:
            continue
        items.append(f)
    return list_response(items, public)


@app.route("/flights/<fid>/check-in", methods=["POST"])
def checkin_flight(fid):
    require({"Instructor", "FrontDesk"})
    f = must_exist(flights, fid, "flight")
    s = sessions.get(f["session_id"])
    # state (priority 4)
    if f["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "flight not SCHEDULED")
    if s is None or s["op_status"] not in ("OPEN", "RUNNING"):
        raise ApiError("ERR_INVALID_STATE", 409, "session not open for check-in")
    m = members.get(f["member_id"])
    # safety gates (priority 6): waiver then weight
    has_valid_waiver = any(
        w["member_id"] == f["member_id"] and waiver_status(w) == "SIGNED"
        for w in waivers.values()
    )
    if not has_valid_waiver:
        raise ApiError("ERR_WAIVER_INVALID", 422, "no valid waiver")
    t = tunnels.get(s["tunnel_id"])
    if t is not None and m is not None and m["weight_kg"] > t["max_weight_kg"]:
        raise ApiError("ERR_WEIGHT_LIMIT_EXCEEDED", 422, "weight limit exceeded")
    f["status"] = "CHECKED_IN"
    touch(f)
    return success(public(f))


@app.route("/flights/<fid>/complete", methods=["POST"])
def complete_flight(fid):
    require({"Instructor"})
    f = must_exist(flights, fid, "flight")
    s = sessions.get(f["session_id"])
    if f["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "flight not CHECKED_IN")
    if s is None or s["op_status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "session not RUNNING")
    f["minutes_charged"] = f["scheduled_minutes"]
    f["status"] = "FLOWN"
    touch(f)
    return success(public(f))


@app.route("/flights/<fid>/abort", methods=["POST"])
def abort_flight(fid):
    require({"Instructor"})
    body = get_body()
    flown_minutes = req_int(body, "flown_minutes")
    f = must_exist(flights, fid, "flight")
    s = sessions.get(f["session_id"])
    if f["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "flight not CHECKED_IN")
    if s is None or s["op_status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "session not RUNNING")
    # CASCADE A: refund scheduled_minutes to booking
    b = bookings.get(f["booking_id"])
    if b:
        refund_minutes(b, f["scheduled_minutes"])
    # provisional reflight credit
    m = members.get(f["member_id"])
    f["reflight_credit_granted"] = f["scheduled_minutes"]
    if m:
        m["reflight_credit_minutes"] += f["scheduled_minutes"]
        m["total_credits_minted"] += f["scheduled_minutes"]
        touch(m)
    f["flown_minutes"] = flown_minutes
    f["minutes_charged"] = 0
    f["status"] = "ABORTED"
    touch(f)
    recompute_seats(f["session_id"])
    return success(public(f))


@app.route("/flights/<fid>/no-show", methods=["POST"])
def noshow_flight(fid):
    require({"FrontDesk", "Instructor"})
    f = must_exist(flights, fid, "flight")
    if f["status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "flight not eligible for no-show")
    f["status"] = "NO_SHOW"
    touch(f)
    recompute_seats(f["session_id"])
    cancel_flight_coaching(f["id"])
    return success(public(f))


@app.route("/flights/<fid>/cancel", methods=["POST"])
def cancel_flight(fid):
    require({"FrontDesk", "Flyer"})
    f = must_exist(flights, fid, "flight")
    if f["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "flight not SCHEDULED")
    f["status"] = "CANCELLED"
    touch(f)
    b = bookings.get(f["booking_id"])
    if b:
        refund_minutes(b, f["scheduled_minutes"])
    recompute_seats(f["session_id"])
    cancel_flight_coaching(f["id"])
    return success(public(f))


@app.route("/flights/<fid>/video", methods=["POST"])
def video_flight(fid):
    require({"FrontDesk", "Flyer"})
    f = must_exist(flights, fid, "flight")
    m = members.get(f["member_id"])
    f["video_addon_purchased"] = True
    f["video_charge_cents"] = video_line(m) if m else 0
    touch(f)
    if m:
        recompute_outstanding(f["member_id"])
    return success(public(f))


# =============================================================================
# COACHING
# =============================================================================
@app.route("/coaching-bookings", methods=["POST"])
def create_coaching():
    require({"FrontDesk", "Flyer"})
    body = get_body()
    flight_id = req_str(body, "flight_id")
    instructor_id = req_str(body, "instructor_id")
    minutes = req_int(body, "minutes")
    # existence order: instructor_id before flight_id
    must_exist(instructors, instructor_id, "instructor")
    f = must_exist(flights, flight_id, "flight")
    m = members.get(f["member_id"])
    charge = coaching_line(m, minutes) if m else 0
    cb = new_common()
    cb.update({
        "flight_id": flight_id,
        "instructor_id": instructor_id,
        "minutes": minutes,
        "charge_cents": charge,
        "status": "REQUESTED",
    })
    coachings[cb["id"]] = cb
    if m:
        recompute_outstanding(f["member_id"])
    return success(public(cb), status=201)


@app.route("/coaching-bookings/<cid>", methods=["GET"])
def get_coaching(cid):
    require({"Flyer", "FrontDesk", "Manager", "Instructor"})
    cb = must_exist(coachings, cid, "coaching")
    return success(public(cb))


@app.route("/coaching-bookings", methods=["GET"])
def list_coaching():
    require({"Flyer", "FrontDesk", "Manager", "Instructor"})
    flight_id = request.args.get("flight_id")
    instructor_id = request.args.get("instructor_id")
    status = request.args.get("status")
    items = []
    for cb in coachings.values():
        if flight_id is not None and cb["flight_id"] != flight_id:
            continue
        if instructor_id is not None and cb["instructor_id"] != instructor_id:
            continue
        if status is not None and cb["status"] != status:
            continue
        items.append(cb)
    return list_response(items, public)


# =============================================================================
# CLOCK
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require({"Manager", "FrontDesk"})
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    dt = parse_dt(to_iso)
    _clock[0] = dt
    return success({"current_utc": iso(dt)})


# =============================================================================
# Entrypoint
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
