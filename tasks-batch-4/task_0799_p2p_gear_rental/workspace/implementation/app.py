import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD.yaml / PRD)
# ---------------------------------------------------------------------------
VERIFICATION_VALIDITY_DAYS = 365
HIGH_VALUE_THRESHOLD_CENTS = 100000
MIN_TRUST_FOR_HIGH_VALUE = 300
HANDOFF_BUFFER_MINUTES = 60
WEEKEND_SURCHARGE_BPS = 2000
WEEKLY_DISCOUNT_BPS = 1000
MONTHLY_DISCOUNT_BPS = 2500
RENTER_SERVICE_FEE_BPS = 1200
OWNER_COMMISSION_BPS = 1500
LATE_PENALTY_BPS = 15000
BASE_TRUST = 300
RATING_POINTS_PER_STAR = 40
LATE_PENALTY_POINTS = 25
CLAIM_PENALTY_POINTS = 40

KNOWN_ROLES = {"Anonymous", "Renter", "Owner", "Platform"}
AVAIL_STATES = {"REQUESTED", "APPROVED", "ACTIVE", "EXTENSION_REQUESTED", "LATE"}

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory storage (wiped on every process start — no seeding)
# ---------------------------------------------------------------------------
users = {}
verifications = {}
listings = {}
bookings = {}
handoffs = {}
condition_reports = {}
deposits = {}
claims = {}
payouts = {}
ratings = {}

_seq_counter = 0
CLOCK = DEFAULT_CLOCK


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


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
def now_str():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def whole_days(start_dt, end_dt):
    return int((end_dt - start_dt).total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def rhu(x):
    """round half up a Decimal to a whole integer."""
    return int(Decimal(x).to_integral_value(rounding=ROUND_HALF_UP))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# Response envelope helpers
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_str()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total):
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    return (
        jsonify({"meta": _meta(pag), "response_type": "array", "data": items}),
        200,
    )


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
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers.")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation.")


def forbidden():
    raise ApiError("ERR_FORBIDDEN", 403, "Not permitted for this resource.")


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")
    return b


def invalid(msg="Invalid request."):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------
def new_entity(store, fields, versioned=True):
    now = now_str()
    e = {"id": str(uuid.uuid4())}
    e.update(fields)
    e["created_at"] = now
    if versioned:
        e["updated_at"] = now
        e["version"] = 1
    e["_seq"] = next_seq()
    store[e["id"]] = e
    return e


def touch(e):
    if "version" in e:
        e["version"] += 1
        e["updated_at"] = now_str()


