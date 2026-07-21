"""Glamping & Unique-Stay Booking API — Python + Flask, in-memory.

Single-file implementation. Storage is in-memory dicts keyed by id; the store
starts empty on every boot (no seeding). Tests build all preconditions via the
declared API surface.
"""
import os
import random
import string
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
LOCK = threading.RLock()

STORE = {
    "Host": {},
    "Guest": {},
    "Listing": {},
    "Permit": {},
    "SeasonalRate": {},
    "AddOn": {},
    "ExperienceSlot": {},
    "Booking": {},
    "Payout": {},
    "Review": {},
    "Message": {},
}

_SEQ = [0]

# Logical clock — startup default per PRD §2.5
STATE = {"clock": datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)}

KNOWN_ROLES = {"Host", "Guest", "PermitReviewer", "PlatformAdmin"}
SITE_TYPES = {"YURT", "CABIN", "TREEHOUSE", "DOME", "AIRSTREAM"}
POLICIES = {"FLEXIBLE", "MODERATE", "STRICT"}
PAYOUT_METHODS = {"BANK", "PAYPAL"}
PERMIT_TYPES = {"CAMPING", "STRUCTURE", "SPECIAL_USE"}
CATEGORIES = {"AMENITY", "EXPERIENCE"}
PRICING_UNITS = {"PER_STAY", "PER_NIGHT", "PER_GUEST"}
SENDER_ROLES = {"HOST", "GUEST"}

# Calculation constants
GUEST_FEE_RATE = Decimal("0.12")
WEEKLY_DISCOUNT_PCT = Decimal("0.10")
MONTHLY_DISCOUNT_PCT = Decimal("0.28")
HOST_FEE_RATE = Decimal("0.03")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Helpers: time, ids, envelope
# ---------------------------------------------------------------------------
def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def now_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def gen_uuid():
    import uuid
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_request_id(), "api_request_timestamp": now_ts()}


