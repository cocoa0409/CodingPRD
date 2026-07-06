import os
import re
import uuid
import random
import string
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# NOTE: The PRD references VENUE_TURNOVER_MINUTES and CHEF_PREP_MINUTES by name
# but never assigns them a numeric value (a scaffold gap). Values chosen here;
# adjust these two lines if the test suite pins different buffers.
VENUE_TURNOVER_MINUTES = 30
CHEF_PREP_MINUTES = 60

HEAD_TABLE_SUPPLEMENT_CENTS = 2000
GROUP_DISCOUNT_MIN_PARTY = 6
GROUP_LARGE_PARTY = 10
GROUP_RATE_SMALL = Decimal("0.10")
GROUP_RATE_LARGE = Decimal("0.15")
MAX_DISCOUNT_CENTS = 15000

FULL_REFUND_DAYS = 14
HALF_REFUND_DAYS = 7
QUARTER_REFUND_DAYS = 2

ROLES = {"PlatformAdmin", "VenueManager", "Chef", "Guest", "CustomerService"}

CADENCES = {"WEEKLY", "BIWEEKLY", "MONTHLY"}
CORKAGE_POLICIES = {"ALLOWED", "NOT_ALLOWED"}
TABLE_MODES = {"COMMUNAL", "PRIVATE"}
CHEF_STATUSES = {"AVAILABLE", "ON_LEAVE"}
DIETARY = {"VEGAN", "VEGETARIAN", "GLUTEN_FREE", "NUT_ALLERGY", "DAIRY_FREE", "PESCATARIAN"}
ALLERGENS = {"NUTS", "DAIRY", "GLUTEN", "SHELLFISH", "SOY"}
SEAT_TYPES = {"STANDARD", "ACCESSIBLE", "HEAD_TABLE"}

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.series = {}
        self.venues = {}
        self.chefs = {}
        self.guests = {}
        self.events = {}
        self.seats = {}
        self.menu_courses = {}
        self.bookings = {}
        self.waitlist = {}
        self.payments = {}
        self._seq = 0
        self.clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso_now_ms():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Errors + response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def meta_base():
    return {"api_request_id": request_id(), "api_request_timestamp": iso_now_ms()}


def ok(data, status=200, response_type="object", pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, pagination):
    return ok(items, status=200, response_type="array", pagination=pagination)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Helpers: rounding, time
