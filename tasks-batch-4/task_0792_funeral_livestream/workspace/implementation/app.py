"""
Funeral Live-Stream & Tribute Service API.

Single-file Flask implementation. In-memory storage only (Python dicts);
every process boot starts with an empty store — no seeding, no persistence.
Every behavior traces to a sentence in workspace/PRD.md / SCAFFOLD.yaml.
"""

import math
import os
import random
import secrets
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
BASE_FEE_CENTS = 15000
PER_CAMERA_CENTS = 5000
INCLUDED_MINUTES = 120
OVERAGE_TIER1_MINUTES = 60
OVERAGE_TIER1_RATE_CENTS = 100
OVERAGE_TIER2_RATE_CENTS = 150
PRIORITY_SUPPORT_SURCHARGE_CENTS = 10000

FEE_PCT = Decimal("0.029")
FEE_FLAT_CENTS = 30

MAX_FAILED_ACCESS_ATTEMPTS = 5

ROLES = {"FuneralHome", "Operator", "PlatformAdmin", "Guest"}

AUDIO_SOURCES = {"HOUSE_SYSTEM", "EXTERNAL_MIXER", "SINGLE_MIC"}
PRIVACY_MODES = {"PUBLIC", "PASSWORD", "INVITE_ONLY"}
SKILLS = {"CAMERA", "AUDIO", "SUPPORT"}
CREW_ROLES = {"CAMERA", "AUDIO", "SUPPORT"}
DUTY_STATES = {"ON_DUTY", "OFF_DUTY"}

NOT_FOUND_ERR = {
    "funeral_home": "ERR_FUNERAL_HOME_NOT_FOUND",
    "venue": "ERR_VENUE_NOT_FOUND",
    "operator": "ERR_OPERATOR_NOT_FOUND",
    "service_order": "ERR_SERVICE_ORDER_NOT_FOUND",
    "venue_booking": "ERR_VENUE_BOOKING_NOT_FOUND",
    "camera_assignment": "ERR_CAMERA_ASSIGNMENT_NOT_FOUND",
    "guestbook_entry": "ERR_GUESTBOOK_ENTRY_NOT_FOUND",
    "donation": "ERR_DONATION_NOT_FOUND",
    "tribute_video": "ERR_TRIBUTE_VIDEO_NOT_FOUND",
}

# ---------------------------------------------------------------------------
# In-memory store (wiped every process start)
# ---------------------------------------------------------------------------
db = {k: {} for k in NOT_FOUND_ERR}
_seq_counter = 0
# Logical clock (PRD §2.11): default 2026-03-01T00:00:00Z, never falls back to
# wall clock. Used only to stamp actual_start / actual_end.
_logical_clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


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
# Time helpers
# ---------------------------------------------------------------------------
def now_dt():
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_str():
    return fmt_dt(now_dt())


def parse_iso(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_base():
    ts = now_str()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(obj):
    """Register a mutation: refresh updated_at and bump version."""
    obj["updated_at"] = now_str()
    obj["version"] += 1


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def mint_token():
    return "tok_" + secrets.token_urlsafe(24)


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD §1.0 / PRD §2.2)
# ---------------------------------------------------------------------------
def meta_base():
    return {
        "api_request_id": getattr(g, "request_id", None) or gen_request_id(),
        "api_request_timestamp": now_str(),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return body, status


def error_body(error_id, message):
    return {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc.error_id, exc.message), exc.http_status


@app.errorhandler(404)
def handle_404(_exc):
    return error_body("ERR_NOT_FOUND", "resource not found"), 404


@app.errorhandler(405)
def handle_405(_exc):
    return error_body("ERR_METHOD_NOT_ALLOWED", "method not allowed"), 405


@app.errorhandler(Exception)
def handle_uncaught(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    return error_body("ERR_INTERNAL", str(exc)), 500


@app.before_request
def _assign_request_id():
    g.request_id = gen_request_id()


# ---------------------------------------------------------------------------
# Auth & RBAC (PRD §2.1, §2.5, §2.6)
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and valid",
        )
    return {"user_id": user_id, "role": role}


def require_roles(ctx, allowed):
    if ctx["role"] not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this endpoint")


def actor_home(ctx):
    """The funeral-home id the actor is scoped to, or None for admin/guest."""
    if ctx["role"] == "FuneralHome":
        return ctx["user_id"]
    if ctx["role"] == "Operator":
        op = db["operator"].get(ctx["user_id"])
        return op["home_id"] if op else "__no_home__"
    return None


def tenant_check(ctx, owner_home_id):
    """Priority 4: FuneralHome/Operator may only touch resources of their home."""
    if ctx["role"] in ("FuneralHome", "Operator"):
        if owner_home_id != actor_home(ctx):
            raise ApiError(
                "ERR_CROSS_TENANT_FORBIDDEN", 403, "resource belongs to another tenant"
            )


def owner_home_of(entity_type, obj):
    if entity_type == "funeral_home":
        return obj["id"]
    if entity_type in ("guestbook_entry", "tribute_video"):
        order = db["service_order"].get(obj["order_id"])
        return order["home_id"] if order else None
    return obj.get("home_id")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(entity_type, rid):
    obj = db[entity_type].get(rid)
    if obj is None:
        raise ApiError(NOT_FOUND_ERR[entity_type], 404, "%s not found" % entity_type)
    return obj


# ---------------------------------------------------------------------------
# Input validation helpers (Priority 5)
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "request body must be an object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", 422, "missing required field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", 422, "invalid value for %s" % field)


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", 422, "%s must be an integer" % field)
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    ordered = sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def duration_minutes_from_range(start_dt, end_dt):
    seconds = (end_dt - start_dt).total_seconds()
    return math.ceil(seconds / 60)


