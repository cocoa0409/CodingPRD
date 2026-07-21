"""Vacation-Club & Points Travel API (task_1037).

Single-file Flask implementation. In-memory storage only: every dict below is
reset on process start, so per-test-server reboots wipe all state. Nothing is
seeded at startup.
"""

import os
import random
import string
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Constants (single source of truth — scaffold §constants)
# =============================================================================
SILVER_MIN = 4000
GOLD_MIN = 7000
PLATINUM_MIN = 13000
STANDARD_WINDOW_DAYS = 366
PRIORITY_WINDOW_DAYS = 396
HIGH_SEASON_MONTHS = {6, 7, 8, 12}
WEEKEND_WEEKDAYS = {4, 5}  # Mon=0 .. Fri=4, Sat=5
FULL_REFUND_DAYS = 60
PARTIAL_REFUND_DAYS = 15
PARTIAL_REFUND_RATIO = 0.5
BANK_DEADLINE_DAYS = 273
BANK_CAP_PCT = 0.5
BORROW_CAP_PCT = 0.5
MAINT_RATE_PER_POINT_USD = Decimal("0.0653")
CLUB_DUES_RATE_PER_POINT_USD = Decimal("0.0089")
GUEST_CERT_FEE_POINTS = 50
STATEMENT_DUE_DAYS = 30
GRACE_DAYS = 15
CLOCK_DEFAULT_UTC = "2026-07-01T00:00:00Z"

ROLE_MEMBER = "Member"
ROLE_ADMIN = "ClubAdmin"
VALID_ROLES = {ROLE_MEMBER, ROLE_ADMIN}

OCCUPYING_STATUSES = {"HELD", "CONFIRMED", "COMPLETED"}
ACTIVE_RES_STATUSES = {"HELD", "CONFIRMED"}

# =============================================================================
# In-memory store (reset on every boot; never seeded)
# =============================================================================
members = {}
buckets = {}
resorts = {}
unit_types = {}
reservations = {}
guest_certs = {}
waitlists = {}
statements = {}
transfers = {}
listings = {}

_seq_counter = 0
CLOCK = None  # logical clock (datetime, UTC)


def reset_clock():
    global CLOCK
    CLOCK = parse_instant(CLOCK_DEFAULT_UTC)


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


# =============================================================================
# Time helpers
# =============================================================================
def iso_now():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_instant(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid timestamp")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid ISO8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_date():
    return CLOCK.astimezone(timezone.utc).date()


def parse_date(s):
    """Parse a YYYY-MM-DD (or ISO date/datetime) into a date."""
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid date")
    txt = s.strip()
    try:
        return date.fromisoformat(txt[:10])
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid date")


# =============================================================================
# Errors + response envelope
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": iso_now(),
    }


def respond(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def respond_list(items, limit, offset, total):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return respond(items, 200, "array", pagination)


@app.errorhandler(ApiError)
def handle_api_error(err):
    meta = _meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    meta = _meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
    }
    return jsonify(body), 500


# =============================================================================
# Auth / RBAC
# =============================================================================
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized credentials")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")
    return uid, role


def check_owner(role, uid, owner_id):
    if role == ROLE_MEMBER and uid != owner_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Member may only act on its own resources")


# =============================================================================
# Body parsing / field validation
# =============================================================================
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return data


def req_str(d, key):
    v = d.get(key)
    if not isinstance(v, str) or v.strip() == "":
        raise ApiError("ERR_VALIDATION", 422, f"Field '{key}' is required")
    return v


def req_int(d, key, minv=None):
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"Field '{key}' must be an integer")
    if minv is not None and v < minv:
        raise ApiError("ERR_VALIDATION", 422, f"Field '{key}' must be >= {minv}")
    return v


def opt_int(d, key, default, minv=None):
    if key not in d or d[key] is None:
        return default
    return req_int(d, key, minv)


# =============================================================================
# Record helpers
# =============================================================================
def stamp_new(rec):
    ts = iso_now()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = iso_now()
    rec["version"] += 1
    return rec


def strip(rec):
    return {k: v for k, v in rec.items() if k != "_seq"}


# =============================================================================
# Pagination + list helpers
# =============================================================================
def paginate_params():
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def make_list(records, serializer):
    limit, offset = paginate_params()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return respond_list([serializer(r) for r in page], limit, offset, total)


# =============================================================================
# Computed fields
# =============================================================================
def compute_tier(owned_points):
    if owned_points >= PLATINUM_MIN:
        return "PLATINUM"
    if owned_points >= GOLD_MIN:
        return "GOLD"
    if owned_points >= SILVER_MIN:
        return "SILVER"
    return "STANDARD"


def bucket_available(b):
    v = (
        b["annual_allotment"] + b["banked_in"] + b["borrowed_in"] + b["transferred_in"]
        - b["banked_out"] - b["borrowed_out"] - b["transferred_out"] - b["points_used"]
    )
    return max(0, v)