def ok(data, status=200, response_type="object", pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def parse_dt(value):
    """Parse an ISO 8601 date/datetime string into an aware UTC datetime."""
    if value is None or not isinstance(value, str):
        raise ValueError("bad date")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # date-only fallback
        dt = datetime.fromisoformat(s + "T00:00:00+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(dec):
    """Round-half-up to whole cents; returns int."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------
def new_obj(type_name, fields, common=True):
    oid = gen_uuid()
    obj = {"_type": type_name, "_seq": next_seq(), "id": oid}
    obj.update(fields)
    obj["created_at"] = now_ts()
    if common:
        obj["updated_at"] = obj["created_at"]
        obj["version"] = 1
    STORE[type_name][oid] = obj
    return obj


def touch(obj):
    obj["updated_at"] = now_ts()
    if "version" in obj:
        obj["version"] = obj["version"] + 1


def get(type_name, oid):
    return STORE[type_name].get(oid)


def require(type_name, oid):
    obj = STORE[type_name].get(oid)
    if obj is None:
        err("ERR_NOT_FOUND", 404, "%s not found" % type_name)
    return obj


# ---------------------------------------------------------------------------
# Computed field recomputation
# ---------------------------------------------------------------------------
def calc_reserved_nights(listing_id):
    total = 0
    for b in STORE["Booking"].values():
        if b["listing_id"] == listing_id and b["status"] in ("CONFIRMED", "CHECKED_IN"):
            total += b["nights"]
    return total


def host_bookings(host_id):
    listing_ids = {l["id"] for l in STORE["Listing"].values() if l["host_id"] == host_id}
    return [b for b in STORE["Booking"].values() if b["listing_id"] in listing_ids]


def host_payouts(host_id):
    listing_ids = {l["id"] for l in STORE["Listing"].values() if l["host_id"] == host_id}
    booking_ids = {b["id"] for b in STORE["Booking"].values() if b["listing_id"] in listing_ids}
    return [p for p in STORE["Payout"].values() if p["booking_id"] in booking_ids]


def host_ledger(host_id):
    pending = 0
    paid = 0
    for p in host_payouts(host_id):
        if p["status"] == "SCHEDULED":
            pending += p["estimated_amount_cents"]
        elif p["status"] in ("PAID", "PARTIAL"):
            paid += (p["final_amount_cents"] or 0)
    completed = sum(1 for b in host_bookings(host_id) if b["status"] == "COMPLETED")
    return {
        "pending_payout_cents": pending,
        "paid_out_cents": paid,
        "completed_stays_count": completed,
    }


def guest_wallet(guest_id):
    total = 0
    for b in STORE["Booking"].values():
        if b["guest_id"] == guest_id and b.get("refund_amount_cents"):
            total += b["refund_amount_cents"]
    return total


def slot_reserved(slot_id):
    total = 0
    active_states = ("REQUESTED", "CONFIRMED", "CHECKED_IN", "COMPLETED")
    for b in STORE["Booking"].values():
        if b["status"] not in active_states:
            continue
        for line in b["add_ons"]:
            if line.get("experience_slot_id") == slot_id:
                total += line.get("participant_count") or 0
    return total


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def public(obj):
    d = {k: v for k, v in obj.items() if not k.startswith("_")}
    t = obj["_type"]
    if t == "Listing":
        d["reserved_nights_count"] = calc_reserved_nights(obj["id"])
    elif t == "Host":
        d.update(host_ledger(obj["id"]))
    elif t == "Guest":
        d["wallet_credit_cents"] = guest_wallet(obj["id"])
    elif t == "ExperienceSlot":
        d["reserved_participants"] = slot_reserved(obj["id"])
    return d


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    g.user_id = uid
    g.role = role
    return uid, role


def require_role(allowed):
    if g.role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role %s not permitted" % g.role)


def ensure_owner(condition):
    if not condition:
        err("ERR_NOT_RESOURCE_OWNER", 403, "Not the resource owner")


# ---------------------------------------------------------------------------
# Body helpers / validation
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        err("ERR_VALIDATION", 400, "Body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            err("ERR_VALIDATION", 400, "Missing required field: %s" % f)


def val_enum(value, allowed, name):
    if value not in allowed:
        err("ERR_VALIDATION", 400, "Invalid %s" % name)


def val_int(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_VALIDATION", 400, "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        err("ERR_VALIDATION", 400, "%s below minimum" % name)
    return value


def paginate(items):
    items = sorted(items, key=lambda o: o["_seq"])
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
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
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def list_response(objs):
    page, pg = paginate(objs)
    return ok([public(o) for o in page], 200, "array", pagination=pg)


# ---------------------------------------------------------------------------
# Pricing / calculations
# ---------------------------------------------------------------------------
def covering_rate(listing_id, d):
    """Return the SeasonalRate covering date `d` (a date), or None."""
    for r in STORE["SeasonalRate"].values():
        if r["listing_id"] != listing_id:
            continue
        if r["_start"].date() <= d < r["_end"].date():
            return r
    return None


def nightly_subtotal(listing_id, ci_dt, co_dt):
    """Sum per-night rates; raise ERR_NO_RATE_FOR_DATES if any night uncovered."""
    nights = (co_dt.date() - ci_dt.date()).days
    subtotal = 0
    for i in range(nights):
        d = ci_dt.date() + timedelta(days=i)
        r = covering_rate(listing_id, d)
        if r is None:
            err("ERR_NO_RATE_FOR_DATES", 400, "No rate covers %s" % d.isoformat())
        subtotal += r["nightly_rate_cents"]
    return subtotal


def discount_pct(nights):
    if nights >= 28:
        return MONTHLY_DISCOUNT_PCT
    if nights >= 7:
        return WEEKLY_DISCOUNT_PCT
    return Decimal("0")


def line_total_for(price_cents, pricing_unit, nights, guest_count):
    if pricing_unit == "PER_STAY":
        return price_cents
    if pricing_unit == "PER_NIGHT":
        return price_cents * nights
    if pricing_unit == "PER_GUEST":
        return price_cents * guest_count
    return price_cents


def addons_subtotal_from_lines(lines):
    return sum(line["line_total_cents"] for line in lines)


def addons_subtotal_repriced(lines, nights, guest_count):
    """Re-price add-on lines against current AddOn.price_cents (accept-time)."""
    total = 0
    for line in lines:
        addon = get("AddOn", line["add_on_id"])
        price = addon["price_cents"] if addon else line["unit_price_snapshot_cents"]
        total += line_total_for(price, addon["pricing_unit"] if addon else "PER_STAY",
                                nights, guest_count)
    return total


def compute_quote(booking, listing):
    """Provisional guest total from rates/prices in effect now; uses stored line totals."""
    ci = booking["_ci"]
    co = booking["_co"]
    nights = booking["nights"]
    nsub = nightly_subtotal(listing["id"], ci, co)
    disc = discount_pct(nights)
    discounted_nightly = rhu(Decimal(nsub) * (Decimal(1) - disc))
    asub = addons_subtotal_from_lines(booking["add_ons"])
    subtotal = discounted_nightly + asub + booking["cleaning_fee_snapshot_cents"]
    guest_fee = rhu(Decimal(subtotal) * GUEST_FEE_RATE)
    return subtotal + guest_fee


def compute_final(booking, listing):
    """Re-snapshot the same formula against rates/prices at ACCEPT time.

    Returns a dict of locked components used for settlement.
    """
    ci = booking["_ci"]
    co = booking["_co"]
    nights = booking["nights"]
    guest_count = booking["guest_count"]
    nsub = nightly_subtotal(listing["id"], ci, co)
    disc = discount_pct(nights)
    discounted_nightly = rhu(Decimal(nsub) * (Decimal(1) - disc))
    asub = addons_subtotal_repriced(booking["add_ons"], nights, guest_count)
    cleaning = booking["cleaning_fee_snapshot_cents"]
    subtotal = discounted_nightly + asub + cleaning
    guest_fee = rhu(Decimal(subtotal) * GUEST_FEE_RATE)
    final_total = subtotal + guest_fee
    stay_and_addons = discounted_nightly + asub
    host_fee = rhu(Decimal(stay_and_addons) * HOST_FEE_RATE)
    estimated = discounted_nightly + asub + cleaning - host_fee
    return {
        "discounted_nightly": discounted_nightly,
        "addons_subtotal": asub,
        "cleaning": cleaning,
        "guest_fee": guest_fee,
        "host_fee": host_fee,
        "final_total": final_total,
        "estimated": estimated,
    }


def refund_fraction(policy, days_before):
    if policy == "FLEXIBLE":
        return Decimal("1.00") if days_before >= 1 else Decimal("0.00")
    if policy == "MODERATE":
        if days_before >= 7:
            return Decimal("1.00")
        if days_before >= 1:
            return Decimal("0.50")
        return Decimal("0.00")
    if policy == "STRICT":
        return Decimal("0.50") if days_before >= 14 else Decimal("0.00")
    return Decimal("0.00")


# ---------------------------------------------------------------------------
# Ownership resolution helpers
# ---------------------------------------------------------------------------
def owns_listing(listing):
    return g.role != "Host" or listing["host_id"] == g.user_id


def listing_of_permit(permit):
    return require("Listing", permit["listing_id"])


def listing_of_booking(booking):
    return require("Listing", booking["listing_id"])


# ===========================================================================
# ENDPOINTS
# ===========================================================================

# --- Clock ---
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    require_role({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        dt = parse_dt(body["to_iso8601"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400, "Invalid to_iso8601")
    with LOCK:
        STATE["clock"] = dt
    return ok({}, 200, "object")


# --- Host ---
@app.route("/hosts", methods=["POST"])
def create_host():
    authenticate()
    require_role({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["display_name", "email"])
    payout_method = body.get("payout_method", "BANK")
    if payout_method is None:
        payout_method = "BANK"
    val_enum(payout_method, PAYOUT_METHODS, "payout_method")
    with LOCK:
        obj = new_obj("Host", {
            "display_name": body["display_name"],
            "email": body["email"],
            "payout_method": payout_method,
        })
    return ok(public(obj), 201, "object")


@app.route("/hosts/<hid>", methods=["GET"])
def get_host(hid):
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    obj = require("Host", hid)
    return ok(public(obj), 200, "object")


# --- Guest ---
@app.route("/guests", methods=["POST"])
def create_guest():
    authenticate()
    require_role({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["display_name", "email"])
    with LOCK:
        obj = new_obj("Guest", {
            "display_name": body["display_name"],
            "email": body["email"],
        })
    return ok(public(obj), 201, "object")


@app.route("/guests/<gid>", methods=["GET"])
def get_guest(gid):
    authenticate()
    require_role({"Guest", "Host", "PlatformAdmin"})
    obj = require("Guest", gid)
    return ok(public(obj), 200, "object")


# --- Listing ---
@app.route("/listings", methods=["POST"])
def create_listing():
    authenticate()
    require_role({"Host"})
    body = get_body()
    require_fields(body, ["host_id", "title", "site_type", "max_guests", "base_nightly_rate_cents"])
    host = require("Host", body["host_id"])
    ensure_owner(host["id"] == g.user_id)
    val_enum(body["site_type"], SITE_TYPES, "site_type")
    val_int(body["max_guests"], "max_guests", minimum=1)
    val_int(body["base_nightly_rate_cents"], "base_nightly_rate_cents", minimum=0)
    min_nights = body.get("min_nights", 1)
    if min_nights is None:
        min_nights = 1
    val_int(min_nights, "min_nights", minimum=1)
    cleaning = body.get("cleaning_fee_cents", 0)
    if cleaning is None:
        cleaning = 0
    val_int(cleaning, "cleaning_fee_cents", minimum=0)
    policy = body.get("cancellation_policy", "MODERATE")
    if policy is None:
        policy = "MODERATE"
    val_enum(policy, POLICIES, "cancellation_policy")
    with LOCK:
        obj = new_obj("Listing", {
            "host_id": host["id"],
            "title": body["title"],
            "site_type": body["site_type"],
            "max_guests": body["max_guests"],
            "min_nights": min_nights,
            "base_nightly_rate_cents": body["base_nightly_rate_cents"],
            "cleaning_fee_cents": cleaning,
            "cancellation_policy": policy,
            "status": "DRAFT",
        })
    return ok(public(obj), 201, "object")


@app.route("/listings/<lid>", methods=["GET"])
def get_listing(lid):
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    obj = require("Listing", lid)
    return ok(public(obj), 200, "object")


@app.route("/listings", methods=["GET"])
def list_listings():
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    items = list(STORE["Listing"].values())
    host_id = request.args.get("host_id")
    status = request.args.get("status")
    site_type = request.args.get("site_type")
    if host_id is not None:
        items = [o for o in items if o["host_id"] == host_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if site_type is not None:
        items = [o for o in items if o["site_type"] == site_type]
    return list_response(items)


@app.route("/listings/<lid>/publish", methods=["POST"])
def publish_listing(lid):
    authenticate()
    require_role({"Host"})
    listing = require("Listing", lid)
    ensure_owner(owns_listing(listing))
    with LOCK:
        if listing["status"] != "PENDING_PERMIT":
            err("ERR_INVALID_STATE", 400, "Listing not PENDING_PERMIT")
        approved = any(p["listing_id"] == lid and p["status"] == "APPROVED"
                       for p in STORE["Permit"].values())
        if not approved:
            err("ERR_PERMIT_NOT_APPROVED", 400, "Permit not approved")
        has_rate = any(r["listing_id"] == lid for r in STORE["SeasonalRate"].values())
        if not has_rate:
            err("ERR_INVALID_STATE", 400, "No seasonal rate on listing")
        listing["status"] = "LISTED"
        touch(listing)
    return ok(public(listing), 200, "object")


def _suspend_cascade(listing):
    """Move listing to SUSPENDED and decline REQUESTED bookings on it."""
    listing["status"] = "SUSPENDED"
    touch(listing)
    for b in STORE["Booking"].values():
        if b["listing_id"] == listing["id"] and b["status"] == "REQUESTED":
            b["status"] = "DECLINED"
            touch(b)
            _touch_booking_slots(b)


@app.route("/listings/<lid>/suspend", methods=["POST"])
def suspend_listing(lid):
    authenticate()
    require_role({"Host", "PlatformAdmin"})
    listing = require("Listing", lid)
    ensure_owner(owns_listing(listing))
    with LOCK:
        if listing["status"] != "LISTED":
            err("ERR_INVALID_STATE", 400, "Listing not LISTED")
        _suspend_cascade(listing)
    return ok(public(listing), 200, "object")


@app.route("/listings/<lid>/reinstate", methods=["POST"])
def reinstate_listing(lid):
    authenticate()
    require_role({"Host"})
    listing = require("Listing", lid)
    ensure_owner(owns_listing(listing))
    with LOCK:
        if listing["status"] != "SUSPENDED":
            err("ERR_INVALID_STATE", 400, "Listing not SUSPENDED")
        approved = any(p["listing_id"] == lid and p["status"] == "APPROVED"
                       for p in STORE["Permit"].values())
        if not approved:
            err("ERR_PERMIT_NOT_APPROVED", 400, "Permit not approved")
        listing["status"] = "LISTED"
        touch(listing)
    return ok(public(listing), 200, "object")


@app.route("/listings/<lid>/delist", methods=["POST"])
def delist_listing(lid):
    authenticate()
    require_role({"Host"})
    listing = require("Listing", lid)
    ensure_owner(owns_listing(listing))
    with LOCK:
        if listing["status"] == "DELISTED":
            err("ERR_INVALID_STATE", 400, "Listing already DELISTED")
        listing["status"] = "DELISTED"
        touch(listing)
        # Cascade: CONFIRMED/CHECKED_IN bookings -> CANCELLED (full refund)
        for b in STORE["Booking"].values():
            if b["listing_id"] == lid and b["status"] in ("CONFIRMED", "CHECKED_IN"):
                _cancel_booking(b, listing, force_full=True)
    return ok(public(listing), 200, "object")


# --- Permit ---
@app.route("/listings/<lid>/permits", methods=["POST"])
def create_permit(lid):
    authenticate()
    require_role({"Host"})
    listing = require("Listing", lid)
    ensure_owner(owns_listing(listing))
    body = get_body()
    require_fields(body, ["permit_type", "authority_name"])
    val_enum(body["permit_type"], PERMIT_TYPES, "permit_type")
    valid_until = body.get("valid_until")
    if valid_until is not None:
        try:
            parse_dt(valid_until)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "Invalid valid_until")
    with LOCK:
        obj = new_obj("Permit", {
            "listing_id": lid,
            "permit_type": body["permit_type"],
            "authority_name": body["authority_name"],
            "status": "DRAFT",
            "review_notes": None,
            "valid_until": valid_until,
        })
    return ok(public(obj), 201, "object")


@app.route("/listings/<lid>/permits", methods=["GET"])
def list_permits(lid):
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    require("Listing", lid)
    items = [p for p in STORE["Permit"].values() if p["listing_id"] == lid]
    return list_response(items)


@app.route("/permits/<pid>/submit", methods=["POST"])
def submit_permit(pid):
    authenticate()
    require_role({"Host"})
    permit = require("Permit", pid)
    listing = listing_of_permit(permit)
    ensure_owner(owns_listing(listing))
    with LOCK:
        if permit["status"] not in ("DRAFT", "REJECTED"):
            err("ERR_INVALID_STATE", 400, "Permit not submittable")
        was_rejected = permit["status"] == "REJECTED"
        permit["status"] = "SUBMITTED"
        if was_rejected:
            permit["review_notes"] = None
        touch(permit)
        if listing["status"] == "DRAFT":
            listing["status"] = "PENDING_PERMIT"
            touch(listing)
    return ok(public(permit), 200, "object")


@app.route("/permits/<pid>/decision", methods=["POST"])
def decide_permit(pid):
    authenticate()
    require_role({"PermitReviewer"})
    permit = require("Permit", pid)
    body = get_body()
    require_fields(body, ["outcome"])
    val_enum(body["outcome"], {"APPROVE", "REJECT"}, "outcome")
    with LOCK:
        if permit["status"] != "SUBMITTED":
            err("ERR_PERMIT_ALREADY_DECIDED", 400, "Permit not in SUBMITTED")
        notes = body.get("review_notes")
        if body["outcome"] == "APPROVE":
            permit["status"] = "APPROVED"
            permit["review_notes"] = notes
            touch(permit)
        else:
            permit["status"] = "REJECTED"
            permit["review_notes"] = notes
            touch(permit)
            listing = get("Listing", permit["listing_id"])
            if listing and listing["status"] == "LISTED":
                _suspend_cascade(listing)
    return ok(public(permit), 200, "object")


# --- SeasonalRate ---
@app.route("/listings/<lid>/seasonal-rates", methods=["POST"])
def create_rate(lid):
    authenticate()
    require_role({"Host"})
    listing = require("Listing", lid)
    ensure_owner(owns_listing(listing))
    body = get_body()
    require_fields(body, ["start_date", "end_date", "nightly_rate_cents"])
    try:
        start = parse_dt(body["start_date"])
        end = parse_dt(body["end_date"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400, "Invalid dates")
    if not (end > start):
        err("ERR_VALIDATION", 400, "end_date must be after start_date")
    val_int(body["nightly_rate_cents"], "nightly_rate_cents", minimum=0)
    min_override = body.get("min_nights_override")
    if min_override is not None:
        val_int(min_override, "min_nights_override", minimum=1)
    with LOCK:
        # overlap check (half-open)
        for r in STORE["SeasonalRate"].values():
            if r["listing_id"] != lid:
                continue
            if start < r["_end"] and r["_start"] < end:
                err("ERR_RATE_OVERLAP", 409, "Rate window overlaps existing")
        obj = new_obj("SeasonalRate", {
            "listing_id": lid,
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "nightly_rate_cents": body["nightly_rate_cents"],
            "min_nights_override": min_override,
        })
        obj["_start"] = start
        obj["_end"] = end
        touch(listing)  # bumps Listing.version
    return ok(public(obj), 201, "object")


@app.route("/listings/<lid>/seasonal-rates", methods=["GET"])
def list_rates(lid):
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    require("Listing", lid)
    items = [r for r in STORE["SeasonalRate"].values() if r["listing_id"] == lid]
    return list_response(items)


@app.route("/seasonal-rates/<rid>", methods=["PATCH"])
def reprice_rate(rid):
    authenticate()
    require_role({"Host"})
    rate = require("SeasonalRate", rid)
    listing = require("Listing", rate["listing_id"])
    ensure_owner(owns_listing(listing))
    body = get_body()
    if "nightly_rate_cents" in body and body["nightly_rate_cents"] is not None:
        val_int(body["nightly_rate_cents"], "nightly_rate_cents", minimum=0)
    if "min_nights_override" in body and body["min_nights_override"] is not None:
        val_int(body["min_nights_override"], "min_nights_override", minimum=1)
    with LOCK:
        if "nightly_rate_cents" in body and body["nightly_rate_cents"] is not None:
            rate["nightly_rate_cents"] = body["nightly_rate_cents"]
        if "min_nights_override" in body:
            rate["min_nights_override"] = body["min_nights_override"]
        touch(rate)
        touch(listing)  # bumps Listing.version
    return ok(public(rate), 200, "object")


# --- AddOn ---
@app.route("/listings/<lid>/add-ons", methods=["POST"])
def create_addon(lid):
    authenticate()
    require_role({"Host"})
    listing = require("Listing", lid)
    ensure_owner(owns_listing(listing))
    body = get_body()
    require_fields(body, ["name", "category", "pricing_unit", "price_cents"])
    val_enum(body["category"], CATEGORIES, "category")
    val_enum(body["pricing_unit"], PRICING_UNITS, "pricing_unit")
    val_int(body["price_cents"], "price_cents", minimum=0)
    with LOCK:
        obj = new_obj("AddOn", {
            "listing_id": lid,
            "name": body["name"],
            "category": body["category"],
            "pricing_unit": body["pricing_unit"],
            "price_cents": body["price_cents"],
            "status": "ACTIVE",
        })
    return ok(public(obj), 201, "object")


@app.route("/listings/<lid>/add-ons", methods=["GET"])
def list_addons(lid):
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    require("Listing", lid)
    items = [a for a in STORE["AddOn"].values() if a["listing_id"] == lid]
    return list_response(items)


@app.route("/add-ons/<aid>", methods=["GET"])
def get_addon(aid):
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    obj = require("AddOn", aid)
    return ok(public(obj), 200, "object")


# --- ExperienceSlot ---
@app.route("/add-ons/<aid>/slots", methods=["POST"])
def create_slot(aid):
    authenticate()
    require_role({"Host"})
    addon = require("AddOn", aid)
    listing = require("Listing", addon["listing_id"])
    ensure_owner(owns_listing(listing))
    body = get_body()
    require_fields(body, ["slot_date", "max_participants"])
    try:
        slot_dt = parse_dt(body["slot_date"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400, "Invalid slot_date")
    val_int(body["max_participants"], "max_participants", minimum=1)
    with LOCK:
        obj = new_obj("ExperienceSlot", {
            "add_on_id": aid,
            "slot_date": body["slot_date"],
            "max_participants": body["max_participants"],
        })
        obj["_slot_dt"] = slot_dt
    return ok(public(obj), 201, "object")


@app.route("/add-ons/<aid>/slots", methods=["GET"])
def list_slots(aid):
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    require("AddOn", aid)
    items = [s for s in STORE["ExperienceSlot"].values() if s["add_on_id"] == aid]
    return list_response(items)


# --- Booking ---
def _touch_booking_slots(booking):
    seen = set()
    for line in booking["add_ons"]:
        sid = line.get("experience_slot_id")
        if sid and sid not in seen:
            seen.add(sid)
            s = get("ExperienceSlot", sid)
            if s:
                touch(s)


@app.route("/listings/<lid>/bookings", methods=["POST"])
def create_booking(lid):
    authenticate()
    require_role({"Guest"})
    listing = require("Listing", lid)
    body = get_body()
    require_fields(body, ["guest_id", "check_in", "check_out", "guest_count",
                          "expected_listing_version"])
    guest = require("Guest", body["guest_id"])
    ensure_owner(guest["id"] == g.user_id)
    # body well-formedness
    try:
        ci = parse_dt(body["check_in"])
        co = parse_dt(body["check_out"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400, "Invalid dates")
    if not (co.date() > ci.date()):
        err("ERR_VALIDATION", 400, "check_out must be after check_in")
    val_int(body["guest_count"], "guest_count", minimum=1)
    val_int(body["expected_listing_version"], "expected_listing_version")
    nights = (co.date() - ci.date()).days
    with LOCK:
        # Business gates (PRD §3.5 order)
        if listing["status"] != "LISTED":
            err("ERR_LISTING_NOT_LISTED", 400, "Listing not LISTED")
        # rate coverage
        for i in range(nights):
            d = ci.date() + timedelta(days=i)
            if covering_rate(lid, d) is None:
                err("ERR_NO_RATE_FOR_DATES", 400, "No rate covers %s" % d.isoformat())
        # effective min nights
        ci_rate = covering_rate(lid, ci.date())
        eff_min = listing["min_nights"]
        if ci_rate and ci_rate.get("min_nights_override") is not None:
            eff_min = ci_rate["min_nights_override"]
        if nights < eff_min:
            err("ERR_MIN_NIGHTS_NOT_MET", 400, "Stay shorter than minimum nights")
        # max guests
        if body["guest_count"] > listing["max_guests"]:
            err("ERR_MAX_GUESTS_EXCEEDED", 400, "guest_count exceeds max_guests")
        # OCC (last)
        if body["expected_listing_version"] != listing["version"]:
            err("ERR_STALE_VERSION", 412, "Stale listing version")

        booking = new_obj("Booking", {
            "listing_id": lid,
            "guest_id": guest["id"],
            "check_in": body["check_in"],
            "check_out": body["check_out"],
            "guest_count": body["guest_count"],
            "nights": nights,
            "status": "REQUESTED",
            "payment_status": "PENDING",
            "add_ons": [],
            "cleaning_fee_snapshot_cents": listing["cleaning_fee_cents"],
            "quoted_total_cents": 0,
            "final_total_cents": None,
            "refund_amount_cents": None,
        })
        booking["_ci"] = ci
        booking["_co"] = co
        booking["quoted_total_cents"] = compute_quote(booking, listing)
        touch(listing)  # increments Listing.version by 1
    return ok(public(booking), 201, "object")


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    obj = require("Booking", bid)
    return ok(public(obj), 200, "object")


@app.route("/bookings", methods=["GET"])
def list_bookings():
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    items = list(STORE["Booking"].values())
    guest_id = request.args.get("guest_id")
    listing_id = request.args.get("listing_id")
    status = request.args.get("status")
    if guest_id is not None:
        items = [o for o in items if o["guest_id"] == guest_id]
    if listing_id is not None:
        items = [o for o in items if o["listing_id"] == listing_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items)


@app.route("/bookings/<bid>/add-ons", methods=["POST"])
def attach_addon(bid):
    authenticate()
    require_role({"Guest"})
    booking = require("Booking", bid)
    ensure_owner(booking["guest_id"] == g.user_id)
    body = get_body()
    require_fields(body, ["add_on_id"])
    addon = require("AddOn", body["add_on_id"])
    slot_id = body.get("experience_slot_id")
    slot = None
    if slot_id is not None:
        slot = require("ExperienceSlot", slot_id)
    participant_count = body.get("participant_count")
    if participant_count is not None:
        val_int(participant_count, "participant_count", minimum=1)
    with LOCK:
        if booking["status"] != "REQUESTED":
            err("ERR_INVALID_STATE", 400, "Booking not REQUESTED")
        listing = get("Listing", booking["listing_id"])
        # ERR_ADDON_NOT_OFFERED: add-on belongs to booking's listing AND ACTIVE
        if addon["listing_id"] != booking["listing_id"] or addon["status"] != "ACTIVE":
            err("ERR_ADDON_NOT_OFFERED", 400, "Add-on not offered/active")
        # ERR_ADDON_LISTING_MISMATCH: referenced slot belongs to referenced add-on
        if slot is not None and slot["add_on_id"] != addon["id"]:
            err("ERR_ADDON_LISTING_MISMATCH", 400, "Slot does not belong to add-on")
        # ERR_EXPERIENCE_SLOT_REQUIRED
        if addon["category"] == "EXPERIENCE" and slot is None:
            err("ERR_EXPERIENCE_SLOT_REQUIRED", 400, "Experience line requires a slot")
        if addon["category"] == "AMENITY" and slot is not None:
            err("ERR_EXPERIENCE_SLOT_REQUIRED", 400, "Amenity line must not supply a slot")
        pcount = participant_count if participant_count is not None else 1
        if slot is not None:
            # ERR_SLOT_DATE_OUT_OF_RANGE
            sd = slot["_slot_dt"].date()
            if not (booking["_ci"].date() <= sd < booking["_co"].date()):
                err("ERR_SLOT_DATE_OUT_OF_RANGE", 400, "Slot date outside stay window")
            # ERR_SLOT_CAPACITY_EXCEEDED
            if slot_reserved(slot["id"]) + pcount > slot["max_participants"]:
                err("ERR_SLOT_CAPACITY_EXCEEDED", 409, "Slot capacity exceeded")
        # Build the line
        line_price = addon["price_cents"]
        lt = line_total_for(line_price, addon["pricing_unit"], booking["nights"],
                            booking["guest_count"])
        line = {
            "add_on_id": addon["id"],
            "experience_slot_id": slot["id"] if slot is not None else None,
            "participant_count": pcount if slot is not None else None,
            "unit_price_snapshot_cents": line_price,
            "line_total_cents": lt,
        }
        booking["add_ons"].append(line)
        booking["quoted_total_cents"] = compute_quote(booking, listing)
        touch(booking)
        if slot is not None:
            touch(slot)
    return ok(public(booking), 200, "object")


@app.route("/bookings/<bid>/accept", methods=["POST"])
def accept_booking(bid):
    authenticate()
    require_role({"Host"})
    booking = require("Booking", bid)
    listing = listing_of_booking(booking)
    ensure_owner(owns_listing(listing))
    with LOCK:
        if booking["status"] != "REQUESTED":
            err("ERR_INVALID_STATE", 400, "Booking not REQUESTED")
        if listing["status"] != "LISTED":
            err("ERR_LISTING_NOT_LISTED", 400, "Listing not LISTED")
        # overlap with CONFIRMED/CHECKED_IN bookings on the listing
        for other in STORE["Booking"].values():
            if other["id"] == bid or other["listing_id"] != listing["id"]:
                continue
            if other["status"] in ("CONFIRMED", "CHECKED_IN"):
                if booking["_ci"].date() < other["_co"].date() and \
                        other["_ci"].date() < booking["_co"].date():
                    err("ERR_DATES_UNAVAILABLE", 409, "Dates overlap existing booking")
        comp = compute_final(booking, listing)
        booking["_locked"] = comp
        booking["final_total_cents"] = comp["final_total"]
        booking["status"] = "CONFIRMED"
        touch(booking)
        payout = new_obj("Payout", {
            "booking_id": bid,
            "estimated_amount_cents": comp["estimated"],
            "final_amount_cents": None,
            "status": "SCHEDULED",
        })
        host = get("Host", listing["host_id"])
        if host:
            touch(host)  # pending_payout_cents changed
        touch(listing)  # reserved_nights_count changed
    return ok(public(booking), 200, "object")


@app.route("/bookings/<bid>/decline", methods=["POST"])
def decline_booking(bid):
    authenticate()
    require_role({"Host"})
    booking = require("Booking", bid)
    listing = listing_of_booking(booking)
    ensure_owner(owns_listing(listing))
    with LOCK:
        if booking["status"] != "REQUESTED":
            err("ERR_INVALID_STATE", 400, "Booking not REQUESTED")
        booking["status"] = "DECLINED"
        touch(booking)
        _touch_booking_slots(booking)
    return ok(public(booking), 200, "object")


@app.route("/bookings/<bid>/check-in", methods=["POST"])
def checkin_booking(bid):
    authenticate()
    require_role({"Host"})
    booking = require("Booking", bid)
    listing = listing_of_booking(booking)
    ensure_owner(owns_listing(listing))
    with LOCK:
        if booking["status"] != "CONFIRMED":
            err("ERR_INVALID_STATE", 400, "Booking not CONFIRMED")
        if STATE["clock"].date() < booking["_ci"].date():
            err("ERR_CHECKIN_TOO_EARLY", 400, "Check-in before check_in date")
        booking["status"] = "CHECKED_IN"
        touch(booking)
    return ok(public(booking), 200, "object")


@app.route("/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    authenticate()
    require_role({"Host"})
    booking = require("Booking", bid)
    listing = listing_of_booking(booking)
    ensure_owner(owns_listing(listing))
    with LOCK:
        if booking["status"] != "CHECKED_IN":
            err("ERR_INVALID_STATE", 400, "Booking not CHECKED_IN")
        booking["status"] = "COMPLETED"
        booking["payment_status"] = "PAID"
        touch(booking)
        payout = _payout_for(bid)
        if payout:
            payout["final_amount_cents"] = payout["estimated_amount_cents"]
            payout["status"] = "PAID"
            touch(payout)
        host = get("Host", listing["host_id"])
        if host:
            touch(host)
        touch(listing)  # reserved_nights_count changed (leaves CHECKED_IN)
    return ok(public(booking), 200, "object")


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    authenticate()
    require_role({"Guest"})
    booking = require("Booking", bid)
    ensure_owner(booking["guest_id"] == g.user_id)
    with LOCK:
        if booking["status"] not in ("CONFIRMED", "CHECKED_IN"):
            err("ERR_BOOKING_NOT_CANCELLABLE", 400, "Booking not cancellable")
        listing = get("Listing", booking["listing_id"])
        _cancel_booking(booking, listing, force_full=False)
    return ok(public(booking), 200, "object")


def _payout_for(bid):
    for p in STORE["Payout"].values():
        if p["booking_id"] == bid:
            return p
    return None


def _cancel_booking(booking, listing, force_full):
    """Shared cancellation ledger unwind (guest cancel or delist cascade)."""
    locked = booking["_locked"]
    base = locked["discounted_nightly"] + locked["addons_subtotal"] + locked["cleaning"]
    if force_full:
        refund = base
    else:
        days_before = (booking["_ci"].date() - STATE["clock"].date()).days
        pct = refund_fraction(listing["cancellation_policy"], days_before)
        refund = rhu(Decimal(base) * pct)
    booking["refund_amount_cents"] = refund
    booking["status"] = "CANCELLED"
    # payment_status parallel dimension
    if refund == base:
        booking["payment_status"] = "REFUNDED"
    elif refund > 0:
        booking["payment_status"] = "PARTIALLY_REFUNDED"
    # host retained / payout settlement
    host_retained_gross = base - refund
    host_fee_on_retained = rhu(Decimal(host_retained_gross) * HOST_FEE_RATE)
    payout_on_cancel = host_retained_gross - host_fee_on_retained
    payout = _payout_for(booking["id"])
    if payout:
        payout["final_amount_cents"] = payout_on_cancel
        payout["status"] = "VOIDED" if payout_on_cancel == 0 else "PARTIAL"
        touch(payout)
    touch(booking)
    guest = get("Guest", booking["guest_id"])
    if guest:
        touch(guest)  # wallet_credit_cents changed
    if listing:
        host = get("Host", listing["host_id"])
        if host:
            touch(host)
        touch(listing)  # reserved_nights_count changed


# --- Payout ---
@app.route("/bookings/<bid>/payout", methods=["GET"])
def get_payout(bid):
    authenticate()
    require_role({"Host", "PlatformAdmin"})
    require("Booking", bid)
    items = [p for p in STORE["Payout"].values() if p["booking_id"] == bid]
    return list_response(items)


# --- Review ---
@app.route("/bookings/<bid>/reviews", methods=["POST"])
def create_review(bid):
    authenticate()
    require_role({"Guest"})
    booking = require("Booking", bid)
    ensure_owner(booking["guest_id"] == g.user_id)
    body = get_body()
    require_fields(body, ["rating"])
    rating = body["rating"]
    if isinstance(rating, bool) or not isinstance(rating, int) or rating < 1 or rating > 5:
        err("ERR_VALIDATION", 400, "rating must be 1..5")
    with LOCK:
        if booking["status"] != "COMPLETED":
            err("ERR_REVIEW_NOT_ALLOWED", 400, "Booking not COMPLETED")
        if any(r["booking_id"] == bid for r in STORE["Review"].values()):
            err("ERR_DUPLICATE_REVIEW", 409, "Review already exists")
        obj = new_obj("Review", {
            "booking_id": bid,
            "rating": rating,
            "comment": body.get("comment"),
        }, common=False)
    return ok(public(obj), 201, "object")


@app.route("/bookings/<bid>/reviews", methods=["GET"])
def list_reviews(bid):
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    require("Booking", bid)
    items = [r for r in STORE["Review"].values() if r["booking_id"] == bid]
    return list_response(items)


# --- Message ---
@app.route("/bookings/<bid>/messages", methods=["POST"])
def create_message(bid):
    authenticate()
    require_role({"Host", "Guest"})
    booking = require("Booking", bid)
    # ownership: sender must be a party to the booking
    if g.role == "Guest":
        ensure_owner(booking["guest_id"] == g.user_id)
    else:  # Host
        listing = get("Listing", booking["listing_id"])
        ensure_owner(listing is not None and listing["host_id"] == g.user_id)
    body = get_body()
    require_fields(body, ["sender_role", "body"])
    val_enum(body["sender_role"], SENDER_ROLES, "sender_role")
    with LOCK:
        obj = new_obj("Message", {
            "booking_id": bid,
            "sender_role": body["sender_role"],
            "sender_id": g.user_id,
            "body": body["body"],
        }, common=False)
    return ok(public(obj), 201, "object")


@app.route("/bookings/<bid>/messages", methods=["GET"])
def list_messages(bid):
    authenticate()
    require_role({"Host", "Guest", "PlatformAdmin"})
    require("Booking", bid)
    items = [m for m in STORE["Message"].values() if m["booking_id"] == bid]
    return list_response(items)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


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
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
