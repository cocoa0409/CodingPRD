"""House-Swap & Home-Exchange Network API.

Single-file Flask implementation. In-memory storage only; every process boot
starts with an empty store and the logical clock at 2026-07-01T00:00:00Z.
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Anonymous", "Member", "PlatformAdmin"}

MIN_EXCHANGE_POINTS = 100
REQUEST_TTL_DAYS = 7
TRAVEL_BUFFER_DAYS = 1
MEMBERSHIP_TERM_DAYS = 365

PEAK_MONTHS = {6, 7, 8, 12}
SHOULDER_MONTHS = {3, 4, 5, 9, 10, 11}
# off = {1, 2}

SEASON_PEAK = Decimal("1.5")
SEASON_SHOULDER = Decimal("1.2")
SEASON_OFF = Decimal("1.0")

MEMBERSHIP_DISCOUNT = {
    "BASIC": Decimal("0"),
    "PLUS": Decimal("0.10"),
    "PREMIER": Decimal("0.20"),
}
WELCOME_BONUS = {"BASIC": 500, "PLUS": 1000, "PREMIER": 2000}
COVERAGE_LIMIT = {"BASIC": 2000, "PLUS": 5000, "PREMIER": 10000}

FIXED_DEDUCTIBLE_POINTS = 50

CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.members = {}
        self.memberships = {}
        self.listings = {}
        self.windows = {}
        self.verifications = {}
        self.requests = {}
        self.agreements = {}
        self.ledger = {}
        self.claims = {}
        self.disputes = {}
        self.clock = CLOCK_DEFAULT
        self.seq = 0


db = Store()


def next_seq():
    db.seq += 1
    return db.seq


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(dt.microsecond // 1000)


def parse_instant(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", "invalid timestamp", 400)
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise ApiError("ERR_VALIDATION", "invalid timestamp", 400)


def parse_date(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", "invalid date", 400)
    try:
        return date.fromisoformat(s)
    except Exception:
        raise ApiError("ERR_VALIDATION", "invalid date", 400)


def rhu(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Errors & envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def _meta(pagination=None):
    m = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


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
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Base record helper
# ---------------------------------------------------------------------------
def base_record():
    ts = now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}


def bump(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now()


# ---------------------------------------------------------------------------
# Auth / body helpers
# ---------------------------------------------------------------------------
def authenticate(exempt=False):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if exempt:
        g.role = role
        g.uid = uid
        return
    if not role or not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or invalid auth headers", 401)
    g.role = role
    g.uid = uid


def require_roles(allowed):
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "role not permitted for this operation", 403)


def get_body():
    b = request.get_json(silent=True)
    if b is None or not isinstance(b, dict):
        return {}
    return b


def req_str(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "missing field: " + key, 400)
        return None
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", "invalid field: " + key, 400)
    return v


def req_int(body, key, required=True, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "missing field: " + key, 400)
        return None
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "invalid integer: " + key, 400)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", "integer below range: " + key, 400)
    if maximum is not None and v > maximum:
        raise ApiError("ERR_VALIDATION", "integer above range: " + key, 400)
    return v


def req_enum(body, key, choices, required=True):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "missing field: " + key, 400)
        return None
    v = body[key]
    if v not in choices:
        raise ApiError("ERR_VALIDATION", "invalid enum: " + key, 400)
    return v


def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except Exception:
            raise ApiError("ERR_VALIDATION", "invalid limit", 400)
        if limit_v < 1 or limit_v > 100:
            raise ApiError("ERR_VALIDATION", "limit out of range", 400)
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except Exception:
            raise ApiError("ERR_VALIDATION", "invalid offset", 400)
        if offset_v < 0:
            raise ApiError("ERR_VALIDATION", "offset out of range", 400)
    return limit_v, offset_v


def paginate(items):
    """items: full list already sorted. Applies limit/offset and returns (page, pagination)."""
    limit_v, offset_v = parse_pagination()
    total = len(items)
    page = items[offset_v:offset_v + limit_v]
    pag = {
        "limit": limit_v,
        "offset": offset_v,
        "total_count": total,
        "has_more": offset_v + limit_v < total,
    }
    return page, pag


def sorted_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


# ---------------------------------------------------------------------------
# Existence getters
# ---------------------------------------------------------------------------
def get_member(mid):
    m = db.members.get(mid)
    if m is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member not found", 404)
    return m


def get_membership(mid):
    m = db.memberships.get(mid)
    if m is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND", "membership not found", 404)
    return m


def get_listing(lid):
    l = db.listings.get(lid)
    if l is None:
        raise ApiError("ERR_LISTING_NOT_FOUND", "listing not found", 404)
    return l


def get_window(wid):
    w = db.windows.get(wid)
    if w is None:
        raise ApiError("ERR_AVAILABILITY_WINDOW_NOT_FOUND", "availability window not found", 404)
    return w


def get_verification(vid):
    v = db.verifications.get(vid)
    if v is None:
        raise ApiError("ERR_VERIFICATION_NOT_FOUND", "verification not found", 404)
    return v


def get_request(rid):
    r = db.requests.get(rid)
    if r is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND", "exchange request not found", 404)
    return r


def get_agreement(aid):
    a = db.agreements.get(aid)
    if a is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", "exchange agreement not found", 404)
    return a


def get_claim(cid):
    c = db.claims.get(cid)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "damage claim not found", 404)
    return c


def get_dispute(did):
    d = db.disputes.get(did)
    if d is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", "dispute not found", 404)
    return d


# ---------------------------------------------------------------------------
# Computed member fields
# ---------------------------------------------------------------------------
def member_verification_status(mid):
    for v in db.verifications.values():
        if v["member_id"] == mid and v["verification_type"] == "IDENTITY" and v["status"] == "VERIFIED":
            return "VERIFIED"
    return "UNVERIFIED"


def active_membership(mid):
    for m in db.memberships.values():
        if m["member_id"] == mid and m["status"] == "ACTIVE":
            return m
    return None


def active_membership_tier(mid):
    m = active_membership(mid)
    return m["tier"] if m else None


def settled_balance(mid):
    return sum(e["amount"] for e in db.ledger.values()
               if e["member_id"] == mid and e["status"] == "POSTED")


def available_balance(mid):
    return sum(e["amount"] for e in db.ledger.values()
               if e["member_id"] == mid and e["status"] in ("POSTED", "HELD"))


def trust_score(member):
    raw = (50
           + 2 * member["completed_exchange_count"]
           - 10 * member["upheld_damage_count"]
           - 15 * member["disputes_lost_count"])
    return max(0, min(100, raw))


def listing_night_totals(lid):
    open_n = 0
    booked_n = 0
    for w in db.windows.values():
        if w["listing_id"] == lid:
            if w["status"] == "OPEN":
                open_n += w["nights"]
            elif w["status"] == "BOOKED":
                booked_n += w["nights"]
    return open_n, booked_n


# ---------------------------------------------------------------------------
# Ledger helper
# ---------------------------------------------------------------------------
def post_ledger(member_id, entry_type, amount, status="POSTED", agreement_id=None, memo=""):
    e = {
        "id": new_id(),
        "created_at": now(),
        "_seq": next_seq(),
        "member_id": member_id,
        "agreement_id": agreement_id,
        "entry_type": entry_type,
        "amount": int(amount),
        "status": status,
        "memo": memo or "",
    }
    db.ledger[e["id"]] = e
    return e


def recompute_balances(member):
    # balances are derived on read; the recompute is a mutation -> bump.
    bump(member)


def recompute_trust(member):
    bump(member)


def void_hold(req_obj):
    hid = req_obj.get("hold_ledger_entry_id")
    if hid and hid in db.ledger and db.ledger[hid]["status"] == "HELD":
        db.ledger[hid]["status"] = "VOIDED"
        member = db.members.get(req_obj["requester_member_id"])
        if member:
            recompute_balances(member)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def season_mult(month):
    if month in PEAK_MONTHS:
        return SEASON_PEAK
    if month in SHOULDER_MONTHS:
        return SEASON_SHOULDER
    return SEASON_OFF


def compute_points_cost(listing, start_d, end_d, tier):
    discount = MEMBERSHIP_DISCOUNT.get(tier, Decimal("0"))
    ppn = Decimal(listing["points_per_night"])
    total = 0
    d = start_d
    while d < end_d:
        nightly = rhu(ppn * season_mult(d.month) * (Decimal("1") - discount))
        total += nightly
        d = d + timedelta(days=1)
    cost = max(MIN_EXCHANGE_POINTS, min(total, listing["max_points_per_exchange"]))
    return cost


def cancellation_refund(points_cost, check_in_str):
    ci = parse_date(check_in_str)
    days_before = (ci - now().date()).days
    if days_before >= 7:
        pct = Decimal("1.0")
    elif days_before >= 2:
        pct = Decimal("0.5")
    else:
        pct = Decimal("0.0")
    return rhu(Decimal(points_cost) * pct)


def damage_payout(amount, coverage_limit):
    if amount <= 500:
        rate = Decimal("0.20")
    elif amount <= 2000:
        rate = Decimal("0.10")
    else:
        rate = Decimal("0.05")
    deductible = max(FIXED_DEDUCTIBLE_POINTS, rhu(Decimal(amount) * rate))
    payout = max(0, min(amount, coverage_limit) - deductible)
    return payout, deductible


def stays_too_close(s1, e1, s2, e2):
    """closed-interval stays; conflict if overlap, abut, or gap <= TRAVEL_BUFFER_DAYS."""
    if e1 < s2:
        gap = (s2 - e1).days
    elif e2 < s1:
        gap = (s1 - e2).days
    else:
        return True  # overlap
    return gap <= TRAVEL_BUFFER_DAYS


# ---------------------------------------------------------------------------
# Lazy expiry
# ---------------------------------------------------------------------------
def run_expiry():
    cur = now()
    for r in list(db.requests.values()):
        if r["status"] in ("PROPOSED", "COUNTERED") and r.get("expires_at") and cur >= r["expires_at"]:
            r["status"] = "EXPIRED"
            bump(r)
            if r["exchange_type"] == "POINTS":
                void_hold(r)
    for m in list(db.memberships.values()):
        if m["status"] == "ACTIVE" and m.get("expires_at") and cur >= m["expires_at"]:
            m["status"] = "EXPIRED"
            bump(m)


@app.before_request
def _before():
    run_expiry()


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_common(o):
    return {
        "id": o["id"],
        "created_at": fmt_ts(o["created_at"]),
        "updated_at": fmt_ts(o["updated_at"]),
        "version": o["version"],
    }


def ser_member(m):
    d = ser_common(m)
    d.update({
        "email": m["email"],
        "full_name": m["full_name"],
        "home_city": m["home_city"],
        "verification_status": member_verification_status(m["id"]),
        "active_membership_tier": active_membership_tier(m["id"]),
        "settled_points_balance": settled_balance(m["id"]),
        "available_points_balance": available_balance(m["id"]),
        "trust_score": trust_score(m),
        "completed_exchange_count": m["completed_exchange_count"],
        "upheld_damage_count": m["upheld_damage_count"],
        "disputes_lost_count": m["disputes_lost_count"],
    })
    return d


def ser_membership(m):
    d = ser_common(m)
    d.update({
        "member_id": m["member_id"],
        "tier": m["tier"],
        "status": m["status"],
        "activated_at": fmt_ts(m["activated_at"]),
        "expires_at": fmt_ts(m["expires_at"]),
    })
    return d


def ser_listing(l):
    d = ser_common(l)
    open_n, booked_n = listing_night_totals(l["id"])
    d.update({
        "owner_member_id": l["owner_member_id"],
        "title": l["title"],
        "address_city": l["address_city"],
        "address_country": l["address_country"],
        "points_per_night": l["points_per_night"],
        "max_points_per_exchange": l["max_points_per_exchange"],
        "min_trust_score": l["min_trust_score"],
        "capacity": l["capacity"],
        "status": l["status"],
        "open_nights": open_n,
        "booked_nights": booked_n,
    })
    return d


def ser_window(w):
    d = ser_common(w)
    d.update({
        "listing_id": w["listing_id"],
        "start_date": w["start_date"],
        "end_date": w["end_date"],
        "nights": w["nights"],
        "status": w["status"],
    })
    return d


def ser_verification(v):
    d = ser_common(v)
    d.update({
        "member_id": v["member_id"],
        "verification_type": v["verification_type"],
        "document_ref": v["document_ref"],
        "status": v["status"],
        "decided_by": v["decided_by"],
    })
    return d


def ser_request(r):
    d = ser_common(r)
    d.update({
        "requester_member_id": r["requester_member_id"],
        "target_listing_id": r["target_listing_id"],
        "offered_listing_id": r["offered_listing_id"],
        "exchange_type": r["exchange_type"],
        "requested_start_date": r["requested_start_date"],
        "requested_end_date": r["requested_end_date"],
        "points_cost": r["points_cost"],
        "hold_ledger_entry_id": r["hold_ledger_entry_id"],
        "status": r["status"],
        "expires_at": fmt_ts(r["expires_at"]),
    })
    return d


def ser_agreement(a):
    d = ser_common(a)
    d.update({
        "request_id": a["request_id"],
        "guest_member_id": a["guest_member_id"],
        "host_member_id": a["host_member_id"],
        "listing_id": a["listing_id"],
        "availability_window_id": a["availability_window_id"],
        "exchange_type": a["exchange_type"],
        "check_in": a["check_in"],
        "check_out": a["check_out"],
        "points_cost": a["points_cost"],
        "coverage_limit_points": a["coverage_limit_points"],
        "insurance_status": a["insurance_status"],
        "refund_points": a["refund_points"],
        "status": a["status"],
    })
    return d


def ser_ledger(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "member_id": e["member_id"],
        "agreement_id": e["agreement_id"],
        "entry_type": e["entry_type"],
        "amount": e["amount"],
        "status": e["status"],
        "memo": e["memo"],
    }


def ser_claim(c):
    d = ser_common(c)
    d.update({
        "agreement_id": c["agreement_id"],
        "claimant_member_id": c["claimant_member_id"],
        "respondent_member_id": c["respondent_member_id"],
        "claimed_amount": c["claimed_amount"],
        "assessed_amount": c["assessed_amount"],
        "provisional_payout": c["provisional_payout"],
        "deductible_points": c["deductible_points"],
        "final_payout": c["final_payout"],
        "status": c["status"],
    })
    return d


def ser_dispute(d0):
    d = ser_common(d0)
    d.update({
        "agreement_id": d0["agreement_id"],
        "opened_by_member_id": d0["opened_by_member_id"],
        "respondent_member_id": d0["respondent_member_id"],
        "reason": d0["reason"],
        "penalty_points": d0["penalty_points"],
        "resolution_note": d0["resolution_note"],
        "status": d0["status"],
    })
    return d


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
@app.route("/members/register", methods=["POST"])
def register_member():
    authenticate(exempt=True)
    body = get_body()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    home_city = req_str(body, "home_city")
    for m in db.members.values():
        if m["email"] == email:
            raise ApiError("ERR_VALIDATION", "email already registered", 400)
    m = base_record()
    m.update({
        "email": email,
        "full_name": full_name,
        "home_city": home_city,
        "completed_exchange_count": 0,
        "upheld_damage_count": 0,
        "disputes_lost_count": 0,
    })
    db.members[m["id"]] = m
    return ok(ser_member(m), status=201)


@app.route("/members/<mid>", methods=["GET"])
def fetch_member(mid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    m = get_member(mid)
    return ok(ser_member(m))


@app.route("/members/<mid>/points-adjustments", methods=["POST"])
def points_adjustment(mid):
    authenticate()
    require_roles({"PlatformAdmin"})
    m = get_member(mid)
    body = get_body()
    amount = req_int(body, "amount")
    memo = req_str(body, "memo", required=False) or ""
    e = post_ledger(mid, "ADMIN_ADJUSTMENT", amount, status="POSTED", memo=memo)
    recompute_balances(m)
    return ok(ser_ledger(e), status=201)


def _list_response(items, serializer):
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return ok([serializer(x) for x in page], response_type="array", pagination=pag)


@app.route("/members/<mid>/ledger-entries", methods=["GET"])
def list_member_ledger(mid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    get_member(mid)
    items = [e for e in db.ledger.values() if e["member_id"] == mid]
    return _list_response(items, ser_ledger)


@app.route("/members/<mid>/memberships", methods=["GET"])
def list_member_memberships(mid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    get_member(mid)
    items = [x for x in db.memberships.values() if x["member_id"] == mid]
    return _list_response(items, ser_membership)


@app.route("/members/<mid>/home-listings", methods=["GET"])
def list_member_listings(mid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    get_member(mid)
    items = [x for x in db.listings.values() if x["owner_member_id"] == mid]
    return _list_response(items, ser_listing)


@app.route("/members/<mid>/verifications", methods=["GET"])
def list_member_verifications(mid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    get_member(mid)
    items = [x for x in db.verifications.values() if x["member_id"] == mid]
    return _list_response(items, ser_verification)


@app.route("/members/<mid>/exchange-requests", methods=["GET"])
def list_member_requests(mid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    get_member(mid)
    items = [x for x in db.requests.values() if x["requester_member_id"] == mid]
    return _list_response(items, ser_request)


# ---------------------------------------------------------------------------
# Memberships
# ---------------------------------------------------------------------------
@app.route("/memberships", methods=["POST"])
def create_membership():
    authenticate()
    require_roles({"Member"})
    body = get_body()
    if "member_id" in body and body["member_id"] is not None and body["member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "cannot act on another member", 403)
    member_id = req_str(body, "member_id")
    get_member(member_id)
    tier = req_enum(body, "tier", {"BASIC", "PLUS", "PREMIER"})
    m = base_record()
    m.update({
        "member_id": member_id,
        "tier": tier,
        "status": "PENDING_ACTIVATION",
        "activated_at": None,
        "expires_at": None,
    })
    db.memberships[m["id"]] = m
    return ok(ser_membership(m), status=201)


@app.route("/memberships/<mid>/activate", methods=["POST"])
def activate_membership(mid):
    authenticate()
    require_roles({"PlatformAdmin"})
    m = get_membership(mid)
    if m["status"] != "PENDING_ACTIVATION":
        raise ApiError("ERR_INVALID_STATE", "membership not pending activation", 409)
    if active_membership(m["member_id"]) is not None:
        raise ApiError("ERR_DUPLICATE_ACTIVE_MEMBERSHIP", "member already has an active membership", 409)
    m["status"] = "ACTIVE"
    m["activated_at"] = now()
    m["expires_at"] = now() + timedelta(days=MEMBERSHIP_TERM_DAYS)
    bump(m)
    member = db.members.get(m["member_id"])
    post_ledger(m["member_id"], "WELCOME_BONUS", WELCOME_BONUS[m["tier"]], status="POSTED",
                memo="welcome bonus " + m["tier"])
    if member:
        recompute_balances(member)
    return ok(ser_membership(m))


@app.route("/memberships/<mid>/cancel", methods=["POST"])
def cancel_membership(mid):
    authenticate()
    require_roles({"Member"})
    m = get_membership(mid)
    if m["member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "cannot cancel another member's membership", 403)
    if m["status"] not in ("PENDING_ACTIVATION", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", "membership not cancellable", 409)
    m["status"] = "CANCELLED"
    bump(m)
    return ok(ser_membership(m))


# ---------------------------------------------------------------------------
# Verifications
# ---------------------------------------------------------------------------
@app.route("/verifications", methods=["POST"])
def create_verification():
    authenticate()
    require_roles({"Member"})
    body = get_body()
    if "member_id" in body and body["member_id"] is not None and body["member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "cannot act on another member", 403)
    member_id = req_str(body, "member_id")
    get_member(member_id)
    vtype = req_enum(body, "verification_type", {"IDENTITY", "HOME"})
    document_ref = req_str(body, "document_ref")
    v = base_record()
    v.update({
        "member_id": member_id,
        "verification_type": vtype,
        "document_ref": document_ref,
        "status": "PENDING_REVIEW",
        "decided_by": None,
    })
    db.verifications[v["id"]] = v
    return ok(ser_verification(v), status=201)


@app.route("/verifications/<vid>/decide", methods=["POST"])
def decide_verification(vid):
    authenticate()
    require_roles({"PlatformAdmin"})
    v = get_verification(vid)
    if v["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "verification not pending review", 409)
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "REJECT"})
    v["decided_by"] = g.uid
    if decision == "APPROVE":
        v["status"] = "VERIFIED"
        if v["verification_type"] == "IDENTITY":
            member = db.members.get(v["member_id"])
            if member:
                bump(member)
    else:
        v["status"] = "REJECTED"
    bump(v)
    return ok(ser_verification(v))


# ---------------------------------------------------------------------------
# Home listings
# ---------------------------------------------------------------------------
@app.route("/home-listings", methods=["POST"])
def create_listing():
    authenticate()
    require_roles({"Member"})
    body = get_body()
    if "owner_member_id" in body and body["owner_member_id"] is not None and body["owner_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "cannot create a listing for another member", 403)
    owner_member_id = req_str(body, "owner_member_id")
    get_member(owner_member_id)
    title = req_str(body, "title")
    address_city = req_str(body, "address_city")
    address_country = req_str(body, "address_country")
    points_per_night = req_int(body, "points_per_night", minimum=1)
    max_points_per_exchange = req_int(body, "max_points_per_exchange", minimum=MIN_EXCHANGE_POINTS)
    capacity = req_int(body, "capacity", minimum=1)
    min_trust_score = req_int(body, "min_trust_score", required=False, minimum=0, maximum=100)
    if min_trust_score is None:
        min_trust_score = 0
    l = base_record()
    l.update({
        "owner_member_id": owner_member_id,
        "title": title,
        "address_city": address_city,
        "address_country": address_country,
        "points_per_night": points_per_night,
        "max_points_per_exchange": max_points_per_exchange,
        "capacity": capacity,
        "min_trust_score": min_trust_score,
        "status": "DRAFT",
    })
    db.listings[l["id"]] = l
    return ok(ser_listing(l), status=201)


@app.route("/home-listings/<lid>", methods=["GET"])
def fetch_listing(lid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    l = get_listing(lid)
    return ok(ser_listing(l))


@app.route("/home-listings/<lid>/activate", methods=["POST"])
def activate_listing(lid):
    authenticate()
    require_roles({"Member"})
    l = get_listing(lid)
    if l["owner_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "only the owner may activate", 403)
    if l["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "listing not in DRAFT", 409)
    if member_verification_status(l["owner_member_id"]) != "VERIFIED":
        raise ApiError("ERR_MEMBER_NOT_VERIFIED", "owner is not verified", 403)
    l["status"] = "ACTIVE"
    bump(l)
    return ok(ser_listing(l))


@app.route("/home-listings/<lid>/availability-windows", methods=["POST"])
def create_window(lid):
    authenticate()
    require_roles({"Member"})
    l = get_listing(lid)
    if l["owner_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "only the owner may add windows", 403)
    body = get_body()
    start_s = req_str(body, "start_date")
    end_s = req_str(body, "end_date")
    start_d = parse_date(start_s)
    end_d = parse_date(end_s)
    if end_d <= start_d:
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_date must be after start_date", 422)
    w = base_record()
    w.update({
        "listing_id": lid,
        "start_date": start_s,
        "end_date": end_s,
        "nights": (end_d - start_d).days,
        "status": "OPEN",
    })
    db.windows[w["id"]] = w
    return ok(ser_window(w), status=201)


@app.route("/home-listings/<lid>/availability-windows", methods=["GET"])
def list_windows(lid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    get_listing(lid)
    items = [w for w in db.windows.values() if w["listing_id"] == lid]
    return _list_response(items, ser_window)


@app.route("/home-listings/<lid>/exchange-requests", methods=["GET"])
def list_listing_requests(lid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    get_listing(lid)
    items = [r for r in db.requests.values()
             if r["target_listing_id"] == lid or r["offered_listing_id"] == lid]
    return _list_response(items, ser_request)


@app.route("/availability-windows/<wid>", methods=["GET"])
def fetch_window(wid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    w = get_window(wid)
    return ok(ser_window(w))


# ---------------------------------------------------------------------------
# Exchange requests
# ---------------------------------------------------------------------------
@app.route("/exchange-requests", methods=["POST"])
def create_request():
    authenticate()
    require_roles({"Member"})
    body = get_body()
    if "requester_member_id" in body and body["requester_member_id"] is not None and body["requester_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "cannot open a request for another member", 403)
    requester_id = req_str(body, "requester_member_id")
    requester = get_member(requester_id)
    target_listing_id = req_str(body, "target_listing_id")
    listing = get_listing(target_listing_id)
    offered_listing_id = req_str(body, "offered_listing_id", required=False)
    if offered_listing_id is not None:
        get_listing(offered_listing_id)
    exchange_type = req_enum(body, "exchange_type", {"POINTS", "RECIPROCAL"})
    start_s = req_str(body, "requested_start_date")
    end_s = req_str(body, "requested_end_date")
    start_d = parse_date(start_s)
    end_d = parse_date(end_s)
    if end_d <= start_d:
        raise ApiError("ERR_INVALID_DATE_RANGE", "requested_end_date must be after requested_start_date", 422)

    # business rules in fixed order
    if listing["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", "target listing is not active", 409)
    tier = active_membership_tier(requester_id)
    if tier is None:
        raise ApiError("ERR_MEMBERSHIP_INACTIVE", "requester has no active membership", 409)
    if trust_score(requester) < listing["min_trust_score"]:
        raise ApiError("ERR_TRUST_TOO_LOW", "requester trust score too low", 403)

    if exchange_type == "POINTS":
        points_cost = compute_points_cost(listing, start_d, end_d, tier)
    else:
        points_cost = 0

    if exchange_type == "POINTS":
        if available_balance(requester_id) < points_cost:
            raise ApiError("ERR_INSUFFICIENT_POINTS", "insufficient available points", 402)

    r = base_record()
    r.update({
        "requester_member_id": requester_id,
        "target_listing_id": target_listing_id,
        "offered_listing_id": offered_listing_id,
        "exchange_type": exchange_type,
        "requested_start_date": start_s,
        "requested_end_date": end_s,
        "points_cost": points_cost,
        "hold_ledger_entry_id": None,
        "status": "PROPOSED",
        "expires_at": now() + timedelta(days=REQUEST_TTL_DAYS),
    })
    if exchange_type == "POINTS":
        hold = post_ledger(requester_id, "EXCHANGE_HOLD", -points_cost, status="HELD",
                           memo="hold for exchange request")
        r["hold_ledger_entry_id"] = hold["id"]
        recompute_balances(requester)
    db.requests[r["id"]] = r
    return ok(ser_request(r), status=201)


@app.route("/exchange-requests/<rid>", methods=["GET"])
def fetch_request(rid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    r = get_request(rid)
    return ok(ser_request(r))


def _recompute_hold(r, listing):
    """Recompute points_cost and update HELD hold for a POINTS request."""
    tier = active_membership_tier(r["requester_member_id"])
    start_d = parse_date(r["requested_start_date"])
    end_d = parse_date(r["requested_end_date"])
    if r["exchange_type"] == "POINTS":
        cost = compute_points_cost(listing, start_d, end_d, tier)
    else:
        cost = 0
    r["points_cost"] = cost
    if r["exchange_type"] == "POINTS":
        hid = r.get("hold_ledger_entry_id")
        if hid and hid in db.ledger and db.ledger[hid]["status"] == "HELD":
            db.ledger[hid]["amount"] = -cost
        member = db.members.get(r["requester_member_id"])
        if member:
            recompute_balances(member)


@app.route("/exchange-requests/<rid>/counter", methods=["POST"])
def counter_request(rid):
    authenticate()
    require_roles({"Member"})
    r = get_request(rid)
    listing = db.listings.get(r["target_listing_id"])
    if listing is None or listing["owner_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "only the host may counter", 403)
    if r["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "request not PROPOSED", 409)
    body = get_body()
    start_s = req_str(body, "requested_start_date")
    end_s = req_str(body, "requested_end_date")
    start_d = parse_date(start_s)
    end_d = parse_date(end_s)
    if end_d <= start_d:
        raise ApiError("ERR_INVALID_DATE_RANGE", "requested_end_date must be after requested_start_date", 422)
    r["requested_start_date"] = start_s
    r["requested_end_date"] = end_s
    r["status"] = "COUNTERED"
    _recompute_hold(r, listing)
    r["expires_at"] = now() + timedelta(days=REQUEST_TTL_DAYS)
    bump(r)
    return ok(ser_request(r))


@app.route("/exchange-requests/<rid>/repropose", methods=["POST"])
def repropose_request(rid):
    authenticate()
    require_roles({"Member"})
    r = get_request(rid)
    if r["requester_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "only the requester may repropose", 403)
    if r["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_STATE", "request not COUNTERED", 409)
    body = get_body()
    start_s = req_str(body, "requested_start_date", required=False)
    end_s = req_str(body, "requested_end_date", required=False)
    new_start = start_s if start_s is not None else r["requested_start_date"]
    new_end = end_s if end_s is not None else r["requested_end_date"]
    start_d = parse_date(new_start)
    end_d = parse_date(new_end)
    if end_d <= start_d:
        raise ApiError("ERR_INVALID_DATE_RANGE", "requested_end_date must be after requested_start_date", 422)
    r["requested_start_date"] = new_start
    r["requested_end_date"] = new_end
    r["status"] = "PROPOSED"
    listing = db.listings.get(r["target_listing_id"])
    _recompute_hold(r, listing)
    r["expires_at"] = now() + timedelta(days=REQUEST_TTL_DAYS)
    bump(r)
    return ok(ser_request(r))


@app.route("/exchange-requests/<rid>/accept", methods=["POST"])
def accept_request(rid):
    authenticate()
    require_roles({"Member"})
    r = get_request(rid)
    listing = db.listings.get(r["target_listing_id"])
    if listing is None or listing["owner_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "only the host may accept", 403)
    body = get_body()
    window_id = req_str(body, "availability_window_id")
    expected_version = req_int(body, "expected_listing_version")
    window = db.windows.get(window_id)
    if window is None or window["listing_id"] != r["target_listing_id"]:
        raise ApiError("ERR_AVAILABILITY_WINDOW_NOT_FOUND", "availability window not found", 404)
    if r["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "request not PROPOSED", 409)

    guest = db.members.get(r["requester_member_id"])
    host = db.members.get(listing["owner_member_id"])
    # business_safety: both verified
    if member_verification_status(r["requester_member_id"]) != "VERIFIED" or \
            member_verification_status(listing["owner_member_id"]) != "VERIFIED":
        raise ApiError("ERR_MEMBER_NOT_VERIFIED", "guest and host must be verified", 403)

    req_start = parse_date(r["requested_start_date"])
    req_end = parse_date(r["requested_end_date"])
    # availability: chosen window OPEN and no BOOKED window overlaps requested half-open span
    if window["status"] != "OPEN":
        raise ApiError("ERR_AVAILABILITY_CONFLICT", "chosen window not open", 409)
    for w in db.windows.values():
        if w["listing_id"] == r["target_listing_id"] and w["status"] == "BOOKED":
            ws = parse_date(w["start_date"])
            we = parse_date(w["end_date"])
            if ws < req_end and req_start < we:  # half-open overlap
                raise ApiError("ERR_AVAILABILITY_CONFLICT", "booked window overlaps requested span", 409)

    # traveler double-booked
    for a in db.agreements.values():
        if a["guest_member_id"] == r["requester_member_id"] and \
                a["status"] in ("PENDING_CONFIRMATION", "CONFIRMED", "IN_PROGRESS"):
            if stays_too_close(parse_date(a["check_in"]), parse_date(a["check_out"]), req_start, req_end):
                raise ApiError("ERR_TRAVELER_DOUBLE_BOOKED", "guest already has a nearby stay", 409)

    # OCC
    if expected_version != listing["version"]:
        raise ApiError("ERR_STALE_LISTING_VERSION", "listing version is stale", 412)

    # ---- cascade ----
    a = base_record()
    a.update({
        "request_id": r["id"],
        "guest_member_id": r["requester_member_id"],
        "host_member_id": listing["owner_member_id"],
        "listing_id": r["target_listing_id"],
        "availability_window_id": window_id,
        "exchange_type": r["exchange_type"],
        "check_in": r["requested_start_date"],
        "check_out": r["requested_end_date"],
        "points_cost": r["points_cost"],
        "coverage_limit_points": 0,
        "insurance_status": "NONE",
        "refund_points": 0,
        "status": "PENDING_CONFIRMATION",
    })
    db.agreements[a["id"]] = a

    window["status"] = "BOOKED"
    bump(window)

    r["status"] = "ACCEPTED"
    bump(r)

    if r["exchange_type"] == "POINTS":
        void_hold(r)
        post_ledger(r["requester_member_id"], "EXCHANGE_DEBIT", -r["points_cost"],
                    status="POSTED", agreement_id=a["id"], memo="exchange debit")
        post_ledger(listing["owner_member_id"], "EXCHANGE_CREDIT", r["points_cost"],
                    status="POSTED", agreement_id=a["id"], memo="exchange credit")
        if guest:
            recompute_balances(guest)
        if host:
            recompute_balances(host)

    listing["version"] = listing["version"] + 1
    listing["updated_at"] = now()

    return ok(ser_agreement(a), status=201)


@app.route("/exchange-requests/<rid>/decline", methods=["POST"])
def decline_request(rid):
    authenticate()
    require_roles({"Member"})
    r = get_request(rid)
    listing = db.listings.get(r["target_listing_id"])
    if listing is None or listing["owner_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "only the host may decline", 403)
    if r["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE", "request not declinable", 409)
    r["status"] = "DECLINED"
    bump(r)
    if r["exchange_type"] == "POINTS":
        void_hold(r)
    return ok(ser_request(r))


@app.route("/exchange-requests/<rid>/withdraw", methods=["POST"])
def withdraw_request(rid):
    authenticate()
    require_roles({"Member"})
    r = get_request(rid)
    if r["requester_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "only the requester may withdraw", 403)
    if r["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE", "request not withdrawable", 409)
    r["status"] = "WITHDRAWN"
    bump(r)
    if r["exchange_type"] == "POINTS":
        void_hold(r)
    return ok(ser_request(r))


# ---------------------------------------------------------------------------
# Exchange agreements
# ---------------------------------------------------------------------------
@app.route("/exchange-agreements/<aid>", methods=["GET"])
def fetch_agreement(aid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    a = get_agreement(aid)
    return ok(ser_agreement(a))


@app.route("/exchange-agreements", methods=["GET"])
def list_agreements():
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    items = list(db.agreements.values())
    for key in ("request_id", "guest_member_id", "host_member_id", "listing_id", "availability_window_id"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]
    return _list_response(items, ser_agreement)


@app.route("/exchange-agreements/<aid>/ledger-entries", methods=["GET"])
def list_agreement_ledger(aid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    get_agreement(aid)
    items = [e for e in db.ledger.values() if e["agreement_id"] == aid]
    return _list_response(items, ser_ledger)


def _require_party(a):
    if g.uid not in (a["guest_member_id"], a["host_member_id"]):
        raise ApiError("ERR_NOT_AGREEMENT_PARTY", "acting member is not a party to the agreement", 403)


@app.route("/exchange-agreements/<aid>/confirm", methods=["POST"])
def confirm_agreement(aid):
    authenticate()
    require_roles({"Member"})
    a = get_agreement(aid)
    _require_party(a)
    if a["status"] != "PENDING_CONFIRMATION":
        raise ApiError("ERR_INVALID_STATE", "agreement not pending confirmation", 409)
    host_tier = active_membership_tier(a["host_member_id"])
    a["coverage_limit_points"] = COVERAGE_LIMIT.get(host_tier, 0)
    a["insurance_status"] = "ACTIVE"
    a["status"] = "CONFIRMED"
    bump(a)
    return ok(ser_agreement(a))


@app.route("/exchange-agreements/<aid>/start", methods=["POST"])
def start_agreement(aid):
    authenticate()
    require_roles({"PlatformAdmin"})
    a = get_agreement(aid)
    if a["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "agreement not confirmed", 409)
    if now().date() < parse_date(a["check_in"]):
        raise ApiError("ERR_INVALID_STATE", "check-in date not reached", 409)
    a["status"] = "IN_PROGRESS"
    bump(a)
    return ok(ser_agreement(a))


@app.route("/exchange-agreements/<aid>/complete", methods=["POST"])
def complete_agreement(aid):
    authenticate()
    require_roles({"Member"})
    a = get_agreement(aid)
    _require_party(a)
    if a["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "agreement not in progress", 409)
    if now().date() < parse_date(a["check_out"]):
        raise ApiError("ERR_INVALID_STATE", "check-out date not reached", 409)
    a["status"] = "COMPLETED"
    bump(a)
    guest = db.members.get(a["guest_member_id"])
    host = db.members.get(a["host_member_id"])
    if guest:
        guest["completed_exchange_count"] += 1
        recompute_trust(guest)
    if host:
        host["completed_exchange_count"] += 1
        recompute_trust(host)
    return ok(ser_agreement(a))


@app.route("/exchange-agreements/<aid>/cancel", methods=["POST"])
def cancel_agreement(aid):
    authenticate()
    require_roles({"Member"})
    a = get_agreement(aid)
    _require_party(a)
    if a["status"] not in ("PENDING_CONFIRMATION", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "agreement not cancellable", 409)
    # release window
    window = db.windows.get(a["availability_window_id"])
    if window and window["status"] == "BOOKED":
        window["status"] = "OPEN"
        bump(window)
    refund = cancellation_refund(a["points_cost"], a["check_in"])
    a["refund_points"] = refund
    a["status"] = "CANCELLED"
    bump(a)
    if a["exchange_type"] == "POINTS" and refund != 0:
        post_ledger(a["guest_member_id"], "EXCHANGE_REFUND", refund, status="POSTED",
                    agreement_id=a["id"], memo="cancellation refund")
        post_ledger(a["host_member_id"], "CREDIT_REVERSAL", -refund, status="POSTED",
                    agreement_id=a["id"], memo="credit reversal")
        guest = db.members.get(a["guest_member_id"])
        host = db.members.get(a["host_member_id"])
        if guest:
            recompute_balances(guest)
        if host:
            recompute_balances(host)
    return ok(ser_agreement(a))


# ---------------------------------------------------------------------------
# Damage claims
# ---------------------------------------------------------------------------
@app.route("/exchange-agreements/<aid>/damage-claims", methods=["POST"])
def file_damage_claim(aid):
    authenticate()
    require_roles({"Member"})
    a = get_agreement(aid)
    body = get_body()
    if "claimant_member_id" in body and body["claimant_member_id"] is not None and body["claimant_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "cannot file a claim for another member", 403)
    claimant_id = req_str(body, "claimant_member_id")
    claimed_amount = req_int(body, "claimed_amount")
    # business_referential: agreement COMPLETED and claimant is a party
    if a["status"] != "COMPLETED" or claimant_id not in (a["guest_member_id"], a["host_member_id"]):
        raise ApiError("ERR_AGREEMENT_NOT_COMPLETED", "agreement not completed or claimant not a party", 409)
    if claimed_amount < 1:
        raise ApiError("ERR_INVALID_CLAIM_AMOUNT", "claimed_amount must be >= 1", 422)
    respondent_id = a["host_member_id"] if claimant_id == a["guest_member_id"] else a["guest_member_id"]
    provisional, _ = damage_payout(claimed_amount, a["coverage_limit_points"])
    c = base_record()
    c.update({
        "agreement_id": aid,
        "claimant_member_id": claimant_id,
        "respondent_member_id": respondent_id,
        "claimed_amount": claimed_amount,
        "assessed_amount": None,
        "provisional_payout": provisional,
        "deductible_points": 0,
        "final_payout": 0,
        "status": "FILED",
    })
    db.claims[c["id"]] = c
    a["insurance_status"] = "CLAIMED"
    bump(a)
    return ok(ser_claim(c), status=201)


@app.route("/damage-claims/<cid>", methods=["GET"])
def fetch_claim(cid):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    c = get_claim(cid)
    return ok(ser_claim(c))


@app.route("/damage-claims", methods=["GET"])
def list_claims():
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    items = list(db.claims.values())
    for key in ("agreement_id", "claimant_member_id"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    return _list_response(items, ser_claim)


@app.route("/damage-claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    authenticate()
    require_roles({"PlatformAdmin"})
    c = get_claim(cid)
    if c["status"] != "FILED":
        raise ApiError("ERR_CLAIM_ALREADY_ADJUDICATED", "claim already adjudicated", 409)
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "REJECT"})
    if decision == "APPROVE":
        assessed_amount = req_int(body, "assessed_amount", minimum=0)
        agreement = db.agreements.get(c["agreement_id"])
        coverage = agreement["coverage_limit_points"] if agreement else 0
        final, deductible = damage_payout(assessed_amount, coverage)
        c["assessed_amount"] = assessed_amount
        c["final_payout"] = final
        c["deductible_points"] = deductible
        c["status"] = "SETTLED"
        bump(c)
        respondent = db.members.get(c["respondent_member_id"])
        claimant = db.members.get(c["claimant_member_id"])
        if final != 0:
            post_ledger(c["respondent_member_id"], "DAMAGE_SETTLEMENT", -final, status="POSTED",
                        agreement_id=c["agreement_id"], memo="damage settlement debit")
            post_ledger(c["claimant_member_id"], "DAMAGE_SETTLEMENT", final, status="POSTED",
                        agreement_id=c["agreement_id"], memo="damage settlement credit")
            if respondent:
                recompute_balances(respondent)
            if claimant:
                recompute_balances(claimant)
        if respondent:
            respondent["upheld_damage_count"] += 1
            recompute_trust(respondent)
    else:
        c["status"] = "REJECTED"
        bump(c)
    return ok(ser_claim(c))


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------
@app.route("/exchange-agreements/<aid>/disputes", methods=["POST"])
def open_dispute(aid):
    authenticate()
    require_roles({"Member"})
    a = get_agreement(aid)
    body = get_body()
    if "opened_by_member_id" in body and body["opened_by_member_id"] is not None and body["opened_by_member_id"] != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "cannot open a dispute for another member", 403)
    opener_id = req_str(body, "opened_by_member_id")
    reason = req_str(body, "reason")
    penalty_points = req_int(body, "penalty_points")
    if opener_id not in (a["guest_member_id"], a["host_member_id"]):
        raise ApiError("ERR_NOT_AGREEMENT_PARTY", "opener is not a party to the agreement", 403)
    if penalty_points < 1:
        raise ApiError("ERR_INVALID_CLAIM_AMOUNT", "penalty_points must be >= 1", 422)
    respondent_id = a["host_member_id"] if opener_id == a["guest_member_id"] else a["guest_member_id"]
    d = base_record()
    d.update({
        "agreement_id": aid,
        "opened_by_member_id": opener_id,
        "respondent_member_id": respondent_id,
        "reason": reason,
        "penalty_points": penalty_points,
        "resolution_note": None,
        "status": "OPEN",
    })
    db.disputes[d["id"]] = d
    return ok(ser_dispute(d), status=201)


@app.route("/disputes/<did>", methods=["GET"])
def fetch_dispute(did):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    d = get_dispute(did)
    return ok(ser_dispute(d))


@app.route("/disputes", methods=["GET"])
def list_disputes():
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    items = list(db.disputes.values())
    for key in ("agreement_id", "opened_by_member_id"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    return _list_response(items, ser_dispute)


DISPUTE_TERMINAL = ("RESOLVED_FOR_CLAIMANT", "RESOLVED_FOR_RESPONDENT", "WITHDRAWN")


@app.route("/disputes/<did>/review", methods=["POST"])
def review_dispute(did):
    authenticate()
    require_roles({"PlatformAdmin"})
    d = get_dispute(did)
    if d["status"] in DISPUTE_TERMINAL:
        raise ApiError("ERR_DISPUTE_ALREADY_RESOLVED", "dispute already terminal", 409)
    if d["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "dispute not OPEN", 409)
    d["status"] = "UNDER_REVIEW"
    bump(d)
    return ok(ser_dispute(d))


@app.route("/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    authenticate()
    require_roles({"Member", "PlatformAdmin"})
    d = get_dispute(did)
    body = get_body()
    decision = req_enum(body, "decision", {"WITHDRAW", "FOR_CLAIMANT", "FOR_RESPONDENT"})
    resolution_note = req_str(body, "resolution_note", required=False)

    if decision == "WITHDRAW":
        if g.role != "Member" or d["opened_by_member_id"] != g.uid:
            raise ApiError("ERR_UNAUTHORIZED", "only the opener may withdraw", 403)
        if d["status"] in DISPUTE_TERMINAL:
            raise ApiError("ERR_DISPUTE_ALREADY_RESOLVED", "dispute already terminal", 409)
        if d["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "dispute not OPEN", 409)
        d["status"] = "WITHDRAWN"
        bump(d)
        return ok(ser_dispute(d))

    # FOR_CLAIMANT / FOR_RESPONDENT -> PlatformAdmin only
    if g.role != "PlatformAdmin":
        raise ApiError("ERR_UNAUTHORIZED", "only a PlatformAdmin may resolve", 403)
    if d["status"] in DISPUTE_TERMINAL:
        raise ApiError("ERR_DISPUTE_ALREADY_RESOLVED", "dispute already terminal", 409)
    if d["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "dispute not UNDER_REVIEW", 409)

    if decision == "FOR_CLAIMANT":
        d["status"] = "RESOLVED_FOR_CLAIMANT"
        d["resolution_note"] = resolution_note
        bump(d)
        penalty = d["penalty_points"]
        post_ledger(d["respondent_member_id"], "DISPUTE_PENALTY", -penalty, status="POSTED",
                    agreement_id=d["agreement_id"], memo="dispute penalty debit")
        post_ledger(d["opened_by_member_id"], "DISPUTE_PENALTY", penalty, status="POSTED",
                    agreement_id=d["agreement_id"], memo="dispute penalty credit")
        respondent = db.members.get(d["respondent_member_id"])
        claimant = db.members.get(d["opened_by_member_id"])
        if respondent:
            recompute_balances(respondent)
        if claimant:
            recompute_balances(claimant)
        if respondent:
            respondent["disputes_lost_count"] += 1
            recompute_trust(respondent)
    else:
        d["status"] = "RESOLVED_FOR_RESPONDENT"
        d["resolution_note"] = resolution_note
        bump(d)
    return ok(ser_dispute(d))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    require_roles({"PlatformAdmin"})
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise ApiError("ERR_VALIDATION", "missing field: to_iso8601", 400)
    db.clock = parse_instant(body["to_iso8601"])
    run_expiry()
    return ok({"current_utc": fmt_ts(db.clock)})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
