"""
Retreat & Wellness-Getaway Booking API — Python + Flask reference implementation.

All storage is in-memory (module-level dicts keyed by id). The store starts EMPTY
on every boot; nothing is seeded. The test harness restarts this process before
every individual test, which wipes all state.
"""

import math
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from PRD / SCAFFOLD calculation tables)
# ---------------------------------------------------------------------------
SPECIAL_DIET_SURCHARGE_CENTS = 5000
DISCOUNT_TIER_2 = 0.08   # party_size >= 2
DISCOUNT_TIER_4 = 0.15   # party_size >= 4
TAX_PCT = 0.085
DEPOSIT_PCT = 0.30
FULL_REFUND_DAYS = 60
HALF_REFUND_DAYS = 30
QUARTER_REFUND_DAYS = 14
FACILITATOR_FLAT_CENTS = 40000
PER_HEAD_CENTS = 3000
SETUP_BUFFER_MINUTES = 30

RECOGNIZED_ROLES = {"Anonymous", "Guest", "Operator", "Facilitator"}

CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Error catalog (error_id -> HTTP status)
# ---------------------------------------------------------------------------
ERR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_RETREAT_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_GUEST_NOT_FOUND": 404,
    "ERR_FACILITATOR_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_WAIVER_NOT_FOUND": 404,
    "ERR_SHUTTLE_NOT_FOUND": 404,
    "ERR_ADDON_NOT_FOUND": 404,
    "ERR_ACTIVITY_SLOT_NOT_FOUND": 404,
    "ERR_TRANSPORT_SEGMENT_NOT_FOUND": 404,
    "ERR_BOOKING_ADDON_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_RETREAT_VERSION": 412,
    "ERR_WAIVER_NOT_CLEARED": 422,
    "ERR_CHECKIN_TOO_EARLY": 409,
    "ERR_FACILITATOR_DOUBLE_BOOKED": 409,
    "ERR_SPACE_UNAVAILABLE": 409,
    "ERR_ROOM_FULL": 409,
    "ERR_RETREAT_FULL": 409,
    "ERR_SHUTTLE_FULL": 409,
    "ERR_ROOM_KIND_MISMATCH": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_WAIVER_ALREADY_EXISTS": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = ERR_HTTP[error_id]
        self.message = message or error_id


def err(error_id, message=""):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
retreats = {}
rooms = {}
guests = {}
facilitators = {}
bookings = {}
payments = {}
waivers = {}
activity_slots = {}
shuttles = {}
transport_segments = {}
addons = {}
booking_addons = {}

CLOCK = {"now": CLOCK_DEFAULT}
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_versioned(fields):
    ts = now_iso()
    r = {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
         "version": 1, "_seq": next_seq()}
    r.update(fields)
    return r


def new_ledger(fields):
    r = {"id": str(uuid.uuid4()), "created_at": now_iso(), "_seq": next_seq()}
    r.update(fields)
    return r


def touch(e):
    e["updated_at"] = now_iso()
    e["version"] += 1


