"""Multifamily Amenity & Resident-Experience Platform API.

In-memory Flask implementation. All state lives in module-level dicts and is
wiped on every process restart (the test harness reboots the server before each
test). No seeding / preloading of entities occurs at startup.
"""
import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ===========================================================================
# Constants
# ===========================================================================
ROLES = {"PropertyManager", "Resident", "Vendor", "FrontDesk"}

# Booking charge
PREMIUM_TIER_DISCOUNT_PCT = Decimal("0.20")
DAILY_FEE_CAP_CENTS = 20000
# Service invoice
MATERIAL_TAX_PCT = Decimal("0.07")
EMERGENCY_TRIP_FEE_CENTS = 7500
# Late cancel
LATE_CANCEL_WINDOW_HOURS = Decimal("24")
LATE_CANCEL_FORFEIT_PCT = Decimal("0.50")
# Account posture thresholds
DELINQUENCY_THRESHOLD_CENTS = 50000
SUSPENSION_THRESHOLD_CENTS = 150000
# Retention scoring
RET_BASE = 50
RET_SATISFACTION_WEIGHT = Decimal("20")
RET_ENGAGEMENT_PER_BOOKING = 3
RET_ENGAGEMENT_CAP = 30
RET_OPEN_SR_PENALTY_PER = 5
RET_OPEN_SR_PENALTY_CAP = 30
RET_NO_SHOW_PENALTY_PER = 10
RETENTION_WINDOW_DAYS = 90
# Undeclared-in-spec constants (pinned choices)
CHECK_IN_GRACE_MINUTES = 15
PACKAGE_HOLD_DAYS = 7

OPEN_SR_STATES = {"SUBMITTED", "TRIAGED", "ASSIGNED", "IN_PROGRESS"}
TRADES = {"PLUMBING", "ELECTRICAL", "HVAC", "APPLIANCE", "GENERAL"}

# ===========================================================================
# In-memory store & logical clock
# ===========================================================================
DB = {
    "properties": {},
    "units": {},
    "residents": {},
    "amenities": {},
    "bookings": {},
    "events": {},
    "registrations": {},
    "vendors": {},
    "service_requests": {},
    "ledger": {},
    "packages": {},
    "guest_passes": {},
    "surveys": {},
    "survey_responses": {},
}

CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now_wall():
    return datetime.now(timezone.utc)


def clock_now():
    return CLOCK["now"]


