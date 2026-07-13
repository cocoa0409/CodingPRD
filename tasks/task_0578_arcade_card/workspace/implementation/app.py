"""
Arcade Card API — Family Entertainment Center & Arcade Card.

Single-file Flask implementation. In-memory only (Python dicts keyed by id).
The store starts EMPTY on every boot; nothing is seeded. Every entity is
constructed by tests through the declared endpoints.
"""
import math
import os
import random
import re
import string
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
KNOWN_ROLES = {"Member", "Cashier", "Attendant", "Coordinator", "Manager"}
ALL_ROLES = KNOWN_ROLES

MAX_VENUE_OCCUPANCY = 200
CARD_BALANCE_CAP_CENTS = 100000
PER_EXTRA_GUEST_CENTS = 1500
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

SILVER_THRESHOLD = 50000
GOLD_THRESHOLD = 200000
PLATINUM_THRESHOLD = 500000

# bonus percentage expressed as integer numerator over 100 (floor division)
BONUS_PCT_NUM = {"NONE": 0, "SILVER": 5, "GOLD": 10, "PLATINUM": 20}
# gameplay points tier multiplier as exact rational num/den (floor)
TIER_MULT = {"NONE": (1, 1), "SILVER": (11, 10), "GOLD": (5, 4), "PLATINUM": (3, 2)}


# =============================================================================
# In-memory store
# =============================================================================
MEMBERS = {}
CARDS = {}
LEDGER = {}
ATTRACTIONS = {}
PRIZES = {}
REDEMPTIONS = {}
GAMEPLAYS = {}
PACKAGES = {}
ROOMS = {}
BOOKINGS = {}
WRISTBANDS = {}
RECONCILIATIONS = {}

STATE = {"clock": None}
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


# =============================================================================
# Time / logical clock
# =============================================================================
def parse_iso(s):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        # Fallback for forms 3.9's fromisoformat rejects (e.g. no seconds).
        m = re.match(
            r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?"
            r"(?:\.(\d+))?(?:([+-]\d{2}):?(\d{2}))?$",
            t,
        )
        if not m:
            raise
        yr, mo, dy, hh, mm = (int(m.group(i)) for i in range(1, 6))
        ss = int(m.group(6) or 0)
        frac = m.group(7) or "0"
        micro = int((frac + "000000")[:6])
        tz = timezone.utc
        if m.group(8) is not None:
            off = int(m.group(8)) * 60 + (int(m.group(9)) if int(m.group(8)) >= 0 else -int(m.group(9)))
            from datetime import timedelta
            tz = timezone(timedelta(minutes=off))
        dt = datetime(yr, mo, dy, hh, mm, ss, micro, tz)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_dt():
    return STATE["clock"]


def now_iso():
    return iso(now_dt())


def business_day():
    return now_dt().strftime("%Y-%m-%d")


STATE["clock"] = parse_iso(DEFAULT_CLOCK_UTC)


# =============================================================================
# Errors + response envelope
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}


def envelope(data, response_type, status, extra_meta=None):
    m = meta_base()
    if extra_meta:
        m.update(extra_meta)
    return jsonify({"meta": m, "response_type": response_type, "data": data}), status


def ok_object(data, status=200):
    return envelope(data, "object", status)


def ok_array(items, pagination):
    return envelope(items, "array", 200, pagination)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return envelope({"error_id": e.error_id, "message": e.message}, "error", e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return envelope({"error_id": "ERR_NOT_FOUND", "message": "route not found"}, "error", 404)


@app.errorhandler(405)
def handle_405(e):
    return envelope({"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "method not allowed"}, "error", 405)


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return envelope({"error_id": "ERR_INTERNAL", "message": str(e)}, "error", 500)


# =============================================================================
# Auth / RBAC
# =============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")


# =============================================================================
# Body / field helpers
# =============================================================================
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 422, "body must be a JSON object")
    return b


def require_present(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", 422, "%s is required" % name)
    return body[name]


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", 422, "%s must be an integer" % name)
    return value


def require_int(body, name, minimum=None, strict=False):
    v = as_int(require_present(body, name), name)
    if minimum is not None:
        if strict and not v > minimum:
            raise ApiError("ERR_VALIDATION", 422, "%s must be > %s" % (name, minimum))
        if not strict and v < minimum:
            raise ApiError("ERR_VALIDATION", 422, "%s must be >= %s" % (name, minimum))
    return v


def require_str(body, name):
    v = require_present(body, name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, "%s must be a non-empty string" % name)
    return v


def require_enum(body, name, allowed):
    v = require_present(body, name)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 422, "%s must be one of %s" % (name, sorted(allowed)))
    return v


# =============================================================================
# Entity construction + serialization
# =============================================================================
def new_common(fields):
    ts = now_iso()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def paginate(items):
    """items: list already sorted. Returns (page, pagination_meta)."""
    args = request.args
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def sorted_by_seq(values):
    return sorted(values, key=lambda e: e["_seq"])


# =============================================================================
# Domain helpers
# =============================================================================
def tier_of(spend):
    if spend >= PLATINUM_THRESHOLD:
        return "PLATINUM"
    if spend >= GOLD_THRESHOLD:
        return "GOLD"
    if spend >= SILVER_THRESHOLD:
        return "SILVER"
    return "NONE"


def append_ledger(card, entry_type, chip_delta=0, bonus_delta=0, points_delta=0, note=""):
    entry = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "card_id": card["id"],
        "entry_type": entry_type,
        "chip_delta_cents": chip_delta,
        "bonus_delta_cents": bonus_delta,
        "points_delta": points_delta,
        "business_day": business_day(),
        "note": note,
        "occurred_at": now_iso(),
        "_seq": next_seq(),
    }
    LEDGER[entry["id"]] = entry
    card["chip_balance_cents"] += chip_delta
    card["bonus_chip_balance_cents"] += bonus_delta
    card["ticket_points_balance"] += points_delta
    return entry


def resolve(store, ident, err_id):
    ent = store.get(ident)
    if ent is None:
        raise ApiError(err_id, 404, "%s: %s" % (err_id, ident))
    return ent


def overlaps(a_start, a_end, b_start, b_end):
    # half-open [start,end): touching boundaries do not overlap
    return a_start < b_end and b_start < a_end


def ceil_hours(start_dt, end_dt):
    seconds = (end_dt - start_dt).total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 3600.0))


