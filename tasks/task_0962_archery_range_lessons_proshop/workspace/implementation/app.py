#!/usr/bin/env python3
"""Archery Range, Lessons & Pro-Shop API — in-memory Flask implementation.

Built verbatim from workspace/PRD.md. Storage is in-memory dicts only; the
store starts empty on every boot. All temporal judgment uses a logical clock
(default 2026-05-01T00:00:00Z) advanced via POST /_clock/set_current_utc.
"""

import math
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, g, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock and stores (start empty; never seeded)
# ---------------------------------------------------------------------------

NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

MEMBERS = {}
WAIVERS = {}
LANES = {}
SESSIONS = {}
PARTICIPANTS = {}
PUNCH_CARDS = {}
RENTAL_ITEMS = {}
AGREEMENTS = {}
COACHES = {}
LESSONS = {}
LEAGUES = {}
ENTRIES = {}
CARDS = {}
PRODUCTS = {}
SALES = {}
REPAIRS = {}
_SEQ = [0]

ROLES = {"Anonymous", "Member", "Coach", "RangeOfficer", "ShopClerk",
         "LeagueDirector", "Admin"}

TIER_DISCOUNT = {"BASIC": Decimal("0.00"), "PLUS": Decimal("0.10"),
                 "ELITE": Decimal("0.20")}
TIERS = set(TIER_DISCOUNT)
PEAK_HOURS = {17, 18, 19, 20}
DISCIPLINES = {"RECURVE", "COMPOUND", "TRADITIONAL"}


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------