def serialize(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def sort_seq(items):
    return sorted(items, key=lambda x: x["_seq"])


def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            invalid("limit must be an integer.")
        if limit < 1 or limit > 100:
            invalid("limit out of range.")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            invalid("offset must be an integer.")
        if offset < 0:
            invalid("offset must be >= 0.")
    return limit, offset


def paged_response(all_items):
    limit, offset = get_pagination()
    ordered = sort_seq(all_items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serialize(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_or_404(store, oid):
    e = store.get(oid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found.")
    return e


def deposit_for_booking(bid):
    for d in deposits.values():
        if d["booking_id"] == bid:
            return d
    return None


def payout_for_booking(bid):
    for p in payouts.values():
        if p["booking_id"] == bid:
            return p
    return None


def claims_for_booking(bid):
    return [c for c in claims.values() if c["booking_id"] == bid]


# ---------------------------------------------------------------------------
# Computed user fields
# ---------------------------------------------------------------------------
def compute_avg_rating(uid):
    scores = [r["score"] for r in ratings.values() if r["ratee_id"] == uid]
    if not scores:
        return None, 0
    return sum(scores) / len(scores), len(scores)


def compute_late_return_count(uid):
    return sum(1 for b in bookings.values() if b["renter_id"] == uid and b.get("_was_late"))


def compute_upheld_claim_count(uid):
    count = 0
    for c in claims.values():
        if c["status"] in ("APPROVED", "PARTIALLY_APPROVED"):
            bk = bookings.get(c["booking_id"])
            if bk and bk["renter_id"] == uid:
                count += 1
    return count


def compute_total_earnings(uid):
    return sum(
        p["net_payout_cents"]
        for p in payouts.values()
        if p["owner_id"] == uid and p["status"] == "RELEASED"
    )


def compute_trust_score(uid):
    avg, count = compute_avg_rating(uid)
    late = compute_late_return_count(uid)
    upheld = compute_upheld_claim_count(uid)
    if count > 0:
        rating_term = rhu(Decimal(RATING_POINTS_PER_STAR) * (Decimal(str(avg)) - Decimal("3.0")))
    else:
        rating_term = 0
    raw = BASE_TRUST + rating_term - LATE_PENALTY_POINTS * late - CLAIM_PENALTY_POINTS * upheld
    return max(0, min(500, int(raw)))


def user_view(u):
    avg, count = compute_avg_rating(u["id"])
    v = serialize(u)
    v["verification_status"] = u["verification_status"]
    v["trust_score"] = compute_trust_score(u["id"])
    v["avg_rating"] = avg
    v["rating_count"] = count
    v["late_return_count"] = compute_late_return_count(u["id"])
    v["upheld_claim_count"] = compute_upheld_claim_count(u["id"])
    v["total_earnings_cents"] = compute_total_earnings(u["id"])
    return v


def listing_view(l):
    v = serialize(l)
    v["active_booking_count"] = sum(
        1 for b in bookings.values()
        if b["listing_id"] == l["id"] and b["status"] in AVAIL_STATES
    )
    return v


# ---------------------------------------------------------------------------
# Pricing calculations
# ---------------------------------------------------------------------------
def price_window(listing, start_dt, end_dt):
    billable = whole_days(start_dt, end_dt)
    if billable < 0:
        billable = 0
    if billable >= 28:
        disc = MONTHLY_DISCOUNT_BPS
    elif billable >= 7:
        disc = WEEKLY_DISCOUNT_BPS
    else:
        disc = 0
    base = Decimal(listing["base_daily_rate_cents"])
    dm = Decimal(listing["demand_multiplier_bps"])
    subtotal = 0
    for i in range(billable):
        day = start_dt + timedelta(days=i)
        raw = base * dm / Decimal(10000)
        if day.weekday() in (5, 6):
            raw = raw * Decimal(10000 + WEEKEND_SURCHARGE_BPS) / Decimal(10000)
        raw = raw * Decimal(10000 - disc) / Decimal(10000)
        subtotal += rhu(raw)
    return billable, subtotal


def service_fee(subtotal):
    return rhu(Decimal(subtotal) * Decimal(RENTER_SERVICE_FEE_BPS) / Decimal(10000))


def owner_commission(gross):
    return rhu(Decimal(gross) * Decimal(OWNER_COMMISSION_BPS) / Decimal(10000))


def late_fee(base_daily_rate, late_days):
    per_day = rhu(Decimal(base_daily_rate) * Decimal(LATE_PENALTY_BPS) / Decimal(10000))
    return per_day * late_days


def apply_booking_pricing(bk, listing):
    start_dt = parse_dt(bk["start_date"])
    end_dt = parse_dt(bk["end_date"])
    billable, subtotal = price_window(listing, start_dt, end_dt)
    fee = service_fee(subtotal)
    bk["billable_days"] = billable
    bk["rental_subtotal_cents"] = subtotal
    bk["renter_service_fee_cents"] = fee
    bk["provisional_total_cents"] = subtotal + fee


def overlaps(a_start, a_end, b_start, b_end):
    # half-open [start, end); adjacency allowed
    return a_start < b_end and b_start < a_end


def count_overlapping(listing_id, start_dt, end_dt, exclude_booking_id=None):
    n = 0
    for b in bookings.values():
        if b["listing_id"] != listing_id:
            continue
        if exclude_booking_id and b["id"] == exclude_booking_id:
            continue
        if b["status"] not in AVAIL_STATES:
            continue
        bs = parse_dt(b["start_date"])
        be = parse_dt(b["end_date"])
        if overlaps(start_dt, end_dt, bs, be):
            n += 1
    return n


def recompute_payout(bid):
    p = payout_for_booking(bid)
    if not p:
        return
    dmg = 0
    for c in claims_for_booking(bid):
        if c["status"] in ("APPROVED", "PARTIALLY_APPROVED"):
            dmg += c["deposit_capture_cents"] + c["coverage_paid_cents"]
    p["damage_reimbursement_cents"] = dmg
    p["net_payout_cents"] = p["gross_earnings_cents"] - p["owner_commission_cents"] + dmg
    touch(p)


def cascade_cancel_handoffs(bid):
    for h in handoffs.values():
        if h["booking_id"] == bid and h["status"] == "SCHEDULED":
            h["status"] = "CANCELLED"
            touch(h)


# ===========================================================================
# ENDPOINTS
# ===========================================================================

# --- Users -----------------------------------------------------------------
@app.route("/users", methods=["POST"])
def create_user():
    b = body()
    email = b.get("email")
    full_name = b.get("full_name")
    phone = b.get("phone")
    if not isinstance(email, str) or not email:
        invalid("email required.")
    if not isinstance(full_name, str) or not full_name:
        invalid("full_name required.")
    if not isinstance(phone, str) or not phone:
        invalid("phone required.")
    for u in users.values():
        if u["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL", 409, "Email already in use.")
    u = new_entity(users, {
        "email": email,
        "full_name": full_name,
        "phone": phone,
        "verification_status": "UNVERIFIED",
    })
    return ok(user_view(u), 201)


@app.route("/users/<uid>", methods=["GET"])
def get_user(uid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    u = get_or_404(users, uid)
    return ok(user_view(u), 200)


@app.route("/users/<uid>/verifications", methods=["POST"])
def submit_verification(uid):
    actor, role = authenticate()
    require_role(role, {"Renter", "Owner"})
    if actor != uid:
        forbidden()
    u = get_or_404(users, uid)
    b = body()
    dtype = b.get("document_type")
    dref = b.get("document_ref")
    if dtype not in ("PASSPORT", "DRIVERS_LICENSE", "NATIONAL_ID"):
        invalid("Invalid document_type.")
    if not isinstance(dref, str) or not dref:
        invalid("document_ref required.")
    v = new_entity(verifications, {
        "user_id": uid,
        "document_type": dtype,
        "document_ref": dref,
        "status": "PENDING",
        "valid_from": None,
        "valid_until": None,
        "reject_reason": None,
        "decided_by": None,
    })
    u["verification_status"] = "PENDING"
    touch(u)
    return ok(serialize(v), 201)


@app.route("/users/<uid>/verifications", methods=["GET"])
def list_verifications(uid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    get_or_404(users, uid)
    items = [v for v in verifications.values() if v["user_id"] == uid]
    return paged_response(items)


@app.route("/verifications/<vid>/decide", methods=["POST"])
def decide_verification(vid):
    actor, role = authenticate()
    require_role(role, {"Platform"})
    v = get_or_404(verifications, vid)
    if v["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Verification is not PENDING.")
    b = body()
    decision = b.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        invalid("decision must be APPROVE or REJECT.")
    u = users.get(v["user_id"])
    if decision == "APPROVE":
        v["status"] = "APPROVED"
        v["valid_from"] = fmt_dt(CLOCK)
        v["valid_until"] = fmt_dt(CLOCK + timedelta(days=VERIFICATION_VALIDITY_DAYS))
        v["decided_by"] = actor
        touch(v)
        if u:
            u["verification_status"] = "VERIFIED"
            touch(u)
    else:
        reason = b.get("reject_reason")
        if not isinstance(reason, str) or not reason:
            invalid("reject_reason required on REJECT.")
        v["status"] = "REJECTED"
        v["reject_reason"] = reason
        v["decided_by"] = actor
        touch(v)
        if u:
            u["verification_status"] = "REJECTED"
            touch(u)
    return ok(serialize(v), 200)


# --- Listings --------------------------------------------------------------
@app.route("/listings", methods=["POST"])
def create_listing():
    actor, role = authenticate()
    require_role(role, {"Owner"})
    b = body()
    owner_id = b.get("owner_id")
    if owner_id is not None and owner_id != actor:
        forbidden()
    if owner_id is None:
        invalid("owner_id required.")
    get_or_404(users, owner_id)
    title = b.get("title")
    category = b.get("category")
    declared = b.get("declared_value_cents")
    base_rate = b.get("base_daily_rate_cents")
    deposit_cents = b.get("deposit_cents")
    quantity = b.get("quantity", 1)
    demand = b.get("demand_multiplier_bps", 10000)
    if not isinstance(title, str) or not title:
        invalid("title required.")
    if not isinstance(category, str) or not category:
        invalid("category required.")
    if not is_int(declared) or declared <= 0:
        invalid("declared_value_cents must be > 0.")
    if not is_int(base_rate) or base_rate <= 0:
        invalid("base_daily_rate_cents must be > 0.")
    if not is_int(deposit_cents) or deposit_cents < 0:
        invalid("deposit_cents must be >= 0.")
    if not is_int(quantity) or quantity < 1:
        invalid("quantity must be >= 1.")
    if not is_int(demand) or demand < 5000 or demand > 30000:
        invalid("demand_multiplier_bps out of range.")
    l = new_entity(listings, {
        "owner_id": owner_id,
        "title": title,
        "category": category,
        "declared_value_cents": declared,
        "base_daily_rate_cents": base_rate,
        "deposit_cents": deposit_cents,
        "quantity": quantity,
        "demand_multiplier_bps": demand,
        "status": "DRAFT",
    })
    return ok(listing_view(l), 201)


@app.route("/listings/<lid>", methods=["GET"])
def get_listing(lid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    l = get_or_404(listings, lid)
    return ok(listing_view(l), 200)


@app.route("/users/<uid>/listings", methods=["GET"])
def list_user_listings(uid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    get_or_404(users, uid)
    items = [l for l in listings.values() if l["owner_id"] == uid]
    limit, offset = get_pagination()
    ordered = sort_seq(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([listing_view(l) for l in page], limit, offset, total)


@app.route("/listings/<lid>", methods=["PATCH"])
def patch_listing(lid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    l = get_or_404(listings, lid)
    if l["owner_id"] != actor:
        forbidden()
    b = body()
    elv = b.get("expected_listing_version")
    if is_int(elv):
        if elv != l["version"]:
            raise ApiError("ERR_STALE_LISTING_VERSION", 412, "Listing version is stale.")
    else:
        invalid("expected_listing_version required.")
    updates = {}
    if "base_daily_rate_cents" in b:
        v = b["base_daily_rate_cents"]
        if not is_int(v) or v <= 0:
            invalid("base_daily_rate_cents must be > 0.")
        updates["base_daily_rate_cents"] = v
    if "demand_multiplier_bps" in b:
        v = b["demand_multiplier_bps"]
        if not is_int(v) or v < 5000 or v > 30000:
            invalid("demand_multiplier_bps out of range.")
        updates["demand_multiplier_bps"] = v
    if "declared_value_cents" in b:
        v = b["declared_value_cents"]
        if not is_int(v) or v <= 0:
            invalid("declared_value_cents must be > 0.")
        updates["declared_value_cents"] = v
    if "deposit_cents" in b:
        v = b["deposit_cents"]
        if not is_int(v) or v < 0:
            invalid("deposit_cents must be >= 0.")
        updates["deposit_cents"] = v
    if "quantity" in b:
        v = b["quantity"]
        if not is_int(v) or v < 1:
            invalid("quantity must be >= 1.")
        updates["quantity"] = v
    l.update(updates)
    touch(l)
    return ok(listing_view(l), 200)


@app.route("/listings/<lid>/activate", methods=["POST"])
def activate_listing(lid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    l = get_or_404(listings, lid)
    if l["owner_id"] != actor:
        forbidden()
    if l["status"] not in ("DRAFT", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Listing cannot be activated from its current state.")
    l["status"] = "ACTIVE"
    touch(l)
    return ok(listing_view(l), 200)


@app.route("/listings/<lid>/suspend", methods=["POST"])
def suspend_listing(lid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    l = get_or_404(listings, lid)
    if l["owner_id"] != actor:
        forbidden()
    if l["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Listing must be ACTIVE to suspend.")
    l["status"] = "SUSPENDED"
    touch(l)
    return ok(listing_view(l), 200)


# --- Bookings --------------------------------------------------------------
@app.route("/bookings", methods=["POST"])
def create_booking():
    actor, role = authenticate()
    require_role(role, {"Renter"})
    b = body()
    renter_id = b.get("renter_id")
    listing_id = b.get("listing_id")
    if renter_id is not None and renter_id != actor:
        forbidden()
    # existence
    if listing_id is None:
        invalid("listing_id required.")
    l = get_or_404(listings, listing_id)
    if renter_id is None:
        invalid("renter_id required.")
    renter = get_or_404(users, renter_id)
    # referenced-entity state
    if l["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "Listing is not ACTIVE.")
    # renter verification
    if renter["verification_status"] != "VERIFIED":
        raise ApiError("ERR_RENTER_NOT_VERIFIED", 409, "Renter is not VERIFIED.")
    # parse window
    start_raw = b.get("start_date")
    end_raw = b.get("end_date")
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if start_dt is None or end_dt is None:
        invalid("start_date and end_date must be valid datetimes.")
    # availability
    if count_overlapping(listing_id, start_dt, end_dt) >= l["quantity"]:
        raise ApiError("ERR_LISTING_UNAVAILABLE", 409, "Listing unavailable for the requested window.")
    # trust gate
    if l["declared_value_cents"] > HIGH_VALUE_THRESHOLD_CENTS:
        if compute_trust_score(renter_id) < MIN_TRUST_FOR_HIGH_VALUE:
            raise ApiError("ERR_TRUST_TOO_LOW", 422, "Renter trust score too low for high-value item.")
    # OCC
    elv = b.get("expected_listing_version")
    if is_int(elv):
        if elv != l["version"]:
            raise ApiError("ERR_STALE_LISTING_VERSION", 412, "Listing version is stale.")
    else:
        invalid("expected_listing_version required.")
    # well-formedness of window
    if end_dt <= start_dt:
        invalid("end_date must be strictly after start_date.")
    bk = new_entity(bookings, {
        "listing_id": listing_id,
        "renter_id": renter_id,
        "start_date": fmt_dt(start_dt),
        "end_date": fmt_dt(end_dt),
        "expected_listing_version": elv,
        "status": "REQUESTED",
        "billable_days": None,
        "rental_subtotal_cents": None,
        "renter_service_fee_cents": None,
        "provisional_total_cents": None,
        "final_total_cents": None,
        "late_days": 0,
        "late_fee_cents": 0,
        "extension_requested_end_date": None,
        "actual_return_at": None,
    })
    apply_booking_pricing(bk, l)
    touch(bk)  # pricing set after creation
    # side effect: listing version bump (booking consumed availability)
    touch(l)
    return ok(serialize(bk), 201)


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    bk = get_or_404(bookings, bid)
    return ok(serialize(bk), 200)


@app.route("/bookings", methods=["GET"])
def list_bookings():
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    items = list(bookings.values())
    lid = request.args.get("listing_id")
    rid = request.args.get("renter_id")
    status = request.args.get("status")
    if lid is not None:
        items = [b for b in items if b["listing_id"] == lid]
    if rid is not None:
        items = [b for b in items if b["renter_id"] == rid]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paged_response(items)


@app.route("/bookings/<bid>/quote", methods=["GET"])
def booking_quote(bid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner"})
    bk = get_or_404(bookings, bid)
    l = listings[bk["listing_id"]]
    start_dt = parse_dt(bk["start_date"])
    end_dt = parse_dt(bk["end_date"])
    billable, subtotal = price_window(l, start_dt, end_dt)
    fee = service_fee(subtotal)
    data = {
        "billable_days": billable,
        "rental_subtotal_cents": subtotal,
        "renter_service_fee_cents": fee,
        "provisional_total_cents": subtotal + fee,
        "deposit_cents": l["deposit_cents"],
    }
    return ok(data, 200)


def _owner_of_booking(bk):
    return listings[bk["listing_id"]]["owner_id"]


@app.route("/bookings/<bid>/approve", methods=["POST"])
def approve_booking(bid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    bk = get_or_404(bookings, bid)
    l = listings[bk["listing_id"]]
    if l["owner_id"] != actor:
        forbidden()
    if bk["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not REQUESTED.")
    if l["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "Listing is not ACTIVE.")
    bk["status"] = "APPROVED"
    touch(bk)
    new_entity(deposits, {
        "booking_id": bid,
        "original_amount_cents": l["deposit_cents"],
        "held_cents": l["deposit_cents"],
        "captured_cents": 0,
        "released_cents": 0,
        "status": "HELD",
    })
    return ok(serialize(bk), 200)


@app.route("/bookings/<bid>/decline", methods=["POST"])
def decline_booking(bid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    bk = get_or_404(bookings, bid)
    l = listings[bk["listing_id"]]
    if l["owner_id"] != actor:
        forbidden()
    if bk["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not REQUESTED.")
    bk["status"] = "DECLINED"
    touch(bk)
    cascade_cancel_handoffs(bid)
    return ok(serialize(bk), 200)


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    actor, role = authenticate()
    require_role(role, {"Renter"})
    bk = get_or_404(bookings, bid)
    if bk["renter_id"] != actor:
        forbidden()
    if bk["status"] not in ("REQUESTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Booking cannot be cancelled from its current state.")
    was_approved = bk["status"] == "APPROVED"
    bk["status"] = "CANCELLED"
    touch(bk)
    if was_approved:
        d = deposit_for_booking(bid)
        if d and d["held_cents"] > 0:
            d["released_cents"] += d["held_cents"]
            d["held_cents"] = 0
            d["status"] = "RELEASED"
            touch(d)
    cascade_cancel_handoffs(bid)
    return ok(serialize(bk), 200)


@app.route("/bookings/<bid>/pickup", methods=["POST"])
def pickup_booking(bid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    bk = get_or_404(bookings, bid)
    l = listings[bk["listing_id"]]
    if l["owner_id"] != actor:
        forbidden()
    if bk["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not APPROVED.")
    renter = users.get(bk["renter_id"])
    if not renter or renter["verification_status"] != "VERIFIED":
        raise ApiError("ERR_RENTER_NOT_VERIFIED", 409, "Renter is not VERIFIED.")
    if not any(cr["booking_id"] == bid and cr["phase"] == "PICKUP" and cr["photo_urls"]
               for cr in condition_reports.values()):
        raise ApiError("ERR_CONDITION_PHOTOS_REQUIRED", 422, "PICKUP condition photos required.")
    if not any(h["booking_id"] == bid and h["type"] == "PICKUP" and h["status"] == "COMPLETED"
               for h in handoffs.values()):
        raise ApiError("ERR_HANDOFF_MISSING", 409, "Completed PICKUP handoff required.")
    bk["status"] = "ACTIVE"
    touch(bk)
    return ok(serialize(bk), 200)


@app.route("/bookings/<bid>/return", methods=["POST"])
def return_booking(bid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    bk = get_or_404(bookings, bid)
    l = listings[bk["listing_id"]]
    if l["owner_id"] != actor:
        forbidden()
    if bk["status"] not in ("ACTIVE", "LATE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not ACTIVE or LATE.")
    if not any(cr["booking_id"] == bid and cr["phase"] == "RETURN" and cr["photo_urls"]
               for cr in condition_reports.values()):
        raise ApiError("ERR_CONDITION_PHOTOS_REQUIRED", 422, "RETURN condition photos required.")
    if not any(h["booking_id"] == bid and h["type"] == "RETURN" and h["status"] == "COMPLETED"
               for h in handoffs.values()):
        raise ApiError("ERR_HANDOFF_MISSING", 409, "Completed RETURN handoff required.")
    bk["status"] = "RETURNED"
    bk["actual_return_at"] = fmt_dt(CLOCK)
    bk["final_total_cents"] = (
        bk["rental_subtotal_cents"] + bk["renter_service_fee_cents"] + bk["late_fee_cents"]
    )
    touch(bk)
    gross = bk["rental_subtotal_cents"]
    commission = owner_commission(gross)
    new_entity(payouts, {
        "booking_id": bid,
        "owner_id": l["owner_id"],
        "gross_earnings_cents": gross,
        "owner_commission_cents": commission,
        "damage_reimbursement_cents": 0,
        "net_payout_cents": gross - commission,
        "status": "PENDING",
    })
    return ok(serialize(bk), 200)


@app.route("/bookings/<bid>/extensions", methods=["POST"])
def request_extension(bid):
    actor, role = authenticate()
    require_role(role, {"Renter"})
    bk = get_or_404(bookings, bid)
    if bk["renter_id"] != actor:
        forbidden()
    if bk["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not ACTIVE.")
    b = body()
    new_end_raw = b.get("new_end_date")
    new_end_dt = parse_dt(new_end_raw)
    if new_end_dt is None:
        invalid("new_end_date must be a valid datetime.")
    cur_end = parse_dt(bk["end_date"])
    l = listings[bk["listing_id"]]
    # availability over extension window [current_end, new_end)
    if count_overlapping(l["id"], cur_end, new_end_dt, exclude_booking_id=bid) >= l["quantity"]:
        raise ApiError("ERR_LISTING_UNAVAILABLE", 409, "Listing unavailable for the extension window.")
    if new_end_dt <= cur_end:
        raise ApiError("ERR_EXTENSION_WINDOW_INVALID", 422, "new_end_date must be after current end_date.")
    bk["status"] = "EXTENSION_REQUESTED"
    bk["extension_requested_end_date"] = fmt_dt(new_end_dt)
    touch(bk)
    return ok(serialize(bk), 200)


@app.route("/bookings/<bid>/extension-decision", methods=["POST"])
def decide_extension(bid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    bk = get_or_404(bookings, bid)
    l = listings[bk["listing_id"]]
    if l["owner_id"] != actor:
        forbidden()
    if bk["status"] != "EXTENSION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not EXTENSION_REQUESTED.")
    b = body()
    decision = b.get("decision")
    if decision not in ("APPROVE", "DECLINE"):
        invalid("decision must be APPROVE or DECLINE.")
    if decision == "APPROVE":
        bk["end_date"] = bk["extension_requested_end_date"]
        bk["extension_requested_end_date"] = None
        bk["status"] = "ACTIVE"
        apply_booking_pricing(bk, l)
        touch(bk)
        touch(l)
    else:
        bk["extension_requested_end_date"] = None
        bk["status"] = "ACTIVE"
        touch(bk)
    return ok(serialize(bk), 200)


# --- Handoffs --------------------------------------------------------------
@app.route("/bookings/<bid>/handoffs", methods=["POST"])
def create_handoff(bid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    bk = get_or_404(bookings, bid)
    l = listings[bk["listing_id"]]
    if l["owner_id"] != actor:
        forbidden()
    b = body()
    htype = b.get("type")
    if htype not in ("PICKUP", "RETURN"):
        invalid("type must be PICKUP or RETURN.")
    # state precondition depends on type
    if htype == "PICKUP":
        if bk["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", 409, "PICKUP handoff requires an APPROVED booking.")
    else:
        if bk["status"] not in ("ACTIVE", "LATE"):
            raise ApiError("ERR_INVALID_STATE", 409, "RETURN handoff requires an ACTIVE or LATE booking.")
    slot_start = parse_dt(b.get("slot_start"))
    slot_end = parse_dt(b.get("slot_end"))
    if slot_start is None or slot_end is None:
        invalid("slot_start and slot_end must be valid datetimes.")
    # buffered-overlap check against owner's other SCHEDULED handoffs
    buf = timedelta(minutes=HANDOFF_BUFFER_MINUTES)
    new_lo = slot_start - buf
    new_hi = slot_end + buf
    for h in handoffs.values():
        if h["owner_id"] != l["owner_id"] or h["status"] != "SCHEDULED":
            continue
        es = parse_dt(h["slot_start"])
        ee = parse_dt(h["slot_end"])
        # closed-interval intersection of new buffered window with existing raw slot
        if es <= new_hi and new_lo <= ee:
            raise ApiError("ERR_HANDOFF_SLOT_CONFLICT", 409, "Handoff slot conflicts with an existing appointment.")
    if slot_end <= slot_start:
        invalid("slot_end must be strictly after slot_start.")
    h = new_entity(handoffs, {
        "booking_id": bid,
        "owner_id": l["owner_id"],
        "type": htype,
        "slot_start": fmt_dt(slot_start),
        "slot_end": fmt_dt(slot_end),
        "status": "SCHEDULED",
    })
    return ok(serialize(h), 201)


@app.route("/bookings/<bid>/handoffs", methods=["GET"])
def list_booking_handoffs(bid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    get_or_404(bookings, bid)
    items = [h for h in handoffs.values() if h["booking_id"] == bid]
    return paged_response(items)


@app.route("/users/<uid>/handoffs", methods=["GET"])
def list_user_handoffs(uid):
    _, role = authenticate()
    require_role(role, {"Owner", "Platform"})
    get_or_404(users, uid)
    items = [h for h in handoffs.values() if h["owner_id"] == uid]
    return paged_response(items)


@app.route("/handoffs/<hid>/complete", methods=["POST"])
def complete_handoff(hid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    h = get_or_404(handoffs, hid)
    if h["owner_id"] != actor:
        forbidden()
    if h["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Handoff is not SCHEDULED.")
    h["status"] = "COMPLETED"
    touch(h)
    return ok(serialize(h), 200)


# --- Condition reports -----------------------------------------------------
@app.route("/bookings/<bid>/condition-reports", methods=["POST"])
def create_condition_report(bid):
    _, role = authenticate()
    require_role(role, {"Owner", "Renter"})
    get_or_404(bookings, bid)
    b = body()
    photo_urls = b.get("photo_urls")
    if not isinstance(photo_urls, list) or len(photo_urls) < 1:
        raise ApiError("ERR_CONDITION_PHOTOS_REQUIRED", 422, "At least one photo is required.")
    phase = b.get("phase")
    if phase not in ("PICKUP", "RETURN"):
        invalid("phase must be PICKUP or RETURN.")
    recorded_by = b.get("recorded_by")
    if recorded_by not in ("OWNER", "RENTER"):
        invalid("recorded_by must be OWNER or RENTER.")
    notes = b.get("notes")
    if notes is not None and not isinstance(notes, str):
        invalid("notes must be a string.")
    cr = new_entity(condition_reports, {
        "booking_id": bid,
        "phase": phase,
        "photo_urls": photo_urls,
        "recorded_by": recorded_by,
        "notes": notes,
    }, versioned=False)
    return ok(serialize(cr), 201)


@app.route("/bookings/<bid>/condition-reports", methods=["GET"])
def list_condition_reports(bid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    get_or_404(bookings, bid)
    items = [cr for cr in condition_reports.values() if cr["booking_id"] == bid]
    return paged_response(items)


# --- Claims ----------------------------------------------------------------
@app.route("/bookings/<bid>/claims", methods=["POST"])
def create_claim(bid):
    actor, role = authenticate()
    require_role(role, {"Owner"})
    bk = get_or_404(bookings, bid)
    l = listings[bk["listing_id"]]
    if l["owner_id"] != actor:
        forbidden()
    if bk["status"] not in ("RETURNED", "LATE", "COMPLETED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not in a claimable state.")
    d = deposit_for_booking(bid)
    if not d:
        raise ApiError("ERR_INVALID_STATE", 409, "No deposit exists for this booking.")
    b = body()
    claim_type = b.get("claim_type")
    if claim_type not in ("DAMAGE", "LOSS"):
        invalid("claim_type must be DAMAGE or LOSS.")
    claimed = b.get("claimed_amount_cents")
    if not is_int(claimed) or claimed <= 0:
        invalid("claimed_amount_cents must be > 0.")
    description = b.get("description")
    if not isinstance(description, str) or not description:
        invalid("description required.")
    c = new_entity(claims, {
        "booking_id": bid,
        "claim_type": claim_type,
        "claimed_amount_cents": claimed,
        "description": description,
        "status": "OPEN",
        "provisional_capture_cents": min(claimed, d["held_cents"]),
        "approved_amount_cents": None,
        "deposit_capture_cents": 0,
        "coverage_paid_cents": 0,
        "reviewed_by": None,
        "resolved_by": None,
    })
    p = payout_for_booking(bid)
    if p and p["status"] == "PENDING":
        p["status"] = "HELD"
        touch(p)
    return ok(serialize(c), 201)


@app.route("/bookings/<bid>/claims", methods=["GET"])
def list_claims(bid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    get_or_404(bookings, bid)
    items = [c for c in claims.values() if c["booking_id"] == bid]
    return paged_response(items)


@app.route("/claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    actor, role = authenticate()
    require_role(role, {"Platform"})
    c = get_or_404(claims, cid)
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not OPEN.")
    c["status"] = "UNDER_REVIEW"
    c["reviewed_by"] = actor
    touch(c)
    return ok(serialize(c), 200)


@app.route("/claims/<cid>/resolve", methods=["POST"])
def resolve_claim(cid):
    actor, role = authenticate()
    require_role(role, {"Platform"})
    c = get_or_404(claims, cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not UNDER_REVIEW.")
    bk = bookings[c["booking_id"]]
    l = listings[bk["listing_id"]]
    d = deposit_for_booking(c["booking_id"])
    b = body()
    edv = b.get("expected_deposit_version")
    # OCC
    if is_int(edv):
        if d is None or edv != d["version"]:
            raise ApiError("ERR_STALE_DEPOSIT_VERSION", 412, "Deposit version is stale.")
    # decision
    decision = b.get("decision")
    if decision not in ("APPROVE", "PARTIAL", "DENY"):
        invalid("decision must be APPROVE, PARTIAL, or DENY.")
    # award legality
    if decision == "APPROVE":
        approved = c["claimed_amount_cents"]
    elif decision == "PARTIAL":
        approved = b.get("approved_amount_cents")
        if not is_int(approved) or approved <= 0 or approved >= c["claimed_amount_cents"]:
            raise ApiError("ERR_INVALID_AWARD", 422, "Partial award must be strictly between 0 and claimed amount.")
    else:
        approved = 0
    # OCC field well-formedness (required)
    if not is_int(edv):
        invalid("expected_deposit_version required.")

    if decision == "DENY":
        c["status"] = "DENIED"
        c["approved_amount_cents"] = 0
        c["deposit_capture_cents"] = 0
        c["coverage_paid_cents"] = 0
        c["resolved_by"] = actor
        touch(c)
        # unblock payout if no other open/under_review claim and payout HELD
        others = [x for x in claims_for_booking(c["booking_id"])
                  if x["id"] != c["id"] and x["status"] in ("OPEN", "UNDER_REVIEW")]
        p = payout_for_booking(c["booking_id"])
        if not others and p and p["status"] == "HELD":
            p["status"] = "PENDING"
            touch(p)
        return ok(serialize(c), 200)

    # APPROVE or PARTIAL
    capture = min(approved, d["held_cents"])
    coverage = max(0, min(approved - capture, l["declared_value_cents"] - d["original_amount_cents"]))
    c["status"] = "APPROVED" if decision == "APPROVE" else "PARTIALLY_APPROVED"
    c["approved_amount_cents"] = approved
    c["deposit_capture_cents"] = capture
    c["coverage_paid_cents"] = coverage
    c["resolved_by"] = actor
    touch(c)
    # capture from deposit
    if capture > 0:
        d["held_cents"] -= capture
        d["captured_cents"] += capture
        if d["held_cents"] == 0:
            d["status"] = "CAPTURED"
        else:
            d["status"] = "PARTIALLY_CAPTURED"
        touch(d)
    recompute_payout(c["booking_id"])
    return ok(serialize(c), 200)


@app.route("/bookings/<bid>/deposit", methods=["GET"])
def get_deposit(bid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    get_or_404(bookings, bid)
    items = [d for d in deposits.values() if d["booking_id"] == bid]
    return paged_response(items)


# --- Payouts ---------------------------------------------------------------
@app.route("/payouts/<pid>/release", methods=["POST"])
def release_payout(pid):
    actor, role = authenticate()
    require_role(role, {"Platform", "Owner"})
    p = get_or_404(payouts, pid)
    if role == "Owner" and p["owner_id"] != actor:
        forbidden()
    if p["status"] not in ("PENDING", "HELD"):
        raise ApiError("ERR_INVALID_STATE", 409, "Payout is not PENDING or HELD.")
    bid = p["booking_id"]
    for c in claims_for_booking(bid):
        if c["status"] in ("OPEN", "UNDER_REVIEW"):
            raise ApiError("ERR_CLAIM_UNRESOLVED", 409, "Unresolved claim on the booking.")
    p["status"] = "RELEASED"
    touch(p)
    bk = bookings.get(bid)
    if bk:
        bk["status"] = "COMPLETED"
        touch(bk)
    d = deposit_for_booking(bid)
    if d and d["held_cents"] > 0:
        d["released_cents"] += d["held_cents"]
        d["held_cents"] = 0
        if d["captured_cents"] == 0:
            d["status"] = "RELEASED"
        else:
            d["status"] = "CAPTURED"
        touch(d)
    return ok(serialize(p), 200)


@app.route("/bookings/<bid>/payout", methods=["GET"])
def get_payout(bid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    get_or_404(bookings, bid)
    items = [p for p in payouts.values() if p["booking_id"] == bid]
    return paged_response(items)


@app.route("/users/<uid>/payouts", methods=["GET"])
def list_user_payouts(uid):
    _, role = authenticate()
    require_role(role, {"Owner", "Platform"})
    get_or_404(users, uid)
    items = [p for p in payouts.values() if p["owner_id"] == uid]
    return paged_response(items)


# --- Ratings ---------------------------------------------------------------
@app.route("/bookings/<bid>/ratings", methods=["POST"])
def create_rating(bid):
    actor, role = authenticate()
    require_role(role, {"Renter", "Owner"})
    bk = get_or_404(bookings, bid)
    l = listings[bk["listing_id"]]
    b = body()
    ratee_id = b.get("ratee_id")
    direction = b.get("direction")
    score = b.get("score")
    comment = b.get("comment")
    # rating eligibility: booking COMPLETED and actor is a participant
    is_participant = actor == bk["renter_id"] or actor == l["owner_id"]
    if bk["status"] != "COMPLETED" or not is_participant:
        raise ApiError("ERR_RATING_NOT_ALLOWED", 409, "Rating not allowed.")
    if direction not in ("RENTER_TO_OWNER", "OWNER_TO_RENTER"):
        invalid("Invalid direction.")
    if not is_int(score) or score < 1 or score > 5:
        invalid("score must be between 1 and 5.")
    if ratee_id is None:
        invalid("ratee_id required.")
    get_or_404(users, ratee_id)
    if comment is not None and not isinstance(comment, str):
        invalid("comment must be a string.")
    r = new_entity(ratings, {
        "booking_id": bid,
        "rater_id": actor,
        "ratee_id": ratee_id,
        "direction": direction,
        "score": score,
        "comment": comment,
    }, versioned=False)
    return ok(serialize(r), 201)


@app.route("/bookings/<bid>/ratings", methods=["GET"])
def list_booking_ratings(bid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    get_or_404(bookings, bid)
    items = [r for r in ratings.values() if r["booking_id"] == bid]
    return paged_response(items)


@app.route("/users/<uid>/ratings", methods=["GET"])
def list_user_ratings(uid):
    _, role = authenticate()
    require_role(role, {"Renter", "Owner", "Platform"})
    get_or_404(users, uid)
    items = [r for r in ratings.values() if r["rater_id"] == uid or r["ratee_id"] == uid]
    return paged_response(items)


# --- Clock & ops -----------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global CLOCK
    _, role = authenticate()
    require_role(role, {"Platform"})
    b = body()
    to_iso = b.get("to_iso8601")
    dt = parse_dt(to_iso)
    if dt is None:
        invalid("to_iso8601 must be a valid datetime.")
    CLOCK = dt
    return ok({"current_utc": fmt_dt(CLOCK)}, 200)


@app.route("/_ops/detect-late-returns", methods=["POST"])
def detect_late_returns():
    _, role = authenticate()
    require_role(role, {"Platform"})
    affected = []
    for bk in bookings.values():
        if bk["status"] != "ACTIVE":
            continue
        end_dt = parse_dt(bk["end_date"])
        if CLOCK > end_dt:
            ld = whole_days(end_dt, CLOCK)
            if ld < 0:
                ld = 0
            l = listings[bk["listing_id"]]
            bk["status"] = "LATE"
            bk["late_days"] = ld
            bk["late_fee_cents"] = late_fee(l["base_daily_rate_cents"], ld)
            bk["_was_late"] = True
            touch(bk)
            affected.append(bk)
    ordered = sort_seq(affected)
    return ok({
        "marked_late_count": len(ordered),
        "booking_ids": [b["id"] for b in ordered],
    }, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