# ---------------------------------------------------------------------------
def rhu(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    return db.clock


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------
def stamp_new(rec, with_version=True):
    ts = iso_now_ms()
    rec["id"] = rec.get("id") or new_id()
    rec["created_at"] = ts
    rec["_seq"] = db.next_seq()
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = iso_now_ms()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized auth headers")
    g.user_id = uid
    g.role = role
    return uid, role


def require_roles(*allowed):
    authenticate()
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body / query helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.data:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
    else:
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return data


def require_present(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
    return body[field]


def val_error(msg):
    raise ApiError("ERR_VALIDATION", 422, msg)


def require_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            val_error(f"Missing required field: {field}")
        return None
    v = body[field]
    if not isinstance(v, str) or v == "":
        val_error(f"Field {field} must be a non-empty string")
    return v


def require_int(body, field, required=True, min_val=None, max_val=None):
    if field not in body or body[field] is None:
        if required:
            val_error(f"Missing required field: {field}")
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        val_error(f"Field {field} must be an integer")
    if min_val is not None and v < min_val:
        val_error(f"Field {field} must be >= {min_val}")
    if max_val is not None and v > max_val:
        val_error(f"Field {field} must be <= {max_val}")
    return v


def require_number(body, field, required=True, min_val=None, max_val=None):
    if field not in body or body[field] is None:
        if required:
            val_error(f"Missing required field: {field}")
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        val_error(f"Field {field} must be a number")
    if min_val is not None and v < min_val:
        val_error(f"Field {field} must be >= {min_val}")
    if max_val is not None and v > max_val:
        val_error(f"Field {field} must be <= {max_val}")
    return v


def require_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        val_error(f"Field {field} must be a boolean")
    return v


def require_enum(body, field, choices, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            val_error(f"Missing required field: {field}")
        return default
    v = body[field]
    if v not in choices:
        val_error(f"Field {field} has illegal value")
    return v


def require_enum_array(body, field, choices, default=None):
    if field not in body or body[field] is None:
        return list(default) if default is not None else []
    v = body[field]
    if not isinstance(v, list):
        val_error(f"Field {field} must be an array")
    for item in v:
        if item not in choices:
            val_error(f"Field {field} contains illegal value")
    return v


def parse_pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            val_error("limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            val_error("limit out of range")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (ValueError, TypeError):
            val_error("offset must be an integer")
        if offset < 0:
            val_error("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def sort_seq(items):
    return sorted(items, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Existence resolvers
# ---------------------------------------------------------------------------
def get_series(sid):
    r = db.series.get(sid)
    if not r:
        raise ApiError("ERR_SERIES_NOT_FOUND", 404, "Series not found")
    return r


def get_venue(vid):
    r = db.venues.get(vid)
    if not r:
        raise ApiError("ERR_VENUE_NOT_FOUND", 404, "Venue not found")
    return r


def get_chef(cid):
    r = db.chefs.get(cid)
    if not r:
        raise ApiError("ERR_CHEF_NOT_FOUND", 404, "Chef not found")
    return r


def get_guest(gid):
    r = db.guests.get(gid)
    if not r:
        raise ApiError("ERR_GUEST_NOT_FOUND", 404, "Guest not found")
    return r


def get_event(eid):
    r = db.events.get(eid)
    if not r:
        raise ApiError("ERR_EVENT_NOT_FOUND", 404, "Event not found")
    return r


def get_seat(sid):
    r = db.seats.get(sid)
    if not r:
        raise ApiError("ERR_SEAT_NOT_FOUND", 404, "Seat not found")
    return r


def get_booking(bid):
    r = db.bookings.get(bid)
    if not r:
        raise ApiError("ERR_BOOKING_NOT_FOUND", 404, "Booking not found")
    return r


def get_waitlist(wid):
    r = db.waitlist.get(wid)
    if not r:
        raise ApiError("ERR_WAITLIST_ENTRY_NOT_FOUND", 404, "Waitlist entry not found")
    return r


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------
def check_event_ownership(event):
    if g.role == "VenueManager" and event["venue_id"] != g.user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "VenueManager does not own this event's venue")
    if g.role == "Chef" and event["chef_id"] != g.user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Chef is not assigned to this event")


def check_booking_ownership(booking):
    if g.role == "Guest" and booking["guest_id"] != g.user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Guest does not own this booking")


def check_waitlist_ownership(entry):
    if g.role == "Guest" and entry["guest_id"] != g.user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Guest does not own this waitlist entry")


# ---------------------------------------------------------------------------
# Pricing / derivations
# ---------------------------------------------------------------------------
def seat_base_price(seat, event):
    base = seat["price_override_cents"] if seat.get("price_override_cents") is not None else event["seat_price_cents"]
    if seat["seat_type"] == "HEAD_TABLE":
        base += HEAD_TABLE_SUPPLEMENT_CENTS
    return base


def compute_deposit_due(seats, event):
    total = 0
    pct = Decimal(str(event["deposit_pct"]))
    for seat in seats:
        base = seat_base_price(seat, event)
        total += rhu(Decimal(base) * pct)
    return total


def compute_total_price(seats, event, party_size, byob_bottles):
    subtotal = sum(seat_base_price(seat, event) for seat in seats)
    if event["table_mode"] == "PRIVATE" and party_size >= GROUP_DISCOUNT_MIN_PARTY:
        rate = GROUP_RATE_LARGE if party_size >= GROUP_LARGE_PARTY else GROUP_RATE_SMALL
        group_discount = min(rhu(Decimal(subtotal) * rate), MAX_DISCOUNT_CENTS)
    else:
        group_discount = 0
    corkage = compute_corkage(event, byob_bottles)
    return subtotal - group_discount + corkage


def compute_corkage(event, byob_bottles):
    if event.get("byob_allowed"):
        return byob_bottles * event["corkage_fee_cents"]
    return 0


def event_seats(event_id):
    return [s for s in db.seats.values() if s["event_id"] == event_id]


def event_bookings(event_id):
    return [b for b in db.bookings.values() if b["event_id"] == event_id]


def event_waitlist(event_id):
    return [w for w in db.waitlist.values() if w["event_id"] == event_id]


def available_seat_count(event_id):
    return sum(1 for s in event_seats(event_id) if s["status"] == "AVAILABLE")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_common(rec, with_version=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if with_version:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def ser_series(r):
    out = ser_common(r)
    for f in ["name", "cadence", "theme", "communal_table", "default_seat_capacity",
              "base_seat_price_cents", "default_deposit_pct", "byob_allowed", "corkage_fee_cents"]:
        out[f] = r[f]
    return out


def ser_venue(r):
    out = ser_common(r)
    for f in ["name", "address", "max_capacity", "corkage_policy"]:
        out[f] = r[f]
    return out


def ser_chef(r):
    out = ser_common(r)
    for f in ["name", "specialty", "status"]:
        out[f] = r[f]
    return out


def ser_guest(r):
    out = ser_common(r)
    for f in ["name", "email", "phone"]:
        out[f] = r[f]
    return out


def ser_event(r):
    out = ser_common(r)
    for f in ["series_id", "venue_id", "chef_id", "title", "event_start", "event_end",
              "booking_deadline", "table_mode", "seat_capacity", "seat_price_cents",
              "deposit_pct", "byob_allowed", "corkage_fee_cents", "status"]:
        out[f] = r[f]
    seats = event_seats(r["id"])
    bookings = event_bookings(r["id"])
    out["confirmed_seat_count"] = sum(1 for s in seats if s["status"] == "BOOKED")
    out["available_seat_count"] = sum(1 for s in seats if s["status"] == "AVAILABLE")
    out["gross_deposit_held_cents"] = sum(b["deposit_paid_cents"] - b["refund_cents"] for b in bookings)
    out["projected_revenue_cents"] = sum(
        b["total_price_cents"] for b in bookings if b["booking_status"] in ("PENDING_DEPOSIT", "CONFIRMED"))
    out["realized_revenue_cents"] = (
        sum(b["total_price_cents"] for b in bookings if b["booking_status"] == "ATTENDED")
        + sum(b["deposit_paid_cents"] for b in bookings if b["booking_status"] == "NO_SHOW"))
    return out


def ser_seat(r):
    out = ser_common(r)
    for f in ["event_id", "seat_label", "seat_type", "status", "price_override_cents", "current_booking_id"]:
        out[f] = r[f]
    return out


def ser_menu(r):
    out = ser_common(r)
    for f in ["event_id", "course_number", "name", "description", "paired_wine_name",
              "wine_varietal", "wine_supplement_cents", "contains_allergens"]:
        out[f] = r[f]
    return out


def ser_booking(r):
    out = ser_common(r)
    for f in ["event_id", "guest_id", "party_size", "seat_ids", "table_preference",
              "dietary_restrictions", "allergy_notes", "byob_bottles", "booking_status",
              "payment_status", "deposit_due_cents", "deposit_paid_cents", "total_price_cents",
              "corkage_due_cents", "refund_cents"]:
        out[f] = r[f]
    return out


def waitlist_position(entry):
    if entry["status"] != "WAITING":
        return None
    waiting = sort_seq([w for w in event_waitlist(entry["event_id"]) if w["status"] == "WAITING"])
    for idx, w in enumerate(waiting, start=1):
        if w["id"] == entry["id"]:
            return idx
    return None


def ser_waitlist(r):
    out = ser_common(r)
    for f in ["event_id", "guest_id", "booking_id", "party_size", "status"]:
        out[f] = r[f]
    out["position"] = waitlist_position(r)
    return out


def ser_payment(r):
    out = {"id": r["id"], "created_at": r["created_at"]}
    for f in ["booking_id", "kind", "direction", "amount_cents", "reason"]:
        out[f] = r[f]
    return out


# ===========================================================================
# Routes: Catalog seeding
# ===========================================================================
@app.route("/series", methods=["POST"])
def create_series():
    require_roles("PlatformAdmin")
    body = get_body()
    rec = {
        "name": require_str(body, "name"),
        "cadence": require_enum(body, "cadence", CADENCES),
        "theme": require_str(body, "theme"),
        "communal_table": require_bool(body, "communal_table", default=True),
        "default_seat_capacity": require_int(body, "default_seat_capacity", min_val=1),
        "base_seat_price_cents": require_int(body, "base_seat_price_cents", min_val=0),
        "default_deposit_pct": require_number(body, "default_deposit_pct", min_val=0, max_val=1),
        "byob_allowed": require_bool(body, "byob_allowed", default=False),
        "corkage_fee_cents": require_int(body, "corkage_fee_cents", required=False, min_val=0) or 0,
    }
    stamp_new(rec)
    db.series[rec["id"]] = rec
    return ok(ser_series(rec), 201)


@app.route("/series/<sid>", methods=["GET"])
def fetch_series(sid):
    require_roles(*ROLES)
    return ok(ser_series(get_series(sid)))


@app.route("/venues", methods=["POST"])
def create_venue():
    require_roles("PlatformAdmin")
    body = get_body()
    rec = {
        "name": require_str(body, "name"),
        "address": require_str(body, "address"),
        "max_capacity": require_int(body, "max_capacity", min_val=1),
        "corkage_policy": require_enum(body, "corkage_policy", CORKAGE_POLICIES),
    }
    stamp_new(rec)
    db.venues[rec["id"]] = rec
    return ok(ser_venue(rec), 201)


@app.route("/venues/<vid>", methods=["GET"])
def fetch_venue(vid):
    require_roles(*ROLES)
    return ok(ser_venue(get_venue(vid)))


@app.route("/chefs", methods=["POST"])
def create_chef():
    require_roles("PlatformAdmin")
    body = get_body()
    rec = {
        "name": require_str(body, "name"),
        "specialty": require_str(body, "specialty"),
        "status": "AVAILABLE",
    }
    stamp_new(rec)
    db.chefs[rec["id"]] = rec
    return ok(ser_chef(rec), 201)


@app.route("/chefs/<cid>", methods=["GET"])
def fetch_chef(cid):
    require_roles(*ROLES)
    return ok(ser_chef(get_chef(cid)))


@app.route("/chefs/<cid>/set-availability", methods=["POST"])
def set_chef_availability(cid):
    require_roles("Chef", "PlatformAdmin")
    chef = get_chef(cid)
    if g.role == "Chef" and chef["id"] != g.user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Chef may only change own availability")
    body = get_body()
    status = require_enum(body, "status", CHEF_STATUSES)
    chef["status"] = status
    touch(chef)
    return ok(ser_chef(chef))


@app.route("/guests", methods=["POST"])
def create_guest():
    require_roles("PlatformAdmin")
    body = get_body()
    rec = {
        "name": require_str(body, "name"),
        "email": require_str(body, "email"),
        "phone": require_str(body, "phone", required=False),
    }
    stamp_new(rec)
    db.guests[rec["id"]] = rec
    return ok(ser_guest(rec), 201)


@app.route("/guests/<gid>", methods=["GET"])
def fetch_guest(gid):
    require_roles(*ROLES)
    return ok(ser_guest(get_guest(gid)))


# ===========================================================================
# Routes: Events
# ===========================================================================
@app.route("/events", methods=["POST"])
def create_event():
    require_roles("VenueManager", "PlatformAdmin")
    body = get_body()
    # ownership (tier 2): VenueManager may only create for own venue
    venue_id_raw = body.get("venue_id")
    if g.role == "VenueManager" and venue_id_raw != g.user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "VenueManager may only create events for own venue")
    # existence (tier 3): series -> venue -> chef, left to right
    series_id = body.get("series_id")
    if series_id is None:
        val_error("Missing required field: series_id")
    get_series(series_id)
    venue_id = body.get("venue_id")
    if venue_id is None:
        val_error("Missing required field: venue_id")
    get_venue(venue_id)
    chef_id = body.get("chef_id")
    if chef_id is None:
        val_error("Missing required field: chef_id")
    get_chef(chef_id)
    # well-formedness (tier 4)
    title = require_str(body, "title")
    event_start = require_str(body, "event_start")
    event_end = require_str(body, "event_end")
    booking_deadline = require_str(body, "booking_deadline")
    try:
        es = parse_dt(event_start)
        ee = parse_dt(event_end)
        bd = parse_dt(booking_deadline)
    except (ValueError, TypeError):
        val_error("Invalid datetime format")
    if not (ee > es):
        val_error("event_end must be after event_start")
    if not (bd <= es):
        val_error("booking_deadline must be at or before event_start")
    table_mode = require_enum(body, "table_mode", TABLE_MODES)
    seat_capacity = require_int(body, "seat_capacity", min_val=1)
    seat_price_cents = require_int(body, "seat_price_cents", min_val=0)
    deposit_pct = require_number(body, "deposit_pct", min_val=0, max_val=1)
    byob_allowed = require_bool(body, "byob_allowed", default=False)
    corkage_fee_cents = require_int(body, "corkage_fee_cents", required=False, min_val=0)
    if corkage_fee_cents is None:
        corkage_fee_cents = 0
    rec = {
        "series_id": series_id, "venue_id": venue_id, "chef_id": chef_id,
        "title": title, "event_start": event_start, "event_end": event_end,
        "booking_deadline": booking_deadline, "table_mode": table_mode,
        "seat_capacity": seat_capacity, "seat_price_cents": seat_price_cents,
        "deposit_pct": deposit_pct, "byob_allowed": byob_allowed,
        "corkage_fee_cents": corkage_fee_cents, "status": "DRAFT",
    }
    stamp_new(rec)
    db.events[rec["id"]] = rec
    return ok(ser_event(rec), 201)


@app.route("/events/<eid>", methods=["GET"])
def fetch_event(eid):
    require_roles(*ROLES)
    return ok(ser_event(get_event(eid)))


@app.route("/events", methods=["GET"])
def list_events():
    require_roles(*ROLES)
    limit, offset = parse_pagination()
    items = list(db.events.values())
    for key in ("series_id", "venue_id", "chef_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    items = sort_seq(items)
    page, pg = paginate(items, limit, offset)
    return ok_list([ser_event(e) for e in page], pg)


def _interval_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end) intersection
    return a_start < b_end and b_start < a_end


@app.route("/events/<eid>/schedule", methods=["POST"])
def schedule_event(eid):
    require_roles("VenueManager", "PlatformAdmin")
    event = get_event(eid)
    check_event_ownership(event)
    body = get_body()
    head_table_count = require_int(body, "head_table_count", required=False, min_val=0)
    if head_table_count is None:
        head_table_count = 0
    # state legality (tier 5)
    if event["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_EVENT_STATE", 409, "Event cannot be scheduled from its current state")
    chef = db.chefs.get(event["chef_id"])
    # chef availability (tier 6)
    if not chef or chef["status"] != "AVAILABLE":
        raise ApiError("ERR_CHEF_UNAVAILABLE", 409, "Chef is not available")
    es = parse_dt(event["event_start"])
    ee = parse_dt(event["event_end"])
    active = [e for e in db.events.values()
              if e["id"] != event["id"] and e["status"] in ("SCHEDULED", "OPEN", "SUSPENDED")]
    # venue conflict (tier 7)
    for other in active:
        if other["venue_id"] != event["venue_id"]:
            continue
        oes = parse_dt(other["event_start"])
        oee = parse_dt(other["event_end"]) + timedelta(minutes=VENUE_TURNOVER_MINUTES)
        if _interval_overlap(es, ee, oes, oee):
            raise ApiError("ERR_VENUE_TIME_CONFLICT", 409, "Venue calendar conflict")
    # chef conflict (tier 7)
    for other in active:
        if other["chef_id"] != event["chef_id"]:
            continue
        oes = parse_dt(other["event_start"]) - timedelta(minutes=CHEF_PREP_MINUTES)
        oee = parse_dt(other["event_end"])
        my_start = es - timedelta(minutes=CHEF_PREP_MINUTES)
        if _interval_overlap(my_start, ee, oes, oee):
            raise ApiError("ERR_CHEF_TIME_CONFLICT", 409, "Chef calendar conflict")
    # side effects: generate seats
    for i in range(1, event["seat_capacity"] + 1):
        seat = {
            "event_id": event["id"],
            "seat_label": f"S{i}",
            "seat_type": "HEAD_TABLE" if i <= head_table_count else "STANDARD",
            "status": "AVAILABLE",
            "price_override_cents": None,
            "current_booking_id": None,
        }
        stamp_new(seat)
        db.seats[seat["id"]] = seat
    event["status"] = "SCHEDULED"
    touch(event)
    return ok(ser_event(event))


@app.route("/events/<eid>/open", methods=["POST"])
def open_event(eid):
    require_roles("VenueManager", "PlatformAdmin")
    event = get_event(eid)
    check_event_ownership(event)
    if event["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_EVENT_STATE", 409, "Event cannot be opened from its current state")
    if not any(m["event_id"] == event["id"] for m in db.menu_courses.values()):
        raise ApiError("ERR_MENU_REQUIRED", 409, "Event requires at least one menu course to open")
    event["status"] = "OPEN"
    touch(event)
    return ok(ser_event(event))


@app.route("/events/<eid>/suspend", methods=["POST"])
def suspend_event(eid):
    require_roles("VenueManager", "PlatformAdmin")
    event = get_event(eid)
    check_event_ownership(event)
    if event["status"] != "OPEN":
        raise ApiError("ERR_INVALID_EVENT_STATE", 409, "Event cannot be suspended from its current state")
    event["status"] = "SUSPENDED"
    touch(event)
    return ok(ser_event(event))


@app.route("/events/<eid>/resume", methods=["POST"])
def resume_event(eid):
    require_roles("VenueManager", "PlatformAdmin")
    event = get_event(eid)
    check_event_ownership(event)
    if event["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_EVENT_STATE", 409, "Event cannot be resumed from its current state")
    event["status"] = "OPEN"
    touch(event)
    return ok(ser_event(event))


@app.route("/events/<eid>/complete", methods=["POST"])
def complete_event(eid):
    require_roles("VenueManager", "PlatformAdmin")
    event = get_event(eid)
    check_event_ownership(event)
    if event["status"] not in ("OPEN", "SUSPENDED"):
        raise ApiError("ERR_INVALID_EVENT_STATE", 409, "Event cannot be completed from its current state")
    if now() < parse_dt(event["event_end"]):
        raise ApiError("ERR_EVENT_NOT_ENDED", 409, "Event has not yet ended")
    for b in event_bookings(event["id"]):
        if b["booking_status"] == "CONFIRMED":
            b["booking_status"] = "NO_SHOW"
            b["payment_status"] = "FORFEITED"
            touch(b)
        elif b["booking_status"] == "PENDING_DEPOSIT":
            b["booking_status"] = "CANCELLED"
            b["refund_cents"] = 0
            touch(b)
    for w in event_waitlist(event["id"]):
        if w["status"] == "WAITING":
            w["status"] = "EXPIRED"
            touch(w)
    event["status"] = "COMPLETED"
    touch(event)
    return ok(ser_event(event))


@app.route("/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    require_roles("VenueManager", "PlatformAdmin")
    event = get_event(eid)
    check_event_ownership(event)
    get_body()  # optional reason
    if event["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_INVALID_EVENT_STATE", 409, "Event cannot be cancelled from its current state")
    if event["status"] != "DRAFT":
        # three-hop cascade
        for b in event_bookings(event["id"]):
            if b["booking_status"] in ("PENDING_DEPOSIT", "CONFIRMED"):
                # hop1
                b["booking_status"] = "CANCELLED"
                # hop2: full refund of what was paid
                if b["deposit_paid_cents"] > 0:
                    b["refund_cents"] = b["deposit_paid_cents"]
                    pay = {
                        "booking_id": b["id"], "kind": "REFUND", "direction": "REFUND",
                        "amount_cents": b["refund_cents"], "reason": "event_cancel_full_refund",
                    }
                    stamp_new(pay, with_version=False)
                    db.payments[pay["id"]] = pay
                    b["payment_status"] = "REFUNDED"
                # else payment_status stays UNPAID, refund stays 0
                # hop3: free the seats held by this booking
                for s in db.seats.values():
                    if s["current_booking_id"] == b["id"]:
                        s["status"] = "AVAILABLE"
                        s["current_booking_id"] = None
                        touch(s)
                touch(b)
        # block remaining unsold / free-held seats
        for s in event_seats(event["id"]):
            if s["status"] in ("AVAILABLE", "HELD"):
                s["status"] = "BLOCKED"
                s["current_booking_id"] = None
                touch(s)
        # expire waitlist
        for w in event_waitlist(event["id"]):
            if w["status"] == "WAITING":
                w["status"] = "EXPIRED"
                touch(w)
    event["status"] = "CANCELLED"
    touch(event)
    return ok(ser_event(event))


@app.route("/events/<eid>/reprice", methods=["POST"])
def reprice_event(eid):
    require_roles("VenueManager", "PlatformAdmin")
    event = get_event(eid)
    check_event_ownership(event)
    body = get_body()
    new_seat_price_cents = require_int(body, "new_seat_price_cents", min_val=0)
    new_deposit_pct = require_number(body, "new_deposit_pct", required=False, min_val=0, max_val=1)
    expected_event_version = require_int(body, "expected_event_version")
    # state legality (tier 5)
    if event["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_INVALID_EVENT_STATE", 409, "Event cannot be repriced from its current state")
    # OCC (tier 5)
    if expected_event_version != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION", 412, "Event version is stale")
    event["seat_price_cents"] = new_seat_price_cents
    if new_deposit_pct is not None:
        event["deposit_pct"] = new_deposit_pct
    touch(event)
    return ok(ser_event(event))


@app.route("/events/<eid>/seats", methods=["GET"])
def list_event_seats(eid):
    require_roles(*ROLES)
    event = get_event(eid)
    items = event_seats(event["id"])
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_seq(items)
    return ok([ser_seat(s) for s in items], response_type="array")


@app.route("/events/<eid>/menu", methods=["GET"])
def list_event_menu(eid):
    require_roles(*ROLES)
    event = get_event(eid)
    items = sort_seq([m for m in db.menu_courses.values() if m["event_id"] == event["id"]])
    return ok([ser_menu(m) for m in items], response_type="array")


@app.route("/events/<eid>/waitlist", methods=["GET"])
def list_event_waitlist(eid):
    require_roles(*ROLES)
    event = get_event(eid)
    items = event_waitlist(event["id"])
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = sort_seq(items)
    return ok([ser_waitlist(w) for w in items], response_type="array")


@app.route("/events/<eid>/menu-courses", methods=["POST"])
def add_menu_course(eid):
    require_roles("Chef", "PlatformAdmin")
    event = get_event(eid)
    check_event_ownership(event)
    body = get_body()
    rec = {
        "event_id": event["id"],
        "course_number": require_int(body, "course_number", min_val=1),
        "name": require_str(body, "name"),
        "description": require_str(body, "description", required=False),
        "paired_wine_name": require_str(body, "paired_wine_name", required=False),
        "wine_varietal": require_str(body, "wine_varietal", required=False),
        "wine_supplement_cents": require_int(body, "wine_supplement_cents", required=False, min_val=0) or 0,
        "contains_allergens": require_enum_array(body, "contains_allergens", ALLERGENS, default=[]),
    }
    stamp_new(rec)
    db.menu_courses[rec["id"]] = rec
    return ok(ser_menu(rec), 201)


@app.route("/events/<eid>/waitlist", methods=["POST"])
def join_waitlist(eid):
    require_roles("Guest")
    body = get_body()
    # ownership: guest acts as self
    guest_id_raw = body.get("guest_id")
    if guest_id_raw != g.user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Guest may only join waitlist for self")
    # existence: event then guest
    event = get_event(eid)
    if guest_id_raw is None:
        val_error("Missing required field: guest_id")
    get_guest(guest_id_raw)
    party_size = require_int(body, "party_size", min_val=1)
    # state (tier 5)
    if event["status"] != "OPEN":
        raise ApiError("ERR_EVENT_NOT_OPEN", 409, "Event is not open")
    # availability (tier 9)
    if available_seat_count(event["id"]) != 0:
        raise ApiError("ERR_SEATS_AVAILABLE", 409, "Seats are still available")
    rec = {
        "event_id": event["id"], "guest_id": guest_id_raw, "booking_id": None,
        "party_size": party_size, "status": "WAITING",
    }
    stamp_new(rec)
    db.waitlist[rec["id"]] = rec
    return ok(ser_waitlist(rec), 201)


# ===========================================================================
# Routes: Waitlist
# ===========================================================================
@app.route("/waitlist/<wid>", methods=["GET"])
def fetch_waitlist(wid):
    require_roles(*ROLES)
    return ok(ser_waitlist(get_waitlist(wid)))


@app.route("/waitlist", methods=["GET"])
def list_waitlist():
    require_roles(*ROLES)
    limit, offset = parse_pagination()
    items = list(db.waitlist.values())
    for key in ("guest_id", "booking_id", "event_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w[key] == val]
    items = sort_seq(items)
    page, pg = paginate(items, limit, offset)
    return ok_list([ser_waitlist(w) for w in page], pg)


@app.route("/waitlist/<wid>/withdraw", methods=["POST"])
def withdraw_waitlist(wid):
    require_roles("Guest", "CustomerService")
    entry = get_waitlist(wid)
    check_waitlist_ownership(entry)
    if entry["status"] != "WAITING":
        raise ApiError("ERR_WAITLIST_ENTRY_NOT_WAITING", 409, "Waitlist entry is not WAITING")
    entry["status"] = "WITHDRAWN"
    touch(entry)
    return ok(ser_waitlist(entry))


# ===========================================================================
# Routes: Bookings
# ===========================================================================
@app.route("/bookings", methods=["POST"])
def create_booking():
    require_roles("Guest")
    body = get_body()
    # ownership (tier 2): guest acts as self
    guest_id_raw = body.get("guest_id")
    if guest_id_raw != g.user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Guest may only book for self")
    # existence (tier 3): event -> guest -> seats
    event_id = body.get("event_id")
    if event_id is None:
        val_error("Missing required field: event_id")
    event = get_event(event_id)
    if guest_id_raw is None:
        val_error("Missing required field: guest_id")
    get_guest(guest_id_raw)
    seat_ids = body.get("seat_ids")
    if seat_ids is None:
        val_error("Missing required field: seat_ids")
    if not isinstance(seat_ids, list):
        val_error("seat_ids must be an array")
    seats = [get_seat(sid) for sid in seat_ids]
    # well-formedness (tier 4)
    party_size = require_int(body, "party_size", min_val=1)
    table_preference = require_enum(body, "table_preference", TABLE_MODES, required=False)
    dietary = require_enum_array(body, "dietary_restrictions", DIETARY, default=[])
    allergy_notes = require_str(body, "allergy_notes", required=False)
    byob_bottles = require_int(body, "byob_bottles", required=False, min_val=0)
    if byob_bottles is None:
        byob_bottles = 0
    # seat count mismatch (tier 4)
    if party_size != len(seat_ids):
        raise ApiError("ERR_SEAT_COUNT_MISMATCH", 422, "party_size must equal len(seat_ids)")
    # event open (tier 5)
    if event["status"] != "OPEN":
        raise ApiError("ERR_EVENT_NOT_OPEN", 409, "Event is not open for bookings")
    # allergen conflict (tier 6)
    if "NUT_ALLERGY" in dietary:
        if any("NUTS" in m["contains_allergens"]
               for m in db.menu_courses.values() if m["event_id"] == event["id"]):
            raise ApiError("ERR_ALLERGEN_CONFLICT", 409, "Nut allergy conflicts with menu")
    # booking deadline (tier 7)
    if now() > parse_dt(event["booking_deadline"]):
        raise ApiError("ERR_PAST_BOOKING_DEADLINE", 409, "Booking deadline has passed")
    # seat belongs to event (tier 8)
    for s in seats:
        if s["event_id"] != event["id"]:
            raise ApiError("ERR_SEAT_NOT_IN_EVENT", 422, "Seat does not belong to this event")
    # seat availability (tier 9)
    for s in seats:
        if s["status"] != "AVAILABLE":
            raise ApiError("ERR_SEAT_UNAVAILABLE", 409, "Seat is not available")
    # byob (tier 9)
    if byob_bottles > 0 and not event["byob_allowed"]:
        raise ApiError("ERR_BYOB_NOT_ALLOWED", 422, "BYOB is not allowed for this event")

    booking = _make_booking(event, guest_id_raw, party_size, seat_ids, seats,
                            table_preference, dietary, allergy_notes, byob_bottles)
    return ok(ser_booking(booking), 201)


def _make_booking(event, guest_id, party_size, seat_ids, seats, table_preference,
                  dietary, allergy_notes, byob_bottles):
    booking = {
        "event_id": event["id"], "guest_id": guest_id, "party_size": party_size,
        "seat_ids": list(seat_ids), "table_preference": table_preference,
        "dietary_restrictions": dietary, "allergy_notes": allergy_notes,
        "byob_bottles": byob_bottles, "booking_status": "PENDING_DEPOSIT",
        "payment_status": "UNPAID",
        "deposit_due_cents": compute_deposit_due(seats, event),
        "deposit_paid_cents": 0,
        "total_price_cents": compute_total_price(seats, event, party_size, byob_bottles),
        "corkage_due_cents": compute_corkage(event, byob_bottles),
        "refund_cents": 0,
    }
    stamp_new(booking)
    db.bookings[booking["id"]] = booking
    for s in seats:
        s["status"] = "HELD"
        s["current_booking_id"] = booking["id"]
        touch(s)
    return booking


@app.route("/bookings/<bid>", methods=["GET"])
def fetch_booking(bid):
    require_roles(*ROLES)
    return ok(ser_booking(get_booking(bid)))


@app.route("/bookings", methods=["GET"])
def list_bookings():
    require_roles(*ROLES)
    limit, offset = parse_pagination()
    items = list(db.bookings.values())
    for key in ("event_id", "guest_id", "booking_status"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b[key] == val]
    items = sort_seq(items)
    page, pg = paginate(items, limit, offset)
    return ok_list([ser_booking(b) for b in page], pg)


@app.route("/bookings/<bid>/pay-deposit", methods=["POST"])
def pay_deposit(bid):
    require_roles("Guest")
    booking = get_booking(bid)
    check_booking_ownership(booking)
    body = get_body()
    amount_cents = require_int(body, "amount_cents", min_val=0)
    reason = require_str(body, "reason", required=False)
    # state (tier 5)
    if booking["booking_status"] != "PENDING_DEPOSIT":
        raise ApiError("ERR_INVALID_BOOKING_STATE", 409, "Booking is not PENDING_DEPOSIT")
    # fiscal (tier 10)
    if amount_cents != booking["deposit_due_cents"]:
        raise ApiError("ERR_DEPOSIT_AMOUNT_MISMATCH", 422, "Amount does not equal deposit due")
    booking["payment_status"] = "DEPOSIT_PAID"
    booking["deposit_paid_cents"] += amount_cents
    booking["booking_status"] = "CONFIRMED"
    pay = {
        "booking_id": booking["id"], "kind": "DEPOSIT", "direction": "CHARGE",
        "amount_cents": amount_cents, "reason": reason,
    }
    stamp_new(pay, with_version=False)
    db.payments[pay["id"]] = pay
    for s in db.seats.values():
        if s["current_booking_id"] == booking["id"] and s["status"] == "HELD":
            s["status"] = "BOOKED"
            touch(s)
    touch(booking)
    return ok(ser_booking(booking))


@app.route("/bookings/<bid>/check-in", methods=["POST"])
def check_in(bid):
    require_roles("VenueManager", "PlatformAdmin")
    booking = get_booking(bid)
    event = get_event(booking["event_id"])
    check_event_ownership(event)
    if event["status"] not in ("OPEN", "SUSPENDED") or booking["booking_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_BOOKING_STATE", 409, "Booking cannot be checked in")
    booking["booking_status"] = "ATTENDED"
    touch(booking)
    return ok(ser_booking(booking))


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    require_roles("Guest", "CustomerService")
    booking = get_booking(bid)
    check_booking_ownership(booking)
    get_body()  # optional reason
    if booking["booking_status"] in ("ATTENDED", "CANCELLED", "NO_SHOW"):
        raise ApiError("ERR_BOOKING_ALREADY_TERMINAL", 409, "Booking is already terminal")
    event = db.events.get(booking["event_id"])
    prev_status = booking["booking_status"]
    freed_seats = []
    if prev_status == "PENDING_DEPOSIT":
        booking["booking_status"] = "CANCELLED"
        booking["refund_cents"] = 0
        for s in db.seats.values():
            if s["current_booking_id"] == booking["id"]:
                s["status"] = "AVAILABLE"
                s["current_booking_id"] = None
                touch(s)
                freed_seats.append(s)
    elif prev_status == "CONFIRMED":
        booking["booking_status"] = "CANCELLED"
        rate = _refund_rate(event)
        refund = rhu(Decimal(booking["deposit_paid_cents"]) * rate)
        booking["refund_cents"] = refund
        if refund > 0 or booking["deposit_paid_cents"] > 0:
            pay = {
                "booking_id": booking["id"], "kind": "REFUND", "direction": "REFUND",
                "amount_cents": refund, "reason": "cancellation_refund",
            }
            stamp_new(pay, with_version=False)
            db.payments[pay["id"]] = pay
        if refund == booking["deposit_paid_cents"]:
            booking["payment_status"] = "REFUNDED"
        else:
            booking["payment_status"] = "PARTIALLY_REFUNDED"
        for s in db.seats.values():
            if s["current_booking_id"] == booking["id"]:
                s["status"] = "AVAILABLE"
                s["current_booking_id"] = None
                touch(s)
                freed_seats.append(s)
    touch(booking)
    if event and freed_seats:
        _promote_waitlist(event, freed_seats)
    return ok(ser_booking(booking))


def _refund_rate(event):
    if event is None:
        return Decimal("0")
    days_before = math.floor((parse_dt(event["event_start"]) - now()).total_seconds() / 86400)
    if days_before >= FULL_REFUND_DAYS:
        return Decimal("1.00")
    if days_before >= HALF_REFUND_DAYS:
        return Decimal("0.50")
    if days_before >= QUARTER_REFUND_DAYS:
        return Decimal("0.25")
    return Decimal("0.00")


def _promote_waitlist(event, freed_seats):
    freed_count = len(freed_seats)
    waiting = sort_seq([w for w in event_waitlist(event["id"]) if w["status"] == "WAITING"])
    for entry in waiting:
        if entry["party_size"] <= freed_count:
            # promote this entry
            take = sort_seq(freed_seats)[:entry["party_size"]]
            guest = db.guests.get(entry["guest_id"])
            booking = _make_booking(
                event, entry["guest_id"], entry["party_size"],
                [s["id"] for s in take], take, None, [], None, 0)
            entry["status"] = "PROMOTED"
            entry["booking_id"] = booking["id"]
            touch(entry)
            return


@app.route("/bookings/<bid>/seats", methods=["GET"])
def list_booking_seats(bid):
    require_roles(*ROLES)
    booking = get_booking(bid)
    items = sort_seq([s for s in db.seats.values() if s["current_booking_id"] == booking["id"]])
    return ok([ser_seat(s) for s in items], response_type="array")


@app.route("/bookings/<bid>/payments", methods=["GET"])
def list_booking_payments(bid):
    require_roles(*ROLES)
    booking = get_booking(bid)
    items = sort_seq([p for p in db.payments.values() if p["booking_id"] == booking["id"]])
    return ok([ser_payment(p) for p in items], response_type="array")


# ===========================================================================
# Test-driving: logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    try:
        db.clock = parse_dt(to_iso)
    except (ValueError, TypeError):
        val_error("Invalid datetime format")
    return ok({"now": to_iso})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