def card_effective_tier(card):
    owner_id = card.get("owner_member_id")
    if owner_id and owner_id in MEMBERS:
        return MEMBERS[owner_id]["membership_tier"]
    return "NONE"


# =============================================================================
# Clock endpoint
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {"Manager"})
    body = get_body()
    target = require_present(body, "to_iso8601")
    try:
        dt = parse_iso(target)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 422, "to_iso8601 must be a valid ISO-8601 instant")
    STATE["clock"] = dt
    return ok_object({})


# =============================================================================
# Attractions
# =============================================================================
@app.route("/attractions", methods=["POST"])
def create_attraction():
    _, role = authenticate()
    authorize(role, {"Manager"})
    body = get_body()
    name = require_str(body, "name")
    chip_cost = require_int(body, "chip_cost_cents", minimum=0, strict=True)
    points_award = require_int(body, "points_award", minimum=0, strict=False)
    ent = new_common({
        "name": name,
        "chip_cost_cents": chip_cost,
        "points_award": points_award,
        "status": "OPEN",
    })
    ATTRACTIONS[ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/attractions/<aid>", methods=["PATCH"])
def patch_attraction(aid):
    _, role = authenticate()
    authorize(role, {"Manager"})
    ent = resolve(ATTRACTIONS, aid, "ERR_ATTRACTION_NOT_FOUND")
    body = get_body()
    if "status" in body and body["status"] is not None:
        if body["status"] not in {"OPEN", "MAINTENANCE", "RETIRED"}:
            raise ApiError("ERR_VALIDATION", 422, "invalid status")
        ent["status"] = body["status"]
    if "chip_cost_cents" in body and body["chip_cost_cents"] is not None:
        ent["chip_cost_cents"] = require_int(body, "chip_cost_cents", minimum=0, strict=True)
    if "points_award" in body and body["points_award"] is not None:
        ent["points_award"] = require_int(body, "points_award", minimum=0, strict=False)
    touch(ent)
    return ok_object(serialize(ent))


@app.route("/attractions/<aid>", methods=["GET"])
def get_attraction(aid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ent = resolve(ATTRACTIONS, aid, "ERR_ATTRACTION_NOT_FOUND")
    return ok_object(serialize(ent))


# =============================================================================
# Prize items
# =============================================================================
@app.route("/prize-items", methods=["POST"])
def create_prize():
    _, role = authenticate()
    authorize(role, {"Manager"})
    body = get_body()
    name = require_str(body, "name")
    points_price = require_int(body, "points_price", minimum=0, strict=True)
    stock_qty = require_int(body, "stock_qty", minimum=0, strict=False)
    ent = new_common({
        "name": name,
        "points_price": points_price,
        "stock_qty": stock_qty,
        "reserved_qty": 0,
        "status": "AVAILABLE",
    })
    PRIZES[ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/prize-items/<pid>", methods=["PATCH"])
def patch_prize(pid):
    _, role = authenticate()
    authorize(role, {"Manager"})
    ent = resolve(PRIZES, pid, "ERR_PRIZE_NOT_FOUND")
    body = get_body()
    status_given = "status" in body and body["status"] is not None
    if status_given:
        if body["status"] not in {"AVAILABLE", "OUT_OF_STOCK", "DISCONTINUED"}:
            raise ApiError("ERR_VALIDATION", 422, "invalid status")
        ent["status"] = body["status"]
    if "points_price" in body and body["points_price"] is not None:
        ent["points_price"] = require_int(body, "points_price", minimum=0, strict=True)
    if "stock_qty" in body and body["stock_qty"] is not None:
        ent["stock_qty"] = require_int(body, "stock_qty", minimum=0, strict=False)
    # Derive OUT_OF_STOCK / AVAILABLE from stock only when status not explicitly
    # set in this request and the prize is not DISCONTINUED.
    if not status_given and ent["status"] != "DISCONTINUED":
        if ent["stock_qty"] == 0:
            ent["status"] = "OUT_OF_STOCK"
        elif ent["status"] == "OUT_OF_STOCK" and ent["stock_qty"] > 0:
            ent["status"] = "AVAILABLE"
    touch(ent)
    return ok_object(serialize(ent))


@app.route("/prize-items/<pid>", methods=["GET"])
def get_prize(pid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ent = resolve(PRIZES, pid, "ERR_PRIZE_NOT_FOUND")
    return ok_object(serialize(ent))


# =============================================================================
# Party packages
# =============================================================================
@app.route("/party-packages", methods=["POST"])
def create_package():
    _, role = authenticate()
    authorize(role, {"Manager"})
    body = get_body()
    ent = new_common({
        "name": require_str(body, "name"),
        "base_price_cents": require_int(body, "base_price_cents", minimum=0, strict=True),
        "included_guests": require_int(body, "included_guests", minimum=0, strict=True),
        "included_hours": require_int(body, "included_hours", minimum=0, strict=True),
        "included_chip_cents": require_int(body, "included_chip_cents", minimum=0, strict=False),
        "tier": require_enum(body, "tier", {"BRONZE", "SILVER", "GOLD"}),
        "combo_name": require_str(body, "combo_name"),
        "combo_value_cents": require_int(body, "combo_value_cents", minimum=0, strict=False),
    })
    PACKAGES[ent["id"]] = ent
    return ok_object(serialize(ent), 201)


# =============================================================================
# Rooms
# =============================================================================
@app.route("/rooms", methods=["POST"])
def create_room():
    _, role = authenticate()
    authorize(role, {"Manager"})
    body = get_body()
    ent = new_common({
        "name": require_str(body, "name"),
        "capacity": require_int(body, "capacity", minimum=0, strict=True),
        "hourly_rate_cents": require_int(body, "hourly_rate_cents", minimum=0, strict=False),
        "status": "AVAILABLE",
    })
    ROOMS[ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/rooms/<rid>", methods=["PATCH"])
def patch_room(rid):
    _, role = authenticate()
    authorize(role, {"Manager"})
    ent = resolve(ROOMS, rid, "ERR_ROOM_NOT_FOUND")
    body = get_body()
    if "status" in body and body["status"] is not None:
        if body["status"] not in {"AVAILABLE", "MAINTENANCE"}:
            raise ApiError("ERR_VALIDATION", 422, "invalid status")
        ent["status"] = body["status"]
    touch(ent)
    return ok_object(serialize(ent))


@app.route("/rooms/<rid>", methods=["GET"])
def get_room(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ent = resolve(ROOMS, rid, "ERR_ROOM_NOT_FOUND")
    return ok_object(serialize(ent))


# =============================================================================
# Members
# =============================================================================
@app.route("/members", methods=["POST"])
def create_member():
    _, role = authenticate()
    authorize(role, {"Cashier", "Manager"})
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    promo_opt_in = body.get("promo_opt_in", False)
    if not isinstance(promo_opt_in, bool):
        raise ApiError("ERR_VALIDATION", 422, "promo_opt_in must be a boolean")
    for m in MEMBERS.values():
        if m["email"] == email:
            raise ApiError("ERR_VALIDATION", 422, "email already in use")
    ent = new_common({
        "email": email,
        "full_name": full_name,
        "promo_opt_in": promo_opt_in,
        "lifetime_spend_cents": 0,
        "membership_tier": "NONE",
        "status": "ACTIVE",
    })
    MEMBERS[ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ent = resolve(MEMBERS, mid, "ERR_MEMBER_NOT_FOUND")
    return ok_object(serialize(ent))


# =============================================================================
# Game cards
# =============================================================================
def new_card(owner_member_id, status):
    ent = new_common({
        "owner_member_id": owner_member_id,
        "status": status,
        "chip_balance_cents": 0,
        "bonus_chip_balance_cents": 0,
        "ticket_points_balance": 0,
    })
    CARDS[ent["id"]] = ent
    return ent


@app.route("/game-cards", methods=["POST"])
def create_card():
    _, role = authenticate()
    authorize(role, {"Cashier"})
    body = get_body()
    owner_id = body.get("owner_member_id")
    if owner_id is not None:
        if not isinstance(owner_id, str):
            raise ApiError("ERR_VALIDATION", 422, "owner_member_id must be a string")
        resolve(MEMBERS, owner_id, "ERR_MEMBER_NOT_FOUND")
    ent = new_card(owner_id, "INACTIVE")
    return ok_object(serialize(ent), 201)


@app.route("/game-cards/<cid>", methods=["GET"])
def get_card(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ent = resolve(CARDS, cid, "ERR_CARD_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/game-cards", methods=["GET"])
def list_cards():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = sorted_by_seq(CARDS.values())
    owner = request.args.get("owner_member_id")
    status = request.args.get("status")
    if owner is not None:
        items = [c for c in items if c.get("owner_member_id") == owner]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return ok_array([serialize(c) for c in page], meta)


@app.route("/game-cards/<cid>/activate", methods=["POST"])
def activate_card(cid):
    _, role = authenticate()
    authorize(role, {"Cashier"})
    card = resolve(CARDS, cid, "ERR_CARD_NOT_FOUND")
    if card["status"] != "INACTIVE":
        raise ApiError("ERR_INVALID_CARD_STATE", 409, "card is not INACTIVE")
    card["status"] = "ACTIVE"
    touch(card)
    return ok_object(serialize(card))


@app.route("/game-cards/<cid>/reload", methods=["POST"])
def reload_card(cid):
    _, role = authenticate()
    authorize(role, {"Cashier"})
    card = resolve(CARDS, cid, "ERR_CARD_NOT_FOUND")
    body = get_body()
    amount = require_int(body, "amount_cents", minimum=0, strict=True)
    # promo_code optional and unused by valuation
    # card operability (step 5)
    if card["status"] == "FROZEN":
        raise ApiError("ERR_CARD_FROZEN", 409, "card is FROZEN")
    if card["status"] != "ACTIVE":
        raise ApiError("ERR_CARD_NOT_ACTIVE", 409, "card is not ACTIVE")
    # fiscal cap (step 11)
    if card["chip_balance_cents"] + amount > CARD_BALANCE_CAP_CENTS:
        raise ApiError("ERR_CARD_BALANCE_CAP_EXCEEDED", 422, "reload exceeds per-card cap")

    owner_id = card.get("owner_member_id")
    member = MEMBERS.get(owner_id) if owner_id else None
    if member is not None:
        tier_at_reload = tier_of(member["lifetime_spend_cents"])
    else:
        tier_at_reload = "NONE"
    bonus = (amount * BONUS_PCT_NUM[tier_at_reload]) // 100

    append_ledger(card, "RELOAD", chip_delta=amount, note="reload")
    if bonus > 0:
        append_ledger(card, "BONUS_GRANT", bonus_delta=bonus, note="reload promo bonus")
    if member is not None:
        member["lifetime_spend_cents"] += amount
        member["membership_tier"] = tier_of(member["lifetime_spend_cents"])
        touch(member)
    touch(card)
    return ok_object(serialize(card))


@app.route("/game-cards/<cid>/freeze", methods=["POST"])
def freeze_card(cid):
    _, role = authenticate()
    authorize(role, {"Manager"})
    card = resolve(CARDS, cid, "ERR_CARD_NOT_FOUND")
    if card["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_CARD_STATE", 409, "card is not ACTIVE")
    card["status"] = "FROZEN"
    touch(card)
    return ok_object(serialize(card))


@app.route("/game-cards/<cid>/close", methods=["POST"])
def close_card(cid):
    _, role = authenticate()
    authorize(role, {"Cashier", "Manager"})
    card = resolve(CARDS, cid, "ERR_CARD_NOT_FOUND")
    if card["status"] not in {"ACTIVE", "FROZEN"}:
        raise ApiError("ERR_INVALID_CARD_STATE", 409, "card cannot be closed from its state")
    card["status"] = "CLOSED"
    touch(card)
    return ok_object(serialize(card))


@app.route("/game-cards/<cid>/ledger", methods=["GET"])
def list_ledger(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    resolve(CARDS, cid, "ERR_CARD_NOT_FOUND")
    items = sorted_by_seq([e for e in LEDGER.values() if e["card_id"] == cid])
    page, meta = paginate(items)
    return ok_array([serialize(e) for e in page], meta)


# =============================================================================
# Game plays
# =============================================================================
@app.route("/game-plays", methods=["POST"])
def create_gameplay():
    uid, role = authenticate()
    authorize(role, {"Attendant", "Member"})
    body = get_body()
    card_id = require_present(body, "card_id")
    attraction_id = require_present(body, "attraction_id")
    if not isinstance(card_id, str) or not isinstance(attraction_id, str):
        raise ApiError("ERR_VALIDATION", 422, "card_id and attraction_id must be strings")
    # existence (path none; body FKs left-to-right)
    card = resolve(CARDS, card_id, "ERR_CARD_NOT_FOUND")
    attraction = resolve(ATTRACTIONS, attraction_id, "ERR_ATTRACTION_NOT_FOUND")
    # member ownership
    if role == "Member" and card.get("owner_member_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "member does not own this card")
    # card operability (step 5)
    if card["status"] == "FROZEN":
        raise ApiError("ERR_CARD_FROZEN", 409, "card is FROZEN")
    if card["status"] != "ACTIVE":
        raise ApiError("ERR_CARD_NOT_ACTIVE", 409, "card is not ACTIVE")
    # referential status (step 7)
    if attraction["status"] != "OPEN":
        raise ApiError("ERR_ATTRACTION_NOT_OPEN", 409, "attraction is not OPEN")
    # fiscal (step 11)
    cost = attraction["chip_cost_cents"]
    if card["bonus_chip_balance_cents"] + card["chip_balance_cents"] < cost:
        raise ApiError("ERR_INSUFFICIENT_CHIP_BALANCE", 402, "insufficient chip balance")

    chip_from_bonus = min(card["bonus_chip_balance_cents"], cost)
    chip_from_stored = cost - chip_from_bonus
    tier = card_effective_tier(card)
    num, den = TIER_MULT[tier]
    points_awarded = (attraction["points_award"] * num) // den

    append_ledger(
        card, "GAMEPLAY_DEBIT",
        chip_delta=-chip_from_stored,
        bonus_delta=-chip_from_bonus,
        points_delta=points_awarded,
        note="gameplay",
    )
    touch(card)

    play = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "card_id": card_id,
        "attraction_id": attraction_id,
        "chip_cost_cents": cost,
        "chip_from_bonus_cents": chip_from_bonus,
        "chip_from_stored_cents": chip_from_stored,
        "points_awarded": points_awarded,
        "business_day": business_day(),
        "_seq": next_seq(),
    }
    GAMEPLAYS[play["id"]] = play
    return ok_object(serialize(play), 201)


@app.route("/game-plays/<gid>", methods=["GET"])
def get_gameplay(gid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ent = resolve(GAMEPLAYS, gid, "ERR_GAMEPLAY_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/game-plays", methods=["GET"])
def list_gameplays():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = sorted_by_seq(GAMEPLAYS.values())
    card_id = request.args.get("card_id")
    attraction_id = request.args.get("attraction_id")
    if card_id is not None:
        items = [g for g in items if g["card_id"] == card_id]
    if attraction_id is not None:
        items = [g for g in items if g["attraction_id"] == attraction_id]
    page, meta = paginate(items)
    return ok_array([serialize(g) for g in page], meta)


# =============================================================================
# Redemptions
# =============================================================================
@app.route("/redemptions", methods=["POST"])
def create_redemption():
    uid, role = authenticate()
    authorize(role, {"Attendant", "Member"})
    body = get_body()
    card_id = require_present(body, "card_id")
    prize_id = require_present(body, "prize_item_id")
    if not isinstance(card_id, str) or not isinstance(prize_id, str):
        raise ApiError("ERR_VALIDATION", 422, "card_id and prize_item_id must be strings")
    # existence (body FKs left-to-right)
    card = resolve(CARDS, card_id, "ERR_CARD_NOT_FOUND")
    prize = resolve(PRIZES, prize_id, "ERR_PRIZE_NOT_FOUND")
    # ownership
    if role == "Member" and card.get("owner_member_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "member does not own this card")
    # body well-formedness (step 4)
    quantity = require_int(body, "quantity", minimum=0, strict=True)
    expected_version = as_int(require_present(body, "expected_card_version"), "expected_card_version")
    # card operability (step 5)
    if card["status"] == "FROZEN":
        raise ApiError("ERR_CARD_FROZEN", 409, "card is FROZEN")
    if card["status"] != "ACTIVE":
        raise ApiError("ERR_CARD_NOT_ACTIVE", 409, "card is not ACTIVE")
    # referential status (step 7)
    if prize["status"] != "AVAILABLE":
        raise ApiError("ERR_PRIZE_UNAVAILABLE", 409, "prize is not AVAILABLE")
    # concurrency (step 8)
    if expected_version != card["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "card version is stale")
    # capacity / stock (step 10)
    available = prize["stock_qty"] - prize["reserved_qty"]
    if quantity > available:
        raise ApiError("ERR_INSUFFICIENT_STOCK", 409, "insufficient prize stock")
    # fiscal (step 11)
    points_hold = prize["points_price"] * quantity
    if card["ticket_points_balance"] < points_hold:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 402, "insufficient ticket points")

    append_ledger(card, "POINTS_HOLD", points_delta=-points_hold, note="redemption hold")
    touch(card)
    prize["reserved_qty"] += quantity
    touch(prize)

    ent = new_common({
        "card_id": card_id,
        "prize_item_id": prize_id,
        "quantity": quantity,
        "points_hold": points_hold,
        "points_settled": None,
        "status": "RESERVED",
    })
    REDEMPTIONS[ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/redemptions/<rid>", methods=["GET"])
def get_redemption(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ent = resolve(REDEMPTIONS, rid, "ERR_REDEMPTION_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/redemptions", methods=["GET"])
def list_redemptions():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = sorted_by_seq(REDEMPTIONS.values())
    card_id = request.args.get("card_id")
    prize_id = request.args.get("prize_item_id")
    status = request.args.get("status")
    if card_id is not None:
        items = [r for r in items if r["card_id"] == card_id]
    if prize_id is not None:
        items = [r for r in items if r["prize_item_id"] == prize_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return ok_array([serialize(r) for r in page], meta)


@app.route("/redemptions/<rid>/fulfill", methods=["POST"])
def fulfill_redemption(rid):
    _, role = authenticate()
    authorize(role, {"Attendant"})
    red = resolve(REDEMPTIONS, rid, "ERR_REDEMPTION_NOT_FOUND")
    if red["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_REDEMPTION_STATE", 409, "redemption is not RESERVED")
    card = CARDS[red["card_id"]]
    prize = PRIZES[red["prize_item_id"]]
    points_settled = prize["points_price"] * red["quantity"]
    delta = points_settled - red["points_hold"]
    # fiscal: must cover a positive delta (step 11)
    if delta > 0 and card["ticket_points_balance"] < delta:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 402, "insufficient ticket points for settlement")
    append_ledger(card, "POINTS_SETTLE", points_delta=-delta, note="redemption settle")
    touch(card)
    prize["reserved_qty"] -= red["quantity"]
    prize["stock_qty"] -= red["quantity"]
    touch(prize)
    red["points_settled"] = points_settled
    red["status"] = "FULFILLED"
    touch(red)
    return ok_object(serialize(red))


@app.route("/redemptions/<rid>/cancel", methods=["POST"])
def cancel_redemption(rid):
    _, role = authenticate()
    authorize(role, {"Attendant"})
    red = resolve(REDEMPTIONS, rid, "ERR_REDEMPTION_NOT_FOUND")
    if red["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_REDEMPTION_STATE", 409, "redemption is not RESERVED")
    card = CARDS[red["card_id"]]
    prize = PRIZES[red["prize_item_id"]]
    append_ledger(card, "POINTS_REFUND", points_delta=red["points_hold"], note="redemption refund")
    touch(card)
    prize["reserved_qty"] -= red["quantity"]
    touch(prize)
    red["status"] = "CANCELLED"
    touch(red)
    return ok_object(serialize(red))


# =============================================================================
# Party bookings
# =============================================================================
def party_charge(package, room, guest_count, hours):
    extra_guests = max(0, guest_count - package["included_guests"])
    overage_hours = max(0, hours - package["included_hours"])
    return (
        package["base_price_cents"]
        + extra_guests * PER_EXTRA_GUEST_CENTS
        + overage_hours * room["hourly_rate_cents"]
    )


def booking_wristbands(booking_id):
    return [w for w in WRISTBANDS.values() if w.get("booking_id") == booking_id]


@app.route("/party-bookings", methods=["POST"])
def create_booking():
    _, role = authenticate()
    authorize(role, {"Coordinator"})
    body = get_body()
    room_id = require_present(body, "room_id")
    package_id = require_present(body, "package_id")
    host_member_id = require_present(body, "host_member_id")
    for v, nm in ((room_id, "room_id"), (package_id, "package_id"), (host_member_id, "host_member_id")):
        if not isinstance(v, str):
            raise ApiError("ERR_VALIDATION", 422, "%s must be a string" % nm)
    # existence (body FKs left-to-right)
    resolve(ROOMS, room_id, "ERR_ROOM_NOT_FOUND")
    resolve(PACKAGES, package_id, "ERR_PACKAGE_NOT_FOUND")
    resolve(MEMBERS, host_member_id, "ERR_MEMBER_NOT_FOUND")
    # well-formedness
    start_raw = require_str(body, "start_at")
    end_raw = require_str(body, "end_at")
    try:
        start_dt = parse_iso(start_raw)
        end_dt = parse_iso(end_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 422, "start_at/end_at must be ISO-8601")
    guest_count = require_int(body, "guest_count", minimum=0, strict=True)
    if not end_dt > start_dt:
        raise ApiError("ERR_VALIDATION", 422, "end_at must be strictly after start_at")

    ent = new_common({
        "room_id": room_id,
        "package_id": package_id,
        "host_member_id": host_member_id,
        "start_at": start_raw,
        "end_at": end_raw,
        "guest_count": guest_count,
        "status": "DRAFT",
        "checked_in_at": None,
        "completed_at": None,
        "provisional_total_cents": None,
        "final_total_cents": None,
        "actual_guest_count": None,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "_checked_in_dt": None,
        "_completed_dt": None,
    })
    BOOKINGS[ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/party-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ent = resolve(BOOKINGS, bid, "ERR_BOOKING_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/party-bookings", methods=["GET"])
def list_bookings():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = sorted_by_seq(BOOKINGS.values())
    for key, arg in (("room_id", "room_id"), ("package_id", "package_id"),
                     ("host_member_id", "host_member_id"), ("status", "status")):
        val = request.args.get(arg)
        if val is not None:
            items = [b for b in items if b[key] == val]
    page, meta = paginate(items)
    return ok_array([serialize(b) for b in page], meta)


@app.route("/party-bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    _, role = authenticate()
    authorize(role, {"Coordinator"})
    booking = resolve(BOOKINGS, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_BOOKING_STATE", 409, "booking is not DRAFT")
    room = ROOMS[booking["room_id"]]
    package = PACKAGES[booking["package_id"]]
    s, e = booking["_start_dt"], booking["_end_dt"]
    # temporal: room time conflict (step 9)
    for other in BOOKINGS.values():
        if other["id"] == bid or other["status"] == "CANCELLED":
            continue
        if other["room_id"] != booking["room_id"]:
            continue
        if overlaps(s, e, other["_start_dt"], other["_end_dt"]):
            raise ApiError("ERR_ROOM_TIME_CONFLICT", 409, "room window conflict")
    # capacity: guest count (step 10)
    if booking["guest_count"] > room["capacity"]:
        raise ApiError("ERR_GUEST_COUNT_EXCEEDS_ROOM", 409, "guest_count exceeds room capacity")
    # capacity: venue occupancy (step 10)
    overlapping_guests = 0
    for other in BOOKINGS.values():
        if other["id"] == bid:
            continue
        if other["status"] not in {"CONFIRMED", "CHECKED_IN"}:
            continue
        if overlaps(s, e, other["_start_dt"], other["_end_dt"]):
            overlapping_guests += other["guest_count"]
    if overlapping_guests + booking["guest_count"] > MAX_VENUE_OCCUPANCY:
        raise ApiError("ERR_VENUE_CAPACITY_EXCEEDED", 409, "venue capacity exceeded")

    hours = ceil_hours(s, e)
    booking["provisional_total_cents"] = party_charge(package, room, booking["guest_count"], hours)
    booking["status"] = "CONFIRMED"

    # 3-hop cascade: wristband -> fresh ACTIVE card -> bonus grant
    included = package["included_chip_cents"]
    for _ in range(booking["guest_count"]):
        card = new_card(None, "ACTIVE")
        append_ledger(card, "BONUS_GRANT", bonus_delta=included, note="party provision bonus")
        band = new_common({
            "booking_id": bid,
            "card_id": card["id"],
            "band_code": "BAND-" + uuid.uuid4().hex[:10].upper(),
            "status": "ISSUED",
            "_auto_provisioned": True,
        })
        WRISTBANDS[band["id"]] = band
    touch(booking)
    return ok_object(serialize(booking))


def compensate_cascade(booking):
    """Void every wristband of the booking; claw back bonus on auto-provisioned cards."""
    included = PACKAGES[booking["package_id"]]["included_chip_cents"]
    for band in booking_wristbands(booking["id"]):
        if band["status"] in {"VOID", "RETURNED"}:
            continue
        if band.get("_auto_provisioned") and band.get("card_id") in CARDS:
            card = CARDS[band["card_id"]]
            append_ledger(card, "BONUS_CLAWBACK", bonus_delta=-included, note="party bonus clawback")
            touch(card)
        band["status"] = "VOID"
        touch(band)


@app.route("/party-bookings/<bid>/revert-to-draft", methods=["POST"])
def revert_booking(bid):
    _, role = authenticate()
    authorize(role, {"Coordinator"})
    booking = resolve(BOOKINGS, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_BOOKING_STATE", 409, "booking is not CONFIRMED")
    compensate_cascade(booking)
    booking["status"] = "DRAFT"
    booking["provisional_total_cents"] = None
    touch(booking)
    return ok_object(serialize(booking))


@app.route("/party-bookings/<bid>/check-in", methods=["POST"])
def checkin_booking(bid):
    _, role = authenticate()
    authorize(role, {"Cashier"})
    booking = resolve(BOOKINGS, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_BOOKING_STATE", 409, "booking is not CONFIRMED")
    room = ROOMS[booking["room_id"]]
    if room["status"] != "AVAILABLE":
        raise ApiError("ERR_ROOM_UNAVAILABLE", 409, "room is in MAINTENANCE")
    clock = now_dt()
    if not (booking["_start_dt"] <= clock < booking["_end_dt"]):
        raise ApiError("ERR_OUTSIDE_BOOKING_WINDOW", 409, "clock outside booking window")
    booking["checked_in_at"] = now_iso()
    booking["_checked_in_dt"] = clock
    for band in booking_wristbands(bid):
        if band["status"] == "ISSUED":
            band["status"] = "ACTIVE"
            touch(band)
    booking["status"] = "CHECKED_IN"
    touch(booking)
    return ok_object(serialize(booking))


@app.route("/party-bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    _, role = authenticate()
    authorize(role, {"Coordinator"})
    booking = resolve(BOOKINGS, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_BOOKING_STATE", 409, "booking is not CHECKED_IN")
    clock = now_dt()
    booking["completed_at"] = now_iso()
    booking["_completed_dt"] = clock
    actual = len([w for w in booking_wristbands(bid) if w["status"] in {"ISSUED", "ACTIVE"}])
    booking["actual_guest_count"] = actual
    room = ROOMS[booking["room_id"]]
    package = PACKAGES[booking["package_id"]]
    hours = ceil_hours(booking["_checked_in_dt"], clock)
    booking["final_total_cents"] = party_charge(package, room, actual, hours)
    booking["status"] = "COMPLETED"
    touch(booking)
    return ok_object(serialize(booking))


@app.route("/party-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    _, role = authenticate()
    authorize(role, {"Coordinator"})
    booking = resolve(BOOKINGS, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] not in {"DRAFT", "CONFIRMED", "CHECKED_IN"}:
        raise ApiError("ERR_INVALID_BOOKING_STATE", 409, "booking cannot be cancelled from its state")
    if booking["status"] in {"CONFIRMED", "CHECKED_IN"}:
        compensate_cascade(booking)
    booking["status"] = "CANCELLED"
    touch(booking)
    return ok_object(serialize(booking))


@app.route("/party-bookings/<bid>/wristbands", methods=["POST"])
def issue_wristband(bid):
    _, role = authenticate()
    authorize(role, {"Cashier"})
    booking = resolve(BOOKINGS, bid, "ERR_BOOKING_NOT_FOUND")
    body = get_body()
    card_id = body.get("card_id")
    if card_id is not None:
        if not isinstance(card_id, str):
            raise ApiError("ERR_VALIDATION", 422, "card_id must be a string")
        resolve(CARDS, card_id, "ERR_CARD_NOT_FOUND")
    expected_version = as_int(require_present(body, "expected_booking_version"), "expected_booking_version")
    # transition legality (step 6)
    if booking["status"] not in {"CONFIRMED", "CHECKED_IN"}:
        raise ApiError("ERR_INVALID_BOOKING_STATE", 409, "booking not in CONFIRMED/CHECKED_IN")
    # concurrency (step 8)
    if expected_version != booking["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "booking version is stale")
    # capacity (step 10)
    room = ROOMS[booking["room_id"]]
    active_count = len([w for w in booking_wristbands(bid) if w["status"] in {"ISSUED", "ACTIVE"}])
    if not active_count < room["capacity"]:
        raise ApiError("ERR_GUEST_COUNT_EXCEEDS_ROOM", 409, "wristband count would exceed room capacity")
    band = new_common({
        "booking_id": bid,
        "card_id": card_id,
        "band_code": "BAND-" + uuid.uuid4().hex[:10].upper(),
        "status": "ISSUED",
        "_auto_provisioned": False,
    })
    WRISTBANDS[band["id"]] = band
    touch(booking)
    return ok_object(serialize(band), 201)


# =============================================================================
# Wristbands
# =============================================================================
@app.route("/wristbands/<wid>", methods=["GET"])
def get_wristband(wid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ent = resolve(WRISTBANDS, wid, "ERR_WRISTBAND_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/wristbands", methods=["GET"])
def list_wristbands():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = sorted_by_seq(WRISTBANDS.values())
    booking_id = request.args.get("booking_id")
    card_id = request.args.get("card_id")
    status = request.args.get("status")
    if booking_id is not None:
        items = [w for w in items if w.get("booking_id") == booking_id]
    if card_id is not None:
        items = [w for w in items if w.get("card_id") == card_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, meta = paginate(items)
    return ok_array([serialize(w) for w in page], meta)


@app.route("/wristbands/<wid>/return", methods=["POST"])
def return_wristband(wid):
    _, role = authenticate()
    authorize(role, {"Cashier"})
    band = resolve(WRISTBANDS, wid, "ERR_WRISTBAND_NOT_FOUND")
    if band["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_WRISTBAND_STATE", 409, "wristband is not ACTIVE")
    band["status"] = "RETURNED"
    touch(band)
    return ok_object(serialize(band))


# =============================================================================
# Daily reconciliation
# =============================================================================
@app.route("/daily-reconciliations", methods=["POST"])
def open_reconciliation():
    _, role = authenticate()
    authorize(role, {"Manager"})
    body = get_body()
    business_day_val = require_str(body, "business_day")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", business_day_val):
        raise ApiError("ERR_VALIDATION", 422, "business_day must be YYYY-MM-DD")
    for r in RECONCILIATIONS.values():
        if r["business_day"] == business_day_val:
            raise ApiError("ERR_RECON_DUPLICATE_DAY", 409, "reconciliation already exists for day")
    expected_chip = sum(
        c["chip_balance_cents"] + c["bonus_chip_balance_cents"]
        for c in CARDS.values()
        if c["status"] in {"ACTIVE", "FROZEN"}
    )
    expected_units = sum(
        p["stock_qty"] for p in PRIZES.values()
        if p["status"] in {"AVAILABLE", "OUT_OF_STOCK"}
    )
    ent = new_common({
        "business_day": business_day_val,
        "expected_chip_liability_cents": expected_chip,
        "expected_prize_units": expected_units,
        "counted_chip_liability_cents": None,
        "counted_prize_units": None,
        "variance_chip_cents": None,
        "variance_prize_units": None,
        "status": "OPEN",
    })
    RECONCILIATIONS[ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/daily-reconciliations/<rid>", methods=["GET"])
def get_reconciliation(rid):
    _, role = authenticate()
    authorize(role, {"Manager"})
    ent = resolve(RECONCILIATIONS, rid, "ERR_RECONCILIATION_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/daily-reconciliations/<rid>/count", methods=["POST"])
def count_reconciliation(rid):
    _, role = authenticate()
    authorize(role, {"Manager"})
    ent = resolve(RECONCILIATIONS, rid, "ERR_RECONCILIATION_NOT_FOUND")
    body = get_body()
    counted_chip = require_int(body, "counted_chip_liability_cents", minimum=0, strict=False)
    counted_units = require_int(body, "counted_prize_units", minimum=0, strict=False)
    if ent["status"] != "OPEN":
        raise ApiError("ERR_INVALID_RECONCILIATION_STATE", 409, "reconciliation is not OPEN")
    ent["counted_chip_liability_cents"] = counted_chip
    ent["counted_prize_units"] = counted_units
    ent["variance_chip_cents"] = counted_chip - ent["expected_chip_liability_cents"]
    ent["variance_prize_units"] = counted_units - ent["expected_prize_units"]
    if ent["variance_chip_cents"] == 0 and ent["variance_prize_units"] == 0:
        ent["status"] = "RECONCILED"
    else:
        ent["status"] = "DISCREPANCY"
    touch(ent)
    return ok_object(serialize(ent))


# =============================================================================
# Entrypoint
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