def round_half_up_cents(dollars_decimal):
    return int(dollars_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# Serializers
# =============================================================================
def ser_member(m):
    out = strip(m)
    out["tier"] = compute_tier(m["owned_points"])
    return out


def ser_bucket(b):
    out = strip(b)
    out["points_available"] = bucket_available(b)
    return out


def ser_resort(r):
    return strip(r)


def ser_unit_type(u):
    return strip(u)


def ser_reservation(r):
    return strip(r)


def ser_guest_cert(g):
    return strip(g)


def ser_waitlist(w):
    return strip(w)


def ser_statement(s):
    return strip(s)


def ser_transfer(t):
    return strip(t)


def ser_listing(l):
    return strip(l)


# =============================================================================
# Existence helpers
# =============================================================================
def get_member(mid):
    m = members.get(mid)
    if m is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member not found")
    return m


def get_bucket(bid):
    b = buckets.get(bid)
    if b is None:
        raise ApiError("ERR_POINTS_BUCKET_NOT_FOUND", 404, "points bucket not found")
    return b


def get_resort(rid):
    r = resorts.get(rid)
    if r is None:
        raise ApiError("ERR_RESORT_NOT_FOUND", 404, "resort not found")
    return r


def get_unit_type(uid):
    u = unit_types.get(uid)
    if u is None:
        raise ApiError("ERR_UNIT_TYPE_NOT_FOUND", 404, "unit type not found")
    return u


def get_reservation(rid):
    r = reservations.get(rid)
    if r is None:
        raise ApiError("ERR_RESERVATION_NOT_FOUND", 404, "reservation not found")
    return r


def get_waitlist(wid):
    w = waitlists.get(wid)
    if w is None:
        raise ApiError("ERR_WAITLIST_NOT_FOUND", 404, "waitlist entry not found")
    return w


def get_statement(sid):
    s = statements.get(sid)
    if s is None:
        raise ApiError("ERR_STATEMENT_NOT_FOUND", 404, "statement not found")
    return s


def get_transfer(tid):
    t = transfers.get(tid)
    if t is None:
        raise ApiError("ERR_TRANSFER_NOT_FOUND", 404, "transfer not found")
    return t


def current_bucket(member):
    for b in buckets.values():
        if b["member_id"] == member["id"] and b["use_year"] == member["current_use_year"]:
            return b
    return None


# =============================================================================
# Domain calculations
# =============================================================================
def compute_cost(unit_type, ci, co):
    cost = 0
    d = ci
    while d < co:
        season_high = d.month in HIGH_SEASON_MONTHS
        weekend = d.weekday() in WEEKEND_WEEKDAYS
        if season_high and weekend:
            cost += unit_type["points_weekend_high"]
        elif season_high and not weekend:
            cost += unit_type["points_weekday_high"]
        elif (not season_high) and weekend:
            cost += unit_type["points_weekend_low"]
        else:
            cost += unit_type["points_weekday_low"]
        d += timedelta(days=1)
    return cost


def occupancy_ok(unit_type_id, ci, co):
    ut = unit_types[unit_type_id]
    cap = ut["total_units"]
    d = ci
    while d < co:
        cnt = 0
        for r in reservations.values():
            if r["unit_type_id"] != unit_type_id:
                continue
            if r["status"] not in OCCUPYING_STATUSES:
                continue
            rci = parse_date(r["check_in"])
            rco = parse_date(r["check_out"])
            if rci <= d < rco:
                cnt += 1
        if cnt >= cap:
            return False
        d += timedelta(days=1)
    return True


def member_has_overlap(member_id, ci, co, exclude_id=None):
    for r in reservations.values():
        if r["member_id"] != member_id:
            continue
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if r["status"] not in ACTIVE_RES_STATUSES:
            continue
        rci = parse_date(r["check_in"])
        rco = parse_date(r["check_out"])
        if rci < co and ci < rco:
            return True
    return False


def window_days_for(member):
    tier = compute_tier(member["owned_points"])
    return PRIORITY_WINDOW_DAYS if tier in ("GOLD", "PLATINUM") else STANDARD_WINDOW_DAYS


def refund_for_cancel(points_cost, ci):
    days_out = (ci - now_date()).days
    if days_out >= FULL_REFUND_DAYS:
        return points_cost
    if days_out >= PARTIAL_REFUND_DAYS:
        return int(points_cost * PARTIAL_REFUND_RATIO)  # floor of half
    return 0


# =============================================================================
# Cascade helpers
# =============================================================================
def cancel_reservation_cascade(res, refunded_points):
    """Common cancel cascade shared by manual cancel and suspension cascade.

    Does NOT include waitlist promotion; caller runs promotion after.
    """
    bucket = buckets.get(res["points_bucket_id"])
    res["refunded_points"] = refunded_points
    res["status"] = "CANCELLED"
    touch(res)
    if bucket is not None and refunded_points:
        bucket["points_used"] -= refunded_points
        touch(bucket)
    # Revoke any ISSUED guest certificate; refund its fee.
    for g in guest_certs.values():
        if g["reservation_id"] == res["id"] and g["status"] == "ISSUED":
            g["status"] = "REVOKED"
            touch(g)
            if bucket is not None:
                bucket["points_used"] -= g["fee_points"]
                touch(bucket)
    # Withdraw any LISTED listing.
    for l in listings.values():
        if l["reservation_id"] == res["id"] and l["status"] == "LISTED":
            l["status"] = "WITHDRAWN"
            touch(l)


def try_promote_waitlist(unit_type_id):
    """Promote the earliest-created ACTIVE waitlist entry on this unit type
    that now fits (capacity + member ACTIVE + points sufficient)."""
    candidates = [
        w for w in waitlists.values()
        if w["unit_type_id"] == unit_type_id and w["status"] == "ACTIVE"
    ]
    candidates.sort(key=lambda w: w["_seq"])
    for w in candidates:
        member = members.get(w["member_id"])
        if member is None or member["account_status"] != "ACTIVE":
            continue
        ut = unit_types.get(w["unit_type_id"])
        if ut is None:
            continue
        ci = parse_date(w["check_in"])
        co = parse_date(w["check_out"])
        if not occupancy_ok(unit_type_id, ci, co):
            continue
        bucket = buckets.get(w["points_bucket_id"])
        if bucket is None:
            continue
        cost = compute_cost(ut, ci, co)
        if bucket_available(bucket) < cost:
            continue
        # Promote: create HELD reservation, reserve points, occupy nights.
        rid = new_id()
        res = {
            "id": rid,
            "member_id": w["member_id"],
            "unit_type_id": w["unit_type_id"],
            "points_bucket_id": w["points_bucket_id"],
            "check_in": w["check_in"],
            "check_out": w["check_out"],
            "nights": (co - ci).days,
            "points_cost": cost,
            "status": "HELD",
            "refunded_points": 0,
            "guest_certificate_id": None,
        }
        stamp_new(res)
        reservations[rid] = res
        bucket["points_used"] += cost
        touch(bucket)
        w["status"] = "PROMOTED"
        w["promoted_reservation_id"] = rid
        touch(w)
        return
    return


# =============================================================================
# System / clock endpoints
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({ROLE_ADMIN})
    body = get_body()
    if "to_iso8601" not in body:
        raise ApiError("ERR_VALIDATION", 422, "to_iso8601 is required")
    global CLOCK
    CLOCK = parse_instant(body["to_iso8601"])
    return respond({}, 200, "object")


@app.route("/_ops/run_billing_cycle", methods=["POST"])
def run_billing_cycle():
    require_auth({ROLE_ADMIN})
    nd = now_date()

    # 1. Aging: CURRENT & not PAID & past due_date -> PAST_DUE
    for s in statements.values():
        if s["aging_status"] == "CURRENT" and s["payment_status"] != "PAID":
            if nd > parse_date(s["due_date"]):
                s["aging_status"] = "PAST_DUE"
                touch(s)

    # 2. Suspension + cascade
    for m in list(members.values()):
        if m["account_status"] != "ACTIVE":
            continue
        delinquent = False
        for s in statements.values():
            if s["member_id"] != m["id"]:
                continue
            if s["aging_status"] == "PAST_DUE" and s["payment_status"] != "PAID":
                if nd > (parse_date(s["due_date"]) + timedelta(days=GRACE_DAYS)):
                    delinquent = True
                    break
        if not delinquent:
            continue
        m["account_status"] = "SUSPENDED"
        touch(m)
        freed_unit_types = []
        for r in list(reservations.values()):
            if r["member_id"] == m["id"] and r["status"] == "HELD":
                cancel_reservation_cascade(r, r["points_cost"])  # full refund
                if r["unit_type_id"] not in freed_unit_types:
                    freed_unit_types.append(r["unit_type_id"])
        for ut_id in freed_unit_types:
            try_promote_waitlist(ut_id)

    # 3. Reservation completion
    for r in reservations.values():
        if r["status"] == "CONFIRMED" and nd >= parse_date(r["check_out"]):
            r["status"] = "COMPLETED"
            touch(r)
            for g in guest_certs.values():
                if g["reservation_id"] == r["id"] and g["status"] == "ISSUED":
                    g["status"] = "USED"
                    touch(g)

    # 4. Expiries
    for w in waitlists.values():
        if w["status"] == "ACTIVE" and nd >= parse_date(w["check_in"]):
            w["status"] = "EXPIRED"
            touch(w)
    for l in listings.values():
        if l["status"] == "LISTED":
            res = reservations.get(l["reservation_id"])
            if res is not None and nd >= parse_date(res["check_in"]):
                l["status"] = "EXPIRED"
                touch(l)

    # 5. Use-year rollover
    clock_year = CLOCK.astimezone(timezone.utc).year
    for b in buckets.values():
        if b["status"] == "OPEN" and clock_year > b["use_year"]:
            b["status"] = "CLOSED"
            touch(b)

    return respond({}, 200, "object")


# =============================================================================
# Member endpoints
# =============================================================================
@app.route("/club/members", methods=["POST"])
def create_member():
    require_auth({ROLE_ADMIN})
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    owned_points = req_int(body, "owned_points", minv=0)

    clock_year = CLOCK.astimezone(timezone.utc).year
    mid = new_id()
    m = {
        "id": mid,
        "full_name": full_name,
        "email": email,
        "owned_points": owned_points,
        "account_status": "ACTIVE",
        "current_use_year": clock_year,
        "current_statement_id": None,
    }
    stamp_new(m)
    members[mid] = m

    bid = new_id()
    b = {
        "id": bid,
        "member_id": mid,
        "use_year": clock_year,
        "annual_allotment": owned_points,
        "banked_in": 0,
        "banked_out": 0,
        "borrowed_in": 0,
        "borrowed_out": 0,
        "transferred_in": 0,
        "transferred_out": 0,
        "points_used": 0,
        "status": "OPEN",
    }
    stamp_new(b)
    buckets[bid] = b

    return respond(ser_member(m), 201, "object")


@app.route("/club/members/<mid>", methods=["GET"])
def get_member_ep(mid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    m = get_member(mid)
    return respond(ser_member(m), 200, "object")


@app.route("/club/members/<mid>/points-buckets", methods=["GET"])
def list_member_buckets(mid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    get_member(mid)
    recs = [b for b in buckets.values() if b["member_id"] == mid]
    use_year = request.args.get("use_year")
    if use_year is not None:
        try:
            uy = int(use_year)
        except ValueError:
            raise ApiError("ERR_VALIDATION", 422, "use_year must be an integer")
        recs = [b for b in recs if b["use_year"] == uy]
    status = request.args.get("status")
    if status is not None:
        recs = [b for b in recs if b["status"] == status]
    return make_list(recs, ser_bucket)


@app.route("/club/members/<mid>/statements", methods=["GET"])
def list_member_statements(mid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    get_member(mid)
    recs = [s for s in statements.values() if s["member_id"] == mid]
    aging = request.args.get("aging_status")
    if aging is not None:
        recs = [s for s in recs if s["aging_status"] == aging]
    payment = request.args.get("payment_status")
    if payment is not None:
        recs = [s for s in recs if s["payment_status"] == payment]
    return make_list(recs, ser_statement)


@app.route("/club/members/<mid>/transfers", methods=["GET"])
def list_member_transfers(mid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    get_member(mid)
    recs = [
        t for t in transfers.values()
        if t["from_member_id"] == mid or t["to_member_id"] == mid
    ]
    status = request.args.get("status")
    if status is not None:
        recs = [t for t in recs if t["status"] == status]
    return make_list(recs, ser_transfer)


# =============================================================================
# PointsBucket endpoints
# =============================================================================
@app.route("/club/points-buckets/<bid>", methods=["GET"])
def get_bucket_ep(bid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    b = get_bucket(bid)
    return respond(ser_bucket(b), 200, "object")


def _get_or_prep_next_bucket(source):
    """Return (existing_next_bucket_or_None, member)."""
    member = members[source["member_id"]]
    for b in buckets.values():
        if b["member_id"] == member["id"] and b["use_year"] == source["use_year"] + 1:
            return b, member
    return None, member


def _create_next_bucket(member, use_year):
    bid = new_id()
    b = {
        "id": bid,
        "member_id": member["id"],
        "use_year": use_year,
        "annual_allotment": member["owned_points"],
        "banked_in": 0,
        "banked_out": 0,
        "borrowed_in": 0,
        "borrowed_out": 0,
        "transferred_in": 0,
        "transferred_out": 0,
        "points_used": 0,
        "status": "OPEN",
    }
    stamp_new(b)
    buckets[bid] = b
    return b


@app.route("/club/points-buckets/<bid>/bank", methods=["POST"])
def bank_points(bid):
    uid, role = require_auth({ROLE_MEMBER})
    source = get_bucket(bid)
    check_owner(role, uid, source["member_id"])
    body = get_body()
    points = req_int(body, "points", minv=1)

    if source["status"] != "OPEN":
        raise ApiError("ERR_BUCKET_CLOSED", 409, "bucket is closed")

    cap = int(source["annual_allotment"] * BANK_CAP_PCT)
    if points > cap:
        raise ApiError("ERR_BANK_CAP_EXCEEDED", 422, "bank cap exceeded")
    if points > bucket_available(source):
        raise ApiError("ERR_INSUFFICIENT_POINTS", 422, "insufficient points")

    deadline = date(source["use_year"], 1, 1) + timedelta(days=BANK_DEADLINE_DAYS)
    if now_date() <= deadline:
        credited = points
    else:
        credited = int(points * 0.5)  # floor

    existing_next, member = _get_or_prep_next_bucket(source)
    source["banked_out"] += points
    touch(source)
    if existing_next is None:
        nb = _create_next_bucket(member, source["use_year"] + 1)
        nb["banked_in"] += credited  # no extra version bump on fresh create
    else:
        existing_next["banked_in"] += credited
        touch(existing_next)

    return respond(ser_bucket(source), 200, "object")


@app.route("/club/points-buckets/<bid>/borrow", methods=["POST"])
def borrow_points(bid):
    uid, role = require_auth({ROLE_MEMBER})
    source = get_bucket(bid)
    check_owner(role, uid, source["member_id"])
    body = get_body()
    points = req_int(body, "points", minv=1)

    if source["status"] != "OPEN":
        raise ApiError("ERR_BUCKET_CLOSED", 409, "bucket is closed")

    cap = int(source["annual_allotment"] * BORROW_CAP_PCT)
    if points > cap:
        raise ApiError("ERR_BORROW_CAP_EXCEEDED", 422, "borrow cap exceeded")

    existing_next, member = _get_or_prep_next_bucket(source)
    next_avail = bucket_available(existing_next) if existing_next else member["owned_points"]
    if points > next_avail:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 422, "insufficient points")

    source["borrowed_in"] += points
    touch(source)
    if existing_next is None:
        nb = _create_next_bucket(member, source["use_year"] + 1)
        nb["borrowed_out"] += points
    else:
        existing_next["borrowed_out"] += points
        touch(existing_next)

    return respond(ser_bucket(source), 200, "object")


# =============================================================================
# Resort / UnitType endpoints
# =============================================================================
@app.route("/club/resorts", methods=["POST"])
def create_resort():
    require_auth({ROLE_ADMIN})
    body = get_body()
    name = req_str(body, "name")
    region = req_str(body, "region")
    rid = new_id()
    r = {"id": rid, "name": name, "region": region}
    stamp_new(r)
    resorts[rid] = r
    return respond(ser_resort(r), 201, "object")


@app.route("/club/resorts/<rid>", methods=["GET"])
def get_resort_ep(rid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    r = get_resort(rid)
    return respond(ser_resort(r), 200, "object")


@app.route("/club/resorts/<rid>/unit-types", methods=["POST"])
def create_unit_type(rid):
    require_auth({ROLE_ADMIN})
    get_resort(rid)
    body = get_body()
    name = req_str(body, "name")
    total_units = req_int(body, "total_units", minv=1)
    pwl = req_int(body, "points_weekday_low", minv=1)
    pwel = req_int(body, "points_weekend_low", minv=1)
    pwh = req_int(body, "points_weekday_high", minv=1)
    pweh = req_int(body, "points_weekend_high", minv=1)
    uid = new_id()
    u = {
        "id": uid,
        "resort_id": rid,
        "name": name,
        "total_units": total_units,
        "points_weekday_low": pwl,
        "points_weekend_low": pwel,
        "points_weekday_high": pwh,
        "points_weekend_high": pweh,
    }
    stamp_new(u)
    unit_types[uid] = u
    return respond(ser_unit_type(u), 201, "object")


@app.route("/club/resorts/<rid>/unit-types", methods=["GET"])
def list_unit_types(rid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    get_resort(rid)
    recs = [u for u in unit_types.values() if u["resort_id"] == rid]
    return make_list(recs, ser_unit_type)


@app.route("/club/unit-types/<uid>", methods=["GET"])
def get_unit_type_ep(uid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    u = get_unit_type(uid)
    return respond(ser_unit_type(u), 200, "object")


# =============================================================================
# Reservation endpoints
# =============================================================================
@app.route("/club/reservations", methods=["POST"])
def create_reservation():
    uid, role = require_auth({ROLE_MEMBER})
    body = get_body()
    # existence, left-to-right: member -> unit_type -> bucket
    member_id = body.get("member_id")
    if not isinstance(member_id, str):
        raise ApiError("ERR_VALIDATION", 422, "member_id is required")
    member = get_member(member_id)
    unit_type_id = body.get("unit_type_id")
    if not isinstance(unit_type_id, str):
        raise ApiError("ERR_VALIDATION", 422, "unit_type_id is required")
    unit_type = get_unit_type(unit_type_id)
    points_bucket_id = body.get("points_bucket_id")
    if not isinstance(points_bucket_id, str):
        raise ApiError("ERR_VALIDATION", 422, "points_bucket_id is required")
    bucket = get_bucket(points_bucket_id)
    # ownership
    check_owner(role, uid, member_id)
    # validation: dates
    ci = parse_date(req_str(body, "check_in"))
    co = parse_date(req_str(body, "check_out"))
    if co <= ci:
        raise ApiError("ERR_VALIDATION", 422, "check_out must be after check_in")
    # state: bucket OPEN
    if bucket["status"] != "OPEN":
        raise ApiError("ERR_BUCKET_CLOSED", 409, "bucket is closed")
    # window
    days_out = (ci - now_date()).days
    wd = window_days_for(member)
    if not (0 < days_out <= wd):
        raise ApiError("ERR_OUTSIDE_BOOKING_WINDOW", 422, "check_in outside booking window")
    # inventory then overlap
    if not occupancy_ok(unit_type_id, ci, co):
        raise ApiError("ERR_NO_INVENTORY", 409, "no inventory for requested nights")
    if member_has_overlap(member_id, ci, co):
        raise ApiError("ERR_MEMBER_DATE_OVERLAP", 409, "member has overlapping reservation")
    # fiscal
    cost = compute_cost(unit_type, ci, co)
    if bucket_available(bucket) < cost:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 422, "insufficient points")

    rid = new_id()
    res = {
        "id": rid,
        "member_id": member_id,
        "unit_type_id": unit_type_id,
        "points_bucket_id": points_bucket_id,
        "check_in": body["check_in"],
        "check_out": body["check_out"],
        "nights": (co - ci).days,
        "points_cost": cost,
        "status": "HELD",
        "refunded_points": 0,
        "guest_certificate_id": None,
    }
    stamp_new(res)
    reservations[rid] = res
    bucket["points_used"] += cost
    touch(bucket)
    return respond(ser_reservation(res), 201, "object")


@app.route("/club/reservations/<rid>", methods=["GET"])
def get_reservation_ep(rid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    r = get_reservation(rid)
    return respond(ser_reservation(r), 200, "object")


@app.route("/club/reservations", methods=["GET"])
def list_reservations():
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    recs = list(reservations.values())
    for key in ("member_id", "unit_type_id", "points_bucket_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return make_list(recs, ser_reservation)


@app.route("/club/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    uid, role = require_auth({ROLE_MEMBER})
    res = get_reservation(rid)
    check_owner(role, uid, res["member_id"])
    # state: HELD -> member ACTIVE -> bucket OPEN (scaffold precondition order)
    if res["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "reservation is not HELD")
    member = members[res["member_id"]]
    if member["account_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409, "member is suspended")
    bucket = buckets[res["points_bucket_id"]]
    if bucket["status"] != "OPEN":
        raise ApiError("ERR_BUCKET_CLOSED", 409, "bucket is closed")
    res["status"] = "CONFIRMED"
    touch(res)
    return respond(ser_reservation(res), 200, "object")


@app.route("/club/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    uid, role = require_auth({ROLE_MEMBER})
    res = get_reservation(rid)
    check_owner(role, uid, res["member_id"])
    if res["status"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "reservation cannot be cancelled")
    ci = parse_date(res["check_in"])
    refunded = refund_for_cancel(res["points_cost"], ci)
    cancel_reservation_cascade(res, refunded)
    try_promote_waitlist(res["unit_type_id"])
    return respond(ser_reservation(res), 200, "object")


# =============================================================================
# Guest Certificate endpoints
# =============================================================================
@app.route("/club/reservations/<rid>/guest-certificates", methods=["POST"])
def issue_guest_cert(rid):
    uid, role = require_auth({ROLE_MEMBER})
    res = get_reservation(rid)
    check_owner(role, uid, res["member_id"])
    body = get_body()
    guest_name = req_str(body, "guest_name")
    if res["status"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "reservation not eligible for guest certificate")
    bucket = buckets[res["points_bucket_id"]]
    if bucket_available(bucket) < GUEST_CERT_FEE_POINTS:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 422, "insufficient points for guest certificate fee")
    gid = new_id()
    g = {
        "id": gid,
        "reservation_id": rid,
        "guest_name": guest_name,
        "fee_points": GUEST_CERT_FEE_POINTS,
        "status": "ISSUED",
    }
    stamp_new(g)
    guest_certs[gid] = g
    bucket["points_used"] += GUEST_CERT_FEE_POINTS
    touch(bucket)
    res["guest_certificate_id"] = gid
    touch(res)
    return respond(ser_guest_cert(g), 201, "object")


@app.route("/club/reservations/<rid>/guest-certificates", methods=["GET"])
def list_guest_certs(rid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    get_reservation(rid)
    recs = [g for g in guest_certs.values() if g["reservation_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        recs = [g for g in recs if g["status"] == status]
    return make_list(recs, ser_guest_cert)


# =============================================================================
# Listing endpoints
# =============================================================================
@app.route("/club/reservations/<rid>/listings", methods=["POST"])
def create_listing(rid):
    uid, role = require_auth({ROLE_MEMBER})
    res = get_reservation(rid)
    check_owner(role, uid, res["member_id"])
    body = get_body()
    listing_type = body.get("listing_type")
    if listing_type not in ("EXCHANGE", "RENTAL"):
        raise ApiError("ERR_VALIDATION", 422, "listing_type must be EXCHANGE or RENTAL")
    ask = opt_int(body, "ask_amount_cents", 0, minv=0)
    if listing_type == "EXCHANGE":
        ask = 0
    if res["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "listing requires a CONFIRMED reservation")
    lid = new_id()
    l = {
        "id": lid,
        "reservation_id": rid,
        "listing_type": listing_type,
        "ask_amount_cents": ask,
        "status": "LISTED",
    }
    stamp_new(l)
    listings[lid] = l
    return respond(ser_listing(l), 201, "object")


@app.route("/club/reservations/<rid>/listings", methods=["GET"])
def list_listings(rid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    get_reservation(rid)
    recs = [l for l in listings.values() if l["reservation_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        recs = [l for l in recs if l["status"] == status]
    return make_list(recs, ser_listing)


# =============================================================================
# Waitlist endpoints
# =============================================================================
@app.route("/club/waitlist-entries", methods=["POST"])
def create_waitlist():
    uid, role = require_auth({ROLE_MEMBER})
    body = get_body()
    member_id = body.get("member_id")
    if not isinstance(member_id, str):
        raise ApiError("ERR_VALIDATION", 422, "member_id is required")
    member = get_member(member_id)
    unit_type_id = body.get("unit_type_id")
    if not isinstance(unit_type_id, str):
        raise ApiError("ERR_VALIDATION", 422, "unit_type_id is required")
    get_unit_type(unit_type_id)
    points_bucket_id = body.get("points_bucket_id")
    if not isinstance(points_bucket_id, str):
        raise ApiError("ERR_VALIDATION", 422, "points_bucket_id is required")
    get_bucket(points_bucket_id)
    check_owner(role, uid, member_id)
    ci = parse_date(req_str(body, "check_in"))
    co = parse_date(req_str(body, "check_out"))
    if co <= ci:
        raise ApiError("ERR_VALIDATION", 422, "check_out must be after check_in")
    days_out = (ci - now_date()).days
    wd = window_days_for(member)
    if not (0 < days_out <= wd):
        raise ApiError("ERR_OUTSIDE_BOOKING_WINDOW", 422, "check_in outside booking window")

    wid = new_id()
    w = {
        "id": wid,
        "member_id": member_id,
        "unit_type_id": unit_type_id,
        "points_bucket_id": points_bucket_id,
        "check_in": body["check_in"],
        "check_out": body["check_out"],
        "status": "ACTIVE",
        "promoted_reservation_id": None,
    }
    stamp_new(w)
    waitlists[wid] = w
    return respond(ser_waitlist(w), 201, "object")


@app.route("/club/waitlist-entries/<wid>", methods=["GET"])
def get_waitlist_ep(wid):
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    w = get_waitlist(wid)
    return respond(ser_waitlist(w), 200, "object")


@app.route("/club/waitlist-entries", methods=["GET"])
def list_waitlist():
    require_auth({ROLE_MEMBER, ROLE_ADMIN})
    recs = list(waitlists.values())
    for key in ("member_id", "unit_type_id", "points_bucket_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [w for w in recs if w[key] == val]
    return make_list(recs, ser_waitlist)


@app.route("/club/waitlist-entries/<wid>/cancel", methods=["POST"])
def cancel_waitlist(wid):
    uid, role = require_auth({ROLE_MEMBER})
    w = get_waitlist(wid)
    check_owner(role, uid, w["member_id"])
    if w["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "waitlist entry not ACTIVE")
    w["status"] = "CANCELLED"
    touch(w)
    return respond(ser_waitlist(w), 200, "object")


# =============================================================================
# Statement endpoints
# =============================================================================
@app.route("/club/members/<mid>/statements", methods=["POST"])
def generate_statement(mid):
    require_auth({ROLE_ADMIN})
    member = get_member(mid)
    body = get_body()
    expected_version = req_int(body, "expected_member_version")
    special = opt_int(body, "special_assessment_cents", 0, minv=0)
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "member version is stale")

    owned = member["owned_points"]
    maint = round_half_up_cents(Decimal(owned) * MAINT_RATE_PER_POINT_USD * Decimal(100))
    dues = round_half_up_cents(Decimal(owned) * CLUB_DUES_RATE_PER_POINT_USD * Decimal(100))
    total = maint + dues + special

    issue = now_date()
    due = issue + timedelta(days=STATEMENT_DUE_DAYS)
    clock_year = CLOCK.astimezone(timezone.utc).year

    sid = new_id()
    s = {
        "id": sid,
        "member_id": mid,
        "billing_year": clock_year,
        "issue_date": issue.isoformat(),
        "due_date": due.isoformat(),
        "maintenance_fee_cents": maint,
        "club_dues_cents": dues,
        "special_assessment_cents": special,
        "total_due_cents": total,
        "amount_paid_cents": 0,
        "payment_status": "UNPAID",
        "aging_status": "CURRENT",
    }
    stamp_new(s)
    statements[sid] = s

    member["current_statement_id"] = sid
    touch(member)  # advances member.version by 1

    return respond(ser_statement(s), 201, "object")


@app.route("/club/statements/<sid>/pay", methods=["POST"])
def pay_statement(sid):
    uid, role = require_auth({ROLE_MEMBER})
    s = get_statement(sid)
    check_owner(role, uid, s["member_id"])
    body = get_body()
    amount = req_int(body, "amount_cents", minv=1)

    if s["payment_status"] == "PAID":
        raise ApiError("ERR_INVALID_STATE", 409, "statement already paid")

    s["amount_paid_cents"] += amount
    if s["amount_paid_cents"] >= s["total_due_cents"]:
        s["payment_status"] = "PAID"
        s["aging_status"] = "CURRENT"
        touch(s)
        member = members[s["member_id"]]
        if member["account_status"] == "SUSPENDED":
            still_delinquent = any(
                st["member_id"] == member["id"]
                and st["aging_status"] == "PAST_DUE"
                and st["payment_status"] != "PAID"
                for st in statements.values()
            )
            if not still_delinquent:
                member["account_status"] = "ACTIVE"
                touch(member)
    else:
        s["payment_status"] = "PARTIALLY_PAID"
        touch(s)
    return respond(ser_statement(s), 200, "object")


# =============================================================================
# Transfer endpoints
# =============================================================================
@app.route("/club/transfers", methods=["POST"])
def create_transfer():
    uid, role = require_auth({ROLE_MEMBER})
    body = get_body()
    from_member_id = body.get("from_member_id")
    if not isinstance(from_member_id, str):
        raise ApiError("ERR_VALIDATION", 422, "from_member_id is required")
    from_member = get_member(from_member_id)
    to_member_id = body.get("to_member_id")
    if not isinstance(to_member_id, str):
        raise ApiError("ERR_VALIDATION", 422, "to_member_id is required")
    to_member = get_member(to_member_id)
    check_owner(role, uid, from_member_id)
    points = req_int(body, "points", minv=1)
    # state: both members ACTIVE
    if from_member["account_status"] != "ACTIVE" or to_member["account_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409, "both members must be ACTIVE")
    # fiscal: sender current-use-year bucket covers points
    sender_bucket = current_bucket(from_member)
    if sender_bucket is None:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 422, "sender has no active bucket")
    if bucket_available(sender_bucket) < points:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 422, "insufficient points")

    tid = new_id()
    t = {
        "id": tid,
        "from_member_id": from_member_id,
        "to_member_id": to_member_id,
        "points": points,
        "status": "PENDING",
    }
    stamp_new(t)
    transfers[tid] = t
    sender_bucket["points_used"] += points  # escrow
    touch(sender_bucket)
    return respond(ser_transfer(t), 201, "object")


@app.route("/club/transfers/<tid>/accept", methods=["POST"])
def accept_transfer(tid):
    uid, role = require_auth({ROLE_MEMBER})
    t = get_transfer(tid)
    check_owner(role, uid, t["to_member_id"])
    body = get_body()
    outcome = body.get("outcome")
    if outcome not in ("ACCEPT", "REJECT"):
        raise ApiError("ERR_VALIDATION", 422, "outcome must be ACCEPT or REJECT")
    if t["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "transfer is not PENDING")

    from_member = members[t["from_member_id"]]
    to_member = members[t["to_member_id"]]
    sender_bucket = current_bucket(from_member)
    points = t["points"]

    if outcome == "ACCEPT":
        if from_member["account_status"] != "ACTIVE" or to_member["account_status"] != "ACTIVE":
            raise ApiError("ERR_MEMBER_SUSPENDED", 409, "both members must be ACTIVE")
        receiver_bucket = current_bucket(to_member)
        # sender: release escrow + record transferred_out
        sender_bucket["points_used"] -= points
        sender_bucket["transferred_out"] += points
        touch(sender_bucket)
        # receiver: record transferred_in
        receiver_bucket["transferred_in"] += points
        touch(receiver_bucket)
        t["status"] = "COMPLETED"
        touch(t)
    else:  # REJECT
        sender_bucket["points_used"] -= points
        touch(sender_bucket)
        t["status"] = "REJECTED"
        touch(t)
    return respond(ser_transfer(t), 200, "object")


# =============================================================================
# Boot
# =============================================================================
reset_clock()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