def rhu(x):
    """Round half up to integer cents."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt_ms(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def bump(e):
    e["version"] += 1
    e["updated_at"] = fmt_ms(NOW)


def new_entity(store, fields):
    e = dict(fields)
    e["id"] = str(uuid.uuid4())
    e["created_at"] = fmt_ms(NOW)
    e["updated_at"] = fmt_ms(NOW)
    e["version"] = 1
    e["_seq"] = next_seq()
    store[e["id"]] = e
    return e


def pub(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Errors, envelope, auth
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_ms(datetime.now(timezone.utc)),
    }


def ok(data, code=200, response_type="object", page_meta=None):
    m = meta()
    if page_meta:
        m.update(page_meta)
    body = {"meta": m, "response_type": response_type, "data": data}
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


@app.errorhandler(Exception)
def handle_generic(e):  # pragma: no cover - safety net
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(e)},
    }
    return jsonify(body), 500


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", 401,
                               "missing or invalid X-User-ID / X-User-Role headers")
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED", 403,
                               "role %s is not permitted on this endpoint" % role)
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def need(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "missing required field: %s" % field)
    return data[field]


def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def list_response(items):
    return _list(items, pub)


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def eighteenth(dob):
    try:
        return date(dob.year + 18, dob.month, dob.day)
    except ValueError:
        return date(dob.year + 18, 2, 28)


def member_is_minor(m):
    dob = parse_date(m["date_of_birth"])
    return NOW.date() < eighteenth(dob)


def pub_member(m):
    d = pub(m)
    d["is_minor"] = member_is_minor(m)
    return d


def pub_card(c):
    d = pub(c)
    d["punches_remaining"] = c["punches_total"] - c["punches_used"]
    return d


def get_member(mid):
    m = MEMBERS.get(mid)
    if not m:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member not found")
    return m


def require_active_member(m):
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409, "member is not ACTIVE")


def require_active_waiver(m):
    ws = [w for w in WAIVERS.values() if w["member_id"] == m["id"]]
    if not ws:
        raise ApiError("ERR_WAIVER_MISSING", 422,
                       "member has never signed a waiver")
    latest = max(ws, key=lambda w: w["_seq"])
    if latest["status"] != "ACTIVE":
        raise ApiError("ERR_WAIVER_EXPIRED", 422,
                       "member's latest waiver is not ACTIVE")


def is_peak(start_dt):
    return start_dt.hour in PEAK_HOURS


def quoted_fee_cents(session, member):
    blocks = math.ceil(session["booked_minutes"] / 30)
    base = 1200 * blocks
    peaked = rhu(Decimal(base) * Decimal("1.25")) if is_peak(session["_start"]) else base
    discounted = rhu(Decimal(peaked) * (1 - TIER_DISCOUNT[member["tier"]]))
    fee = max(discounted, 1200)
    if session["booking_type"] == "WALK_IN":
        fee += 300
    return fee


def final_fee_cents(session, member):
    secs = (session["_closed"] - session["_checked_in"]).total_seconds()
    actual_minutes = math.ceil(secs / 60)
    blocks = math.ceil(actual_minutes / 30)
    base = 1200 * blocks
    peaked = rhu(Decimal(base) * Decimal("1.25")) if is_peak(session["_start"]) else base
    discounted = rhu(Decimal(peaked) * (1 - TIER_DISCOUNT[member["tier"]]))
    return max(discounted, 1200)


def session_participants(session_id):
    return [p for p in PARTICIPANTS.values() if p["session_id"] == session_id]


def void_agreement(a):
    a["status"] = "VOIDED"
    bump(a)
    item = RENTAL_ITEMS.get(a["rental_item_id"])
    if item and item["status"] == "RENTED":
        item["status"] = "AVAILABLE"
        bump(item)


def void_session_rentals(session):
    for a in AGREEMENTS.values():
        if a.get("session_id") == session["id"] and a["status"] == "OPEN":
            void_agreement(a)


def cancel_session(session, system):
    """BOOKED -> CANCELLED with refund tiers and rental-void cascade."""
    total_refund = 0
    notice = session["_start"] - NOW
    for p in session_participants(session["id"]):
        if p["status"] != "ACTIVE":
            continue
        if p["payment_method"] == "WALLET":
            if system or notice >= timedelta(hours=24):
                refund = p["quoted_fee_cents"]
            elif notice >= timedelta(hours=4):
                refund = rhu(Decimal(p["quoted_fee_cents"]) * Decimal("0.5"))
            else:
                refund = 0
            if refund > 0:
                m = MEMBERS.get(p["member_id"])
                if m:
                    m["wallet_balance_cents"] += refund
                    bump(m)
                p["status"] = "REFUNDED"
                total_refund += refund
            else:
                p["status"] = "FORFEITED"
            bump(p)
        else:  # PUNCH_CARD
            restore = system or notice >= timedelta(hours=4)
            card = PUNCH_CARDS.get(p.get("punch_card_id") or "")
            if restore and card:
                card["punches_used"] -= 1
                if card["status"] == "EXHAUSTED" and \
                        card["punches_used"] < card["punches_total"]:
                    card["status"] = "ACTIVE"
                bump(card)
                p["status"] = "REFUNDED"
            else:
                p["status"] = "FORFEITED"
            bump(p)
    session["session_status"] = "CANCELLED"
    session["cancellation_refund_cents"] = total_refund
    if total_refund > 0:
        session["payment_status"] = "REFUNDED"
    bump(session)
    void_session_rentals(session)


def no_show_session(session):
    session["session_status"] = "NO_SHOW"
    bump(session)
    for p in session_participants(session["id"]):
        if p["status"] == "ACTIVE":
            p["status"] = "FORFEITED"
            bump(p)
    void_session_rentals(session)


def recompute_league_pools(league):
    gross = sum(e["fee_paid_cents"] for e in ENTRIES.values()
                if e["league_id"] == league["id"] and e["status"] == "CONFIRMED")
    share = rhu(Decimal(gross) * Decimal("0.15"))
    league["gross_entry_fees_cents"] = gross
    league["range_share_cents"] = share
    league["prize_pool_cents"] = gross - share
    bump(league)


def lesson_interval(lesson):
    start = lesson["_proposed"]
    return start, start + timedelta(minutes=lesson["duration_minutes"])


def coach_has_conflict(coach_id, lesson):
    s1, e1 = lesson_interval(lesson)
    buf = timedelta(minutes=15)
    for other in LESSONS.values():
        if other["id"] == lesson["id"] or other["coach_id"] != coach_id:
            continue
        if other["status"] != "CONFIRMED":
            continue
        s2, e2 = lesson_interval(other)
        if not (s1 >= e2 + buf or e1 <= s2 - buf):
            return True
    return False


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@app.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("Admin")
def set_clock():
    global NOW
    data = body()
    raw = need(data, "to_iso8601")
    try:
        new_now = parse_dt(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid to_iso8601")
    NOW = new_now
    no_show = 0
    expired = 0
    for s in list(SESSIONS.values()):
        if s["session_status"] == "BOOKED" and NOW > s["_start"] + timedelta(minutes=15):
            no_show_session(s)
            no_show += 1
    today = NOW.date()
    for w in list(WAIVERS.values()):
        if w["status"] == "ACTIVE" and today > date.fromisoformat(w["valid_until"]):
            w["status"] = "EXPIRED"
            bump(w)
            expired += 1
    return ok({"current_utc": fmt_ms(NOW),
               "no_show_sessions": no_show,
               "expired_waivers": expired})


# ---------------------------------------------------------------------------
# Members, waivers, punch cards
# ---------------------------------------------------------------------------

@app.route("/members", methods=["POST"])
@require_roles("Anonymous")
def create_member():
    data = body()
    email = need(data, "email")
    full_name = need(data, "full_name")
    dob_raw = need(data, "date_of_birth")
    if not isinstance(email, str) or not isinstance(full_name, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "email and full_name must be strings")
    try:
        dob = parse_date(dob_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "date_of_birth must be YYYY-MM-DD")
    tier = data.get("tier", "BASIC")
    if tier not in TIERS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid tier")
    if any(m["email"] == email for m in MEMBERS.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "email already registered")
    guardian_id = data.get("guardian_id")
    guardian = None
    if guardian_id is not None:
        guardian = MEMBERS.get(guardian_id)
        if not guardian:
            raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "guardian member not found")
    minor = NOW.date() < eighteenth(dob)
    if minor:
        if guardian_id is None:
            raise ApiError("ERR_MINOR_GUARDIAN_REQUIRED", 422,
                           "minor registration requires guardian_id")
        if member_is_minor(guardian):
            raise ApiError("ERR_GUARDIAN_NOT_ADULT", 422,
                           "guardian must be an adult member")
    m = new_entity(MEMBERS, {
        "email": email,
        "full_name": full_name,
        "date_of_birth": dob_raw,
        "tier": tier,
        "guardian_id": guardian_id,
        "status": "ACTIVE",
        "safety_strikes": 0,
        "wallet_balance_cents": 0,
    })
    return ok(pub_member(m), 201)


@app.route("/members", methods=["GET"])
@require_roles("Member", "RangeOfficer", "Admin")
def list_members():
    items = list(MEMBERS.values())
    status = request.args.get("status")
    guardian_id = request.args.get("guardian_id")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if guardian_id is not None:
        items = [m for m in items if m.get("guardian_id") == guardian_id]
    return _list(items, pub_member)


def _list(items, ser):
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    limit = max(1, min(100, _int_arg("limit", 10)))
    offset = max(0, _int_arg("offset", 0))
    page = items[offset:offset + limit]
    pm = {"limit": limit, "offset": offset, "total_count": total,
          "has_more": (offset + len(page)) < total}
    return ok([ser(e) for e in page], 200, "array", pm)


@app.route("/members/<mid>", methods=["GET"])
@require_roles("Member", "RangeOfficer", "Admin")
def get_member_route(mid):
    m = get_member(mid)
    if g.role == "Member" and g.uid != mid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "members may only read themselves")
    return ok(pub_member(m))


@app.route("/members/<mid>/safety-strikes", methods=["POST"])
@require_roles("RangeOfficer")
def add_strike(mid):
    m = get_member(mid)
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409, "member is not ACTIVE")
    m["safety_strikes"] += 1
    bump(m)
    if m["safety_strikes"] == 3:
        m["status"] = "SUSPENDED"
        bump(m)
        # cascade hop 1: future BOOKED sessions created by this member
        for s in list(SESSIONS.values()):
            if s["created_by_member_id"] == mid and \
                    s["session_status"] == "BOOKED" and s["_start"] > NOW:
                cancel_session(s, system=True)
        # suspension also voids the member's own OPEN rental agreements
        for a in list(AGREEMENTS.values()):
            if a["member_id"] == mid and a["status"] == "OPEN":
                void_agreement(a)
    return ok(pub_member(m), 201)


@app.route("/members/<mid>/reinstate", methods=["POST"])
@require_roles("RangeOfficer")
def reinstate(mid):
    m = get_member(mid)
    if m["status"] != "SUSPENDED":
        raise ApiError("ERR_MEMBER_NOT_SUSPENDED", 409, "member is not SUSPENDED")
    m["status"] = "ACTIVE"
    m["safety_strikes"] = 0
    bump(m)
    return ok(pub_member(m))


@app.route("/members/<mid>/wallet/adjustments", methods=["POST"])
@require_roles("Admin")
def wallet_adjust(mid):
    m = get_member(mid)
    data = body()
    amount = need(data, "amount_cents")
    if not is_int(amount):
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be an integer")
    m["wallet_balance_cents"] += amount
    bump(m)
    return ok(pub_member(m), 201)


@app.route("/members/<mid>/waivers", methods=["POST"])
@require_roles("Member")
def sign_waiver(mid):
    m = get_member(mid)
    if member_is_minor(m):
        if g.uid == mid:
            raise ApiError("ERR_MINOR_GUARDIAN_REQUIRED", 422,
                           "a minor may not sign their own waiver")
        guardian = MEMBERS.get(m.get("guardian_id") or "")
        if g.uid != m.get("guardian_id") or not guardian or member_is_minor(guardian):
            raise ApiError("ERR_GUARDIAN_NOT_ADULT", 422,
                           "signer must be the member's adult guardian")
        signer = g.uid
    else:
        if g.uid != mid:
            raise ApiError("ERR_UNAUTHORIZED", 403,
                           "adults sign only their own waiver")
        signer = g.uid
    signed_date = NOW.date()
    w = new_entity(WAIVERS, {
        "member_id": mid,
        "signed_by_member_id": signer,
        "signed_at": fmt_ms(NOW),
        "valid_until": (signed_date + timedelta(days=365)).isoformat(),
        "status": "ACTIVE",
    })
    return ok(pub(w), 201)


@app.route("/members/<mid>/waivers", methods=["GET"])
@require_roles("Member", "RangeOfficer", "Admin")
def list_waivers(mid):
    m = get_member(mid)
    if g.role == "Member" and g.uid != mid and g.uid != m.get("guardian_id"):
        raise ApiError("ERR_UNAUTHORIZED", 403, "members may only read own waivers")
    items = [w for w in WAIVERS.values() if w["member_id"] == mid]
    return _list(items, pub)


@app.route("/waivers/<wid>/revoke", methods=["POST"])
@require_roles("Admin")
def revoke_waiver(wid):
    w = WAIVERS.get(wid)
    if not w:
        raise ApiError("ERR_WAIVER_NOT_FOUND", 404, "waiver not found")
    if w["status"] == "REVOKED":
        raise ApiError("ERR_WAIVER_NOT_REVOKABLE", 409, "waiver already REVOKED")
    w["status"] = "REVOKED"
    bump(w)
    return ok(pub(w))


@app.route("/members/<mid>/punch-cards", methods=["POST"])
@require_roles("Member", "Admin")
def buy_punch_card(mid):
    m = get_member(mid)
    if g.role == "Member" and g.uid != mid:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "members may only purchase their own punch cards")
    data = body()
    total = need(data, "punches_total")
    if total not in (5, 10) or not is_int(total):
        raise ApiError("ERR_INVALID_REQUEST", 400, "punches_total must be 5 or 10")
    require_active_member(m)
    price = rhu(Decimal(total * 1000) * (1 - TIER_DISCOUNT[m["tier"]]))
    if m["wallet_balance_cents"] < price:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", 402, "wallet balance too low")
    m["wallet_balance_cents"] -= price
    bump(m)
    c = new_entity(PUNCH_CARDS, {
        "member_id": mid,
        "punches_total": total,
        "punches_used": 0,
        "price_paid_cents": price,
        "status": "ACTIVE",
    })
    return ok(pub_card(c), 201)


@app.route("/members/<mid>/punch-cards", methods=["GET"])
@require_roles("Member", "RangeOfficer", "Admin")
def list_punch_cards(mid):
    get_member(mid)
    if g.role == "Member" and g.uid != mid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "members may only read own cards")
    items = [c for c in PUNCH_CARDS.values() if c["member_id"] == mid]
    return _list(items, pub_card)


@app.route("/punch-cards/<cid>", methods=["GET"])
@require_roles("Member", "RangeOfficer", "Admin")
def get_punch_card(cid):
    c = PUNCH_CARDS.get(cid)
    if not c:
        raise ApiError("ERR_PUNCH_CARD_NOT_FOUND", 404, "punch card not found")
    if g.role == "Member" and g.uid != c["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "members may only read own cards")
    return ok(pub_card(c))


# ---------------------------------------------------------------------------
# Lanes, range sessions, participants
# ---------------------------------------------------------------------------

@app.route("/lanes", methods=["POST"])
@require_roles("Admin")
def create_lane():
    data = body()
    name = need(data, "name")
    lane_type = need(data, "lane_type")
    max_archers = need(data, "max_archers")
    if lane_type not in ("INDOOR", "OUTDOOR"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid lane_type")
    if not is_int(max_archers) or max_archers < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "max_archers must be >= 1")
    if any(l["name"] == name for l in LANES.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "lane name must be unique")
    lane = new_entity(LANES, {"name": name, "lane_type": lane_type,
                              "max_archers": max_archers})
    return ok(pub(lane), 201)


@app.route("/lanes", methods=["GET"])
@require_roles("Anonymous", "Member", "Coach", "RangeOfficer", "ShopClerk",
               "LeagueDirector", "Admin")
def list_lanes():
    return _list(list(LANES.values()), pub)


@app.route("/lanes/<lid>", methods=["GET"])
@require_roles("Anonymous", "Member", "Coach", "RangeOfficer", "ShopClerk",
               "LeagueDirector", "Admin")
def get_lane(lid):
    lane = LANES.get(lid)
    if not lane:
        raise ApiError("ERR_LANE_NOT_FOUND", 404, "lane not found")
    return ok(pub(lane))


@app.route("/lanes/<lid>/sessions", methods=["GET"])
@require_roles("Member", "RangeOfficer", "Admin")
def lane_sessions(lid):
    if lid not in LANES:
        raise ApiError("ERR_LANE_NOT_FOUND", 404, "lane not found")
    items = [s for s in SESSIONS.values() if s["lane_id"] == lid]
    return _list(items, pub)


def get_session(sid):
    s = SESSIONS.get(sid)
    if not s:
        raise ApiError("ERR_SESSION_NOT_FOUND", 404, "range session not found")
    return s


@app.route("/range-sessions", methods=["POST"])
@require_roles("Member", "RangeOfficer")
def create_session():
    data = body()
    lane_id = need(data, "lane_id")
    lane = LANES.get(lane_id)
    if not lane:
        raise ApiError("ERR_LANE_NOT_FOUND", 404, "lane not found")
    created_for = data.get("created_for_member_id")
    if g.role == "Member":
        if created_for is not None and created_for != g.uid:
            raise ApiError("ERR_UNAUTHORIZED", 403,
                           "members may only book for themselves")
        creator_id = g.uid
    else:
        if created_for is None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "created_for_member_id is required for RangeOfficer bookings")
        creator_id = created_for
    creator = MEMBERS.get(creator_id)
    if not creator:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "creator member not found")
    booking_type = need(data, "booking_type")
    start_raw = need(data, "start_at")
    end_raw = need(data, "end_at")
    if booking_type not in ("WALK_IN", "RESERVATION"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid booking_type")
    try:
        start = parse_dt(start_raw)
        end = parse_dt(end_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid start_at/end_at")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_at must be after start_at")
    require_active_member(creator)
    require_active_waiver(creator)
    for other in SESSIONS.values():
        if other["lane_id"] != lane_id:
            continue
        if other["session_status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        if other["_start"] < end and start < other["_end"]:
            raise ApiError("ERR_LANE_OVERLAP", 409,
                           "session overlaps an existing booking on this lane")
    if booking_type == "RESERVATION":
        if start < NOW + timedelta(minutes=120):
            raise ApiError("ERR_BOOKING_WINDOW_VIOLATION", 422,
                           "reservations require at least 120 minutes lead time")
    else:
        if start.date() != NOW.date() or end <= NOW:
            raise ApiError("ERR_BOOKING_WINDOW_VIOLATION", 422,
                           "walk-ins must start today and end after now")
    booked_minutes = int((end - start).total_seconds() // 60)
    s = new_entity(SESSIONS, {
        "lane_id": lane_id,
        "created_by_member_id": creator_id,
        "booking_type": booking_type,
        "start_at": start_raw,
        "end_at": end_raw,
        "booked_minutes": booked_minutes,
        "session_status": "BOOKED",
        "payment_status": "UNPAID",
        "quoted_charge_cents": 0,
        "final_charge_cents": None,
        "cancellation_refund_cents": None,
        "checked_in_at": None,
        "closed_at": None,
        "_start": start,
        "_end": end,
        "_checked_in": None,
        "_closed": None,
    })
    return ok(pub(s), 201)


@app.route("/range-sessions", methods=["GET"])
@require_roles("Member", "RangeOfficer", "Admin")
def list_sessions():
    items = list(SESSIONS.values())
    for f in ("lane_id", "created_by_member_id", "session_status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s.get(f) == v]
    return _list(items, pub)


@app.route("/range-sessions/<sid>", methods=["GET"])
@require_roles("Member", "RangeOfficer", "Admin")
def get_session_route(sid):
    s = get_session(sid)
    if g.role == "Member" and g.uid != s["created_by_member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the session creator")
    return ok(pub(s))


@app.route("/range-sessions/<sid>/participants", methods=["POST"])
@require_roles("Member", "RangeOfficer")
def add_participant(sid):
    s = get_session(sid)
    if g.role == "Member" and g.uid != s["created_by_member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the session creator")
    data = body()
    member_id = need(data, "member_id")
    archer = MEMBERS.get(member_id)
    if not archer:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "participant member not found")
    payment_method = need(data, "payment_method")
    if payment_method not in ("WALLET", "PUNCH_CARD"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid payment_method")
    punch_card_id = data.get("punch_card_id")
    if payment_method == "PUNCH_CARD":
        if punch_card_id is None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "punch_card_id is required for PUNCH_CARD payment")
    else:
        if punch_card_id is not None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "punch_card_id only allowed with PUNCH_CARD payment")
    if s["session_status"] == "CLOSED":
        raise ApiError("ERR_SESSION_ALREADY_CLOSED", 409, "session is CLOSED")
    if s["session_status"] != "BOOKED":
        raise ApiError("ERR_SESSION_NOT_BOOKED", 409, "session is not BOOKED")
    require_active_member(archer)
    require_active_waiver(archer)
    existing = session_participants(sid)
    if any(p["member_id"] == member_id for p in existing):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "member is already a participant in this session")
    lane = LANES[s["lane_id"]]
    active_count = sum(1 for p in existing if p["status"] == "ACTIVE")
    if active_count + 1 > lane["max_archers"]:
        raise ApiError("ERR_LANE_CAPACITY_EXCEEDED", 422,
                       "lane capacity would be exceeded")
    card = None
    if payment_method == "PUNCH_CARD":
        card = PUNCH_CARDS.get(punch_card_id)
        if not card or card["member_id"] != s["created_by_member_id"] or \
                card["status"] != "ACTIVE" or \
                (card["punches_total"] - card["punches_used"]) < 1:
            raise ApiError("ERR_PUNCH_CARD_EXHAUSTED", 422,
                           "punch card missing, not owned by creator, inactive, or exhausted")
    fee = quoted_fee_cents(s, archer)
    if payment_method == "WALLET":
        if archer["wallet_balance_cents"] < fee:
            raise ApiError("ERR_INSUFFICIENT_FUNDS", 402, "wallet balance too low")
        archer["wallet_balance_cents"] -= fee
        bump(archer)
    else:
        card["punches_used"] += 1
        if card["punches_used"] == card["punches_total"]:
            card["status"] = "EXHAUSTED"
        bump(card)
    p = new_entity(PARTICIPANTS, {
        "session_id": sid,
        "member_id": member_id,
        "payment_method": payment_method,
        "punch_card_id": punch_card_id,
        "quoted_fee_cents": fee,
        "final_fee_cents": None,
        "status": "ACTIVE",
    })
    s["quoted_charge_cents"] += fee
    s["payment_status"] = "PAID"
    bump(s)
    return ok(pub(p), 201)


@app.route("/session-participants", methods=["GET"])
@require_roles("Member", "RangeOfficer", "Admin")
def list_participants():
    items = list(PARTICIPANTS.values())
    for f in ("session_id", "member_id", "punch_card_id"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p.get(f) == v]
    return _list(items, pub)


@app.route("/session-participants/<pid>", methods=["GET"])
@require_roles("Member", "RangeOfficer", "Admin")
def get_participant(pid):
    p = PARTICIPANTS.get(pid)
    if not p:
        raise ApiError("ERR_PARTICIPANT_NOT_FOUND", 404, "participant not found")
    if g.role == "Member":
        sess = SESSIONS.get(p["session_id"])
        if g.uid != p["member_id"] and \
                (not sess or g.uid != sess["created_by_member_id"]):
            raise ApiError("ERR_UNAUTHORIZED", 403, "not the participant")
    return ok(pub(p))


def session_not_booked_error(s):
    if s["session_status"] == "CLOSED":
        raise ApiError("ERR_SESSION_ALREADY_CLOSED", 409, "session is CLOSED")
    raise ApiError("ERR_SESSION_NOT_BOOKED", 409, "session is not BOOKED")


@app.route("/range-sessions/<sid>/check-in", methods=["POST"])
@require_roles("RangeOfficer")
def check_in(sid):
    s = get_session(sid)
    if s["session_status"] != "BOOKED":
        session_not_booked_error(s)
    active = [p for p in session_participants(sid) if p["status"] == "ACTIVE"]
    if not active:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "session has no ACTIVE participants")
    for p in active:
        m = MEMBERS.get(p["member_id"])
        if not m or m["status"] != "ACTIVE":
            raise ApiError("ERR_MEMBER_SUSPENDED", 409,
                           "participant member is not ACTIVE")
        require_active_waiver(m)
    if not (s["_start"] <= NOW <= s["_start"] + timedelta(minutes=15)):
        raise ApiError("ERR_BOOKING_WINDOW_VIOLATION", 422,
                       "outside the check-in window")
    s["session_status"] = "CHECKED_IN"
    s["checked_in_at"] = fmt_ms(NOW)
    s["_checked_in"] = NOW
    bump(s)
    return ok(pub(s))


@app.route("/range-sessions/<sid>/close", methods=["POST"])
@require_roles("RangeOfficer")
def close_session(sid):
    s = get_session(sid)
    if s["session_status"] != "CHECKED_IN":
        session_not_booked_error(s)
    if not NOW > s["_checked_in"]:
        raise ApiError("ERR_BOOKING_WINDOW_VIOLATION", 422,
                       "close requires clock after check-in time")
    s["closed_at"] = fmt_ms(NOW)
    s["_closed"] = NOW
    total = 0
    for p in session_participants(sid):
        if p["status"] != "ACTIVE":
            continue
        m = MEMBERS[p["member_id"]]
        fee = final_fee_cents(s, m)
        p["final_fee_cents"] = fee
        total += fee
        if p["payment_method"] == "WALLET":
            delta = fee - p["quoted_fee_cents"]
            if delta != 0:
                m["wallet_balance_cents"] -= delta
                bump(m)
        bump(p)
    s["final_charge_cents"] = total
    s["payment_status"] = "PAID"
    s["session_status"] = "CLOSED"
    bump(s)
    return ok(pub(s))


@app.route("/range-sessions/<sid>/cancel", methods=["POST"])
@require_roles("Member", "RangeOfficer")
def cancel_session_route(sid):
    s = get_session(sid)
    if g.role == "Member" and g.uid != s["created_by_member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the session creator")
    if s["session_status"] != "BOOKED":
        session_not_booked_error(s)
    cancel_session(s, system=False)
    return ok(pub(s))


# ---------------------------------------------------------------------------
# Rental items and agreements
# ---------------------------------------------------------------------------

@app.route("/rental-items", methods=["POST"])
@require_roles("ShopClerk", "Admin")
def create_rental_item():
    data = body()
    name = need(data, "name")
    item_type = need(data, "item_type")
    rate = need(data, "daily_rate_cents")
    if item_type not in ("BOW", "ARROW_SET", "ARMGUARD", "RELEASE"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid item_type")
    if not is_int(rate) or rate < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "daily_rate_cents must be >= 0")
    item = new_entity(RENTAL_ITEMS, {"name": name, "item_type": item_type,
                                     "daily_rate_cents": rate,
                                     "status": "AVAILABLE"})
    return ok(pub(item), 201)


@app.route("/rental-items", methods=["GET"])
@require_roles("Member", "RangeOfficer", "ShopClerk", "Admin")
def list_rental_items():
    items = list(RENTAL_ITEMS.values())
    v = request.args.get("status")
    if v is not None:
        items = [i for i in items if i["status"] == v]
    return _list(items, pub)


def get_agreement(aid):
    a = AGREEMENTS.get(aid)
    if not a:
        raise ApiError("ERR_RENTAL_AGREEMENT_NOT_FOUND", 404,
                       "rental agreement not found")
    return a


@app.route("/rental-agreements", methods=["POST"])
@require_roles("Member", "RangeOfficer")
def create_agreement():
    data = body()
    item_id = need(data, "rental_item_id")
    item = RENTAL_ITEMS.get(item_id)
    if not item:
        raise ApiError("ERR_RENTAL_ITEM_NOT_FOUND", 404, "rental item not found")
    member_id = need(data, "member_id")
    member = MEMBERS.get(member_id)
    if not member:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member not found")
    session_id = data.get("session_id")
    if session_id is not None and session_id not in SESSIONS:
        raise ApiError("ERR_SESSION_NOT_FOUND", 404, "range session not found")
    if g.role == "Member" and g.uid != member_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "members rent only for themselves")
    dl = need(data, "draw_length_in")
    dw = need(data, "draw_weight_lb")
    due_raw = need(data, "due_date")
    if not is_num(dl) or dl < 14.0 or dl > 32.0 or \
            (Decimal(str(dl)) * 2) != (Decimal(str(dl)) * 2).to_integral_value():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "draw_length_in must be 14.0..32.0 in 0.5 steps")
    if not is_int(dw) or dw < 10 or dw > 70:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "draw_weight_lb must be an integer 10..70")
    try:
        parse_date(due_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "due_date must be YYYY-MM-DD")
    require_active_member(member)
    require_active_waiver(member)
    if item["status"] != "AVAILABLE":
        raise ApiError("ERR_RENTAL_ITEM_UNAVAILABLE", 422,
                       "rental item is not AVAILABLE")
    a = new_entity(AGREEMENTS, {
        "rental_item_id": item_id,
        "member_id": member_id,
        "session_id": session_id,
        "draw_length_in": dl,
        "draw_weight_lb": dw,
        "checked_out_at": fmt_ms(NOW),
        "due_date": due_raw,
        "returned_at": None,
        "returned_condition": None,
        "damage_fee_cents": 0,
        "status": "OPEN",
        "settlement_total_cents": None,
        "_checked_out": NOW,
        "_returned": None,
    })
    item["status"] = "RENTED"
    bump(item)
    return ok(pub(a), 201)


@app.route("/rental-agreements", methods=["GET"])
@require_roles("Member", "RangeOfficer", "ShopClerk", "Admin")
def list_agreements():
    items = list(AGREEMENTS.values())
    for f in ("member_id", "rental_item_id", "session_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    return _list(items, pub)


@app.route("/rental-agreements/<aid>", methods=["GET"])
@require_roles("Member", "RangeOfficer", "ShopClerk", "Admin")
def get_agreement_route(aid):
    a = get_agreement(aid)
    if g.role == "Member" and g.uid != a["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the renter")
    return ok(pub(a))


@app.route("/rental-agreements/<aid>/return", methods=["POST"])
@require_roles("RangeOfficer")
def return_agreement(aid):
    a = get_agreement(aid)
    data = body()
    condition = need(data, "returned_condition")
    fee = data.get("damage_fee_cents", 0)
    if condition not in ("GOOD", "DAMAGED"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid returned_condition")
    if not is_int(fee) or fee < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid damage_fee_cents")
    if condition == "GOOD" and fee != 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "damage_fee_cents must be 0 when condition is GOOD")
    if condition == "DAMAGED" and fee <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "damage_fee_cents must be > 0 when condition is DAMAGED")
    if a["status"] != "OPEN":
        raise ApiError("ERR_RENTAL_INVALID_STATE", 409,
                       "agreement is not OPEN")
    a["returned_at"] = fmt_ms(NOW)
    a["_returned"] = NOW
    a["returned_condition"] = condition
    a["damage_fee_cents"] = fee
    a["status"] = "RETURNED"
    bump(a)
    item = RENTAL_ITEMS.get(a["rental_item_id"])
    if item and item["status"] == "RENTED":
        item["status"] = "AVAILABLE"
        bump(item)
    return ok(pub(a))


@app.route("/rental-agreements/<aid>/settle", methods=["POST"])
@require_roles("RangeOfficer")
def settle_agreement(aid):
    a = get_agreement(aid)
    if a["status"] != "RETURNED":
        raise ApiError("ERR_RENTAL_INVALID_STATE", 409,
                       "agreement is not RETURNED")
    item = RENTAL_ITEMS[a["rental_item_id"]]
    checkout_date = a["_checked_out"].date()
    return_date = a["_returned"].date()
    billable_days = max(1, (return_date - checkout_date).days)
    rental_charge = billable_days * item["daily_rate_cents"]
    late_days = max(0, (return_date - parse_date(a["due_date"])).days)
    late_fee = late_days * 500
    total = rental_charge + late_fee + a["damage_fee_cents"]
    member = MEMBERS[a["member_id"]]
    if member["wallet_balance_cents"] < total:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", 402, "wallet balance too low")
    member["wallet_balance_cents"] -= total
    bump(member)
    a["settlement_total_cents"] = total
    a["status"] = "SETTLED"
    bump(a)
    return ok(pub(a))


# ---------------------------------------------------------------------------
# Coaches and lessons
# ---------------------------------------------------------------------------

@app.route("/coaches", methods=["POST"])
@require_roles("Admin")
def create_coach():
    data = body()
    full_name = need(data, "full_name")
    disciplines = need(data, "disciplines")
    if not isinstance(disciplines, list) or not disciplines or \
            any(d not in DISCIPLINES for d in disciplines):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "disciplines must be a non-empty array of valid disciplines")
    c = new_entity(COACHES, {"full_name": full_name,
                             "disciplines": disciplines,
                             "status": "ACTIVE"})
    return ok(pub(c), 201)


@app.route("/coaches", methods=["GET"])
@require_roles("Anonymous", "Member", "Coach", "RangeOfficer", "ShopClerk",
               "LeagueDirector", "Admin")
def list_coaches():
    return _list(list(COACHES.values()), pub)


def get_coach(cid):
    c = COACHES.get(cid)
    if not c:
        raise ApiError("ERR_COACH_NOT_FOUND", 404, "coach not found")
    return c


@app.route("/coaches/<cid>/deactivate", methods=["POST"])
@require_roles("Admin")
def deactivate_coach(cid):
    c = get_coach(cid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_REQUEST", 400, "coach is not ACTIVE")
    c["status"] = "INACTIVE"
    bump(c)
    return ok(pub(c))


@app.route("/coaches/<cid>/activate", methods=["POST"])
@require_roles("Admin")
def activate_coach(cid):
    c = get_coach(cid)
    if c["status"] != "INACTIVE":
        raise ApiError("ERR_INVALID_REQUEST", 400, "coach is not INACTIVE")
    c["status"] = "ACTIVE"
    bump(c)
    return ok(pub(c))


def get_lesson(lid):
    l = LESSONS.get(lid)
    if not l:
        raise ApiError("ERR_LESSON_NOT_FOUND", 404, "lesson not found")
    return l


@app.route("/lessons", methods=["POST"])
@require_roles("Member")
def create_lesson():
    data = body()
    coach_id = need(data, "coach_id")
    coach = COACHES.get(coach_id)
    if not coach:
        raise ApiError("ERR_COACH_NOT_FOUND", 404, "coach not found")
    discipline = need(data, "discipline")
    start_raw = need(data, "proposed_start_at")
    duration = data.get("duration_minutes", 60)
    if discipline not in DISCIPLINES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid discipline")
    try:
        start = parse_dt(start_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid proposed_start_at")
    if not is_int(duration) or duration < 30 or duration > 120:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "duration_minutes must be 30..120")
    member = MEMBERS[g.uid]
    require_active_member(member)
    require_active_waiver(member)
    if discipline not in coach["disciplines"]:
        raise ApiError("ERR_DISCIPLINE_MISMATCH", 422,
                       "discipline not in coach's disciplines")
    fee = rhu(Decimal(6000 * math.ceil(duration / 60)) *
              (1 - TIER_DISCOUNT[member["tier"]]))
    lesson = new_entity(LESSONS, {
        "coach_id": coach_id,
        "member_id": g.uid,
        "discipline": discipline,
        "proposed_start_at": start_raw,
        "duration_minutes": duration,
        "fee_cents": fee,
        "status": "REQUESTED",
        "_proposed": start,
    })
    return ok(pub(lesson), 201)


@app.route("/lessons", methods=["GET"])
@require_roles("Member", "Coach", "Admin")
def list_lessons():
    items = list(LESSONS.values())
    for f in ("coach_id", "member_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l.get(f) == v]
    return _list(items, pub)


@app.route("/lessons/<lid>", methods=["GET"])
@require_roles("Member", "Coach", "Admin")
def get_lesson_route(lid):
    l = get_lesson(lid)
    if g.role == "Member" and g.uid != l["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the lesson student")
    if g.role == "Coach" and g.uid != l["coach_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the lesson coach")
    return ok(pub(l))


def lesson_confirm_common(lesson, from_status):
    if lesson["status"] != from_status:
        raise ApiError("ERR_LESSON_NOT_ACTIONABLE", 409,
                       "lesson is not in %s" % from_status)
    coach = COACHES[lesson["coach_id"]]
    if coach["status"] != "ACTIVE":
        raise ApiError("ERR_COACH_INACTIVE", 409, "coach is INACTIVE")
    if coach_has_conflict(lesson["coach_id"], lesson):
        raise ApiError("ERR_COACH_OVERLAP", 409,
                       "buffered-interval conflict with another confirmed lesson")
    member = MEMBERS[lesson["member_id"]]
    if member["wallet_balance_cents"] < lesson["fee_cents"]:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", 402, "wallet balance too low")
    member["wallet_balance_cents"] -= lesson["fee_cents"]
    bump(member)
    lesson["status"] = "CONFIRMED"
    bump(lesson)
    return lesson


@app.route("/lessons/<lid>/confirm", methods=["POST"])
@require_roles("Coach")
def confirm_lesson(lid):
    l = get_lesson(lid)
    if g.uid != l["coach_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the lesson coach")
    lesson_confirm_common(l, "REQUESTED")
    return ok(pub(l))


@app.route("/lessons/<lid>/accept", methods=["POST"])
@require_roles("Member")
def accept_lesson(lid):
    l = get_lesson(lid)
    if g.uid != l["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the lesson student")
    lesson_confirm_common(l, "COUNTERED")
    return ok(pub(l))


@app.route("/lessons/<lid>/counter", methods=["POST"])
@require_roles("Member", "Coach")
def counter_lesson(lid):
    l = get_lesson(lid)
    if g.role == "Coach" and g.uid != l["coach_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the lesson coach")
    if g.role == "Member" and g.uid != l["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the lesson student")
    data = body()
    start_raw = need(data, "proposed_start_at")
    try:
        start = parse_dt(start_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid proposed_start_at")
    coach = COACHES[l["coach_id"]]
    if g.role == "Coach":
        if l["status"] != "REQUESTED":
            raise ApiError("ERR_LESSON_NOT_ACTIONABLE", 409,
                           "coach may only counter a REQUESTED lesson")
        if coach["status"] != "ACTIVE":
            raise ApiError("ERR_COACH_INACTIVE", 409, "coach is INACTIVE")
        l["status"] = "COUNTERED"
    else:
        if l["status"] != "COUNTERED":
            raise ApiError("ERR_LESSON_NOT_ACTIONABLE", 409,
                           "member may only counter a COUNTERED lesson")
        if coach["status"] != "ACTIVE":
            raise ApiError("ERR_COACH_INACTIVE", 409, "coach is INACTIVE")
        l["status"] = "REQUESTED"
    l["proposed_start_at"] = start_raw
    l["_proposed"] = start
    bump(l)
    return ok(pub(l))


@app.route("/lessons/<lid>/cancel", methods=["POST"])
@require_roles("Member", "Coach")
def cancel_lesson(lid):
    l = get_lesson(lid)
    if g.role == "Coach" and g.uid != l["coach_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the lesson coach")
    if g.role == "Member" and g.uid != l["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the lesson student")
    if l["status"] not in ("REQUESTED", "COUNTERED", "CONFIRMED"):
        raise ApiError("ERR_LESSON_NOT_ACTIONABLE", 409,
                       "lesson cannot be cancelled from %s" % l["status"])
    if l["status"] == "CONFIRMED" and NOW < l["_proposed"]:
        member = MEMBERS[l["member_id"]]
        member["wallet_balance_cents"] += l["fee_cents"]
        bump(member)
    l["status"] = "CANCELLED"
    bump(l)
    return ok(pub(l))


@app.route("/lessons/<lid>/complete", methods=["POST"])
@require_roles("Coach")
def complete_lesson(lid):
    l = get_lesson(lid)
    if g.uid != l["coach_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the lesson coach")
    if l["status"] != "CONFIRMED":
        raise ApiError("ERR_LESSON_NOT_ACTIONABLE", 409,
                       "lesson is not CONFIRMED")
    if NOW < l["_proposed"]:
        raise ApiError("ERR_LESSON_NOT_ACTIONABLE", 409,
                       "lesson cannot be completed before its proposed start")
    l["status"] = "COMPLETED"
    bump(l)
    return ok(pub(l))


# ---------------------------------------------------------------------------
# Leagues, entries, scorecards, standings
# ---------------------------------------------------------------------------

@app.route("/leagues", methods=["POST"])
@require_roles("LeagueDirector")
def create_league():
    data = body()
    name = need(data, "name")
    fee = need(data, "entry_fee_cents")
    cap = need(data, "max_entries")
    if not is_int(fee) or fee < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "entry_fee_cents must be >= 0")
    if not is_int(cap) or cap < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "max_entries must be >= 1")
    lg = new_entity(LEAGUES, {
        "name": name,
        "entry_fee_cents": fee,
        "max_entries": cap,
        "status": "OPEN",
        "gross_entry_fees_cents": 0,
        "range_share_cents": 0,
        "prize_pool_cents": 0,
    })
    return ok(pub(lg), 201)


def get_league(lid):
    lg = LEAGUES.get(lid)
    if not lg:
        raise ApiError("ERR_LEAGUE_NOT_FOUND", 404, "league not found")
    return lg


@app.route("/leagues/<lid>", methods=["GET"])
@require_roles("Anonymous", "Member", "Coach", "RangeOfficer", "ShopClerk",
               "LeagueDirector", "Admin")
def get_league_route(lid):
    return ok(pub(get_league(lid)))


@app.route("/leagues/<lid>/entries", methods=["POST"])
@require_roles("Member")
def enter_league(lid):
    lg = get_league(lid)
    member = MEMBERS.get(g.uid)
    if not member:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member not found")
    if lg["status"] != "OPEN":
        raise ApiError("ERR_LEAGUE_NOT_OPEN", 409, "league is not OPEN")
    require_active_member(member)
    require_active_waiver(member)
    entries = [e for e in ENTRIES.values() if e["league_id"] == lid]
    if any(e["member_id"] == g.uid for e in entries):
        raise ApiError("ERR_DUPLICATE_LEAGUE_ENTRY", 409,
                       "member already has an entry in this league")
    confirmed = sum(1 for e in entries if e["status"] == "CONFIRMED")
    if confirmed >= lg["max_entries"]:
        raise ApiError("ERR_LEAGUE_FULL", 422, "league is full")
    if member["wallet_balance_cents"] < lg["entry_fee_cents"]:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", 402, "wallet balance too low")
    member["wallet_balance_cents"] -= lg["entry_fee_cents"]
    bump(member)
    e = new_entity(ENTRIES, {
        "league_id": lid,
        "member_id": g.uid,
        "fee_paid_cents": lg["entry_fee_cents"],
        "status": "CONFIRMED",
        "refund_status": "NONE",
    })
    recompute_league_pools(lg)
    return ok(pub(e), 201)


@app.route("/league-entries", methods=["GET"])
@require_roles("Member", "LeagueDirector", "Admin")
def list_entries():
    items = list(ENTRIES.values())
    for f in ("league_id", "member_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    return _list(items, pub)


def get_entry(eid):
    e = ENTRIES.get(eid)
    if not e:
        raise ApiError("ERR_LEAGUE_ENTRY_NOT_FOUND", 404, "league entry not found")
    return e


@app.route("/league-entries/<eid>", methods=["GET"])
@require_roles("Member", "LeagueDirector", "Admin")
def get_entry_route(eid):
    e = get_entry(eid)
    if g.role == "Member" and g.uid != e["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the entrant")
    return ok(pub(e))


@app.route("/leagues/<lid>/close", methods=["POST"])
@require_roles("LeagueDirector")
def close_league(lid):
    lg = get_league(lid)
    if lg["status"] != "OPEN":
        raise ApiError("ERR_LEAGUE_NOT_OPEN", 409, "league is not OPEN")
    confirmed = [e for e in ENTRIES.values()
                 if e["league_id"] == lid and e["status"] == "CONFIRMED"]
    if not confirmed:
        raise ApiError("ERR_LEAGUE_NOT_OPEN", 409,
                       "league has no CONFIRMED entries")
    lg["status"] = "CLOSED"
    bump(lg)
    return ok(pub(lg))


@app.route("/leagues/<lid>/cancel", methods=["POST"])
@require_roles("LeagueDirector")
def cancel_league(lid):
    lg = get_league(lid)
    if lg["status"] == "OPEN":
        pass
    elif lg["status"] == "CLOSED":
        locked = [c for c in CARDS.values()
                  if ENTRIES.get(c["league_entry_id"], {}).get("league_id") == lid
                  and c["status"] == "LOCKED"]
        if locked:
            raise ApiError("ERR_LEAGUE_NOT_OPEN", 409,
                           "league has LOCKED scorecards")
    else:
        raise ApiError("ERR_LEAGUE_NOT_OPEN", 409,
                       "league cannot be cancelled from %s" % lg["status"])
    for e in [e for e in ENTRIES.values()
              if e["league_id"] == lid and e["status"] == "CONFIRMED"]:
        e["status"] = "CANCELLED"
        e["refund_status"] = "REFUNDED"
        bump(e)
        member = MEMBERS.get(e["member_id"])
        if member:
            member["wallet_balance_cents"] += e["fee_paid_cents"]
            bump(member)
    lg["status"] = "CANCELLED"
    recompute_league_pools(lg)
    return ok(pub(lg))


@app.route("/leagues/<lid>/standings", methods=["GET"])
@require_roles("Anonymous", "Member", "Coach", "RangeOfficer", "ShopClerk",
               "LeagueDirector", "Admin")
def standings(lid):
    get_league(lid)
    variant = request.args.get("variant", "SCRATCH")
    if variant not in ("SCRATCH", "HANDICAP"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid variant")
    rows = []
    for e in ENTRIES.values():
        if e["league_id"] != lid or e["status"] != "CONFIRMED":
            continue
        cards = [c for c in CARDS.values()
                 if c["league_entry_id"] == e["id"] and c["status"] == "LOCKED"]
        if not cards:
            continue
        total = sum(c["total_points"] for c in cards)
        xh = sum(c["x_hits"] for c in cards)
        avg = rhu(Decimal(total) / Decimal(len(cards)))
        handicap = rhu(Decimal("1.2") * max(0, 300 - avg))
        first = min(cards, key=lambda c: c["_seq"])
        rows.append({
            "league_entry_id": e["id"],
            "member_id": e["member_id"],
            "total_points": total,
            "x_hits": xh,
            "handicap_index": handicap,
            "adjusted_points": total + handicap,
            "_first": first["_seq"],
        })
    if variant == "HANDICAP":
        rows.sort(key=lambda r: (-r["adjusted_points"], -r["total_points"],
                                 -r["x_hits"], r["_first"]))
    else:
        rows.sort(key=lambda r: (-r["total_points"], -r["x_hits"], r["_first"]))
    out = []
    for i, r in enumerate(rows):
        d = {k: v for k, v in r.items() if not k.startswith("_")}
        d["rank"] = i + 1
        out.append(d)
    return ok({"variant": variant, "rows": out})


def validate_ends(ends):
    if not isinstance(ends, list) or len(ends) != 10:
        raise ApiError("ERR_INVALID_REQUEST", 400, "ends must contain exactly 10 ends")
    for end in ends:
        if not isinstance(end, list) or len(end) != 3:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "each end must contain exactly 3 arrows")
        for arrow in end:
            if not is_int(arrow) or arrow < 0 or arrow > 10:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "each arrow must be an integer 0..10")


def validate_x_hits(x):
    if not is_int(x) or x < 0 or x > 30:
        raise ApiError("ERR_INVALID_REQUEST", 400, "x_hits must be an integer 0..30")


@app.route("/league-entries/<eid>/scorecards", methods=["POST"])
@require_roles("Member")
def submit_scorecard(eid):
    e = get_entry(eid)
    if g.uid != e["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the entrant")
    data = body()
    ends = need(data, "ends")
    x_hits = need(data, "x_hits")
    validate_ends(ends)
    validate_x_hits(x_hits)
    lg = LEAGUES[e["league_id"]]
    if lg["status"] != "CLOSED" or e["status"] != "CONFIRMED":
        raise ApiError("ERR_LEAGUE_NOT_OPEN", 409,
                       "scorecards require a CLOSED league and CONFIRMED entry")
    total = sum(a for end in ends for a in end)
    c = new_entity(CARDS, {
        "league_entry_id": eid,
        "ends": ends,
        "x_hits": x_hits,
        "total_points": total,
        "status": "SUBMITTED",
    })
    return ok(pub(c), 201)


@app.route("/league-entries/<eid>/scorecards", methods=["GET"])
@require_roles("Member", "LeagueDirector", "Admin")
def list_scorecards(eid):
    e = get_entry(eid)
    if g.role == "Member" and g.uid != e["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the entrant")
    items = [c for c in CARDS.values() if c["league_entry_id"] == eid]
    return _list(items, pub)


def get_scorecard(cid):
    c = CARDS.get(cid)
    if not c:
        raise ApiError("ERR_SCORECARD_NOT_FOUND", 404, "scorecard not found")
    return c


@app.route("/scorecards/<cid>", methods=["PUT"])
@require_roles("Member")
def edit_scorecard(cid):
    c = get_scorecard(cid)
    e = ENTRIES[c["league_entry_id"]]
    if g.uid != e["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the entrant")
    data = body()
    ends = need(data, "ends")
    x_hits = need(data, "x_hits")
    expected = need(data, "expected_scorecard_version")
    validate_ends(ends)
    validate_x_hits(x_hits)
    if not is_int(expected):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_scorecard_version must be an integer")
    if c["status"] not in ("SUBMITTED", "DISPUTED"):
        raise ApiError("ERR_SCORECARD_NOT_EDITABLE", 409,
                       "scorecard is not editable in %s" % c["status"])
    if expected != c["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_scorecard_version does not match current version")
    c["ends"] = ends
    c["x_hits"] = x_hits
    c["total_points"] = sum(a for end in ends for a in end)
    c["status"] = "SUBMITTED"
    bump(c)
    return ok(pub(c))


@app.route("/scorecards/<cid>/verify", methods=["POST"])
@require_roles("LeagueDirector")
def verify_scorecard(cid):
    c = get_scorecard(cid)
    if c["status"] == "LOCKED":
        raise ApiError("ERR_SCORECARD_LOCKED", 409, "scorecard is LOCKED")
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_SCORECARD_NOT_EDITABLE", 409,
                       "scorecard is not SUBMITTED")
    e = ENTRIES[c["league_entry_id"]]
    if e["status"] != "CONFIRMED":
        raise ApiError("ERR_LEAGUE_NOT_OPEN", 409,
                       "parent entry is not CONFIRMED")
    c["status"] = "VERIFIED"
    bump(c)
    return ok(pub(c))


@app.route("/scorecards/<cid>/dispute", methods=["POST"])
@require_roles("LeagueDirector")
def dispute_scorecard(cid):
    c = get_scorecard(cid)
    if c["status"] == "LOCKED":
        raise ApiError("ERR_SCORECARD_LOCKED", 409, "scorecard is LOCKED")
    if c["status"] != "VERIFIED":
        raise ApiError("ERR_SCORECARD_NOT_EDITABLE", 409,
                       "scorecard is not VERIFIED")
    c["status"] = "DISPUTED"
    bump(c)
    return ok(pub(c))


@app.route("/scorecards/<cid>/lock", methods=["POST"])
@require_roles("LeagueDirector")
def lock_scorecard(cid):
    c = get_scorecard(cid)
    if c["status"] == "LOCKED":
        raise ApiError("ERR_SCORECARD_LOCKED", 409, "scorecard is already LOCKED")
    if c["status"] != "VERIFIED":
        raise ApiError("ERR_SCORECARD_NOT_EDITABLE", 409,
                       "scorecard is not VERIFIED")
    c["status"] = "LOCKED"
    bump(c)
    e = ENTRIES[c["league_entry_id"]]
    lg = LEAGUES[e["league_id"]]
    if lg["status"] == "CLOSED":
        confirmed = [x for x in ENTRIES.values()
                     if x["league_id"] == lg["id"] and x["status"] == "CONFIRMED"]
        complete = bool(confirmed)
        for x in confirmed:
            cards = [sc for sc in CARDS.values() if sc["league_entry_id"] == x["id"]]
            if not cards or any(sc["status"] != "LOCKED" for sc in cards):
                complete = False
                break
        if complete:
            lg["status"] = "COMPLETED"
            bump(lg)
    return ok(pub(c))


# ---------------------------------------------------------------------------
# Pro-shop: products, sales, repair orders
# ---------------------------------------------------------------------------

@app.route("/shop-products", methods=["POST"])
@require_roles("ShopClerk", "Admin")
def create_product():
    data = body()
    name = need(data, "name")
    sku = need(data, "sku")
    price = need(data, "unit_price_cents")
    stock = need(data, "initial_stock")
    if not is_int(price) or price < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "unit_price_cents must be >= 0")
    if not is_int(stock) or stock < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "initial_stock must be >= 0")
    if any(p["sku"] == sku for p in PRODUCTS.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "sku must be unique")
    p = new_entity(PRODUCTS, {"name": name, "sku": sku,
                              "unit_price_cents": price,
                              "stock_quantity": stock,
                              "initial_stock": stock})
    return ok(pub(p), 201)


@app.route("/shop-products", methods=["GET"])
@require_roles("Anonymous", "Member", "Coach", "RangeOfficer", "ShopClerk",
               "LeagueDirector", "Admin")
def list_products():
    return _list(list(PRODUCTS.values()), pub)


@app.route("/sales", methods=["POST"])
@require_roles("ShopClerk")
def create_sale():
    data = body()
    items = need(data, "items")
    member_id = data.get("member_id")
    if member_id is not None and member_id not in MEMBERS:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member not found")
    if not isinstance(items, list) or not items:
        raise ApiError("ERR_INVALID_REQUEST", 400, "items must be a non-empty array")
    lines = []
    for line in items:
        if not isinstance(line, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid line item")
        pid = line.get("product_id")
        qty = line.get("qty")
        pct = line.get("line_discount_pct", 0)
        if pid is None or not is_int(qty) or qty < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid line item")
        if not is_num(pct) or pct < 0 or pct > 0.9:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "line_discount_pct must be 0..0.9")
        product = PRODUCTS.get(pid)
        if not product:
            raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
        lines.append((product, qty, pct))
    for product, qty, _pct in lines:
        if qty > product["stock_quantity"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 422,
                           "insufficient stock for product %s" % product["id"])
    line_gross = []
    for product, qty, pct in lines:
        lg = rhu(Decimal(qty) * Decimal(product["unit_price_cents"]) *
                 (1 - Decimal(str(pct))))
        line_gross.append(lg)
    subtotal = sum(line_gross)
    volume = rhu(Decimal(subtotal) * Decimal("0.10")) if subtotal >= 10000 else 0
    taxable = subtotal - volume
    tax = rhu(Decimal(taxable) * Decimal("0.0825"))
    total = taxable + tax
    for product, qty, _pct in lines:
        product["stock_quantity"] -= qty
        bump(product)
    sale = new_entity(SALES, {
        "member_id": member_id,
        "items": items,
        "line_gross_cents": line_gross,
        "subtotal_cents": subtotal,
        "volume_discount_cents": volume,
        "tax_cents": tax,
        "total_cents": total,
    })
    return ok(pub(sale), 201)


@app.route("/sales", methods=["GET"])
@require_roles("ShopClerk", "Admin")
def list_sales():
    items = list(SALES.values())
    v = request.args.get("member_id")
    if v is not None:
        items = [s for s in items if s.get("member_id") == v]
    return _list(items, pub)


@app.route("/sales/<sid>", methods=["GET"])
@require_roles("ShopClerk", "Admin")
def get_sale(sid):
    s = SALES.get(sid)
    if not s:
        raise ApiError("ERR_SALE_NOT_FOUND", 404, "sale not found")
    return ok(pub(s))


def get_repair(rid):
    r = REPAIRS.get(rid)
    if not r:
        raise ApiError("ERR_REPAIR_ORDER_NOT_FOUND", 404, "repair order not found")
    return r


@app.route("/repair-orders", methods=["POST"])
@require_roles("ShopClerk")
def create_repair():
    data = body()
    member_id = need(data, "member_id")
    if member_id not in MEMBERS:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member not found")
    desc = need(data, "item_description")
    if not isinstance(desc, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "item_description must be a string")
    r = new_entity(REPAIRS, {
        "member_id": member_id,
        "item_description": desc,
        "status": "INTAKE",
        "parts_reserved": [],
        "labor_minutes": None,
        "promised_hours": None,
        "parts_total_cents": None,
        "labor_total_cents": None,
        "quote_total_cents": None,
    })
    return ok(pub(r), 201)


@app.route("/repair-orders", methods=["GET"])
@require_roles("ShopClerk", "Member", "Admin")
def list_repairs():
    items = list(REPAIRS.values())
    for f in ("member_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    return _list(items, pub)


@app.route("/repair-orders/<rid>", methods=["GET"])
@require_roles("ShopClerk", "Member", "Admin")
def get_repair_route(rid):
    r = get_repair(rid)
    if g.role == "Member" and g.uid != r["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the equipment owner")
    return ok(pub(r))


@app.route("/repair-orders/<rid>/quote", methods=["POST"])
@require_roles("ShopClerk")
def quote_repair(rid):
    r = get_repair(rid)
    data = body()
    parts = data.get("parts", data.get("parts_reserved"))
    if parts is None:
        parts = []
    labor = need(data, "labor_minutes")
    promised = need(data, "promised_hours")
    expected = need(data, "expected_repair_order_version")
    if not isinstance(parts, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "parts must be an array")
    if not is_int(labor) or labor <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "labor_minutes must be > 0")
    if not is_num(promised):
        raise ApiError("ERR_INVALID_REQUEST", 400, "promised_hours is required")
    if not is_int(expected):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_repair_order_version must be an integer")
    norm_parts = []
    for part in parts:
        if not isinstance(part, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid part entry")
        pid = part.get("product_id")
        qty = part.get("qty")
        if pid is None or not is_int(qty) or qty < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid part entry")
        product = PRODUCTS.get(pid)
        if not product:
            raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
        norm_parts.append({"product_id": pid, "qty": qty})
    if r["status"] not in ("INTAKE", "QUOTED"):
        raise ApiError("ERR_REPAIR_INVALID_STATE", 409,
                       "cannot quote from %s" % r["status"])
    if expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_repair_order_version does not match current version")
    # release any previously reserved parts before reserving the new set
    for old in r["parts_reserved"]:
        product = PRODUCTS.get(old["product_id"])
        if product:
            product["stock_quantity"] += old["qty"]
            bump(product)
    for part in norm_parts:
        product = PRODUCTS[part["product_id"]]
        if part["qty"] > product["stock_quantity"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 422,
                           "insufficient stock for part %s" % part["product_id"])
    owner = MEMBERS[r["member_id"]]
    parts_total = sum(p["qty"] * PRODUCTS[p["product_id"]]["unit_price_cents"]
                      for p in norm_parts)
    labor_blocks = math.ceil(labor / 30)
    labor_amount = labor_blocks * 1500
    labor_discounted = rhu(Decimal(labor_amount) *
                           (1 - TIER_DISCOUNT[owner["tier"]]))
    rush = rhu(Decimal(labor_discounted) * Decimal("0.25")) if promised < 48 else 0
    labor_total = labor_discounted + rush
    for part in norm_parts:
        product = PRODUCTS[part["product_id"]]
        product["stock_quantity"] -= part["qty"]
        bump(product)
    r["parts_reserved"] = norm_parts
    r["labor_minutes"] = labor
    r["promised_hours"] = promised
    r["parts_total_cents"] = parts_total
    r["labor_total_cents"] = labor_total
    r["quote_total_cents"] = parts_total + labor_total
    r["status"] = "QUOTED"
    bump(r)
    return ok(pub(r))


def release_reserved_parts(r):
    for part in r["parts_reserved"]:
        product = PRODUCTS.get(part["product_id"])
        if product:
            product["stock_quantity"] += part["qty"]
            bump(product)
    r["parts_reserved"] = []


@app.route("/repair-orders/<rid>/approve", methods=["POST"])
@require_roles("Member")
def approve_repair(rid):
    r = get_repair(rid)
    if g.uid != r["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the equipment owner")
    if r["status"] != "QUOTED":
        raise ApiError("ERR_REPAIR_INVALID_STATE", 409, "order is not QUOTED")
    r["status"] = "IN_REPAIR"
    bump(r)
    return ok(pub(r))


@app.route("/repair-orders/<rid>/decline", methods=["POST"])
@require_roles("Member")
def decline_repair(rid):
    r = get_repair(rid)
    if g.uid != r["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the equipment owner")
    if r["status"] != "QUOTED":
        raise ApiError("ERR_REPAIR_INVALID_STATE", 409, "order is not QUOTED")
    release_reserved_parts(r)
    r["status"] = "DECLINED"
    bump(r)
    return ok(pub(r))


@app.route("/repair-orders/<rid>/complete", methods=["POST"])
@require_roles("ShopClerk")
def complete_repair(rid):
    r = get_repair(rid)
    if r["status"] != "IN_REPAIR":
        raise ApiError("ERR_REPAIR_INVALID_STATE", 409,
                       "order is not IN_REPAIR")
    r["status"] = "READY"
    bump(r)
    return ok(pub(r))


@app.route("/repair-orders/<rid>/pickup", methods=["POST"])
@require_roles("ShopClerk")
def pickup_repair(rid):
    r = get_repair(rid)
    if r["status"] not in ("READY", "DECLINED"):
        raise ApiError("ERR_REPAIR_INVALID_STATE", 409,
                       "order cannot be picked up from %s" % r["status"])
    if r["status"] == "READY":
        owner = MEMBERS[r["member_id"]]
        if owner["wallet_balance_cents"] < r["quote_total_cents"]:
            raise ApiError("ERR_INSUFFICIENT_FUNDS", 402,
                           "wallet balance too low")
        owner["wallet_balance_cents"] -= r["quote_total_cents"]
        bump(owner)
    r["status"] = "PICKED_UP"
    bump(r)
    return ok(pub(r))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