def service_billing(duration_minutes, camera_count, priority_support):
    overage = max(0, duration_minutes - INCLUDED_MINUTES)
    tier1 = min(overage, OVERAGE_TIER1_MINUTES) * OVERAGE_TIER1_RATE_CENTS
    tier2 = max(0, overage - OVERAGE_TIER1_MINUTES) * OVERAGE_TIER2_RATE_CENTS
    surcharge = PRIORITY_SUPPORT_SURCHARGE_CENTS if priority_support else 0
    return BASE_FEE_CENTS + PER_CAMERA_CENTS * camera_count + tier1 + tier2 + surcharge


def recording_duration_minutes(order):
    if order["actual_end"] is None or order["actual_start"] is None:
        return 0
    seconds = (order["actual_end"] - order["actual_start"]).total_seconds()
    return math.ceil(seconds / 60)


def donation_fee(gross):
    return round_half_up(Decimal(gross) * FEE_PCT) + FEE_FLAT_CENTS


# ---------------------------------------------------------------------------
# Derived-field reconciliation (PRD §2.8)
# ---------------------------------------------------------------------------
def donations_of_order(order_id):
    return [d for d in db["donation"].values() if d["order_id"] == order_id]


def donations_of_home(home_id):
    return [d for d in db["donation"].values() if d["home_id"] == home_id]


def recompute_order_net(order):
    new_val = sum(
        d["net_amount_cents"] or 0
        for d in donations_of_order(order["id"])
        if d["status"] == "SETTLED"
    )
    if order["donations_net_cents"] != new_val:
        order["donations_net_cents"] = new_val
        touch(order)


def recompute_home_totals(home):
    pledged = sum(
        d["gross_amount_cents"]
        for d in donations_of_home(home["id"])
        if d["status"] in ("PLEDGED", "SETTLED")
    )
    net = sum(
        d["net_amount_cents"] or 0
        for d in donations_of_home(home["id"])
        if d["status"] == "SETTLED"
    )
    changed = False
    if home["donations_pledged_cents"] != pledged:
        home["donations_pledged_cents"] = pledged
        changed = True
    if home["donations_net_cents"] != net:
        home["donations_net_cents"] = net
        changed = True
    if changed:
        touch(home)


def recompute_guestbook_count(order):
    new_val = sum(
        1
        for e in db["guestbook_entry"].values()
        if e["order_id"] == order["id"] and e["status"] == "APPROVED"
    )
    if order["guestbook_entry_count"] != new_val:
        order["guestbook_entry_count"] = new_val
        touch(order)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(entity_type, obj):
    out = {k: v for k, v in obj.items() if not k.startswith("_")}
    if entity_type == "service_order":
        out["actual_start"] = fmt_dt(obj["actual_start"]) if obj["actual_start"] else None
        out["actual_end"] = fmt_dt(obj["actual_end"]) if obj["actual_end"] else None
        out["recording_duration_minutes"] = recording_duration_minutes(obj)
        out["access_locked"] = obj["failed_access_count"] >= MAX_FAILED_ACCESS_ATTEMPTS
    return out


# ---------------------------------------------------------------------------
# Overlap helpers
# ---------------------------------------------------------------------------
def intervals_overlap(a_start, a_end, b_start, b_end):
    # Strict overlap; exact adjacency (touching endpoints) is NOT an overlap.
    return a_start < b_end and b_start < a_end


# ===========================================================================
# ROUTES
# ===========================================================================

# ---- FuneralHome ----
@app.route("/funeral-homes", methods=["POST"])
def create_funeral_home():
    ctx = authenticate()
    require_roles(ctx, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["name", "contact_email"])
    initial = body.get("initial_credits", 0)
    if initial is None:
        initial = 0
    initial = as_int(initial, "initial_credits")
    home = new_base()
    home.update(
        {
            "name": body["name"],
            "contact_email": body["contact_email"],
            "stream_credit_balance": initial,
            "donations_pledged_cents": 0,
            "donations_net_cents": 0,
        }
    )
    db["funeral_home"][home["id"]] = home
    return success(serialize("funeral_home", home), 201)


