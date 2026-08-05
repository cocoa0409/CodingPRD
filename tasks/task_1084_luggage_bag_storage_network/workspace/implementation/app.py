"""Luggage & Bag Storage Network API (Bounce-style) — Flask reference server.

In-memory only. The store is reconstructed empty on every process boot.
"""
import os
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

import errors as E
from errors import ApiError
import store as S

app = Flask(__name__)
db = S.Store()

# Constants
OVERSIZE_THRESHOLD_CM = 150
LATE_FEE_MULTIPLIER = 2
PAYOUT_HOLD_DAYS = 2
CLAIM_WINDOW_DAYS = 3

ROLES = {"Anonymous", "Traveler", "Host", "PlatformAdmin"}

# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _meta(extra=None):
    m = {
        "api_request_id": S.request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_array(items, pagination, code=200):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), code


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _handle_404(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": E.ERR_NOT_FOUND, "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": E.ERR_NOT_FOUND, "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Request body / auth helpers
# ---------------------------------------------------------------------------

def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ApiError(E.ERR_VALIDATION, 400, "Request body must be a JSON object")
        return data
    return {}


def require_auth(allowed_roles, anonymous_ok=False):
    """Validate auth headers and role. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if anonymous_ok and not uid and not role:
        return None, "Anonymous"
    if not uid or not role:
        raise ApiError(E.ERR_MISSING_AUTH_HEADER, 401, "Missing authentication headers")
    if role not in allowed_roles:
        raise ApiError(E.ERR_INVALID_ROLE, 403, "Role not permitted for this endpoint")
    return uid, role


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(E.ERR_VALIDATION, 400, "Missing required field: %s" % f)


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(E.ERR_VALIDATION, 400, "Field must be an integer: %s" % field)
    return value


def round_half_up(numerator, denominator):
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def paginate(items):
    """items: list already sorted. Returns (page_items, pagination_meta)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError(E.ERR_INVALID_PAGINATION, 400, "Invalid limit")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError(E.ERR_INVALID_PAGINATION, 400, "Invalid offset")
    if limit < 1 or limit > 100:
        raise ApiError(E.ERR_INVALID_PAGINATION, 400, "limit out of range")
    if offset < 0:
        raise ApiError(E.ERR_INVALID_PAGINATION, 400, "offset out of range")
    total = len(items)
    window = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, meta


def sorted_by_created(entities):
    return sorted(entities, key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_or_404(coll, rid):
    ent = coll.get(rid)
    if ent is None:
        raise ApiError(E.ERR_NOT_FOUND, 404, "Resource not found")
    return ent


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        new_clock = S.parse_clock(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError(E.ERR_VALIDATION, 400, "Invalid to_iso8601")
    db.clock = new_clock
    current_date = db.current_date()
    swept = 0
    for bk in db.bookings.values():
        if bk["status"] == "STORED":
            if S.parse_date(bk["check_out_date"]) < current_date:
                bk["status"] = "OVERDUE"
                S.touch(db, bk)
                swept += 1
    return ok_object({"current_utc": S.iso(db.clock), "overdue_swept_count": swept})


# ---------------------------------------------------------------------------
# Host
# ---------------------------------------------------------------------------

@app.route("/hosts", methods=["POST"])
def create_host():
    require_auth({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["display_name", "email"])
    fee = body.get("platform_fee_bps", 2000)
    maxc = body.get("max_concurrent_bookings", 5)
    if fee is None:
        fee = 2000
    if maxc is None:
        maxc = 5
    fee = as_int(fee, "platform_fee_bps")
    maxc = as_int(maxc, "max_concurrent_bookings")
    host = S.base_fields(db)
    host.update({
        "display_name": body["display_name"],
        "email": body["email"],
        "platform_fee_bps": fee,
        "max_concurrent_bookings": maxc,
        "status": "ACTIVE",
        "pending_payout_cents": 0,
        "payout_balance_cents": 0,
        "lifetime_earnings_cents": 0,
        "rating_sum": 0,
        "rating_count": 0,
        "avg_rating": 0,
    })
    db.hosts[host["id"]] = host
    return ok_object(S.serialize(host), 201)


@app.route("/hosts/<hid>", methods=["GET"])
def get_host(hid):
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    host = get_or_404(db.hosts, hid)
    return ok_object(S.serialize(host))


@app.route("/hosts/<hid>/status", methods=["POST"])
def host_status(hid):
    require_auth({"PlatformAdmin"})
    host = get_or_404(db.hosts, hid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    if to_status not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(E.ERR_VALIDATION, 400, "Invalid to_status")
    cur = host["status"]
    if cur == "ACTIVE" and to_status == "SUSPENDED":
        host["status"] = "SUSPENDED"
        S.touch(db, host)
        _cascade_suspend_host_locations(host)
    elif cur == "SUSPENDED" and to_status == "ACTIVE":
        host["status"] = "ACTIVE"
        S.touch(db, host)
        # Locations are NOT auto-reopened.
    else:
        raise ApiError(E.ERR_INVALID_STATE, 409, "Invalid host status transition")
    return ok_object(S.serialize(host))


def _cascade_suspend_host_locations(host):
    for loc in db.locations.values():
        if loc["host_id"] == host["id"] and loc["status"] == "OPEN":
            loc["status"] = "SUSPENDED"
            S.touch(db, loc)


# ---------------------------------------------------------------------------
# Traveler
# ---------------------------------------------------------------------------

@app.route("/travelers", methods=["POST"])
def create_traveler():
    require_auth({"Anonymous", "Traveler", "Host", "PlatformAdmin"}, anonymous_ok=True)
    body = get_body()
    require_fields(body, ["email", "full_name"])
    trav = S.base_fields(db)
    trav.update({
        "email": body["email"],
        "full_name": body["full_name"],
        "status": "ACTIVE",
    })
    db.travelers[trav["id"]] = trav
    return ok_object(S.serialize(trav), 201)


@app.route("/travelers/<tid>", methods=["GET"])
def get_traveler(tid):
    require_auth({"Traveler", "PlatformAdmin"})
    trav = get_or_404(db.travelers, tid)
    return ok_object(S.serialize(trav))


# ---------------------------------------------------------------------------
# InsurancePlan
# ---------------------------------------------------------------------------

@app.route("/insurance-plans", methods=["POST"])
def create_plan():
    require_auth({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["tier", "per_bag_coverage_cents", "premium_cents_per_bag_day"])
    if body["tier"] not in ("NONE", "BASIC", "PREMIUM"):
        raise ApiError(E.ERR_VALIDATION, 400, "Invalid tier")
    cov = as_int(body["per_bag_coverage_cents"], "per_bag_coverage_cents")
    prem = as_int(body["premium_cents_per_bag_day"], "premium_cents_per_bag_day")
    plan = S.base_fields(db)
    plan.update({
        "tier": body["tier"],
        "per_bag_coverage_cents": cov,
        "premium_cents_per_bag_day": prem,
    })
    db.plans[plan["id"]] = plan
    return ok_object(S.serialize(plan), 201)


@app.route("/insurance-plans/<pid>", methods=["GET"])
def get_plan(pid):
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    plan = get_or_404(db.plans, pid)
    return ok_object(S.serialize(plan))


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

@app.route("/hosts/<hid>/locations", methods=["POST"])
def create_location(hid):
    uid, role = require_auth({"Host", "PlatformAdmin"})
    host = get_or_404(db.hosts, hid)
    if role == "Host" and uid != hid:
        raise ApiError(E.ERR_NOT_LOCATION_HOST, 403, "Host does not own this host account")
    body = get_body()
    require_fields(body, ["name", "address", "daily_bag_capacity", "oversize_capacity",
                          "per_bag_day_rate_cents", "oversize_surcharge_cents_per_day"])
    loc = S.base_fields(db)
    loc.update({
        "host_id": hid,
        "name": body["name"],
        "address": body["address"],
        "daily_bag_capacity": as_int(body["daily_bag_capacity"], "daily_bag_capacity"),
        "oversize_capacity": as_int(body["oversize_capacity"], "oversize_capacity"),
        "per_bag_day_rate_cents": as_int(body["per_bag_day_rate_cents"], "per_bag_day_rate_cents"),
        "oversize_surcharge_cents_per_day": as_int(body["oversize_surcharge_cents_per_day"],
                                                   "oversize_surcharge_cents_per_day"),
        "status": "DRAFT",
    })
    db.locations[loc["id"]] = loc
    return ok_object(S.serialize(loc), 201)


@app.route("/locations/<lid>", methods=["GET"])
def get_location(lid):
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    loc = get_or_404(db.locations, lid)
    return ok_object(S.serialize(loc))


@app.route("/hosts/<hid>/locations", methods=["GET"])
def list_host_locations(hid):
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    get_or_404(db.hosts, hid)
    status = request.args.get("status")
    items = [l for l in db.locations.values() if l["host_id"] == hid]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = sorted_by_created(items)
    window, meta = paginate(items)
    return ok_array([S.serialize(l) for l in window], meta)


@app.route("/locations/<lid>/status", methods=["POST"])
def location_status(lid):
    uid, role = require_auth({"Host", "PlatformAdmin"})
    loc = get_or_404(db.locations, lid)
    if role == "Host" and loc["host_id"] != uid:
        raise ApiError(E.ERR_NOT_LOCATION_HOST, 403, "Host does not own this location")
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    if to_status not in ("OPEN", "SUSPENDED", "CLOSED"):
        raise ApiError(E.ERR_VALIDATION, 400, "Invalid to_status")
    cur = loc["status"]
    host = db.hosts.get(loc["host_id"])
    if to_status == "OPEN":
        if cur not in ("DRAFT", "SUSPENDED"):
            raise ApiError(E.ERR_INVALID_STATE, 409, "Cannot open from state %s" % cur)
        if host is None or host["status"] != "ACTIVE":
            raise ApiError(E.ERR_HOST_SUSPENDED, 409, "Owning host is not active")
        loc["status"] = "OPEN"
    elif to_status == "SUSPENDED":
        if cur != "OPEN":
            raise ApiError(E.ERR_INVALID_STATE, 409, "Cannot suspend from state %s" % cur)
        loc["status"] = "SUSPENDED"
    else:  # CLOSED
        if cur not in ("OPEN", "SUSPENDED"):
            raise ApiError(E.ERR_INVALID_STATE, 409, "Cannot close from state %s" % cur)
        if _location_has_active_bookings(lid):
            raise ApiError(E.ERR_LOCATION_HAS_ACTIVE_BOOKINGS, 409, "Location has active bookings")
        loc["status"] = "CLOSED"
    S.touch(db, loc)
    return ok_object(S.serialize(loc))


def _location_has_active_bookings(lid):
    for bk in db.bookings.values():
        if bk["location_id"] == lid and bk["status"] in ("RESERVED", "STORED", "OVERDUE"):
            return True
    return False


# ---------------------------------------------------------------------------
# Capacity helpers (dynamic occupancy over active bookings)
# ---------------------------------------------------------------------------

CAP_ACTIVE = ("RESERVED", "STORED", "OVERDUE")


def _daily_occupancy(location_id, day, exclude_booking_id=None):
    """(total_bags, total_oversize) reserved at location on the given day."""
    total = 0
    over = 0
    for bk in db.bookings.values():
        if bk["location_id"] != location_id:
            continue
        if bk["status"] not in CAP_ACTIVE:
            continue
        if exclude_booking_id is not None and bk["id"] == exclude_booking_id:
            continue
        ci = S.parse_date(bk["check_in_date"])
        co = S.parse_date(bk["check_out_date"])
        if ci <= day < co:
            total += bk["bag_count"]
            over += bk["oversize_count"]
    return total, over


def _check_capacity(location, start, end, add_bags, add_oversize, exclude_booking_id=None):
    """Check daily then oversize capacity for [start, end). Raises on violation."""
    from datetime import timedelta
    day = start
    while day < end:
        total, _ = _daily_occupancy(location["id"], day, exclude_booking_id)
        if total + add_bags > location["daily_bag_capacity"]:
            raise ApiError(E.ERR_CAPACITY_EXCEEDED, 409, "Daily bag capacity exceeded")
        day += timedelta(days=1)
    day = start
    while day < end:
        _, over = _daily_occupancy(location["id"], day, exclude_booking_id)
        if over + add_oversize > location["oversize_capacity"]:
            raise ApiError(E.ERR_OVERSIZE_CAPACITY_EXCEEDED, 409, "Oversize capacity exceeded")
        day += timedelta(days=1)


# ---------------------------------------------------------------------------
# Pricing helpers
# ---------------------------------------------------------------------------

def _price_components(location, plan, bag_count, oversize_count, billable_days):
    base = location["per_bag_day_rate_cents"] * bag_count * billable_days
    over = location["oversize_surcharge_cents_per_day"] * oversize_count * billable_days
    ins = plan["premium_cents_per_bag_day"] * bag_count * billable_days
    return base, over, ins


def _billable_days(ci, co):
    return max(1, (co - ci).days)


def _host_active_booking_count(host_id):
    count = 0
    host_locs = {l["id"] for l in db.locations.values() if l["host_id"] == host_id}
    for bk in db.bookings.values():
        if bk["location_id"] in host_locs and bk["status"] in ("RESERVED", "STORED"):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------

@app.route("/bookings", methods=["POST"])
def create_booking():
    uid, role = require_auth({"Traveler"})
    body = get_body()
    require_fields(body, ["location_id", "traveler_id", "insurance_plan_id",
                          "check_in_date", "check_out_date", "bags", "expected_location_version"])
    bags_in = body["bags"]
    if not isinstance(bags_in, list) or len(bags_in) == 0:
        raise ApiError(E.ERR_VALIDATION, 400, "bags must be a non-empty array")
    for b in bags_in:
        if not isinstance(b, dict) or "declared_value_cents" not in b or "dimension_sum_cm" not in b:
            raise ApiError(E.ERR_VALIDATION, 400, "each bag needs declared_value_cents and dimension_sum_cm")
        as_int(b["declared_value_cents"], "declared_value_cents")
        as_int(b["dimension_sum_cm"], "dimension_sum_cm")
    expected_version = as_int(body["expected_location_version"], "expected_location_version")
    # Existence (left to right): location, traveler, plan
    location = get_or_404(db.locations, body["location_id"])
    get_or_404(db.travelers, body["traveler_id"])
    plan = get_or_404(db.plans, body["insurance_plan_id"])
    # OCC
    if expected_version != location["version"]:
        raise ApiError(E.ERR_STALE_LOCATION_VERSION, 412, "Stale location version")
    # State: location must be OPEN
    if location["status"] != "OPEN":
        raise ApiError(E.ERR_LOCATION_NOT_OPEN, 409, "Location is not OPEN")
    # Temporal
    try:
        ci = S.parse_date(body["check_in_date"])
        co = S.parse_date(body["check_out_date"])
    except (ValueError, TypeError):
        raise ApiError(E.ERR_VALIDATION, 400, "Invalid date format")
    if co <= ci:
        raise ApiError(E.ERR_INVALID_DATE_RANGE, 422, "check_out_date must be after check_in_date")
    if ci < db.current_date():
        raise ApiError(E.ERR_INVALID_DATE_RANGE, 422, "check_in_date must not be in the past")
    # Capacity
    bag_count = len(bags_in)
    oversize_count = sum(1 for b in bags_in if b["dimension_sum_cm"] >= OVERSIZE_THRESHOLD_CM)
    _check_capacity(location, ci, co, bag_count, oversize_count)
    # Host concurrency
    host = db.hosts.get(location["host_id"])
    if host is not None and _host_active_booking_count(host["id"]) >= host["max_concurrent_bookings"]:
        raise ApiError(E.ERR_HOST_CONCURRENCY_EXCEEDED, 409, "Host max concurrent bookings exceeded")
    # Create
    billable = _billable_days(ci, co)
    base, over, ins = _price_components(location, plan, bag_count, oversize_count, billable)
    booking = S.base_fields(db)
    booking.update({
        "location_id": location["id"],
        "traveler_id": body["traveler_id"],
        "insurance_plan_id": plan["id"],
        "check_in_date": body["check_in_date"],
        "check_out_date": body["check_out_date"],
        "bag_count": bag_count,
        "oversize_count": oversize_count,
        "billable_days": billable,
        "estimated_total_cents": base + over + ins,
        "final_total_cents": None,
        "overage_days": 0,
        "late_fee_cents": 0,
        "dropoff_at": None,
        "pickup_at": None,
        "status": "RESERVED",
    })
    db.bookings[booking["id"]] = booking
    for b in bags_in:
        bag = S.base_fields(db)
        dim = b["dimension_sum_cm"]
        bag.update({
            "booking_id": booking["id"],
            "declared_value_cents": b["declared_value_cents"],
            "dimension_sum_cm": dim,
            "is_oversize": dim >= OVERSIZE_THRESHOLD_CM,
            "seal_code": None,
            "drop_photo_url": None,
            "status": "AWAITING_DROP",
        })
        db.bags[bag["id"]] = bag
    # Reserve day-capacity -> bump location version
    S.touch(db, location)
    return ok_object(S.serialize(booking), 201)


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    bk = get_or_404(db.bookings, bid)
    return ok_object(S.serialize(bk))


@app.route("/bookings", methods=["GET"])
def list_bookings():
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    items = list(db.bookings.values())
    traveler_id = request.args.get("traveler_id")
    location_id = request.args.get("location_id")
    host_id = request.args.get("host_id")
    plan_id = request.args.get("insurance_plan_id")
    status = request.args.get("status")
    if traveler_id is not None:
        items = [b for b in items if b["traveler_id"] == traveler_id]
    if location_id is not None:
        items = [b for b in items if b["location_id"] == location_id]
    if host_id is not None:
        host_locs = {l["id"] for l in db.locations.values() if l["host_id"] == host_id}
        items = [b for b in items if b["location_id"] in host_locs]
    if plan_id is not None:
        items = [b for b in items if b["insurance_plan_id"] == plan_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sorted_by_created(items)
    window, meta = paginate(items)
    return ok_array([S.serialize(b) for b in window], meta)


def _booking_bags(bid):
    return [b for b in db.bags.values() if b["booking_id"] == bid]


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = require_auth({"Traveler"})
    bk = get_or_404(db.bookings, bid)
    if bk["traveler_id"] != uid:
        raise ApiError(E.ERR_NOT_BOOKING_OWNER, 403, "Traveler does not own this booking")
    if bk["status"] != "RESERVED":
        raise ApiError(E.ERR_CANCEL_NOT_ALLOWED, 409, "Booking cannot be cancelled")
    bk["status"] = "CANCELLED"
    S.touch(db, bk)
    for bag in _booking_bags(bid):
        bag["status"] = "VOIDED"
        S.touch(db, bag)
    return ok_object(S.serialize(bk))


@app.route("/bookings/<bid>/dropoff", methods=["POST"])
def dropoff_booking(bid):
    uid, role = require_auth({"Host"})
    bk = get_or_404(db.bookings, bid)
    location = db.locations.get(bk["location_id"])
    if location is None or location["host_id"] != uid:
        raise ApiError(E.ERR_NOT_LOCATION_HOST, 403, "Host does not own this booking's location")
    if bk["status"] != "RESERVED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Booking is not RESERVED")
    if location["status"] != "OPEN":
        raise ApiError(E.ERR_LOCATION_NOT_OPEN, 409, "Location is not OPEN")
    body = get_body()
    seals = body.get("seals")
    bags = sorted_by_created(_booking_bags(bid))
    _apply_seals(bags, seals, location)
    bk["status"] = "STORED"
    bk["dropoff_at"] = db.now_iso()
    S.touch(db, bk)
    return ok_object(S.serialize(bk))


def _apply_seals(bags, seals, location):
    if not isinstance(seals, list) or len(seals) != len(bags):
        raise ApiError(E.ERR_BAG_NOT_SEALED, 409, "seals must cover every bag exactly once")
    # Build mapping by bag_id when present, else positional.
    have_ids = all(isinstance(s, dict) and s.get("bag_id") for s in seals)
    mapping = {}
    if have_ids:
        by_id = {b["id"]: b for b in bags}
        for s in seals:
            bag = by_id.get(s["bag_id"])
            if bag is None:
                raise ApiError(E.ERR_BAG_NOT_SEALED, 409, "seal references unknown bag")
            mapping[bag["id"]] = s
        if len(mapping) != len(bags):
            raise ApiError(E.ERR_BAG_NOT_SEALED, 409, "seals must cover every bag exactly once")
    else:
        for bag, s in zip(bags, seals):
            if not isinstance(s, dict):
                raise ApiError(E.ERR_BAG_NOT_SEALED, 409, "malformed seal entry")
            mapping[bag["id"]] = s
    # Validate seal codes + photos non-empty, and no duplicate against other SEALED bags.
    existing = set()
    for b in db.bags.values():
        if b["status"] == "SEALED" and b["seal_code"]:
            loc = db.locations.get(db.bookings.get(b["booking_id"], {}).get("location_id"))
            if loc is not None and loc["id"] == location["id"]:
                existing.add(b["seal_code"])
    seen = set()
    for bag in bags:
        s = mapping[bag["id"]]
        code = s.get("seal_code")
        photo = s.get("photo_url")
        if not code or not photo:
            raise ApiError(E.ERR_BAG_NOT_SEALED, 409, "each seal needs a non-empty seal_code and photo_url")
        if code in existing or code in seen:
            raise ApiError(E.ERR_DUPLICATE_SEAL, 409, "duplicate seal_code at location")
        seen.add(code)
    # Commit
    for bag in bags:
        s = mapping[bag["id"]]
        bag["status"] = "SEALED"
        bag["seal_code"] = s["seal_code"]
        bag["drop_photo_url"] = s["photo_url"]
        S.touch(db, bag)


@app.route("/bookings/<bid>/pickup", methods=["POST"])
def pickup_booking(bid):
    uid, role = require_auth({"Host"})
    bk = get_or_404(db.bookings, bid)
    location = db.locations.get(bk["location_id"])
    if location is None or location["host_id"] != uid:
        raise ApiError(E.ERR_NOT_LOCATION_HOST, 403, "Host does not own this booking's location")
    if bk["status"] not in ("STORED", "OVERDUE"):
        raise ApiError(E.ERR_INVALID_STATE, 409, "Booking is not STORED or OVERDUE")
    body = get_body()
    presented = body.get("presented_seals")
    bags = sorted_by_created(_booking_bags(bid))
    if presented is not None:
        _check_presented_seals(bags, presented)
    # Final settlement
    _settle(bk, location)
    for bag in bags:
        bag["status"] = "RETRIEVED"
        S.touch(db, bag)
    bk["status"] = "COMPLETED"
    bk["pickup_at"] = db.now_iso()
    S.touch(db, bk)
    # Cascade: payout + host balances
    _create_payout(bk, location)
    return ok_object(S.serialize(bk))


def _check_presented_seals(bags, presented):
    if not isinstance(presented, list):
        raise ApiError(E.ERR_SEAL_TAMPERED, 409, "presented_seals malformed")
    by_id = {b["id"]: b for b in bags}
    codes = {b["seal_code"] for b in bags if b["seal_code"]}
    for s in presented:
        if not isinstance(s, dict):
            raise ApiError(E.ERR_SEAL_TAMPERED, 409, "presented seal malformed")
        code = s.get("seal_code")
        bag_id = s.get("bag_id")
        if bag_id is not None:
            bag = by_id.get(bag_id)
            if bag is None or bag["seal_code"] != code:
                raise ApiError(E.ERR_SEAL_TAMPERED, 409, "presented seal does not match")
        else:
            if code not in codes:
                raise ApiError(E.ERR_SEAL_TAMPERED, 409, "presented seal does not match")


def _settle(bk, location):
    plan = db.plans.get(bk["insurance_plan_id"])
    ci = S.parse_date(bk["check_in_date"])
    co = S.parse_date(bk["check_out_date"])
    pickup_date = db.current_date()
    billable = _billable_days(ci, co)
    overage_days = max(0, (pickup_date - co).days)
    base, over, ins = _price_components(location, plan, bk["bag_count"], bk["oversize_count"], billable)
    late_fee = overage_days * LATE_FEE_MULTIPLIER * location["per_bag_day_rate_cents"] * bk["bag_count"]
    bk["billable_days"] = billable
    bk["overage_days"] = overage_days
    bk["late_fee_cents"] = late_fee
    bk["final_total_cents"] = base + over + ins + late_fee
    bk["_gross_base"] = base
    bk["_gross_over"] = over
    bk["_gross_late"] = late_fee


def _create_payout(bk, location):
    host = db.hosts.get(location["host_id"])
    gross = bk["_gross_base"] + bk["_gross_over"] + bk["_gross_late"]
    fee = round_half_up(gross * host["platform_fee_bps"], 10000)
    net = gross - fee - 0
    payout = S.base_fields(db)
    payout.update({
        "host_id": host["id"],
        "booking_id": bk["id"],
        "gross_cents": gross,
        "platform_fee_cents": fee,
        "claim_deduction_cents": 0,
        "net_cents": net,
        "status": "PENDING",
    })
    db.payouts[payout["id"]] = payout
    host["pending_payout_cents"] += net
    host["lifetime_earnings_cents"] += net
    S.touch(db, host)


# ---------------------------------------------------------------------------
# Bag
# ---------------------------------------------------------------------------

@app.route("/bags/<bag_id>", methods=["GET"])
def get_bag(bag_id):
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    bag = get_or_404(db.bags, bag_id)
    return ok_object(S.serialize(bag))


@app.route("/bookings/<bid>/bags", methods=["GET"])
def list_booking_bags(bid):
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    get_or_404(db.bookings, bid)
    items = sorted_by_created(_booking_bags(bid))
    window, meta = paginate(items)
    return ok_array([S.serialize(b) for b in window], meta)


# ---------------------------------------------------------------------------
# Extension
# ---------------------------------------------------------------------------

@app.route("/bookings/<bid>/extensions", methods=["POST"])
def request_extension(bid):
    uid, role = require_auth({"Traveler"})
    bk = get_or_404(db.bookings, bid)
    if bk["traveler_id"] != uid:
        raise ApiError(E.ERR_NOT_BOOKING_OWNER, 403, "Traveler does not own this booking")
    body = get_body()
    require_fields(body, ["new_check_out_date"])
    try:
        new_co = S.parse_date(body["new_check_out_date"])
        prev_co = S.parse_date(bk["check_out_date"])
    except (ValueError, TypeError):
        raise ApiError(E.ERR_VALIDATION, 400, "Invalid date format")
    if new_co <= prev_co:
        raise ApiError(E.ERR_EXTENSION_INVALID_DATE, 422, "new_check_out_date must be after current check_out_date")
    added_days = (new_co - prev_co).days
    location = db.locations.get(bk["location_id"])
    plan = db.plans.get(bk["insurance_plan_id"])
    base, over, ins = _price_components(location, plan, bk["bag_count"], bk["oversize_count"], added_days)
    ext = S.base_fields(db)
    ext.update({
        "booking_id": bk["id"],
        "previous_check_out_date": bk["check_out_date"],
        "new_check_out_date": body["new_check_out_date"],
        "added_days": added_days,
        "added_cost_cents": base + over + ins,
        "status": "REQUESTED",
    })
    db.extensions[ext["id"]] = ext
    return ok_object(S.serialize(ext), 201)


@app.route("/extensions/<eid>/decide", methods=["POST"])
def decide_extension(eid):
    uid, role = require_auth({"Host", "PlatformAdmin"})
    ext = get_or_404(db.extensions, eid)
    bk = db.bookings.get(ext["booking_id"])
    location = db.locations.get(bk["location_id"]) if bk else None
    if role == "Host" and (location is None or location["host_id"] != uid):
        raise ApiError(E.ERR_NOT_LOCATION_HOST, 403, "Host does not own this booking's location")
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("CONFIRM", "REJECT"):
        raise ApiError(E.ERR_VALIDATION, 400, "Invalid decision")
    if ext["status"] != "REQUESTED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Extension is not REQUESTED")
    if decision == "REJECT":
        ext["status"] = "REJECTED"
        S.touch(db, ext)
        return ok_object(S.serialize(ext))
    # CONFIRM
    if bk["status"] != "STORED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Booking is not STORED")
    prev_co = S.parse_date(ext["previous_check_out_date"])
    new_co = S.parse_date(ext["new_check_out_date"])
    _check_capacity(location, prev_co, new_co, bk["bag_count"], bk["oversize_count"],
                    exclude_booking_id=bk["id"])
    # Apply
    bk["check_out_date"] = ext["new_check_out_date"]
    ci = S.parse_date(bk["check_in_date"])
    bk["billable_days"] = _billable_days(ci, new_co)
    plan = db.plans.get(bk["insurance_plan_id"])
    base, over, ins = _price_components(location, plan, bk["bag_count"], bk["oversize_count"], bk["billable_days"])
    bk["estimated_total_cents"] = base + over + ins
    S.touch(db, bk)
    ext["status"] = "CONFIRMED"
    S.touch(db, ext)
    return ok_object(S.serialize(ext))


@app.route("/bookings/<bid>/extensions", methods=["GET"])
def list_booking_extensions(bid):
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    get_or_404(db.bookings, bid)
    status = request.args.get("status")
    items = [e for e in db.extensions.values() if e["booking_id"] == bid]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sorted_by_created(items)
    window, meta = paginate(items)
    return ok_array([S.serialize(e) for e in window], meta)


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

@app.route("/bookings/<bid>/claims", methods=["POST"])
def file_claim(bid):
    uid, role = require_auth({"Traveler"})
    body = get_body()
    require_fields(body, ["bag_id", "reason", "description", "claimed_amount_cents"])
    if body["reason"] not in ("DAMAGE", "LOSS", "THEFT"):
        raise ApiError(E.ERR_VALIDATION, 400, "Invalid reason")
    claimed = as_int(body["claimed_amount_cents"], "claimed_amount_cents")
    bk = get_or_404(db.bookings, bid)
    bag = get_or_404(db.bags, body["bag_id"])
    if bag["booking_id"] != bk["id"]:
        raise ApiError(E.ERR_NOT_FOUND, 404, "Bag does not belong to booking")
    if bk["traveler_id"] != uid:
        raise ApiError(E.ERR_NOT_BOOKING_OWNER, 403, "Traveler does not own this booking")
    # Temporal: claim window (only meaningful once picked up)
    if bk["pickup_at"] is not None:
        pickup_date = S.parse_clock(bk["pickup_at"]).date()
        if (db.current_date() - pickup_date).days > CLAIM_WINDOW_DAYS:
            raise ApiError(E.ERR_CLAIM_WINDOW_CLOSED, 422, "Claim window has closed")
    # Insurance / booking-completed preconditions
    if bk["status"] != "COMPLETED":
        raise ApiError(E.ERR_BOOKING_NOT_COMPLETED, 409, "Booking is not COMPLETED")
    plan = db.plans.get(bk["insurance_plan_id"])
    if plan is None or plan["tier"] == "NONE":
        raise ApiError(E.ERR_NO_INSURANCE_COVERAGE, 409, "Booking has no insurance coverage")
    # Monetary bounds
    if claimed <= 0 or claimed > bag["declared_value_cents"]:
        raise ApiError(E.ERR_CLAIM_AMOUNT_INVALID, 422, "Invalid claimed_amount_cents")
    claim = S.base_fields(db)
    claim.update({
        "booking_id": bk["id"],
        "bag_id": bag["id"],
        "reason": body["reason"],
        "description": body["description"],
        "claimed_amount_cents": claimed,
        "approved_amount_cents": None,
        "status": "OPEN",
    })
    db.claims[claim["id"]] = claim
    return ok_object(S.serialize(claim), 201)


@app.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    claim = get_or_404(db.claims, cid)
    return ok_object(S.serialize(claim))


@app.route("/claims", methods=["GET"])
def list_claims():
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    items = list(db.claims.values())
    booking_id = request.args.get("booking_id")
    bag_id = request.args.get("bag_id")
    status = request.args.get("status")
    if booking_id is not None:
        items = [c for c in items if c["booking_id"] == booking_id]
    if bag_id is not None:
        items = [c for c in items if c["bag_id"] == bag_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_created(items)
    window, meta = paginate(items)
    return ok_array([S.serialize(c) for c in window], meta)


@app.route("/claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    require_auth({"Host", "PlatformAdmin"})
    claim = get_or_404(db.claims, cid)
    if claim["status"] != "OPEN":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Claim is not OPEN")
    claim["status"] = "UNDER_REVIEW"
    S.touch(db, claim)
    return ok_object(S.serialize(claim))


@app.route("/claims/<cid>/request-info", methods=["POST"])
def request_info_claim(cid):
    require_auth({"Host", "PlatformAdmin"})
    claim = get_or_404(db.claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Claim is not UNDER_REVIEW")
    claim["status"] = "NEEDS_INFO"
    S.touch(db, claim)
    return ok_object(S.serialize(claim))


@app.route("/claims/<cid>/resubmit", methods=["POST"])
def resubmit_claim(cid):
    uid, role = require_auth({"Traveler"})
    claim = get_or_404(db.claims, cid)
    bk = db.bookings.get(claim["booking_id"])
    if bk is None or bk["traveler_id"] != uid:
        raise ApiError(E.ERR_NOT_BOOKING_OWNER, 403, "Traveler does not own this claim")
    if claim["status"] != "NEEDS_INFO":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Claim is not NEEDS_INFO")
    claim["status"] = "UNDER_REVIEW"
    S.touch(db, claim)
    return ok_object(S.serialize(claim))


@app.route("/claims/<cid>/decide", methods=["POST"])
def decide_claim(cid):
    require_auth({"PlatformAdmin"})
    claim = get_or_404(db.claims, cid)
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError(E.ERR_VALIDATION, 400, "Invalid decision")
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Claim is not UNDER_REVIEW")
    if decision == "REJECT":
        claim["status"] = "REJECTED"
        S.touch(db, claim)
        return ok_object(S.serialize(claim))
    # APPROVE
    require_fields(body, ["approved_amount_cents"])
    approved = as_int(body["approved_amount_cents"], "approved_amount_cents")
    bk = db.bookings.get(claim["booking_id"])
    bag = db.bags.get(claim["bag_id"])
    plan = db.plans.get(bk["insurance_plan_id"])
    cap = min(plan["per_bag_coverage_cents"], bag["declared_value_cents"], claim["claimed_amount_cents"])
    if approved <= 0:
        raise ApiError(E.ERR_VALIDATION, 400, "approved_amount_cents must be positive")
    if approved > cap:
        raise ApiError(E.ERR_COVERAGE_CAP_EXCEEDED, 422, "approved_amount_cents exceeds coverage cap")
    claim["approved_amount_cents"] = approved
    claim["status"] = "APPROVED"
    S.touch(db, claim)
    _cascade_claim_approval(claim, approved)
    return ok_object(S.serialize(claim))


def _cascade_claim_approval(claim, approved):
    # Hop 1: payout for the claim's booking
    for payout in db.payouts.values():
        if payout["booking_id"] == claim["booking_id"]:
            payout["claim_deduction_cents"] += approved
            payout["net_cents"] = (payout["gross_cents"] - payout["platform_fee_cents"]
                                   - payout["claim_deduction_cents"])
            S.touch(db, payout)
            host = db.hosts.get(payout["host_id"])
            # Hop 2: host pending balance
            if host is not None:
                host["pending_payout_cents"] -= approved
                S.touch(db, host)
                if host["pending_payout_cents"] < 0 and host["status"] == "ACTIVE":
                    host["status"] = "SUSPENDED"
                    S.touch(db, host)
                    # Hop 3: suspend OPEN locations
                    _cascade_suspend_host_locations(host)
            break


# ---------------------------------------------------------------------------
# Payout
# ---------------------------------------------------------------------------

@app.route("/payouts/<pid>", methods=["GET"])
def get_payout(pid):
    require_auth({"Host", "PlatformAdmin"})
    payout = get_or_404(db.payouts, pid)
    return ok_object(S.serialize(payout))


@app.route("/payouts", methods=["GET"])
def list_payouts():
    require_auth({"Host", "PlatformAdmin"})
    items = list(db.payouts.values())
    host_id = request.args.get("host_id")
    booking_id = request.args.get("booking_id")
    status = request.args.get("status")
    if host_id is not None:
        items = [p for p in items if p["host_id"] == host_id]
    if booking_id is not None:
        items = [p for p in items if p["booking_id"] == booking_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sorted_by_created(items)
    window, meta = paginate(items)
    return ok_array([S.serialize(p) for p in window], meta)


@app.route("/payouts/<pid>/release", methods=["POST"])
def release_payout(pid):
    require_auth({"PlatformAdmin"})
    payout = get_or_404(db.payouts, pid)
    if payout["status"] != "PENDING":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Payout is not PENDING")
    for claim in db.claims.values():
        if claim["booking_id"] == payout["booking_id"] and claim["status"] in ("OPEN", "UNDER_REVIEW", "NEEDS_INFO"):
            raise ApiError(E.ERR_PAYOUT_HAS_OPEN_CLAIM, 409, "Payout blocked by an open claim")
    bk = db.bookings.get(payout["booking_id"])
    pickup_date = S.parse_clock(bk["pickup_at"]).date()
    if db.current_date() < pickup_date + S.timedelta(days=PAYOUT_HOLD_DAYS):
        raise ApiError(E.ERR_PAYOUT_HELD, 409, "Payout is still held")
    payout["status"] = "RELEASED"
    S.touch(db, payout)
    host = db.hosts.get(payout["host_id"])
    if host is not None:
        host["pending_payout_cents"] -= payout["net_cents"]
        host["payout_balance_cents"] += payout["net_cents"]
        S.touch(db, host)
    return ok_object(S.serialize(payout))


@app.route("/payouts/<pid>/reverse", methods=["POST"])
def reverse_payout(pid):
    require_auth({"PlatformAdmin"})
    payout = get_or_404(db.payouts, pid)
    if payout["status"] != "RELEASED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Payout is not RELEASED")
    payout["status"] = "REVERSED"
    S.touch(db, payout)
    host = db.hosts.get(payout["host_id"])
    if host is not None:
        host["payout_balance_cents"] -= payout["net_cents"]
        S.touch(db, host)
    return ok_object(S.serialize(payout))


# ---------------------------------------------------------------------------
# Rating
# ---------------------------------------------------------------------------

@app.route("/bookings/<bid>/rating", methods=["POST"])
def create_rating(bid):
    uid, role = require_auth({"Traveler"})
    bk = get_or_404(db.bookings, bid)
    body = get_body()
    require_fields(body, ["score"])
    score = body["score"]
    if isinstance(score, bool) or not isinstance(score, int) or score < 1 or score > 5:
        raise ApiError(E.ERR_VALIDATION, 400, "score must be an integer 1..5")
    if bk["traveler_id"] != uid:
        raise ApiError(E.ERR_NOT_BOOKING_OWNER, 403, "Traveler does not own this booking")
    if bk["status"] != "COMPLETED":
        raise ApiError(E.ERR_BOOKING_NOT_COMPLETED, 409, "Booking is not COMPLETED")
    for r in db.ratings.values():
        if r["booking_id"] == bid:
            raise ApiError(E.ERR_RATING_ALREADY_EXISTS, 409, "Rating already exists for this booking")
    rating = S.base_fields(db)
    rating.update({
        "booking_id": bid,
        "score": score,
        "comment": body.get("comment"),
    })
    db.ratings[rating["id"]] = rating
    # Update host aggregates
    location = db.locations.get(bk["location_id"])
    host = db.hosts.get(location["host_id"]) if location else None
    if host is not None:
        host["rating_sum"] += score
        host["rating_count"] += 1
        host["avg_rating"] = float(
            (Decimal(host["rating_sum"]) / Decimal(host["rating_count"])).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
        S.touch(db, host)
    return ok_object(S.serialize(rating), 201)


@app.route("/bookings/<bid>/rating", methods=["GET"])
def get_rating(bid):
    require_auth({"Traveler", "Host", "PlatformAdmin"})
    get_or_404(db.bookings, bid)
    items = [r for r in db.ratings.values() if r["booking_id"] == bid]
    items = sorted_by_created(items)
    window, meta = paginate(items)
    return ok_array([S.serialize(r) for r in window], meta)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