def public(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope helpers
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def respond_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_array(items, pag):
    body = {"meta": _meta(pag), "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authn():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in RECOGNIZED_ROLES:
        err("ERR_UNAUTHENTICATED", "missing or unrecognized credentials")
    # An Anonymous caller is unauthenticated: self-registration (the sole
    # operation not requiring prior authentication) never reaches authn(), so
    # any request arriving here as Anonymous is unauthenticated.
    if role == "Anonymous":
        err("ERR_UNAUTHENTICATED", "anonymous caller is unauthenticated")
    return uid, role


def authorize(allowed):
    uid, role = authn()
    if role not in allowed:
        err("ERR_UNAUTHORIZED", "role not permitted for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Parsing / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(force=True, silent=True)
    if b is None or not isinstance(b, dict):
        return {}
    return b


def parse_dt(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_present(body, names):
    for n in names:
        if n not in body or body[n] is None:
            err("ERR_VALIDATION", "missing required field: %s" % n)


def as_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", "field %s must be an integer" % name)
    return v


def as_str(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        err("ERR_VALIDATION", "field %s must be a string" % name)
    return v


def need(coll, oid, err_id):
    if not isinstance(oid, str) or oid not in coll:
        err(err_id, "%s not found" % oid)
    return coll[oid]


def rhu(amount_cents, rate):
    return int((Decimal(int(amount_cents)) * Decimal(str(rate))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        err("ERR_VALIDATION", "invalid pagination parameter")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    limit, offset = get_pagination()
    items = sorted(items, key=lambda x: x["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [public(x) for x in page], pag


# ---------------------------------------------------------------------------
# Derived-value recomputation
# ---------------------------------------------------------------------------
def recompute_schedule_ready(retreat_id):
    r = retreats.get(retreat_id)
    if not r:
        return
    ready = any(s["status"] == "SCHEDULED"
                for s in activity_slots.values() if s["retreat_id"] == retreat_id)
    if r["schedule_ready"] != ready:
        r["schedule_ready"] = ready
        touch(r)


def compute_booking_charges(b):
    retreat = retreats[b["retreat_id"]]
    room = rooms[b["room_id"]]
    party = b["party_size"]
    base_line = retreat["base_price_cents"] * party
    room_delta = room["tier_delta_cents"]
    addon_prices = [ba["price_cents_snapshot"] for ba in booking_addons.values()
                    if ba["booking_id"] == b["id"]]
    subtotal = base_line + room_delta + sum(addon_prices)

    if party >= 4:
        pct = DISCOUNT_TIER_4
    elif party >= 2:
        pct = DISCOUNT_TIER_2
    else:
        pct = 0.0
    discount = rhu(subtotal, pct)
    surcharge = SPECIAL_DIET_SURCHARGE_CENTS if b["has_special_diet"] else 0
    total = subtotal - discount + surcharge

    # Tax: round each pre-discount line item's tax, THEN sum (order-sensitive).
    line_items = [base_line, room_delta] + addon_prices
    tax = sum(rhu(li, TAX_PCT) for li in line_items)
    grand = total + tax
    deposit = rhu(grand, DEPOSIT_PCT)
    balance = grand - deposit

    b["subtotal_cents"] = subtotal
    b["group_discount_pct"] = pct
    b["discount_cents"] = discount
    b["special_diet_surcharge_cents"] = surcharge
    b["total_cents"] = total
    b["tax_cents"] = tax
    b["grand_total_cents"] = grand
    b["deposit_cents"] = deposit
    b["balance_due_cents"] = balance


def waiver_of_booking(booking_id):
    for w in waivers.values():
        if w["booking_id"] == booking_id:
            return w
    return None


# ---------------------------------------------------------------------------
# Cancellation (shared by guest cancel + operator retreat-cancel cascade)
# ---------------------------------------------------------------------------
def do_cancel_booking(b, cancelled_by):
    retreat = retreats[b["retreat_id"]]
    room = rooms[b["room_id"]]

    if cancelled_by == "OPERATOR":
        pct = 1.0
    else:
        start = parse_dt(retreat["start_date"])
        delta = (start - CLOCK["now"]).total_seconds()
        days_before = math.floor(delta / 86400)
        if days_before >= FULL_REFUND_DAYS:
            pct = 1.0
        elif days_before >= HALF_REFUND_DAYS:
            pct = 0.5
        elif days_before >= QUARTER_REFUND_DAYS:
            pct = 0.25
        else:
            pct = 0.0

    refund = rhu(b["amount_paid_cents"], pct)
    b["status"] = "CANCELLED"
    b["cancelled_by"] = cancelled_by
    b["refund_cents"] = refund
    touch(b)
    if refund > 0:
        p = new_ledger({
            "booking_id": b["id"],
            "type": "REFUND",
            "amount_cents": refund,
            "note": "%s cancel refund" % cancelled_by.lower(),
        })
        payments[p["id"]] = p

    # Release beds / seats
    room["reserved_beds"] -= b["party_size"]
    touch(room)
    retreat["reserved_count"] -= b["party_size"]
    if retreat["status"] == "FULL" and retreat["reserved_count"] < retreat["capacity"]:
        retreat["status"] = "PUBLISHED"
    touch(retreat)

    # Cascade transport segments
    for seg in transport_segments.values():
        if seg["booking_id"] == b["id"] and seg["status"] == "BOOKED":
            seg["status"] = "CANCELLED"
            touch(seg)
            sh = shuttles.get(seg["shuttle_id"])
            if sh:
                sh["reserved_seats"] -= seg["seat_count"]
                touch(sh)


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize({"Operator"})
    body = get_body()
    require_present(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"])
    if dt is None:
        err("ERR_VALIDATION", "invalid to_iso8601")
    CLOCK["now"] = dt
    return respond_object({}, 200)


# ===========================================================================
# RETREATS
# ===========================================================================
@app.route("/v1/retreats", methods=["POST"])
def create_retreat():
    authorize({"Operator"})
    body = get_body()
    require_present(body, ["name", "theme", "location", "start_date", "end_date",
                           "capacity", "base_price_cents"])
    name = as_str(body, "name")
    theme = as_str(body, "theme")
    location = as_str(body, "location")
    start = parse_dt(body["start_date"])
    end = parse_dt(body["end_date"])
    if start is None or end is None:
        err("ERR_VALIDATION", "invalid start_date/end_date")
    if not (end > start):
        err("ERR_VALIDATION", "end_date must be strictly after start_date")
    capacity = as_int(body, "capacity")
    base_price = as_int(body, "base_price_cents")
    if capacity < 1:
        err("ERR_VALIDATION", "capacity must be >= 1")
    if base_price < 0:
        err("ERR_VALIDATION", "base_price_cents must be >= 0")

    r = new_versioned({
        "name": name, "theme": theme, "location": location,
        "start_date": body["start_date"], "end_date": body["end_date"],
        "capacity": capacity, "base_price_cents": base_price,
        "status": "DRAFT", "reserved_count": 0, "schedule_ready": False,
    })
    retreats[r["id"]] = r
    return respond_object(public(r), 201)


@app.route("/v1/retreats/<rid>", methods=["GET"])
def get_retreat(rid):
    authorize({"Operator", "Guest"})
    r = need(retreats, rid, "ERR_RETREAT_NOT_FOUND")
    return respond_object(public(r), 200)


@app.route("/v1/retreats", methods=["GET"])
def list_retreats():
    authorize({"Operator", "Guest"})
    status = request.args.get("status")
    items = [r for r in retreats.values() if status is None or r["status"] == status]
    page, pag = paginate(items)
    return respond_array(page, pag)


@app.route("/v1/retreats/<rid>/publish", methods=["POST"])
def publish_retreat(rid):
    authorize({"Operator"})
    r = need(retreats, rid, "ERR_RETREAT_NOT_FOUND")
    if r["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "retreat is not in DRAFT")
    has_lodging = any(rm["retreat_id"] == rid and rm["kind"] == "LODGING"
                      for rm in rooms.values())
    if not has_lodging:
        err("ERR_INVALID_STATE", "retreat has no LODGING room")
    r["status"] = "PUBLISHED"
    touch(r)
    return respond_object(public(r), 200)


@app.route("/v1/retreats/<rid>/cancel", methods=["POST"])
def cancel_retreat(rid):
    authorize({"Operator"})
    r = need(retreats, rid, "ERR_RETREAT_NOT_FOUND")
    if r["status"] not in ("PUBLISHED", "FULL"):
        err("ERR_INVALID_STATE", "retreat cannot be cancelled from its current state")

    active = ("PENDING_DEPOSIT", "DEPOSIT_PAID", "CONFIRMED", "CHECKED_IN")
    for b in sorted([b for b in bookings.values()
                     if b["retreat_id"] == rid and b["status"] in active],
                    key=lambda x: x["_seq"]):
        do_cancel_booking(b, "OPERATOR")
    for s in activity_slots.values():
        if s["retreat_id"] == rid and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)
    recompute_schedule_ready(rid)
    r["status"] = "CANCELLED"
    touch(r)
    return respond_object(public(r), 200)


@app.route("/v1/retreats/<rid>/complete", methods=["POST"])
def complete_retreat(rid):
    authorize({"Operator"})
    r = need(retreats, rid, "ERR_RETREAT_NOT_FOUND")
    if r["status"] not in ("PUBLISHED", "FULL"):
        err("ERR_INVALID_STATE", "retreat cannot be completed from its current state")
    end = parse_dt(r["end_date"])
    if CLOCK["now"] < end:
        err("ERR_INVALID_STATE", "retreat end_date not yet reached")

    attendee_count = sum(b["party_size"] for b in bookings.values()
                         if b["retreat_id"] == rid
                         and b["status"] in ("CONFIRMED", "CHECKED_IN", "COMPLETED"))
    fac_ids = {s["facilitator_id"] for s in activity_slots.values()
               if s["retreat_id"] == rid and s["status"] in ("SCHEDULED", "COMPLETED")}
    for fid in fac_ids:
        f = facilitators.get(fid)
        if f:
            f["payout_cents"] = PER_HEAD_CENTS * attendee_count
            touch(f)
    for s in activity_slots.values():
        if s["retreat_id"] == rid and s["status"] == "SCHEDULED":
            s["status"] = "COMPLETED"
            touch(s)
    for b in bookings.values():
        if b["retreat_id"] == rid and b["status"] == "CHECKED_IN":
            b["status"] = "COMPLETED"
            touch(b)
    recompute_schedule_ready(rid)
    r["status"] = "COMPLETED"
    touch(r)
    return respond_object(public(r), 200)


@app.route("/v1/retreats/<rid>/rooms", methods=["GET"])
def list_retreat_rooms(rid):
    authorize({"Operator", "Guest"})
    need(retreats, rid, "ERR_RETREAT_NOT_FOUND")
    kind = request.args.get("kind")
    items = [rm for rm in rooms.values()
             if rm["retreat_id"] == rid and (kind is None or rm["kind"] == kind)]
    page, pag = paginate(items)
    return respond_array(page, pag)


@app.route("/v1/retreats/<rid>/shuttles", methods=["GET"])
def list_retreat_shuttles(rid):
    authorize({"Operator", "Guest"})
    need(retreats, rid, "ERR_RETREAT_NOT_FOUND")
    direction = request.args.get("direction")
    items = [s for s in shuttles.values()
             if s["retreat_id"] == rid and (direction is None or s["direction"] == direction)]
    page, pag = paginate(items)
    return respond_array(page, pag)


# ===========================================================================
# ROOMS
# ===========================================================================
@app.route("/v1/rooms", methods=["POST"])
def create_room():
    authorize({"Operator"})
    body = get_body()
    # existence (body FK) first
    if body.get("retreat_id") is not None:
        need(retreats, body["retreat_id"], "ERR_RETREAT_NOT_FOUND")
    require_present(body, ["retreat_id", "kind", "label"])
    kind = as_str(body, "kind")
    if kind not in ("LODGING", "COMMON"):
        err("ERR_VALIDATION", "invalid kind")
    tier = body.get("tier", "STANDARD")
    if tier not in ("PRIVATE", "STANDARD", "SHARED_DORM"):
        err("ERR_VALIDATION", "invalid tier")
    tier_delta = body.get("tier_delta_cents", 0)
    if isinstance(tier_delta, bool) or not isinstance(tier_delta, int):
        err("ERR_VALIDATION", "tier_delta_cents must be an integer")
    bed_count = body.get("bed_count", 0)
    if isinstance(bed_count, bool) or not isinstance(bed_count, int) or bed_count < 0:
        err("ERR_VALIDATION", "bed_count must be an integer >= 0")
    label = as_str(body, "label")

    rm = new_versioned({
        "retreat_id": body["retreat_id"], "kind": kind, "tier": tier,
        "tier_delta_cents": tier_delta, "bed_count": bed_count, "label": label,
        "reserved_beds": 0,
    })
    rooms[rm["id"]] = rm
    return respond_object(public(rm), 201)


# ===========================================================================
# GUESTS
# ===========================================================================
@app.route("/v1/guests", methods=["POST"])
def create_guest():
    # Anonymous self-registration — no authentication required.
    body = get_body()
    require_present(body, ["email", "full_name"])
    email = as_str(body, "email")
    full_name = as_str(body, "full_name")
    g = new_versioned({
        "email": email, "full_name": full_name,
        "phone": body.get("phone", "") or "" if isinstance(body.get("phone", ""), str) else "",
        "dietary_notes": body.get("dietary_notes", "") if isinstance(body.get("dietary_notes", ""), str) else "",
        "health_notes": body.get("health_notes", "") if isinstance(body.get("health_notes", ""), str) else "",
    })
    guests[g["id"]] = g
    return respond_object(public(g), 201)


@app.route("/v1/guests/<gid>", methods=["GET"])
def get_guest(gid):
    uid, role = authorize({"Guest", "Operator"})
    g = need(guests, gid, "ERR_GUEST_NOT_FOUND")
    if role == "Guest" and uid != gid:
        err("ERR_UNAUTHORIZED", "guest may only read own profile")
    return respond_object(public(g), 200)


# ===========================================================================
# FACILITATORS
# ===========================================================================
@app.route("/v1/facilitators", methods=["POST"])
def create_facilitator():
    authorize({"Operator"})
    body = get_body()
    require_present(body, ["full_name", "email", "specialty"])
    f = new_versioned({
        "full_name": as_str(body, "full_name"),
        "email": as_str(body, "email"),
        "specialty": as_str(body, "specialty"),
        "status": "ACTIVE", "payout_cents": 0,
    })
    facilitators[f["id"]] = f
    return respond_object(public(f), 201)


@app.route("/v1/facilitators/<fid>", methods=["GET"])
def get_facilitator(fid):
    uid, role = authorize({"Operator", "Facilitator"})
    f = need(facilitators, fid, "ERR_FACILITATOR_NOT_FOUND")
    if role == "Facilitator" and uid != fid:
        err("ERR_UNAUTHORIZED", "facilitator may only read own profile")
    return respond_object(public(f), 200)


@app.route("/v1/facilitators/<fid>/withdraw", methods=["POST"])
def withdraw_facilitator(fid):
    authorize({"Operator"})
    f = need(facilitators, fid, "ERR_FACILITATOR_NOT_FOUND")
    if f["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "facilitator is not ACTIVE")
    affected = set()
    for s in activity_slots.values():
        if s["facilitator_id"] == fid and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)
            affected.add(s["retreat_id"])
    f["status"] = "WITHDRAWN"
    touch(f)
    for rid in affected:
        recompute_schedule_ready(rid)
    return respond_object(public(f), 200)


# ===========================================================================
# BOOKINGS
# ===========================================================================
@app.route("/v1/bookings", methods=["POST"])
def create_booking():
    uid, role = authorize({"Guest"})
    body = get_body()

    # Ownership (priority 2): body guest_id must equal caller.
    if body.get("guest_id") is not None and body["guest_id"] != uid:
        err("ERR_UNAUTHORIZED", "guest_id must equal the acting guest")

    # Existence (priority 3): path (none) then body FKs in declaration order.
    if body.get("retreat_id") is not None:
        need(retreats, body["retreat_id"], "ERR_RETREAT_NOT_FOUND")
    if body.get("guest_id") is not None:
        need(guests, body["guest_id"], "ERR_GUEST_NOT_FOUND")
    if body.get("room_id") is not None:
        need(rooms, body["room_id"], "ERR_ROOM_NOT_FOUND")
    addon_ids = body.get("addon_ids", [])
    if addon_ids is None:
        addon_ids = []
    if not isinstance(addon_ids, list):
        err("ERR_VALIDATION", "addon_ids must be a list")
    for aid in addon_ids:
        need(addons, aid, "ERR_ADDON_NOT_FOUND")

    # Validation (priority 4)
    require_present(body, ["retreat_id", "guest_id", "room_id", "party_size",
                           "expected_retreat_version"])
    party = as_int(body, "party_size")
    if party < 1:
        err("ERR_VALIDATION", "party_size must be >= 1")
    expected_ver = as_int(body, "expected_retreat_version")
    has_diet = body.get("has_special_diet", False)
    if not isinstance(has_diet, bool):
        err("ERR_VALIDATION", "has_special_diet must be a boolean")

    retreat = retreats[body["retreat_id"]]
    room = rooms[body["room_id"]]

    # State (priority 5)
    if retreat["status"] != "PUBLISHED":
        err("ERR_INVALID_STATE", "retreat is not PUBLISHED")

    # OCC (priority 6)
    if expected_ver != retreat["version"]:
        err("ERR_STALE_RETREAT_VERSION", "expected_retreat_version is stale")

    # Capacity / kind (priority 9)
    if room["kind"] != "LODGING":
        err("ERR_ROOM_KIND_MISMATCH", "room is not LODGING")
    if room["reserved_beds"] + party > room["bed_count"]:
        err("ERR_ROOM_FULL", "room bed capacity exceeded")
    if retreat["reserved_count"] + party > retreat["capacity"]:
        err("ERR_RETREAT_FULL", "retreat capacity exceeded")

    # Create
    b = new_versioned({
        "retreat_id": body["retreat_id"], "guest_id": body["guest_id"],
        "room_id": body["room_id"], "party_size": party,
        "has_special_diet": has_diet, "status": "PENDING_DEPOSIT",
        "subtotal_cents": 0, "group_discount_pct": 0, "discount_cents": 0,
        "special_diet_surcharge_cents": 0, "total_cents": 0, "tax_cents": 0,
        "grand_total_cents": 0, "deposit_cents": 0, "balance_due_cents": 0,
        "amount_paid_cents": 0, "refund_cents": 0, "cancelled_by": None,
    })
    bookings[b["id"]] = b
    for aid in addon_ids:
        ao = addons[aid]
        link = new_ledger({
            "booking_id": b["id"], "addon_id": aid,
            "price_cents_snapshot": ao["price_cents"],
        })
        booking_addons[link["id"]] = link
    compute_booking_charges(b)

    # Side effects on room / retreat (single retreat version bump for the create)
    room["reserved_beds"] += party
    touch(room)
    retreat["reserved_count"] += party
    if retreat["reserved_count"] == retreat["capacity"]:
        retreat["status"] = "FULL"
    touch(retreat)

    return respond_object(public(b), 201)


def _resolve_owned_booking(bid, uid, role):
    b = need(bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if role == "Guest" and b["guest_id"] != uid:
        err("ERR_UNAUTHORIZED", "booking is not owned by the acting guest")
    return b


@app.route("/v1/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    uid, role = authorize({"Guest", "Operator"})
    b = _resolve_owned_booking(bid, uid, role)
    return respond_object(public(b), 200)


@app.route("/v1/bookings", methods=["GET"])
def list_bookings():
    authorize({"Guest", "Operator"})
    f_retreat = request.args.get("retreat_id")
    f_guest = request.args.get("guest_id")
    f_room = request.args.get("room_id")
    f_status = request.args.get("status")
    items = [b for b in bookings.values()
             if (f_retreat is None or b["retreat_id"] == f_retreat)
             and (f_guest is None or b["guest_id"] == f_guest)
             and (f_room is None or b["room_id"] == f_room)
             and (f_status is None or b["status"] == f_status)]
    page, pag = paginate(items)
    return respond_array(page, pag)


@app.route("/v1/bookings/<bid>/pay-deposit", methods=["POST"])
def pay_deposit(bid):
    uid, role = authorize({"Guest"})
    b = _resolve_owned_booking(bid, uid, role)
    body = get_body()
    require_present(body, ["amount_cents"])
    amount = as_int(body, "amount_cents")
    if b["status"] != "PENDING_DEPOSIT":
        err("ERR_INVALID_STATE", "booking is not awaiting a deposit")
    if amount != b["deposit_cents"]:
        err("ERR_PAYMENT_AMOUNT_MISMATCH", "amount_cents must equal deposit_cents")
    p = new_ledger({"booking_id": b["id"], "type": "DEPOSIT",
                    "amount_cents": b["deposit_cents"], "note": ""})
    payments[p["id"]] = p
    b["amount_paid_cents"] += b["deposit_cents"]
    b["status"] = "DEPOSIT_PAID"
    touch(b)
    return respond_object(public(b), 200)


@app.route("/v1/bookings/<bid>/pay-balance", methods=["POST"])
def pay_balance(bid):
    uid, role = authorize({"Guest"})
    b = _resolve_owned_booking(bid, uid, role)
    body = get_body()
    require_present(body, ["amount_cents"])
    amount = as_int(body, "amount_cents")
    if b["status"] != "DEPOSIT_PAID":
        err("ERR_INVALID_STATE", "booking is not awaiting a balance payment")
    w = waiver_of_booking(b["id"])
    if w is None or w["status"] != "CLEARED":
        err("ERR_WAIVER_NOT_CLEARED", "waiver must be CLEARED before balance payment")
    if amount != b["balance_due_cents"]:
        err("ERR_PAYMENT_AMOUNT_MISMATCH", "amount_cents must equal balance_due_cents")
    p = new_ledger({"booking_id": b["id"], "type": "BALANCE",
                    "amount_cents": b["balance_due_cents"], "note": ""})
    payments[p["id"]] = p
    b["amount_paid_cents"] += b["balance_due_cents"]
    b["status"] = "CONFIRMED"
    touch(b)
    return respond_object(public(b), 200)


@app.route("/v1/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = authorize({"Guest"})
    b = _resolve_owned_booking(bid, uid, role)
    if b["status"] not in ("PENDING_DEPOSIT", "DEPOSIT_PAID", "CONFIRMED"):
        err("ERR_INVALID_STATE", "booking cannot be cancelled from its current state")
    do_cancel_booking(b, "GUEST")
    return respond_object(public(b), 200)


@app.route("/v1/bookings/<bid>/check-in", methods=["POST"])
def check_in(bid):
    authorize({"Operator"})
    b = need(bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if b["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", "booking is not CONFIRMED")
    w = waiver_of_booking(b["id"])
    if w is None or w["status"] != "CLEARED":
        err("ERR_WAIVER_NOT_CLEARED", "waiver must be CLEARED before check-in")
    retreat = retreats[b["retreat_id"]]
    if CLOCK["now"] < parse_dt(retreat["start_date"]):
        err("ERR_CHECKIN_TOO_EARLY", "check-in before retreat start_date")
    b["status"] = "CHECKED_IN"
    touch(b)
    return respond_object(public(b), 200)


@app.route("/v1/bookings/<bid>/payments", methods=["GET"])
def list_booking_payments(bid):
    uid, role = authorize({"Guest", "Operator"})
    _resolve_owned_booking(bid, uid, role)
    items = [p for p in payments.values() if p["booking_id"] == bid]
    page, pag = paginate(items)
    return respond_array(page, pag)


@app.route("/v1/bookings/<bid>/waiver", methods=["GET"])
def list_booking_waiver(bid):
    uid, role = authorize({"Guest", "Operator"})
    _resolve_owned_booking(bid, uid, role)
    items = [w for w in waivers.values() if w["booking_id"] == bid]
    page, pag = paginate(items)
    return respond_array(page, pag)


# ===========================================================================
# WAIVERS
# ===========================================================================
@app.route("/v1/waivers", methods=["POST"])
def create_waiver():
    uid, role = authorize({"Guest"})
    body = get_body()
    if body.get("booking_id") is not None:
        b = need(bookings, body["booking_id"], "ERR_BOOKING_NOT_FOUND")
        if role == "Guest" and b["guest_id"] != uid:
            err("ERR_UNAUTHORIZED", "booking is not owned by the acting guest")
    require_present(body, ["booking_id", "health_disclosures"])
    health = as_str(body, "health_disclosures")
    if waiver_of_booking(body["booking_id"]) is not None:
        err("ERR_WAIVER_ALREADY_EXISTS", "a waiver already exists for this booking")
    w = new_versioned({
        "booking_id": body["booking_id"], "health_disclosures": health,
        "signature_name": None, "status": "PENDING", "review_decision": None,
    })
    waivers[w["id"]] = w
    return respond_object(public(w), 201)


def _resolve_owned_waiver(wid, uid, role):
    w = need(waivers, wid, "ERR_WAIVER_NOT_FOUND")
    if role == "Guest":
        b = bookings.get(w["booking_id"])
        if b is None or b["guest_id"] != uid:
            err("ERR_UNAUTHORIZED", "waiver is not owned by the acting guest")
    return w


@app.route("/v1/waivers/<wid>/sign", methods=["POST"])
def sign_waiver(wid):
    uid, role = authorize({"Guest"})
    w = _resolve_owned_waiver(wid, uid, role)
    body = get_body()
    require_present(body, ["signature_name"])
    sig = as_str(body, "signature_name")
    if w["status"] != "PENDING":
        err("ERR_INVALID_STATE", "waiver is not PENDING")
    w["signature_name"] = sig
    w["status"] = "SIGNED"
    touch(w)
    return respond_object(public(w), 200)


@app.route("/v1/waivers/<wid>/review", methods=["POST"])
def review_waiver(wid):
    authorize({"Operator"})
    w = need(waivers, wid, "ERR_WAIVER_NOT_FOUND")
    body = get_body()
    require_present(body, ["decision"])
    decision = body["decision"]
    if decision not in ("CLEAR", "REJECT"):
        err("ERR_VALIDATION", "decision must be CLEAR or REJECT")
    if w["status"] != "SIGNED":
        err("ERR_INVALID_STATE", "waiver is not SIGNED")
    w["review_decision"] = decision
    w["status"] = "CLEARED" if decision == "CLEAR" else "REJECTED"
    touch(w)
    return respond_object(public(w), 200)


# ===========================================================================
# ACTIVITY SLOTS
# ===========================================================================
@app.route("/v1/activity-slots", methods=["POST"])
def create_activity_slot():
    authorize({"Operator"})
    body = get_body()
    if body.get("retreat_id") is not None:
        need(retreats, body["retreat_id"], "ERR_RETREAT_NOT_FOUND")
    if body.get("facilitator_id") is not None:
        need(facilitators, body["facilitator_id"], "ERR_FACILITATOR_NOT_FOUND")
    if body.get("room_id") is not None:
        need(rooms, body["room_id"], "ERR_ROOM_NOT_FOUND")
    require_present(body, ["retreat_id", "facilitator_id", "room_id", "title",
                           "start_datetime", "end_datetime"])
    title = as_str(body, "title")
    start = parse_dt(body["start_datetime"])
    end = parse_dt(body["end_datetime"])
    if start is None or end is None:
        err("ERR_VALIDATION", "invalid start/end datetime")
    if not (end > start):
        err("ERR_VALIDATION", "end_datetime must be strictly after start_datetime")

    facilitator = facilitators[body["facilitator_id"]]
    room = rooms[body["room_id"]]

    # State (priority 5): facilitator must be ACTIVE.
    if facilitator["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "facilitator is not ACTIVE")

    # Temporal (priority 8): facilitator overlap, then room setup buffer.
    for s in activity_slots.values():
        if s["facilitator_id"] == body["facilitator_id"] and s["status"] == "SCHEDULED":
            es = parse_dt(s["start_datetime"])
            ee = parse_dt(s["end_datetime"])
            if start < ee and es < end:  # half-open overlap
                err("ERR_FACILITATOR_DOUBLE_BOOKED", "facilitator already scheduled")
    buffer_sec = SETUP_BUFFER_MINUTES * 60
    for s in activity_slots.values():
        if s["room_id"] == body["room_id"] and s["status"] == "SCHEDULED":
            es = parse_dt(s["start_datetime"]).timestamp()
            ee = parse_dt(s["end_datetime"]).timestamp()
            ns = start.timestamp()
            ne = end.timestamp()
            # Buffered existing interval [es-buffer, ee+buffer); strict "within".
            if ns < ee + buffer_sec and es - buffer_sec < ne:
                err("ERR_SPACE_UNAVAILABLE", "room setup buffer conflict")

    # Kind (priority 9): room must be COMMON.
    if room["kind"] != "COMMON":
        err("ERR_ROOM_KIND_MISMATCH", "activity slot room is not COMMON")

    slot = new_versioned({
        "retreat_id": body["retreat_id"], "facilitator_id": body["facilitator_id"],
        "room_id": body["room_id"], "title": title,
        "start_datetime": body["start_datetime"], "end_datetime": body["end_datetime"],
        "status": "SCHEDULED",
    })
    activity_slots[slot["id"]] = slot
    recompute_schedule_ready(body["retreat_id"])
    return respond_object(public(slot), 201)


@app.route("/v1/activity-slots/<sid>", methods=["GET"])
def get_activity_slot(sid):
    authorize({"Operator", "Guest", "Facilitator"})
    s = need(activity_slots, sid, "ERR_ACTIVITY_SLOT_NOT_FOUND")
    return respond_object(public(s), 200)


@app.route("/v1/activity-slots", methods=["GET"])
def list_activity_slots():
    authorize({"Operator", "Guest", "Facilitator"})
    f_retreat = request.args.get("retreat_id")
    f_fac = request.args.get("facilitator_id")
    f_room = request.args.get("room_id")
    f_status = request.args.get("status")
    items = [s for s in activity_slots.values()
             if (f_retreat is None or s["retreat_id"] == f_retreat)
             and (f_fac is None or s["facilitator_id"] == f_fac)
             and (f_room is None or s["room_id"] == f_room)
             and (f_status is None or s["status"] == f_status)]
    page, pag = paginate(items)
    return respond_array(page, pag)


@app.route("/v1/activity-slots/<sid>/cancel", methods=["POST"])
def cancel_activity_slot(sid):
    authorize({"Operator"})
    s = need(activity_slots, sid, "ERR_ACTIVITY_SLOT_NOT_FOUND")
    if s["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "activity slot is not SCHEDULED")
    s["status"] = "CANCELLED"
    touch(s)
    recompute_schedule_ready(s["retreat_id"])
    return respond_object(public(s), 200)


# ===========================================================================
# SHUTTLES
# ===========================================================================
@app.route("/v1/shuttles", methods=["POST"])
def create_shuttle():
    authorize({"Operator"})
    body = get_body()
    if body.get("retreat_id") is not None:
        need(retreats, body["retreat_id"], "ERR_RETREAT_NOT_FOUND")
    require_present(body, ["retreat_id", "direction", "depart_datetime", "seat_capacity"])
    direction = body["direction"]
    if direction not in ("ARRIVAL", "DEPARTURE"):
        err("ERR_VALIDATION", "invalid direction")
    depart = parse_dt(body["depart_datetime"])
    if depart is None:
        err("ERR_VALIDATION", "invalid depart_datetime")
    seat_capacity = as_int(body, "seat_capacity")
    if seat_capacity < 1:
        err("ERR_VALIDATION", "seat_capacity must be >= 1")
    sh = new_versioned({
        "retreat_id": body["retreat_id"], "direction": direction,
        "depart_datetime": body["depart_datetime"], "seat_capacity": seat_capacity,
        "reserved_seats": 0,
    })
    shuttles[sh["id"]] = sh
    return respond_object(public(sh), 201)


# ===========================================================================
# TRANSPORT SEGMENTS
# ===========================================================================
@app.route("/v1/transport-segments", methods=["POST"])
def create_transport_segment():
    uid, role = authorize({"Guest"})
    body = get_body()
    if body.get("booking_id") is not None:
        b = need(bookings, body["booking_id"], "ERR_BOOKING_NOT_FOUND")
        if role == "Guest" and b["guest_id"] != uid:
            err("ERR_UNAUTHORIZED", "booking is not owned by the acting guest")
    if body.get("shuttle_id") is not None:
        need(shuttles, body["shuttle_id"], "ERR_SHUTTLE_NOT_FOUND")
    require_present(body, ["booking_id", "shuttle_id"])
    b = bookings[body["booking_id"]]
    sh = shuttles[body["shuttle_id"]]
    if b["status"] not in ("DEPOSIT_PAID", "CONFIRMED", "CHECKED_IN"):
        err("ERR_INVALID_STATE", "booking not eligible for transport")
    if sh["reserved_seats"] + b["party_size"] > sh["seat_capacity"]:
        err("ERR_SHUTTLE_FULL", "shuttle seat capacity exceeded")
    seg = new_versioned({
        "booking_id": body["booking_id"], "shuttle_id": body["shuttle_id"],
        "seat_count": b["party_size"], "status": "BOOKED",
    })
    transport_segments[seg["id"]] = seg
    sh["reserved_seats"] += b["party_size"]
    touch(sh)
    return respond_object(public(seg), 201)


@app.route("/v1/transport-segments/<tid>", methods=["GET"])
def get_transport_segment(tid):
    uid, role = authorize({"Guest", "Operator"})
    seg = need(transport_segments, tid, "ERR_TRANSPORT_SEGMENT_NOT_FOUND")
    if role == "Guest":
        b = bookings.get(seg["booking_id"])
        if b is None or b["guest_id"] != uid:
            err("ERR_UNAUTHORIZED", "transport segment not owned by the acting guest")
    return respond_object(public(seg), 200)


@app.route("/v1/transport-segments", methods=["GET"])
def list_transport_segments():
    authorize({"Guest", "Operator"})
    f_booking = request.args.get("booking_id")
    f_shuttle = request.args.get("shuttle_id")
    f_status = request.args.get("status")
    items = [s for s in transport_segments.values()
             if (f_booking is None or s["booking_id"] == f_booking)
             and (f_shuttle is None or s["shuttle_id"] == f_shuttle)
             and (f_status is None or s["status"] == f_status)]
    page, pag = paginate(items)
    return respond_array(page, pag)


# ===========================================================================
# ADDONS
# ===========================================================================
@app.route("/v1/addons", methods=["POST"])
def create_addon():
    authorize({"Operator"})
    body = get_body()
    require_present(body, ["name", "category", "price_cents"])
    name = as_str(body, "name")
    category = body["category"]
    if category not in ("SPA", "EXCURSION", "MEAL", "GEAR"):
        err("ERR_VALIDATION", "invalid category")
    price = as_int(body, "price_cents")
    if price < 0:
        err("ERR_VALIDATION", "price_cents must be >= 0")
    a = new_ledger({"name": name, "category": category, "price_cents": price})
    addons[a["id"]] = a
    return respond_object(public(a), 201)


@app.route("/v1/addons/<aid>", methods=["GET"])
def get_addon(aid):
    authorize({"Operator", "Guest"})
    a = need(addons, aid, "ERR_ADDON_NOT_FOUND")
    return respond_object(public(a), 200)


# ===========================================================================
# BOOKING ADDONS
# ===========================================================================
@app.route("/v1/booking-addons", methods=["POST"])
def create_booking_addon():
    uid, role = authorize({"Guest"})
    body = get_body()
    if body.get("booking_id") is not None:
        b = need(bookings, body["booking_id"], "ERR_BOOKING_NOT_FOUND")
        if role == "Guest" and b["guest_id"] != uid:
            err("ERR_UNAUTHORIZED", "booking is not owned by the acting guest")
    if body.get("addon_id") is not None:
        need(addons, body["addon_id"], "ERR_ADDON_NOT_FOUND")
    require_present(body, ["booking_id", "addon_id"])
    b = bookings[body["booking_id"]]
    ao = addons[body["addon_id"]]
    if b["status"] != "PENDING_DEPOSIT":
        err("ERR_INVALID_STATE", "add-ons may only attach to a PENDING_DEPOSIT booking")
    link = new_ledger({
        "booking_id": body["booking_id"], "addon_id": body["addon_id"],
        "price_cents_snapshot": ao["price_cents"],
    })
    booking_addons[link["id"]] = link
    compute_booking_charges(b)
    touch(b)
    return respond_object(public(link), 201)


@app.route("/v1/booking-addons/<baid>", methods=["GET"])
def get_booking_addon(baid):
    uid, role = authorize({"Guest", "Operator"})
    link = need(booking_addons, baid, "ERR_BOOKING_ADDON_NOT_FOUND")
    if role == "Guest":
        b = bookings.get(link["booking_id"])
        if b is None or b["guest_id"] != uid:
            err("ERR_UNAUTHORIZED", "booking-addon not owned by the acting guest")
    return respond_object(public(link), 200)


@app.route("/v1/booking-addons", methods=["GET"])
def list_booking_addons():
    authorize({"Guest", "Operator"})
    f_booking = request.args.get("booking_id")
    f_addon = request.args.get("addon_id")
    items = [l for l in booking_addons.values()
             if (f_booking is None or l["booking_id"] == f_booking)
             and (f_addon is None or l["addon_id"] == f_addon)]
    page, pag = paginate(items)
    return respond_array(page, pag)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