@app.route("/funeral-homes/<rid>", methods=["GET"])
def get_funeral_home(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    home = get_or_404("funeral_home", rid)
    tenant_check(ctx, owner_home_of("funeral_home", home))
    return success(serialize("funeral_home", home), 200)


@app.route("/funeral-homes/<rid>/credit-grants", methods=["POST"])
def grant_credits(rid):
    ctx = authenticate()
    require_roles(ctx, {"PlatformAdmin"})
    home = get_or_404("funeral_home", rid)
    body = get_body()
    require_fields(body, ["credit_amount"])
    amount = as_int(body["credit_amount"], "credit_amount")
    home["stream_credit_balance"] += amount
    if home["stream_credit_balance"] < 0:
        home["stream_credit_balance"] = 0
    touch(home)
    return success(serialize("funeral_home", home), 200)


# ---- Venue ----
@app.route("/venues", methods=["POST"])
def create_venue():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    body = get_body()
    if body.get("home_id") is not None:
        get_or_404("funeral_home", body["home_id"])
        tenant_check(ctx, body["home_id"])
    require_fields(body, ["home_id", "name", "capacity", "turnaround_minutes"])
    venue = new_base()
    venue.update(
        {
            "home_id": body["home_id"],
            "name": body["name"],
            "capacity": as_int(body["capacity"], "capacity"),
            "turnaround_minutes": as_int(body["turnaround_minutes"], "turnaround_minutes"),
        }
    )
    db["venue"][venue["id"]] = venue
    return success(serialize("venue", venue), 201)


@app.route("/venues", methods=["GET"])
def list_venues():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    home_filter = request.args.get("home_id")
    ah = actor_home(ctx)
    items = []
    for v in db["venue"].values():
        if ah is not None and v["home_id"] != ah:
            continue
        if home_filter is not None and v["home_id"] != home_filter:
            continue
        items.append(v)
    page, pg = paginate(items)
    return success([serialize("venue", v) for v in page], 200, "array", pg)


@app.route("/venues/<rid>", methods=["GET"])
def get_venue(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    venue = get_or_404("venue", rid)
    tenant_check(ctx, owner_home_of("venue", venue))
    return success(serialize("venue", venue), 200)


# ---- Operator ----
@app.route("/operators", methods=["POST"])
def create_operator():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    body = get_body()
    if body.get("home_id") is not None:
        get_or_404("funeral_home", body["home_id"])
        tenant_check(ctx, body["home_id"])
    require_fields(body, ["home_id", "full_name", "skill"])
    require_enum(body["skill"], SKILLS, "skill")
    op = new_base()
    op.update(
        {
            "home_id": body["home_id"],
            "full_name": body["full_name"],
            "skill": body["skill"],
            "duty_status": "OFF_DUTY",
        }
    )
    db["operator"][op["id"]] = op
    return success(serialize("operator", op), 201)


@app.route("/operators", methods=["GET"])
def list_operators():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    home_filter = request.args.get("home_id")
    ah = actor_home(ctx)
    items = []
    for o in db["operator"].values():
        if ah is not None and o["home_id"] != ah:
            continue
        if home_filter is not None and o["home_id"] != home_filter:
            continue
        items.append(o)
    page, pg = paginate(items)
    return success([serialize("operator", o) for o in page], 200, "array", pg)


@app.route("/operators/<rid>", methods=["GET"])
def get_operator(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    op = get_or_404("operator", rid)
    tenant_check(ctx, owner_home_of("operator", op))
    return success(serialize("operator", op), 200)


@app.route("/operators/<rid>/duty", methods=["POST"])
def set_duty(rid):
    ctx = authenticate()
    require_roles(ctx, {"Operator", "FuneralHome", "PlatformAdmin"})
    op = get_or_404("operator", rid)
    tenant_check(ctx, owner_home_of("operator", op))
    body = get_body()
    require_fields(body, ["duty_status"])
    require_enum(body["duty_status"], DUTY_STATES, "duty_status")
    op["duty_status"] = body["duty_status"]
    touch(op)
    return success(serialize("operator", op), 200)


# ---- ServiceOrder ----
@app.route("/service-orders", methods=["POST"])
def create_service_order():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    body = get_body()
    # existence (priority 3): home then venue, left to right, when provided
    if body.get("home_id") is not None:
        get_or_404("funeral_home", body["home_id"])
        tenant_check(ctx, body["home_id"])
    if body.get("venue_id") is not None:
        get_or_404("venue", body["venue_id"])
    # shape (priority 5)
    require_fields(
        body, ["home_id", "venue_id", "decedent_name", "scheduled_start", "scheduled_end"]
    )
    audio_source = body.get("audio_source", "HOUSE_SYSTEM")
    if audio_source is None:
        audio_source = "HOUSE_SYSTEM"
    require_enum(audio_source, AUDIO_SOURCES, "audio_source")
    privacy_mode = body.get("privacy_mode", "PASSWORD")
    if privacy_mode is None:
        privacy_mode = "PASSWORD"
    require_enum(privacy_mode, PRIVACY_MODES, "privacy_mode")
    start_dt = parse_iso(body["scheduled_start"])
    end_dt = parse_iso(body["scheduled_end"])
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_TIME_RANGE", 422, "scheduled_end must be after scheduled_start")
    camera_count = body.get("camera_count", 1)
    if camera_count is None:
        camera_count = 1
    camera_count = as_int(camera_count, "camera_count")
    if camera_count < 1 or camera_count > 4:
        raise ApiError("ERR_INVALID_CAMERA_COUNT", 422, "camera_count must be 1..4")

    order = new_base()
    order.update(
        {
            "home_id": body["home_id"],
            "venue_id": body["venue_id"],
            "decedent_name": body["decedent_name"],
            "scheduled_start": body["scheduled_start"],
            "scheduled_end": body["scheduled_end"],
            "expected_viewers": as_int(body.get("expected_viewers", 0) or 0, "expected_viewers"),
            "priority_support": bool(body.get("priority_support", False)),
            "camera_count": camera_count,
            "audio_source": audio_source,
            "stream_status": "PENDING",
            "broadcast_status": "DRAFT",
            "settlement_status": "UNBILLED",
            "actual_start": None,
            "actual_end": None,
            "estimated_cost_cents": None,
            "final_invoice_cents": None,
            "recording_status": "NONE",
            "delivery_email": body.get("delivery_email"),
            "privacy_mode": privacy_mode,
            "access_password": body.get("access_password"),
            "access_token": mint_token(),
            "failed_access_count": 0,
            "memorial_status": "DRAFT",
            "headline": body.get("headline"),
            "donation_goal_cents": as_int(
                body.get("donation_goal_cents", 0) or 0, "donation_goal_cents"
            ),
            "donations_net_cents": 0,
            "guestbook_entry_count": 0,
        }
    )
    db["service_order"][order["id"]] = order
    return success(serialize("service_order", order), 201)


@app.route("/service-orders", methods=["GET"])
def list_service_orders():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    home_filter = request.args.get("home_id")
    venue_filter = request.args.get("venue_id")
    ah = actor_home(ctx)
    items = []
    for o in db["service_order"].values():
        if ah is not None and o["home_id"] != ah:
            continue
        if home_filter is not None and o["home_id"] != home_filter:
            continue
        if venue_filter is not None and o["venue_id"] != venue_filter:
            continue
        items.append(o)
    page, pg = paginate(items)
    return success([serialize("service_order", o) for o in page], 200, "array", pg)


@app.route("/service-orders/<rid>", methods=["GET"])
def get_service_order(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    order = get_or_404("service_order", rid)
    tenant_check(ctx, owner_home_of("service_order", order))
    return success(serialize("service_order", order), 200)


ORDER_ACTION_ROLES = {
    "SCHEDULE": {"FuneralHome", "PlatformAdmin"},
    "GO_LIVE": {"FuneralHome", "Operator", "PlatformAdmin"},
    "END": {"FuneralHome", "Operator", "PlatformAdmin"},
    "CANCEL": {"FuneralHome", "PlatformAdmin"},
    "INVOICE": {"FuneralHome", "PlatformAdmin"},
    "PAY": {"FuneralHome", "PlatformAdmin"},
    "SET_STREAM_READY": {"FuneralHome", "Operator", "PlatformAdmin"},
    "SET_STREAM_FAILED": {"FuneralHome", "Operator", "PlatformAdmin"},
    "START_EDIT": {"FuneralHome", "PlatformAdmin"},
    "MARK_RECORDING_READY": {"FuneralHome", "PlatformAdmin"},
    "DELIVER_RECORDING": {"FuneralHome", "PlatformAdmin"},
    "PUBLISH_MEMORIAL": {"FuneralHome", "PlatformAdmin"},
    "ARCHIVE_MEMORIAL": {"FuneralHome", "PlatformAdmin"},
}


def has_confirmed_booking(order_id):
    return any(
        b["order_id"] == order_id and b["status"] == "CONFIRMED"
        for b in db["venue_booking"].values()
    )


def cascade_cancel(order):
    """Cancel cascade: HELD/CONFIRMED bookings -> RELEASED, which releases the
    order's ASSIGNED camera assignments (PRD §2.8, §3.6)."""
    for b in db["venue_booking"].values():
        if b["order_id"] == order["id"] and b["status"] in ("HELD", "CONFIRMED"):
            b["status"] = "RELEASED"
            touch(b)
    for a in db["camera_assignment"].values():
        if a["order_id"] == order["id"] and a["status"] == "ASSIGNED":
            a["status"] = "RELEASED"
            touch(a)


@app.route("/service-orders/<rid>/transitions", methods=["POST"])
def service_order_transition(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "Operator", "PlatformAdmin"})
    order = get_or_404("service_order", rid)
    tenant_check(ctx, owner_home_of("service_order", order))
    body = get_body()
    require_fields(body, ["action"])
    action = body["action"]
    if action not in ORDER_ACTION_ROLES:
        raise ApiError("ERR_VALIDATION", 422, "unknown action: %s" % action)
    require_roles(ctx, ORDER_ACTION_ROLES[action])

    if action == "SCHEDULE":
        _schedule(order)
    elif action == "GO_LIVE":
        _go_live(order)
    elif action == "END":
        _end(order)
    elif action == "CANCEL":
        _cancel(order)
    elif action == "INVOICE":
        _invoice(order)
    elif action == "PAY":
        _pay(order)
    elif action == "SET_STREAM_READY":
        _set_stream(order, "READY", {"PENDING", "FAILED"})
    elif action == "SET_STREAM_FAILED":
        _set_stream(order, "FAILED", {"PENDING", "READY"})
    elif action == "START_EDIT":
        _recording(order, "RAW", "EDITING")
    elif action == "MARK_RECORDING_READY":
        _recording(order, "EDITING", "READY")
    elif action == "DELIVER_RECORDING":
        _deliver(order, body)
    elif action == "PUBLISH_MEMORIAL":
        _memorial(order, "DRAFT", "PUBLISHED")
    elif action == "ARCHIVE_MEMORIAL":
        _memorial(order, "PUBLISHED", "ARCHIVED")

    return success(serialize("service_order", order), 200)


def _schedule(order):
    if order["broadcast_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", 409, "order not in DRAFT")
    if not has_confirmed_booking(order["id"]):
        raise ApiError("ERR_VENUE_NOT_CONFIRMED", 409, "no confirmed venue booking")
    if order["stream_status"] != "READY":
        raise ApiError("ERR_STREAM_NOT_READY", 409, "stream not READY")
    home = db["funeral_home"].get(order["home_id"])
    if home is None or home["stream_credit_balance"] < 1:
        raise ApiError("ERR_INSUFFICIENT_STREAM_CREDITS", 402, "insufficient stream credits")
    home["stream_credit_balance"] -= 1
    touch(home)
    start_dt = parse_iso(order["scheduled_start"])
    end_dt = parse_iso(order["scheduled_end"])
    dur = duration_minutes_from_range(start_dt, end_dt)
    order["estimated_cost_cents"] = service_billing(
        dur, order["camera_count"], order["priority_support"]
    )
    order["broadcast_status"] = "SCHEDULED"
    touch(order)


def _go_live(order):
    if order["broadcast_status"] != "SCHEDULED":
        raise ApiError("ERR_ORDER_NOT_SCHEDULED", 409, "order not SCHEDULED")
    if order["stream_status"] != "READY":
        raise ApiError("ERR_STREAM_NOT_READY", 409, "stream not READY")
    order["actual_start"] = _logical_clock
    order["broadcast_status"] = "LIVE"
    touch(order)


def _end(order):
    if order["broadcast_status"] != "LIVE":
        raise ApiError("ERR_ORDER_NOT_LIVE", 409, "order not LIVE")
    order["actual_end"] = _logical_clock
    order["broadcast_status"] = "ENDED"
    if order["recording_status"] == "NONE":
        order["recording_status"] = "RAW"
    touch(order)


def _cancel(order):
    if order["broadcast_status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE", 409, "order not cancellable")
    was_scheduled = order["broadcast_status"] == "SCHEDULED"
    if was_scheduled:
        home = db["funeral_home"].get(order["home_id"])
        if home is not None:
            home["stream_credit_balance"] += 1
            touch(home)
    order["settlement_status"] = "VOID"
    order["broadcast_status"] = "CANCELLED"
    cascade_cancel(order)
    touch(order)


def _invoice(order):
    if order["broadcast_status"] != "ENDED":
        raise ApiError("ERR_ORDER_NOT_ENDED", 409, "order not ENDED")
    if order["settlement_status"] != "UNBILLED":
        raise ApiError("ERR_ORDER_NOT_UNBILLED", 409, "settlement not UNBILLED")
    dur = recording_duration_minutes(order)
    order["final_invoice_cents"] = service_billing(
        dur, order["camera_count"], order["priority_support"]
    )
    order["settlement_status"] = "INVOICED"
    touch(order)


def _pay(order):
    if order["settlement_status"] != "INVOICED":
        raise ApiError("ERR_ORDER_NOT_INVOICED", 409, "settlement not INVOICED")
    order["settlement_status"] = "PAID"
    touch(order)


def _set_stream(order, target, allowed_from):
    if order["stream_status"] not in allowed_from:
        raise ApiError("ERR_STREAM_INVALID_STATE", 409, "invalid stream transition")
    order["stream_status"] = target
    touch(order)


def _recording(order, from_state, to_state):
    if order["recording_status"] != from_state:
        raise ApiError("ERR_RECORDING_INVALID_STATE", 409, "invalid recording transition")
    order["recording_status"] = to_state
    touch(order)


def _deliver(order, body):
    if order["recording_status"] != "READY":
        raise ApiError("ERR_RECORDING_INVALID_STATE", 409, "recording not READY")
    if "delivery_email" in body and body["delivery_email"] is not None:
        order["delivery_email"] = body["delivery_email"]
    if not order.get("delivery_email"):
        raise ApiError("ERR_DELIVERY_EMAIL_MISSING", 409, "delivery_email required")
    order["recording_status"] = "DELIVERED"
    touch(order)


def _memorial(order, from_state, to_state):
    if order["memorial_status"] != from_state:
        raise ApiError("ERR_MEMORIAL_INVALID_STATE", 409, "invalid memorial transition")
    order["memorial_status"] = to_state
    touch(order)


@app.route("/service-orders/<rid>/access", methods=["POST"])
def access_order(rid):
    ctx = authenticate()
    require_roles(ctx, {"Guest"})
    order = get_or_404("service_order", rid)
    body = get_body()
    require_fields(body, ["password"])
    # state (priority 6): already locked
    if order["failed_access_count"] >= MAX_FAILED_ACCESS_ATTEMPTS:
        raise ApiError("ERR_ACCESS_LOCKED", 409, "guest link is locked")
    # password (priority 10)
    if body["password"] != order.get("access_password"):
        order["failed_access_count"] += 1
        touch(order)
        raise ApiError("ERR_INVALID_ACCESS_PASSWORD", 403, "wrong access password")
    return success(serialize("service_order", order), 200)


# ---- VenueBooking ----
@app.route("/venue-bookings", methods=["POST"])
def create_venue_booking():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    body = get_body()
    # existence (priority 3): order then venue
    order = None
    if body.get("order_id") is not None:
        order = get_or_404("service_order", body["order_id"])
    if body.get("venue_id") is not None:
        get_or_404("venue", body["venue_id"])
    # tenant (priority 4)
    if order is not None:
        tenant_check(ctx, order["home_id"])
    # shape (priority 5)
    require_fields(
        body, ["order_id", "venue_id", "window_start", "window_end", "expected_order_version"]
    )
    ws = parse_iso(body["window_start"])
    we = parse_iso(body["window_end"])
    if not (we > ws):
        raise ApiError("ERR_INVALID_TIME_RANGE", 422, "window_end must be after window_start")
    expected_version = as_int(body["expected_order_version"], "expected_order_version")
    venue = db["venue"][body["venue_id"]]

    # venue time conflict (priority 9): expand new window by turnaround on both
    # sides, compare against other orders' HELD/CONFIRMED bookings on the venue.
    buffer = timedelta(minutes=venue["turnaround_minutes"])
    exp_start = ws - buffer
    exp_end = we + buffer
    for b in db["venue_booking"].values():
        if b["venue_id"] != venue["id"]:
            continue
        if b["status"] not in ("HELD", "CONFIRMED"):
            continue
        if b["order_id"] == order["id"]:
            continue
        b_ws = parse_iso(b["window_start"])
        b_we = parse_iso(b["window_end"])
        if intervals_overlap(exp_start, exp_end, b_ws, b_we):
            raise ApiError("ERR_VENUE_TIME_CONFLICT", 409, "venue time conflict")

    # OCC (priority 12)
    if expected_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION", 412, "stale order version")

    # side effects
    booking = new_base()
    booking.update(
        {
            "order_id": order["id"],
            "venue_id": venue["id"],
            "home_id": order["home_id"],
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "status": "HELD",
        }
    )
    db["venue_booking"][booking["id"]] = booking
    # supersede any prior HELD booking of the same order
    for b in db["venue_booking"].values():
        if b["id"] == booking["id"]:
            continue
        if b["order_id"] == order["id"] and b["status"] == "HELD":
            b["status"] = "RELEASED"
            touch(b)
    # advance the order's version by one
    touch(order)
    return success(serialize("venue_booking", booking), 201)


@app.route("/venue-bookings", methods=["GET"])
def list_venue_bookings():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    of = request.args.get("order_id")
    vf = request.args.get("venue_id")
    hf = request.args.get("home_id")
    ah = actor_home(ctx)
    items = []
    for b in db["venue_booking"].values():
        if ah is not None and b["home_id"] != ah:
            continue
        if of is not None and b["order_id"] != of:
            continue
        if vf is not None and b["venue_id"] != vf:
            continue
        if hf is not None and b["home_id"] != hf:
            continue
        items.append(b)
    page, pg = paginate(items)
    return success([serialize("venue_booking", b) for b in page], 200, "array", pg)


@app.route("/venue-bookings/<rid>", methods=["GET"])
def get_venue_booking(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    b = get_or_404("venue_booking", rid)
    tenant_check(ctx, owner_home_of("venue_booking", b))
    return success(serialize("venue_booking", b), 200)


@app.route("/venue-bookings/<rid>/confirm", methods=["POST"])
def confirm_venue_booking(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    b = get_or_404("venue_booking", rid)
    tenant_check(ctx, owner_home_of("venue_booking", b))
    if b["status"] != "HELD":
        raise ApiError("ERR_BOOKING_NOT_HELD", 409, "booking not HELD")
    b["status"] = "CONFIRMED"
    touch(b)
    return success(serialize("venue_booking", b), 200)


# ---- CameraAssignment ----
@app.route("/camera-assignments", methods=["POST"])
def create_camera_assignment():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    body = get_body()
    order = None
    op = None
    if body.get("order_id") is not None:
        order = get_or_404("service_order", body["order_id"])
    if body.get("operator_id") is not None:
        op = get_or_404("operator", body["operator_id"])
    if order is not None:
        tenant_check(ctx, order["home_id"])
    require_fields(body, ["order_id", "operator_id", "role"])
    require_enum(body["role"], CREW_ROLES, "role")
    # operator on duty (priority 8)
    if op["duty_status"] != "ON_DUTY":
        raise ApiError("ERR_OPERATOR_OFF_DUTY", 409, "operator not on duty")
    # operator time conflict (priority 9): order window vs other ASSIGNED
    o_start = parse_iso(order["scheduled_start"])
    o_end = parse_iso(order["scheduled_end"])
    for a in db["camera_assignment"].values():
        if a["operator_id"] != op["id"] or a["status"] != "ASSIGNED":
            continue
        a_order = db["service_order"].get(a["order_id"])
        if a_order is None:
            continue
        a_start = parse_iso(a_order["scheduled_start"])
        a_end = parse_iso(a_order["scheduled_end"])
        if intervals_overlap(o_start, o_end, a_start, a_end):
            raise ApiError("ERR_OPERATOR_TIME_CONFLICT", 409, "operator time conflict")

    assignment = new_base()
    assignment.update(
        {
            "order_id": order["id"],
            "operator_id": op["id"],
            "home_id": order["home_id"],
            "role": body["role"],
            "status": "ASSIGNED",
        }
    )
    db["camera_assignment"][assignment["id"]] = assignment
    return success(serialize("camera_assignment", assignment), 201)


@app.route("/camera-assignments", methods=["GET"])
def list_camera_assignments():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    of = request.args.get("order_id")
    opf = request.args.get("operator_id")
    hf = request.args.get("home_id")
    ah = actor_home(ctx)
    items = []
    for a in db["camera_assignment"].values():
        if ah is not None and a["home_id"] != ah:
            continue
        if of is not None and a["order_id"] != of:
            continue
        if opf is not None and a["operator_id"] != opf:
            continue
        if hf is not None and a["home_id"] != hf:
            continue
        items.append(a)
    page, pg = paginate(items)
    return success([serialize("camera_assignment", a) for a in page], 200, "array", pg)


@app.route("/camera-assignments/<rid>", methods=["GET"])
def get_camera_assignment(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    a = get_or_404("camera_assignment", rid)
    tenant_check(ctx, owner_home_of("camera_assignment", a))
    return success(serialize("camera_assignment", a), 200)


# ---- GuestbookEntry ----
@app.route("/guestbook-entries", methods=["POST"])
def create_guestbook_entry():
    ctx = authenticate()
    require_roles(ctx, {"Guest"})
    body = get_body()
    order = None
    if body.get("order_id") is not None:
        order = get_or_404("service_order", body["order_id"])
    require_fields(body, ["order_id", "author_name", "message"])
    if order["memorial_status"] != "PUBLISHED":
        raise ApiError("ERR_MEMORIAL_NOT_PUBLISHED", 409, "memorial not published")
    entry = new_base()
    entry.update(
        {
            "order_id": order["id"],
            "author_name": body["author_name"],
            "message": body["message"],
            "status": "PENDING",
        }
    )
    db["guestbook_entry"][entry["id"]] = entry
    return success(serialize("guestbook_entry", entry), 201)


@app.route("/guestbook-entries", methods=["GET"])
def list_guestbook_entries():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    of = request.args.get("order_id")
    ah = actor_home(ctx)
    items = []
    for e in db["guestbook_entry"].values():
        if ah is not None and owner_home_of("guestbook_entry", e) != ah:
            continue
        if of is not None and e["order_id"] != of:
            continue
        items.append(e)
    page, pg = paginate(items)
    return success([serialize("guestbook_entry", e) for e in page], 200, "array", pg)


@app.route("/guestbook-entries/<rid>", methods=["GET"])
def get_guestbook_entry(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    e = get_or_404("guestbook_entry", rid)
    tenant_check(ctx, owner_home_of("guestbook_entry", e))
    return success(serialize("guestbook_entry", e), 200)


@app.route("/guestbook-entries/<rid>/moderation", methods=["POST"])
def moderate_guestbook_entry(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    e = get_or_404("guestbook_entry", rid)
    tenant_check(ctx, owner_home_of("guestbook_entry", e))
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    require_enum(decision, {"APPROVE", "HIDE"}, "decision")
    order = db["service_order"].get(e["order_id"])
    if decision == "APPROVE":
        if e["status"] != "PENDING":
            raise ApiError("ERR_GUESTBOOK_INVALID_STATE", 409, "entry not PENDING")
        e["status"] = "APPROVED"
        touch(e)
        if order:
            recompute_guestbook_count(order)
    else:  # HIDE
        if e["status"] not in ("PENDING", "APPROVED"):
            raise ApiError("ERR_GUESTBOOK_INVALID_STATE", 409, "entry not hideable")
        was_approved = e["status"] == "APPROVED"
        e["status"] = "HIDDEN"
        touch(e)
        if was_approved and order:
            recompute_guestbook_count(order)
    return success(serialize("guestbook_entry", e), 200)


# ---- Donation ----
@app.route("/donations", methods=["POST"])
def create_donation():
    ctx = authenticate()
    require_roles(ctx, {"Guest"})
    body = get_body()
    order = None
    if body.get("order_id") is not None:
        order = get_or_404("service_order", body["order_id"])
    require_fields(body, ["order_id", "donor_name", "gross_amount_cents"])
    gross = as_int(body["gross_amount_cents"], "gross_amount_cents")
    if gross <= 0:
        raise ApiError("ERR_INVALID_DONATION_AMOUNT", 422, "gross_amount_cents must be > 0")
    if order["memorial_status"] != "PUBLISHED":
        raise ApiError("ERR_MEMORIAL_NOT_PUBLISHED", 409, "memorial not published")
    donation = new_base()
    donation.update(
        {
            "order_id": order["id"],
            "home_id": order["home_id"],
            "donor_name": body["donor_name"],
            "gross_amount_cents": gross,
            "fee_cents": None,
            "net_amount_cents": None,
            "status": "PLEDGED",
        }
    )
    db["donation"][donation["id"]] = donation
    home = db["funeral_home"].get(order["home_id"])
    if home:
        recompute_home_totals(home)
    return success(serialize("donation", donation), 201)


@app.route("/donations", methods=["GET"])
def list_donations():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    of = request.args.get("order_id")
    hf = request.args.get("home_id")
    ah = actor_home(ctx)
    items = []
    for d in db["donation"].values():
        if ah is not None and d["home_id"] != ah:
            continue
        if of is not None and d["order_id"] != of:
            continue
        if hf is not None and d["home_id"] != hf:
            continue
        items.append(d)
    page, pg = paginate(items)
    return success([serialize("donation", d) for d in page], 200, "array", pg)


@app.route("/donations/<rid>", methods=["GET"])
def get_donation(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    d = get_or_404("donation", rid)
    tenant_check(ctx, owner_home_of("donation", d))
    return success(serialize("donation", d), 200)


@app.route("/donations/<rid>/transitions", methods=["POST"])
def donation_transition(rid):
    ctx = authenticate()
    require_roles(ctx, {"PlatformAdmin"})
    d = get_or_404("donation", rid)
    body = get_body()
    require_fields(body, ["action"])
    action = body["action"]
    require_enum(action, {"SETTLE", "REFUND"}, "action")
    order = db["service_order"].get(d["order_id"])
    home = db["funeral_home"].get(d["home_id"])
    if action == "SETTLE":
        if d["status"] != "PLEDGED":
            raise ApiError("ERR_DONATION_NOT_PLEDGED", 409, "donation not PLEDGED")
        fee = donation_fee(d["gross_amount_cents"])
        d["fee_cents"] = fee
        d["net_amount_cents"] = d["gross_amount_cents"] - fee
        d["status"] = "SETTLED"
        touch(d)
        if order:
            recompute_order_net(order)
        if home:
            recompute_home_totals(home)
    else:  # REFUND
        if d["status"] not in ("PLEDGED", "SETTLED"):
            raise ApiError("ERR_DONATION_NOT_REFUNDABLE", 409, "donation not refundable")
        d["status"] = "REFUNDED"
        touch(d)
        # recompute rollups; PLEDGED->REFUNDED leaves net totals unchanged,
        # SETTLED->REFUNDED removes this donation's net (compensating).
        if order:
            recompute_order_net(order)
        if home:
            recompute_home_totals(home)
    return success(serialize("donation", d), 200)


# ---- TributeVideo ----
TRIBUTE_ACTION_ROLES = {
    "SUBMIT": {"FuneralHome", "PlatformAdmin"},
    "PUBLISH": {"FuneralHome", "PlatformAdmin"},
    "REQUEST_CHANGES": {"PlatformAdmin"},
    "APPROVE": {"PlatformAdmin"},
}


@app.route("/tribute-videos", methods=["POST"])
def create_tribute_video():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    body = get_body()
    order = None
    if body.get("order_id") is not None:
        order = get_or_404("service_order", body["order_id"])
    if order is not None:
        tenant_check(ctx, order["home_id"])
    require_fields(body, ["order_id", "title", "photo_count"])
    tribute = new_base()
    tribute.update(
        {
            "order_id": order["id"],
            "title": body["title"],
            "photo_count": as_int(body["photo_count"], "photo_count"),
            "status": "DRAFT",
            "revision_count": 0,
        }
    )
    db["tribute_video"][tribute["id"]] = tribute
    return success(serialize("tribute_video", tribute), 201)


@app.route("/tribute-videos", methods=["GET"])
def list_tribute_videos():
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    of = request.args.get("order_id")
    ah = actor_home(ctx)
    items = []
    for t in db["tribute_video"].values():
        if ah is not None and owner_home_of("tribute_video", t) != ah:
            continue
        if of is not None and t["order_id"] != of:
            continue
        items.append(t)
    page, pg = paginate(items)
    return success([serialize("tribute_video", t) for t in page], 200, "array", pg)


@app.route("/tribute-videos/<rid>", methods=["GET"])
def get_tribute_video(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    t = get_or_404("tribute_video", rid)
    tenant_check(ctx, owner_home_of("tribute_video", t))
    return success(serialize("tribute_video", t), 200)


@app.route("/tribute-videos/<rid>/transitions", methods=["POST"])
def tribute_video_transition(rid):
    ctx = authenticate()
    require_roles(ctx, {"FuneralHome", "PlatformAdmin"})
    t = get_or_404("tribute_video", rid)
    tenant_check(ctx, owner_home_of("tribute_video", t))
    body = get_body()
    require_fields(body, ["action"])
    action = body["action"]
    if action not in TRIBUTE_ACTION_ROLES:
        raise ApiError("ERR_VALIDATION", 422, "unknown action: %s" % action)
    require_roles(ctx, TRIBUTE_ACTION_ROLES[action])

    if action == "SUBMIT":
        if t["status"] == "DRAFT":
            t["status"] = "SUBMITTED"
        elif t["status"] == "CHANGES_REQUESTED":
            t["status"] = "SUBMITTED"
            t["revision_count"] += 1
        else:
            raise ApiError("ERR_TRIBUTE_INVALID_TRANSITION", 409, "cannot submit")
        touch(t)
    elif action == "REQUEST_CHANGES":
        if t["status"] != "SUBMITTED":
            raise ApiError("ERR_TRIBUTE_INVALID_TRANSITION", 409, "cannot request changes")
        t["status"] = "CHANGES_REQUESTED"
        touch(t)
    elif action == "APPROVE":
        if t["status"] != "SUBMITTED":
            raise ApiError("ERR_TRIBUTE_INVALID_TRANSITION", 409, "cannot approve")
        t["status"] = "APPROVED"
        touch(t)
    elif action == "PUBLISH":
        if t["status"] != "APPROVED":
            raise ApiError("ERR_TRIBUTE_INVALID_TRANSITION", 409, "cannot publish")
        t["status"] = "PUBLISHED"
        touch(t)

    return success(serialize("tribute_video", t), 200)


# ---- Logical clock (test-driving) ----
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global _logical_clock
    ctx = authenticate()
    require_roles(ctx, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    _logical_clock = parse_iso(body["to_iso8601"])
    return success(None, 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