# ===========================================================================
# Errors
# ===========================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ===========================================================================
# Serialization helpers
# ===========================================================================
def iso3(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def serialize(obj):
    out = {}
    for k, v in obj.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso3(v)
        else:
            out[k] = v
    return out


def rhu(x):
    """Round half up to whole integer cents."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ===========================================================================
# Response envelope
# ===========================================================================
def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": iso3(now_wall())}


def ok(data, response_type="object", code=200, pagination=None):
    m = _meta()
    if pagination:
        m.update(pagination)
    return jsonify({"meta": m, "response_type": response_type, "data": data}), code


def list_response(items, total, limit, offset):
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    return ok(items, response_type="array", code=200, pagination=pag)


@app.errorhandler(ApiError)
def handle_api_error(e):
    m = _meta()
    return jsonify({
        "meta": m,
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.http_status


@app.errorhandler(404)
def handle_404(e):
    m = _meta()
    return jsonify({
        "meta": m,
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found."},
    }), 404


@app.errorhandler(405)
def handle_405(e):
    m = _meta()
    return jsonify({
        "meta": m,
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed."},
    }), 405


# ===========================================================================
# Auth / RBAC
# ===========================================================================
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint.")


def get_body():
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        return {}
    return body


# ===========================================================================
# Field/validation helpers
# ===========================================================================
def verr(msg="Validation error."):
    return ApiError("ERR_VALIDATION", 422, msg)


def require_str(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, str) or (not allow_empty and v == ""):
        raise verr(f"Field '{field}' must be a non-empty string.")
    return v


def require_int(body, field, min_val=None, max_val=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise verr(f"Field '{field}' must be an integer.")
    if min_val is not None and v < min_val:
        raise verr(f"Field '{field}' must be >= {min_val}.")
    if max_val is not None and v > max_val:
        raise verr(f"Field '{field}' must be <= {max_val}.")
    return v


def opt_int(body, field, default, min_val=None, max_val=None):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field, min_val, max_val)


def require_number(body, field, min_val=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise verr(f"Field '{field}' must be a number.")
    if min_val is not None and v < min_val:
        raise verr(f"Field '{field}' must be >= {min_val}.")
    return v


def require_enum(body, field, choices):
    v = body.get(field)
    if v not in choices:
        raise verr(f"Field '{field}' must be one of {sorted(choices)}.")
    return v


def opt_enum(body, field, choices, default):
    if field not in body or body.get(field) is None:
        return default
    return require_enum(body, field, choices)


def require_dt(body, field):
    v = body.get(field)
    try:
        return parse_dt(v)
    except Exception:
        raise verr(f"Field '{field}' must be an ISO-8601 datetime.")


# ===========================================================================
# Entity creation / common fields
# ===========================================================================
def new_common(fields, with_version=True):
    now = now_wall()
    obj = dict(fields)
    obj["id"] = str(uuid.uuid4())
    obj["created_at"] = now
    obj["_seq"] = next_seq()
    if with_version:
        obj["updated_at"] = now
        obj["version"] = 1
    return obj


def touch(obj):
    if "version" in obj:
        obj["version"] += 1
        obj["updated_at"] = now_wall()


# ===========================================================================
# Lookup helpers
# ===========================================================================
def get_or_404(store_key, rid, err_id):
    o = DB[store_key].get(rid)
    if o is None:
        raise ApiError(err_id, 404, f"{err_id}.")
    return o


def property_of_resident(resident):
    unit = DB["units"].get(resident["unit_id"])
    if unit is None:
        return None
    return DB["properties"].get(unit["property_id"])


# ===========================================================================
# Pagination
# ===========================================================================
def paginate(items):
    """items: already-filtered list. Returns (page_items_serialized, meta)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except Exception:
            raise verr("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise verr("limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except Exception:
            raise verr("offset must be an integer.")
        if offset < 0:
            raise verr("offset must be >= 0.")
    ordered = sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return [serialize(o) for o in window], limit, offset, total


# ===========================================================================
# Calculations
# ===========================================================================
def booking_charge(amenity, resident, wstart, wend):
    dur_sec = Decimal((wend - wstart).total_seconds())
    dur_hours = dur_sec / Decimal(3600)
    # minute-of-day of window start
    sm = (Decimal(wstart.hour * 60 + wstart.minute)
          + Decimal(wstart.second) / Decimal(60)
          + Decimal(wstart.microsecond) / Decimal(60_000_000))
    em = sm + dur_sec / Decimal(60)
    ps = Decimal(amenity["peak_start_minute"])
    pe = Decimal(amenity["peak_end_minute"])
    overlap_min = max(Decimal(0), min(em, pe) - max(sm, ps))
    peak_hours = overlap_min / Decimal(60)
    offpeak_hours = dur_hours - peak_hours
    mult = Decimal(str(amenity["peak_multiplier"]))
    base = Decimal(amenity["base_rate_cents_per_hour"])
    gross = rhu(base * (offpeak_hours + peak_hours * mult))
    disc = PREMIUM_TIER_DISCOUNT_PCT if resident["membership_tier"] == "PREMIUM" else Decimal(0)
    discounted = rhu(Decimal(gross) * (Decimal(1) - disc))
    return min(discounted, DAILY_FEE_CAP_CENTS)


def service_estimate(vendor, estimated_hours, estimated_parts_cents):
    labor = rhu(Decimal(vendor["hourly_rate_cents"]) * Decimal(str(estimated_hours)))
    return labor + estimated_parts_cents


def service_actual(vendor, labor_hours, parts, priority):
    labor_line = rhu(Decimal(vendor["hourly_rate_cents"]) * Decimal(str(labor_hours)))
    part_lines = [rhu(Decimal(str(p["cents"])) * (Decimal(1) + MATERIAL_TAX_PCT)) for p in parts]
    subtotal = labor_line + sum(part_lines)
    trip = EMERGENCY_TRIP_FEE_CENTS if priority == "EMERGENCY" else 0
    return subtotal + trip


def late_cancel_penalty(deposit_hold_cents, start_at):
    hours_before = (Decimal((start_at - clock_now()).total_seconds())) / Decimal(3600)
    if hours_before >= LATE_CANCEL_WINDOW_HOURS:
        return 0
    return rhu(Decimal(deposit_hold_cents) * LATE_CANCEL_FORFEIT_PCT)


# ===========================================================================
# Ledger / balance / posture
# ===========================================================================
def add_ledger(resident, entry_type, amount_cents, source_type, source_id, description):
    entry = new_common({
        "resident_id": resident["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "source_type": source_type,
        "source_id": source_id,
        "description": description,
    }, with_version=False)
    DB["ledger"][entry["id"]] = entry
    return entry


def charge(resident, amount, entry_type, source_type, source_id, description):
    resident["rent_balance_cents"] += amount
    add_ledger(resident, entry_type, amount, source_type, source_id, description)


def refund_to_wallet(resident, amount, source_type, source_id, description):
    resident["wallet_credit_cents"] += amount
    add_ledger(resident, "REFUND", -amount, source_type, source_id, description)
    touch(resident)


def apply_payment(resident, amount, payment_id, method):
    applied = min(amount, resident["rent_balance_cents"])
    resident["rent_balance_cents"] -= applied
    overflow = amount - applied
    resident["wallet_credit_cents"] += overflow
    add_ledger(resident, "PAYMENT", -amount, "Payment", payment_id,
               f"Payment via {method}")


def recompute_posture(resident):
    bal = resident["rent_balance_cents"]
    if bal > SUSPENSION_THRESHOLD_CENTS:
        new = "SUSPENDED"
    elif bal > DELINQUENCY_THRESHOLD_CENTS:
        new = "DELINQUENT"
    else:
        new = "GOOD_STANDING"
    resident["account_status"] = new
    if new in ("DELINQUENT", "SUSPENDED"):
        _cascade_suspend(resident)
    else:
        _cascade_reconfirm(resident)
    touch(resident)


def _cascade_suspend(resident):
    now = clock_now()
    for b in DB["bookings"].values():
        if b["resident_id"] != resident["id"]:
            continue
        if b["status"] == "CONFIRMED" and b["start_at"] > now:
            b["status"] = "SUSPENDED"
            resident["hold_balance_cents"] -= b["deposit_hold_cents"]
            touch(b)


def _cascade_reconfirm(resident):
    now = clock_now()
    suspended = [b for b in DB["bookings"].values()
                 if b["resident_id"] == resident["id"] and b["status"] == "SUSPENDED"
                 and b["start_at"] > now]
    suspended.sort(key=lambda b: (b["created_at"], b["_seq"]))
    for b in suspended:
        amenity = DB["amenities"].get(b["amenity_id"])
        if amenity is None:
            continue
        if not booking_conflict(amenity, b["start_at"], b["end_at"], exclude_id=b["id"]):
            b["status"] = "CONFIRMED"
            resident["hold_balance_cents"] += b["deposit_hold_cents"]
            touch(b)


# ===========================================================================
# Temporal window helpers
# ===========================================================================
def within_operating_hours(amenity, start, end):
    if start.date() != end.date():
        return False
    sm = start.hour * 60 + start.minute + start.second / 60 + start.microsecond / 60_000_000
    em = end.hour * 60 + end.minute + end.second / 60 + end.microsecond / 60_000_000
    return sm >= amenity["open_minute"] and em <= amenity["close_minute"]


def booking_conflict(amenity, new_start, new_end, exclude_id=None):
    buf = timedelta(minutes=amenity["buffer_minutes"])
    intervals = []
    for b in DB["bookings"].values():
        if b["amenity_id"] != amenity["id"]:
            continue
        if exclude_id is not None and b["id"] == exclude_id:
            continue
        if b["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        intervals.append((b["start_at"], b["end_at"] + buf))
    intervals.append((new_start, new_end + buf))
    cap = amenity["capacity"]
    starts = {s for s, _ in intervals}
    for p in starts:
        c = sum(1 for s, e in intervals if s <= p < e)
        if c > cap:
            return True
    return False


def guest_conflict(prop, new_start, new_end):
    intervals = []
    for gp in DB["guest_passes"].values():
        if gp["status"] not in ("ISSUED", "CHECKED_IN"):
            continue
        res = DB["residents"].get(gp["resident_id"])
        if res is None:
            continue
        p = property_of_resident(res)
        if p is None or p["id"] != prop["id"]:
            continue
        intervals.append((gp["arrival_at"], gp["expected_departure_at"]))
    intervals.append((new_start, new_end))
    cap = prop["guest_parking_capacity"]
    starts = {s for s, _ in intervals}
    for pt in starts:
        c = sum(1 for s, e in intervals if s <= pt < e)
        if c > cap:
            return True
    return False


# ===========================================================================
# Retention
# ===========================================================================
def resident_responses(resident_id):
    return [r for r in DB["survey_responses"].values() if r["resident_id"] == resident_id]


def open_sr_count(resident_id):
    return sum(1 for sr in DB["service_requests"].values()
               if sr["resident_id"] == resident_id and sr["status"] in OPEN_SR_STATES)


def completed_bookings_90d(resident_id):
    now = clock_now()
    window_start = now - timedelta(days=RETENTION_WINDOW_DAYS)
    cnt = 0
    for b in DB["bookings"].values():
        if b["resident_id"] != resident_id or b["status"] != "COMPLETED":
            continue
        co = b.get("checked_out_at")
        if co is not None and window_start <= co <= now:
            cnt += 1
    return cnt


def compute_retention(resident):
    responses = resident_responses(resident["id"])
    if responses:
        avg_score = Decimal(sum(r["satisfaction_score"] for r in responses)) / Decimal(len(responses))
    else:
        avg_score = Decimal("3.0")
    satisfaction = rhu((avg_score / Decimal(5)) * RET_SATISFACTION_WEIGHT)
    engagement = min(completed_bookings_90d(resident["id"]) * RET_ENGAGEMENT_PER_BOOKING,
                     RET_ENGAGEMENT_CAP)
    open_pen = min(open_sr_count(resident["id"]) * RET_OPEN_SR_PENALTY_PER,
                   RET_OPEN_SR_PENALTY_CAP)
    no_show_pen = resident["no_show_strikes"] * RET_NO_SHOW_PENALTY_PER
    score = RET_BASE + engagement + satisfaction - open_pen - no_show_pen
    score = max(0, min(100, score))
    resident["retention_score"] = score
    avg_sat = float(avg_score)
    return score, avg_sat


# ===========================================================================
# Ownership
# ===========================================================================
def check_owner_resident(role, uid, resident_id):
    if role == "Resident" and uid != resident_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Resident does not own this resource.")


def check_owner_vendor(role, uid, vendor_id):
    if role == "Vendor" and uid != vendor_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Vendor is not assigned to this resource.")


# ===========================================================================
# Properties
# ===========================================================================
@app.route("/properties", methods=["POST"])
def create_property():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    name = require_str(body, "name")
    address = require_str(body, "address")
    timezone_label = body.get("timezone", "America/New_York")
    if not isinstance(timezone_label, str) or timezone_label == "":
        timezone_label = "America/New_York"
    guest_parking_capacity = require_int(body, "guest_parking_capacity", min_val=0)
    guest_window_hours = opt_int(body, "guest_window_hours", 24, min_val=0)
    prop = new_common({
        "name": name,
        "address": address,
        "timezone": timezone_label,
        "guest_parking_capacity": guest_parking_capacity,
        "guest_window_hours": guest_window_hours,
    })
    DB["properties"][prop["id"]] = prop
    return ok(serialize(prop), code=201)


@app.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident", "FrontDesk"})
    prop = get_or_404("properties", pid, "ERR_PROPERTY_NOT_FOUND")
    return ok(serialize(prop))


@app.route("/properties", methods=["GET"])
def list_properties():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    items, limit, offset, total = paginate(list(DB["properties"].values()))
    return list_response(items, total, limit, offset)


@app.route("/properties/<pid>/report", methods=["GET"])
def property_report(pid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    prop = get_or_404("properties", pid, "ERR_PROPERTY_NOT_FOUND")
    unit_ids = {u["id"] for u in DB["units"].values() if u["property_id"] == pid}
    residents = [r for r in DB["residents"].values() if r["unit_id"] in unit_ids]
    amenity_ids = {a["id"] for a in DB["amenities"].values() if a["property_id"] == pid}
    active_bookings = sum(1 for b in DB["bookings"].values()
                          if b["amenity_id"] in amenity_ids and b["status"] in ("CONFIRMED", "CHECKED_IN"))
    open_srs = sum(1 for sr in DB["service_requests"].values()
                   if sr["unit_id"] in unit_ids and sr["status"] in OPEN_SR_STATES)
    scores = []
    for r in residents:
        s, _ = compute_retention(r)
        scores.append(s)
    if scores:
        avg_ret = rhu(Decimal(sum(scores)) / Decimal(len(scores)))
    else:
        avg_ret = 0
    data = {
        "unit_count": len(unit_ids),
        "resident_count": len(residents),
        "active_bookings": active_bookings,
        "open_service_requests": open_srs,
        "avg_retention_score": avg_ret,
    }
    return ok(data)


# ===========================================================================
# Units
# ===========================================================================
@app.route("/units", methods=["POST"])
def create_unit():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    property_id = require_str(body, "property_id")
    unit_number = require_str(body, "unit_number")
    bedrooms = require_int(body, "bedrooms", min_val=0)
    prop = get_or_404("properties", property_id, "ERR_PROPERTY_NOT_FOUND")
    for u in DB["units"].values():
        if u["property_id"] == property_id and u["unit_number"] == unit_number:
            raise verr("unit_number must be unique within the property.")
    unit = new_common({
        "property_id": property_id,
        "unit_number": unit_number,
        "bedrooms": bedrooms,
        "occupancy_status": "VACANT",
    })
    DB["units"][unit["id"]] = unit
    return ok(serialize(unit), code=201)


@app.route("/units/<uid_>", methods=["GET"])
def get_unit(uid_):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident"})
    unit = get_or_404("units", uid_, "ERR_UNIT_NOT_FOUND")
    return ok(serialize(unit))


@app.route("/units", methods=["GET"])
def list_units():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    items = list(DB["units"].values())
    pid = request.args.get("property_id")
    if pid is not None:
        items = [u for u in items if u["property_id"] == pid]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


# ===========================================================================
# Residents
# ===========================================================================
@app.route("/residents", methods=["POST"])
def create_resident():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    unit_id = require_str(body, "unit_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    membership_tier = opt_enum(body, "membership_tier", {"STANDARD", "PREMIUM"}, "STANDARD")
    unit = get_or_404("units", unit_id, "ERR_UNIT_NOT_FOUND")
    for r in DB["residents"].values():
        if r["email"] == email:
            raise verr("email must be unique across residents.")
    resident = new_common({
        "unit_id": unit_id,
        "full_name": full_name,
        "email": email,
        "membership_tier": membership_tier,
        "account_status": "GOOD_STANDING",
        "rent_balance_cents": 0,
        "hold_balance_cents": 0,
        "wallet_credit_cents": 0,
        "no_show_strikes": 0,
        "retention_score": 50,
    })
    DB["residents"][resident["id"]] = resident
    unit["occupancy_status"] = "OCCUPIED"
    touch(unit)
    return ok(serialize(resident), code=201)


@app.route("/residents/<rid>", methods=["GET"])
def get_resident(rid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident"})
    resident = get_or_404("residents", rid, "ERR_RESIDENT_NOT_FOUND")
    return ok(serialize(resident))


@app.route("/residents", methods=["GET"])
def list_residents():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    items = list(DB["residents"].values())
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        items = [r for r in items if r["unit_id"] == unit_id]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


@app.route("/residents/<rid>/ledger", methods=["GET"])
def resident_ledger(rid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident"})
    resident = get_or_404("residents", rid, "ERR_RESIDENT_NOT_FOUND")
    items = [e for e in DB["ledger"].values() if e["resident_id"] == rid]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


@app.route("/residents/<rid>/retention", methods=["GET"])
def resident_retention(rid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    resident = get_or_404("residents", rid, "ERR_RESIDENT_NOT_FOUND")
    score, avg_sat = compute_retention(resident)
    data = {
        "retention_score": score,
        "avg_satisfaction": avg_sat,
        "completed_bookings_90d": completed_bookings_90d(rid),
        "open_service_requests": open_sr_count(rid),
    }
    return ok(data)


@app.route("/residents/<rid>/rent-charges", methods=["POST"])
def create_rent_charge(rid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    amount_cents = require_int(body, "amount_cents", min_val=1)
    description = body.get("description")
    if description is not None and not isinstance(description, str):
        raise verr("description must be a string.")
    resident = get_or_404("residents", rid, "ERR_RESIDENT_NOT_FOUND")
    charge(resident, amount_cents, "RENT_CHARGE", "RentCharge", rid,
           description or "Rent charge")
    recompute_posture(resident)
    return ok(serialize(resident), code=201)


# ===========================================================================
# Payments
# ===========================================================================
@app.route("/payments", methods=["POST"])
def create_payment():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    resident_id = require_str(body, "resident_id")
    amount_cents = require_int(body, "amount_cents", min_val=1)
    method = require_str(body, "method")
    resident = get_or_404("residents", resident_id, "ERR_RESIDENT_NOT_FOUND")
    payment_id = str(uuid.uuid4())
    apply_payment(resident, amount_cents, payment_id, method)
    recompute_posture(resident)
    return ok(serialize(resident), code=201)


# ===========================================================================
# Amenities
# ===========================================================================
@app.route("/amenities", methods=["POST"])
def create_amenity():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    property_id = require_str(body, "property_id")
    name = require_str(body, "name")
    amenity_type = require_enum(body, "amenity_type", {"GYM", "POOL", "CLUBROOM"})
    capacity = require_int(body, "capacity", min_val=1)
    base_rate = require_int(body, "base_rate_cents_per_hour", min_val=0)
    deposit_cents = opt_int(body, "deposit_cents", 0, min_val=0)
    buffer_minutes = opt_int(body, "buffer_minutes", 0, min_val=0)
    open_minute = require_int(body, "open_minute", min_val=0, max_val=1440)
    close_minute = require_int(body, "close_minute", min_val=0, max_val=1440)
    if close_minute <= open_minute:
        raise verr("close_minute must be greater than open_minute.")
    peak_start_minute = opt_int(body, "peak_start_minute", 0, min_val=0, max_val=1440)
    peak_end_minute = opt_int(body, "peak_end_minute", 0, min_val=0, max_val=1440)
    peak_multiplier = body.get("peak_multiplier", 1.0)
    if peak_multiplier is None:
        peak_multiplier = 1.0
    if isinstance(peak_multiplier, bool) or not isinstance(peak_multiplier, (int, float)):
        raise verr("peak_multiplier must be a number.")
    status = opt_enum(body, "status", {"OPEN", "CLOSED", "MAINTENANCE"}, "OPEN")
    prop = get_or_404("properties", property_id, "ERR_PROPERTY_NOT_FOUND")
    amenity = new_common({
        "property_id": property_id,
        "name": name,
        "amenity_type": amenity_type,
        "capacity": capacity,
        "base_rate_cents_per_hour": base_rate,
        "deposit_cents": deposit_cents,
        "buffer_minutes": buffer_minutes,
        "open_minute": open_minute,
        "close_minute": close_minute,
        "peak_start_minute": peak_start_minute,
        "peak_end_minute": peak_end_minute,
        "peak_multiplier": peak_multiplier,
        "status": status,
    })
    DB["amenities"][amenity["id"]] = amenity
    return ok(serialize(amenity), code=201)


@app.route("/amenities/<aid>", methods=["GET"])
def get_amenity(aid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident", "FrontDesk"})
    amenity = get_or_404("amenities", aid, "ERR_AMENITY_NOT_FOUND")
    return ok(serialize(amenity))


@app.route("/amenities", methods=["GET"])
def list_amenities():
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident"})
    items = list(DB["amenities"].values())
    pid = request.args.get("property_id")
    if pid is not None:
        items = [a for a in items if a["property_id"] == pid]
    atype = request.args.get("amenity_type")
    if atype is not None:
        items = [a for a in items if a["amenity_type"] == atype]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


# ===========================================================================
# Amenity Bookings
# ===========================================================================
@app.route("/amenity-bookings", methods=["POST"])
def create_booking():
    uid, role = auth()
    authorize(role, {"Resident", "PropertyManager"})
    body = get_body()
    amenity_id = require_str(body, "amenity_id")
    resident_id = require_str(body, "resident_id")
    start_at = require_dt(body, "start_at")
    end_at = require_dt(body, "end_at")
    expected_amenity_version = require_int(body, "expected_amenity_version")
    if start_at >= end_at:
        raise verr("start_at must be before end_at.")
    # existence (left to right: amenity, resident)
    amenity = get_or_404("amenities", amenity_id, "ERR_AMENITY_NOT_FOUND")
    resident = get_or_404("residents", resident_id, "ERR_RESIDENT_NOT_FOUND")
    # ownership
    check_owner_resident(role, uid, resident_id)
    # state: amenity bookable
    if amenity["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Amenity is not OPEN for booking.")
    # posture gate
    if resident["account_status"] != "GOOD_STANDING":
        raise ApiError("ERR_ACCOUNT_DELINQUENT", 403, "Resident is not in GOOD_STANDING.")
    # temporal: operating hours
    if not within_operating_hours(amenity, start_at, end_at):
        raise ApiError("ERR_OUTSIDE_OPERATING_HOURS", 422, "Booking outside operating hours.")
    # temporal: capacity/overlap
    if booking_conflict(amenity, start_at, end_at):
        raise ApiError("ERR_BOOKING_OVERLAP", 409, "Booking exceeds amenity capacity.")
    # OCC
    if expected_amenity_version != amenity["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale amenity version.")
    # create
    deposit = amenity["deposit_cents"]
    provisional = booking_charge(amenity, resident, start_at, end_at)
    booking = new_common({
        "amenity_id": amenity_id,
        "resident_id": resident_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "CONFIRMED",
        "provisional_fee_cents": provisional,
        "final_fee_cents": None,
        "deposit_hold_cents": deposit,
        "checked_in_at": None,
        "checked_out_at": None,
    })
    DB["bookings"][booking["id"]] = booking
    resident["hold_balance_cents"] += deposit
    touch(resident)
    touch(amenity)  # version bump for OCC
    return ok(serialize(booking), code=201)


@app.route("/amenity-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident", "FrontDesk"})
    booking = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND")
    return ok(serialize(booking))


@app.route("/amenity-bookings", methods=["GET"])
def list_bookings():
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident", "FrontDesk"})
    items = list(DB["bookings"].values())
    aid = request.args.get("amenity_id")
    if aid is not None:
        items = [b for b in items if b["amenity_id"] == aid]
    rid = request.args.get("resident_id")
    if rid is not None:
        items = [b for b in items if b["resident_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


@app.route("/amenity-bookings/<bid>/check-in", methods=["POST"])
def booking_check_in(bid):
    uid, role = auth()
    authorize(role, {"FrontDesk"})
    booking = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not CONFIRMED.")
    now = clock_now()
    grace = timedelta(minutes=CHECK_IN_GRACE_MINUTES)
    if not (booking["start_at"] - grace <= now < booking["end_at"]):
        raise ApiError("ERR_INVALID_STATE", 409, "Outside check-in window.")
    booking["status"] = "CHECKED_IN"
    booking["checked_in_at"] = now
    touch(booking)
    return ok(serialize(booking))


@app.route("/amenity-bookings/<bid>/check-out", methods=["POST"])
def booking_check_out(bid):
    uid, role = auth()
    authorize(role, {"FrontDesk"})
    booking = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not CHECKED_IN.")
    now = clock_now()
    booking["checked_out_at"] = now
    amenity = DB["amenities"].get(booking["amenity_id"])
    resident = DB["residents"].get(booking["resident_id"])
    final_fee = booking_charge(amenity, resident, booking["checked_in_at"], now)
    booking["final_fee_cents"] = final_fee
    booking["status"] = "COMPLETED"
    charge(resident, final_fee, "BOOKING_FEE", "AmenityBooking", bid,
           "Amenity booking fee")
    resident["hold_balance_cents"] -= booking["deposit_hold_cents"]
    recompute_posture(resident)
    touch(booking)
    return ok(serialize(booking))


@app.route("/amenity-bookings/<bid>/cancel", methods=["POST"])
def booking_cancel(bid):
    uid, role = auth()
    authorize(role, {"Resident", "PropertyManager"})
    booking = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND")
    check_owner_resident(role, uid, booking["resident_id"])
    resident = DB["residents"].get(booking["resident_id"])
    if booking["status"] == "CONFIRMED":
        penalty = late_cancel_penalty(booking["deposit_hold_cents"], booking["start_at"])
        booking["status"] = "CANCELLED"
        if penalty > 0:
            charge(resident, penalty, "PENALTY", "AmenityBooking", bid,
                   "Late cancellation penalty")
        resident["hold_balance_cents"] -= booking["deposit_hold_cents"]
        recompute_posture(resident)
        touch(booking)
    elif booking["status"] == "SUSPENDED":
        booking["status"] = "CANCELLED"
        touch(booking)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Booking cannot be cancelled from its current state.")
    return ok(serialize(booking))


@app.route("/amenity-bookings/<bid>/mark-no-show", methods=["POST"])
def booking_mark_no_show(bid):
    uid, role = auth()
    authorize(role, {"FrontDesk", "PropertyManager"})
    booking = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not CONFIRMED.")
    now = clock_now()
    if not (now >= booking["end_at"] and booking["checked_in_at"] is None):
        raise ApiError("ERR_INVALID_STATE", 409, "Booking not eligible for no-show.")
    resident = DB["residents"].get(booking["resident_id"])
    booking["status"] = "NO_SHOW"
    deposit = booking["deposit_hold_cents"]
    charge(resident, deposit, "DEPOSIT_FORFEIT", "AmenityBooking", bid,
           "No-show deposit forfeit")
    resident["hold_balance_cents"] -= deposit
    resident["no_show_strikes"] += 1
    recompute_posture(resident)
    touch(booking)
    return ok(serialize(booking))


# ===========================================================================
# Community Events
# ===========================================================================
@app.route("/events", methods=["POST"])
def create_event():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    property_id = require_str(body, "property_id")
    amenity_id = body.get("amenity_id")
    if amenity_id is not None and not isinstance(amenity_id, str):
        raise verr("amenity_id must be a string.")
    title = require_str(body, "title")
    start_at = require_dt(body, "start_at")
    end_at = require_dt(body, "end_at")
    capacity = require_int(body, "capacity", min_val=1)
    fee_cents = opt_int(body, "fee_cents", 0, min_val=0)
    prop = get_or_404("properties", property_id, "ERR_PROPERTY_NOT_FOUND")
    if amenity_id is not None:
        get_or_404("amenities", amenity_id, "ERR_AMENITY_NOT_FOUND")
    event = new_common({
        "property_id": property_id,
        "amenity_id": amenity_id,
        "title": title,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
        "fee_cents": fee_cents,
        "status": "DRAFT",
        "reserved_count": 0,
        "waitlist_count": 0,
    })
    DB["events"][event["id"]] = event
    return ok(serialize(event), code=201)


@app.route("/events/<eid>", methods=["GET"])
def get_event(eid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident"})
    event = get_or_404("events", eid, "ERR_EVENT_NOT_FOUND")
    return ok(serialize(event))


@app.route("/events", methods=["GET"])
def list_events():
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident"})
    items = list(DB["events"].values())
    pid = request.args.get("property_id")
    if pid is not None:
        items = [e for e in items if e["property_id"] == pid]
    aid = request.args.get("amenity_id")
    if aid is not None:
        items = [e for e in items if e["amenity_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


@app.route("/events/<eid>/publish", methods=["POST"])
def publish_event(eid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    event = get_or_404("events", eid, "ERR_EVENT_NOT_FOUND")
    if event["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Event is not DRAFT.")
    if event["amenity_id"] is not None:
        amenity = DB["amenities"].get(event["amenity_id"])
        if amenity is None or amenity["property_id"] != event["property_id"]:
            raise ApiError("ERR_PROPERTY_MISMATCH", 422, "Event amenity belongs to a different property.")
    if not (event["capacity"] >= 1 and event["start_at"] > clock_now()):
        raise ApiError("ERR_INVALID_STATE", 409, "Event cannot be published (start not in future).")
    event["status"] = "PUBLISHED"
    touch(event)
    return ok(serialize(event))


@app.route("/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    event = get_or_404("events", eid, "ERR_EVENT_NOT_FOUND")
    if event["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Event is not PUBLISHED.")
    event["status"] = "CANCELLED"
    regs = [r for r in DB["registrations"].values() if r["event_id"] == eid
            and r["status"] in ("RESERVED", "WAITLISTED")]
    regs.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for reg in regs:
        was_reserved = reg["status"] == "RESERVED"
        reg["status"] = "CANCELLED"
        if reg["fee_charged_cents"] > 0:
            resident = DB["residents"].get(reg["resident_id"])
            refund_to_wallet(resident, reg["fee_charged_cents"], "CommunityEvent", eid,
                             "Event cancellation refund")
        if was_reserved:
            event["reserved_count"] -= 1
        else:
            event["waitlist_count"] -= 1
        touch(reg)
    touch(event)
    return ok(serialize(event))


@app.route("/events/<eid>/complete", methods=["POST"])
def complete_event(eid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    event = get_or_404("events", eid, "ERR_EVENT_NOT_FOUND")
    if event["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Event is not PUBLISHED.")
    if clock_now() < event["end_at"]:
        raise ApiError("ERR_INVALID_STATE", 409, "Event end time has not passed.")
    event["status"] = "COMPLETED"
    for reg in DB["registrations"].values():
        if reg["event_id"] == eid and reg["status"] == "RESERVED":
            reg["status"] = "NO_SHOW"
            touch(reg)
    touch(event)
    return ok(serialize(event))


@app.route("/events/<eid>/register", methods=["POST"])
def register_event(eid):
    uid, role = auth()
    authorize(role, {"Resident"})
    body = get_body()
    resident_id = require_str(body, "resident_id")
    event = get_or_404("events", eid, "ERR_EVENT_NOT_FOUND")
    resident = get_or_404("residents", resident_id, "ERR_RESIDENT_NOT_FOUND")
    check_owner_resident(role, uid, resident_id)
    if event["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Event is not PUBLISHED.")
    for reg in DB["registrations"].values():
        if reg["event_id"] == eid and reg["resident_id"] == resident_id \
                and reg["status"] in ("RESERVED", "WAITLISTED"):
            raise ApiError("ERR_DUPLICATE_REGISTRATION", 409, "Resident already registered.")
    if event["reserved_count"] < event["capacity"]:
        status = "RESERVED"
        fee = event["fee_cents"]
    else:
        status = "WAITLISTED"
        fee = 0
    reg = new_common({
        "event_id": eid,
        "resident_id": resident_id,
        "status": status,
        "fee_charged_cents": fee,
    })
    DB["registrations"][reg["id"]] = reg
    if status == "RESERVED":
        event["reserved_count"] += 1
        if fee > 0:
            charge(resident, fee, "EVENT_FEE", "CommunityEvent", eid, "Event registration fee")
            recompute_posture(resident)
    else:
        event["waitlist_count"] += 1
    touch(event)
    return ok(serialize(reg), code=201)


# ===========================================================================
# Event Registrations
# ===========================================================================
@app.route("/event-registrations/<rid>", methods=["GET"])
def get_registration(rid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident"})
    reg = get_or_404("registrations", rid, "ERR_REGISTRATION_NOT_FOUND")
    return ok(serialize(reg))


@app.route("/event-registrations", methods=["GET"])
def list_registrations():
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident"})
    items = list(DB["registrations"].values())
    eid = request.args.get("event_id")
    if eid is not None:
        items = [r for r in items if r["event_id"] == eid]
    resident_id = request.args.get("resident_id")
    if resident_id is not None:
        items = [r for r in items if r["resident_id"] == resident_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


@app.route("/event-registrations/<rid>/cancel", methods=["POST"])
def cancel_registration(rid):
    uid, role = auth()
    authorize(role, {"Resident", "PropertyManager"})
    reg = get_or_404("registrations", rid, "ERR_REGISTRATION_NOT_FOUND")
    check_owner_resident(role, uid, reg["resident_id"])
    event = DB["events"].get(reg["event_id"])
    if reg["status"] == "RESERVED":
        reg["status"] = "CANCELLED"
        if reg["fee_charged_cents"] > 0:
            resident = DB["residents"].get(reg["resident_id"])
            refund_to_wallet(resident, reg["fee_charged_cents"], "CommunityEvent",
                             reg["event_id"], "Event registration refund")
        event["reserved_count"] -= 1
        touch(reg)
        # promote earliest waitlisted
        waitlisted = [r for r in DB["registrations"].values()
                      if r["event_id"] == reg["event_id"] and r["status"] == "WAITLISTED"]
        if waitlisted:
            waitlisted.sort(key=lambda r: (r["created_at"], r["_seq"]))
            promo = waitlisted[0]
            promo["status"] = "RESERVED"
            promo["fee_charged_cents"] = event["fee_cents"]
            event["waitlist_count"] -= 1
            event["reserved_count"] += 1
            if event["fee_cents"] > 0:
                promo_res = DB["residents"].get(promo["resident_id"])
                charge(promo_res, event["fee_cents"], "EVENT_FEE", "CommunityEvent",
                       reg["event_id"], "Event registration fee (waitlist promotion)")
                recompute_posture(promo_res)
            touch(promo)
        touch(event)
    elif reg["status"] == "WAITLISTED":
        reg["status"] = "CANCELLED"
        event["waitlist_count"] -= 1
        touch(reg)
        touch(event)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Registration cannot be cancelled from its current state.")
    return ok(serialize(reg))


@app.route("/event-registrations/<rid>/check-in", methods=["POST"])
def checkin_registration(rid):
    uid, role = auth()
    authorize(role, {"FrontDesk"})
    reg = get_or_404("registrations", rid, "ERR_REGISTRATION_NOT_FOUND")
    event = DB["events"].get(reg["event_id"])
    if reg["status"] != "RESERVED" or event["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Registration is not RESERVED at a PUBLISHED event.")
    reg["status"] = "ATTENDED"
    touch(reg)
    return ok(serialize(reg))


# ===========================================================================
# Vendors
# ===========================================================================
@app.route("/vendors", methods=["POST"])
def create_vendor():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    name = require_str(body, "name")
    trades = body.get("trades")
    if not isinstance(trades, list) or len(trades) == 0 or any(t not in TRADES for t in trades):
        raise verr("trades must be a non-empty list of valid trade members.")
    hourly_rate_cents = require_int(body, "hourly_rate_cents", min_val=0)
    active_job_limit = opt_int(body, "active_job_limit", 5, min_val=0)
    vendor = new_common({
        "name": name,
        "trades": list(trades),
        "hourly_rate_cents": hourly_rate_cents,
        "active_job_limit": active_job_limit,
        "active_job_count": 0,
        "status": "ACTIVE",
    })
    DB["vendors"][vendor["id"]] = vendor
    return ok(serialize(vendor), code=201)


@app.route("/vendors/<vid>", methods=["GET"])
def get_vendor(vid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Vendor"})
    vendor = get_or_404("vendors", vid, "ERR_VENDOR_NOT_FOUND")
    return ok(serialize(vendor))


@app.route("/vendors", methods=["GET"])
def list_vendors():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    items = list(DB["vendors"].values())
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


@app.route("/vendors/<vid>/suspend", methods=["POST"])
def suspend_vendor(vid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    vendor = get_or_404("vendors", vid, "ERR_VENDOR_NOT_FOUND")
    vendor["status"] = "SUSPENDED"
    touch(vendor)
    return ok(serialize(vendor))


# ===========================================================================
# Service Requests
# ===========================================================================
@app.route("/service-requests", methods=["POST"])
def create_service_request():
    uid, role = auth()
    authorize(role, {"Resident", "PropertyManager"})
    body = get_body()
    unit_id = require_str(body, "unit_id")
    resident_id = require_str(body, "resident_id")
    trade = require_enum(body, "trade", TRADES)
    priority = opt_enum(body, "priority", {"ROUTINE", "URGENT", "EMERGENCY"}, "ROUTINE")
    description = require_str(body, "description")
    unit = get_or_404("units", unit_id, "ERR_UNIT_NOT_FOUND")
    resident = get_or_404("residents", resident_id, "ERR_RESIDENT_NOT_FOUND")
    check_owner_resident(role, uid, resident_id)
    sr = new_common({
        "unit_id": unit_id,
        "resident_id": resident_id,
        "vendor_id": None,
        "trade": trade,
        "priority": priority,
        "description": description,
        "status": "SUBMITTED",
        "estimated_cost_cents": None,
        "final_invoice_cents": None,
        "triaged_by_user_id": None,
        "invoice_approved_by_user_id": None,
    })
    DB["service_requests"][sr["id"]] = sr
    return ok(serialize(sr), code=201)


@app.route("/service-requests/<sid>", methods=["GET"])
def get_service_request(sid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident", "Vendor"})
    sr = get_or_404("service_requests", sid, "ERR_SERVICE_REQUEST_NOT_FOUND")
    return ok(serialize(sr))


@app.route("/service-requests", methods=["GET"])
def list_service_requests():
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident", "Vendor"})
    items = list(DB["service_requests"].values())
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        items = [s for s in items if s["unit_id"] == unit_id]
    resident_id = request.args.get("resident_id")
    if resident_id is not None:
        items = [s for s in items if s["resident_id"] == resident_id]
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        items = [s for s in items if s["vendor_id"] == vendor_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


@app.route("/service-requests/<sid>/triage", methods=["POST"])
def triage_service_request(sid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    sr = get_or_404("service_requests", sid, "ERR_SERVICE_REQUEST_NOT_FOUND")
    if sr["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Service request is not SUBMITTED.")
    if "trade" in body and body.get("trade") is not None:
        sr["trade"] = require_enum(body, "trade", TRADES)
    if "priority" in body and body.get("priority") is not None:
        sr["priority"] = require_enum(body, "priority", {"ROUTINE", "URGENT", "EMERGENCY"})
    sr["status"] = "TRIAGED"
    sr["triaged_by_user_id"] = uid
    touch(sr)
    return ok(serialize(sr))


@app.route("/service-requests/<sid>/assign", methods=["POST"])
def assign_service_request(sid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    vendor_id = require_str(body, "vendor_id")
    estimated_hours = require_number(body, "estimated_hours", min_val=0)
    estimated_parts_cents = opt_int(body, "estimated_parts_cents", 0, min_val=0)
    sr = get_or_404("service_requests", sid, "ERR_SERVICE_REQUEST_NOT_FOUND")
    vendor = get_or_404("vendors", vendor_id, "ERR_VENDOR_NOT_FOUND")
    if sr["status"] != "TRIAGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Service request is not TRIAGED.")
    if vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_INACTIVE", 409, "Vendor is not ACTIVE.")
    if sr["trade"] not in vendor["trades"]:
        raise ApiError("ERR_VENDOR_TRADE_MISMATCH", 422, "Vendor does not service this trade.")
    if vendor["active_job_count"] >= vendor["active_job_limit"]:
        raise ApiError("ERR_VENDOR_AT_CAPACITY", 409, "Vendor is at capacity.")
    sr["vendor_id"] = vendor_id
    sr["estimated_cost_cents"] = service_estimate(vendor, estimated_hours, estimated_parts_cents)
    sr["status"] = "ASSIGNED"
    vendor["active_job_count"] += 1
    touch(vendor)
    touch(sr)
    return ok(serialize(sr))


@app.route("/service-requests/<sid>/unassign", methods=["POST"])
def unassign_service_request(sid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    sr = get_or_404("service_requests", sid, "ERR_SERVICE_REQUEST_NOT_FOUND")
    if sr["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Service request is not ASSIGNED.")
    vendor = DB["vendors"].get(sr["vendor_id"])
    if vendor is not None:
        vendor["active_job_count"] -= 1
        touch(vendor)
    sr["vendor_id"] = None
    sr["estimated_cost_cents"] = None
    sr["status"] = "TRIAGED"
    touch(sr)
    return ok(serialize(sr))


@app.route("/service-requests/<sid>/start", methods=["POST"])
def start_service_request(sid):
    uid, role = auth()
    authorize(role, {"Vendor"})
    sr = get_or_404("service_requests", sid, "ERR_SERVICE_REQUEST_NOT_FOUND")
    check_owner_vendor(role, uid, sr["vendor_id"])
    if sr["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Service request is not ASSIGNED.")
    sr["status"] = "IN_PROGRESS"
    touch(sr)
    return ok(serialize(sr))


@app.route("/service-requests/<sid>/complete", methods=["POST"])
def complete_service_request(sid):
    uid, role = auth()
    authorize(role, {"Vendor"})
    body = get_body()
    labor_hours = require_number(body, "labor_hours", min_val=0)
    parts = body.get("parts", [])
    if parts is None:
        parts = []
    if not isinstance(parts, list):
        raise verr("parts must be a list.")
    for p in parts:
        if not isinstance(p, dict) or "cents" not in p or isinstance(p["cents"], bool) \
                or not isinstance(p["cents"], int):
            raise verr("each part must have an integer 'cents'.")
    sr = get_or_404("service_requests", sid, "ERR_SERVICE_REQUEST_NOT_FOUND")
    check_owner_vendor(role, uid, sr["vendor_id"])
    if sr["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Service request is not IN_PROGRESS.")
    vendor = DB["vendors"].get(sr["vendor_id"])
    sr["final_invoice_cents"] = service_actual(vendor, labor_hours, parts, sr["priority"])
    sr["status"] = "COMPLETED"
    if vendor is not None:
        vendor["active_job_count"] -= 1
        touch(vendor)
    touch(sr)
    return ok(serialize(sr))


@app.route("/service-requests/<sid>/approve-invoice", methods=["POST"])
def approve_invoice(sid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    sr = get_or_404("service_requests", sid, "ERR_SERVICE_REQUEST_NOT_FOUND")
    if sr["triaged_by_user_id"] is not None and uid == sr["triaged_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Approver must differ from triager.")
    if sr["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "Service request is not COMPLETED.")
    sr["status"] = "CLOSED"
    sr["invoice_approved_by_user_id"] = uid
    resident = DB["residents"].get(sr["resident_id"])
    charge(resident, sr["final_invoice_cents"], "SERVICE_CHARGE", "ServiceRequest", sid,
           "Service invoice charge")
    recompute_posture(resident)
    touch(sr)
    return ok(serialize(sr))


@app.route("/service-requests/<sid>/cancel", methods=["POST"])
def cancel_service_request(sid):
    uid, role = auth()
    authorize(role, {"Resident", "PropertyManager"})
    sr = get_or_404("service_requests", sid, "ERR_SERVICE_REQUEST_NOT_FOUND")
    check_owner_resident(role, uid, sr["resident_id"])
    status = sr["status"]
    # Resident may cancel only from SUBMITTED; PropertyManager from SUBMITTED/TRIAGED/ASSIGNED.
    if role == "Resident":
        allowed = status == "SUBMITTED"
    else:
        allowed = status in ("SUBMITTED", "TRIAGED", "ASSIGNED")
    if not allowed:
        raise ApiError("ERR_INVALID_STATE", 409, "Service request cannot be cancelled from its current state.")
    if status == "ASSIGNED":
        vendor = DB["vendors"].get(sr["vendor_id"])
        if vendor is not None:
            vendor["active_job_count"] -= 1
            touch(vendor)
    sr["status"] = "CANCELLED"
    touch(sr)
    return ok(serialize(sr))


# ===========================================================================
# Packages
# ===========================================================================
@app.route("/packages", methods=["POST"])
def create_package():
    uid, role = auth()
    authorize(role, {"FrontDesk"})
    body = get_body()
    resident_id = require_str(body, "resident_id")
    carrier = require_str(body, "carrier")
    resident = get_or_404("residents", resident_id, "ERR_RESIDENT_NOT_FOUND")
    access_code = "".join(random.choices(string.digits, k=6))
    package = new_common({
        "resident_id": resident_id,
        "carrier": carrier,
        "status": "RECEIVED",
        "access_code": access_code,
        "received_at": clock_now(),
        "picked_up_at": None,
    })
    DB["packages"][package["id"]] = package
    return ok(serialize(package), code=201)


@app.route("/packages/<pid>", methods=["GET"])
def get_package(pid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident", "FrontDesk"})
    package = get_or_404("packages", pid, "ERR_PACKAGE_NOT_FOUND")
    return ok(serialize(package))


@app.route("/packages", methods=["GET"])
def list_packages():
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident", "FrontDesk"})
    items = list(DB["packages"].values())
    resident_id = request.args.get("resident_id")
    if resident_id is not None:
        items = [p for p in items if p["resident_id"] == resident_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


@app.route("/packages/<pid>/notify", methods=["POST"])
def notify_package(pid):
    uid, role = auth()
    authorize(role, {"FrontDesk"})
    package = get_or_404("packages", pid, "ERR_PACKAGE_NOT_FOUND")
    if package["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Package is not RECEIVED.")
    package["status"] = "NOTIFIED"
    touch(package)
    return ok(serialize(package))


@app.route("/packages/<pid>/pickup", methods=["POST"])
def pickup_package(pid):
    uid, role = auth()
    authorize(role, {"Resident", "FrontDesk"})
    body = get_body()
    access_code = require_str(body, "access_code")
    package = get_or_404("packages", pid, "ERR_PACKAGE_NOT_FOUND")
    check_owner_resident(role, uid, package["resident_id"])
    if package["status"] != "NOTIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Package is not NOTIFIED.")
    if access_code != package["access_code"]:
        raise ApiError("ERR_ACCESS_CODE_MISMATCH", 422, "Access code does not match.")
    package["status"] = "PICKED_UP"
    package["picked_up_at"] = clock_now()
    touch(package)
    return ok(serialize(package))


@app.route("/packages/<pid>/return", methods=["POST"])
def return_package(pid):
    uid, role = auth()
    authorize(role, {"FrontDesk"})
    package = get_or_404("packages", pid, "ERR_PACKAGE_NOT_FOUND")
    if package["status"] != "NOTIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Package is not NOTIFIED.")
    if clock_now() < package["received_at"] + timedelta(days=PACKAGE_HOLD_DAYS):
        raise ApiError("ERR_INVALID_STATE", 409, "Package hold period has not elapsed.")
    package["status"] = "RETURNED"
    touch(package)
    return ok(serialize(package))


# ===========================================================================
# Guest Passes
# ===========================================================================
@app.route("/guest-passes", methods=["POST"])
def create_guest_pass():
    uid, role = auth()
    authorize(role, {"Resident"})
    body = get_body()
    resident_id = require_str(body, "resident_id")
    guest_name = require_str(body, "guest_name")
    arrival_at = require_dt(body, "arrival_at")
    expected_departure_at = require_dt(body, "expected_departure_at")
    if arrival_at >= expected_departure_at:
        raise verr("arrival_at must be before expected_departure_at.")
    resident = get_or_404("residents", resident_id, "ERR_RESIDENT_NOT_FOUND")
    check_owner_resident(role, uid, resident_id)
    prop = property_of_resident(resident)
    # posture gate
    if resident["account_status"] == "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 403, "Resident is SUSPENDED.")
    # span within guest_window_hours
    span_hours = (expected_departure_at - arrival_at).total_seconds() / 3600
    if prop is not None and span_hours > prop["guest_window_hours"]:
        raise verr("Guest pass span exceeds guest_window_hours.")
    # concurrency
    if prop is not None and guest_conflict(prop, arrival_at, expected_departure_at):
        raise ApiError("ERR_GUEST_CAPACITY_EXCEEDED", 409, "Guest parking capacity exceeded.")
    pass_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    gp = new_common({
        "resident_id": resident_id,
        "guest_name": guest_name,
        "arrival_at": arrival_at,
        "expected_departure_at": expected_departure_at,
        "status": "ISSUED",
        "pass_code": pass_code,
    })
    DB["guest_passes"][gp["id"]] = gp
    return ok(serialize(gp), code=201)


@app.route("/guest-passes/<gid>", methods=["GET"])
def get_guest_pass(gid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident", "FrontDesk"})
    gp = get_or_404("guest_passes", gid, "ERR_GUEST_PASS_NOT_FOUND")
    return ok(serialize(gp))


@app.route("/guest-passes", methods=["GET"])
def list_guest_passes():
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident", "FrontDesk"})
    items = list(DB["guest_passes"].values())
    resident_id = request.args.get("resident_id")
    if resident_id is not None:
        items = [g for g in items if g["resident_id"] == resident_id]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


@app.route("/guest-passes/<gid>/check-in", methods=["POST"])
def checkin_guest_pass(gid):
    uid, role = auth()
    authorize(role, {"FrontDesk"})
    gp = get_or_404("guest_passes", gid, "ERR_GUEST_PASS_NOT_FOUND")
    if gp["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Guest pass is not ISSUED.")
    now = clock_now()
    if now >= gp["expected_departure_at"]:
        gp["status"] = "EXPIRED"
        touch(gp)
        return ok(serialize(gp))
    if now < gp["arrival_at"]:
        raise ApiError("ERR_INVALID_STATE", 409, "Before guest pass arrival window.")
    gp["status"] = "CHECKED_IN"
    touch(gp)
    return ok(serialize(gp))


@app.route("/guest-passes/<gid>/check-out", methods=["POST"])
def checkout_guest_pass(gid):
    uid, role = auth()
    authorize(role, {"FrontDesk"})
    gp = get_or_404("guest_passes", gid, "ERR_GUEST_PASS_NOT_FOUND")
    if gp["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Guest pass is not CHECKED_IN.")
    gp["status"] = "DEPARTED"
    touch(gp)
    return ok(serialize(gp))


@app.route("/guest-passes/<gid>/cancel", methods=["POST"])
def cancel_guest_pass(gid):
    uid, role = auth()
    authorize(role, {"Resident"})
    gp = get_or_404("guest_passes", gid, "ERR_GUEST_PASS_NOT_FOUND")
    check_owner_resident(role, uid, gp["resident_id"])
    if gp["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Guest pass is not ISSUED.")
    gp["status"] = "CANCELLED"
    touch(gp)
    return ok(serialize(gp))


# ===========================================================================
# Surveys
# ===========================================================================
@app.route("/surveys", methods=["POST"])
def create_survey():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    property_id = require_str(body, "property_id")
    title = require_str(body, "title")
    prop = get_or_404("properties", property_id, "ERR_PROPERTY_NOT_FOUND")
    survey = new_common({
        "property_id": property_id,
        "title": title,
        "status": "DRAFT",
        "response_count": 0,
    })
    DB["surveys"][survey["id"]] = survey
    return ok(serialize(survey), code=201)


@app.route("/surveys/<sid>", methods=["GET"])
def get_survey(sid):
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident"})
    survey = get_or_404("surveys", sid, "ERR_SURVEY_NOT_FOUND")
    return ok(serialize(survey))


@app.route("/surveys", methods=["GET"])
def list_surveys():
    uid, role = auth()
    authorize(role, {"PropertyManager", "Resident"})
    items = list(DB["surveys"].values())
    pid = request.args.get("property_id")
    if pid is not None:
        items = [s for s in items if s["property_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


@app.route("/surveys/<sid>/open", methods=["POST"])
def open_survey(sid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    survey = get_or_404("surveys", sid, "ERR_SURVEY_NOT_FOUND")
    if survey["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Survey is not DRAFT.")
    survey["status"] = "OPEN"
    touch(survey)
    return ok(serialize(survey))


@app.route("/surveys/<sid>/close", methods=["POST"])
def close_survey(sid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    survey = get_or_404("surveys", sid, "ERR_SURVEY_NOT_FOUND")
    if survey["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Survey is not OPEN.")
    survey["status"] = "CLOSED"
    touch(survey)
    return ok(serialize(survey))


@app.route("/surveys/<sid>/responses", methods=["POST"])
def create_survey_response(sid):
    uid, role = auth()
    authorize(role, {"Resident"})
    body = get_body()
    resident_id = require_str(body, "resident_id")
    satisfaction_score = require_int(body, "satisfaction_score", min_val=1, max_val=5)
    comment = body.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise verr("comment must be a string.")
    survey = get_or_404("surveys", sid, "ERR_SURVEY_NOT_FOUND")
    resident = get_or_404("residents", resident_id, "ERR_RESIDENT_NOT_FOUND")
    check_owner_resident(role, uid, resident_id)
    if survey["status"] != "OPEN":
        raise ApiError("ERR_SURVEY_NOT_OPEN", 409, "Survey is not OPEN.")
    for r in DB["survey_responses"].values():
        if r["survey_id"] == sid and r["resident_id"] == resident_id:
            raise ApiError("ERR_DUPLICATE_SURVEY_RESPONSE", 409, "Resident already responded.")
    resp = new_common({
        "survey_id": sid,
        "resident_id": resident_id,
        "satisfaction_score": satisfaction_score,
        "comment": comment,
    }, with_version=False)
    DB["survey_responses"][resp["id"]] = resp
    survey["response_count"] += 1
    touch(survey)
    return ok(serialize(resp), code=201)


# ===========================================================================
# Survey Responses
# ===========================================================================
@app.route("/survey-responses/<rid>", methods=["GET"])
def get_survey_response(rid):
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    resp = get_or_404("survey_responses", rid, "ERR_SURVEY_NOT_FOUND")
    return ok(serialize(resp))


@app.route("/survey-responses", methods=["GET"])
def list_survey_responses():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    items = list(DB["survey_responses"].values())
    survey_id = request.args.get("survey_id")
    if survey_id is not None:
        items = [r for r in items if r["survey_id"] == survey_id]
    resident_id = request.args.get("resident_id")
    if resident_id is not None:
        items = [r for r in items if r["resident_id"] == resident_id]
    items, limit, offset, total = paginate(items)
    return list_response(items, total, limit, offset)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = auth()
    authorize(role, {"PropertyManager"})
    body = get_body()
    to_iso8601 = body.get("to_iso8601")
    try:
        dt = parse_dt(to_iso8601)
    except Exception:
        raise verr("to_iso8601 must be an ISO-8601 datetime.")
    CLOCK["now"] = dt
    return ok({"current_utc": iso3(dt)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
