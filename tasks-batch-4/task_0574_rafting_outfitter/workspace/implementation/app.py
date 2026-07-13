"""
Whitewater Rafting & River Outfitter API — Python + Flask reference implementation.

In-memory only. The store starts empty on every boot; every entity is created by
the caller through the declared endpoints. No seeding, no persistence.
"""
import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from itertools import count

from flask import Flask, request, jsonify, g

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"OutfitterManager", "Reservationist", "SafetyOfficer", "Guest"}

CLASS_ORDER = {"CLASS_I": 1, "CLASS_II": 2, "CLASS_III": 3, "CLASS_IV": 4, "CLASS_V": 5}
DIFFICULTY_CLASSES = set(CLASS_ORDER.keys())
GUIDE_ROLES = {"LEAD", "SAFETY", "SWEEP"}
ROLE_WEIGHT = {"LEAD": 3, "SAFETY": 2, "SWEEP": 1}
BOOKING_TYPES = {"GROUP", "PRIVATE"}
GEAR_TYPES = {"RAFT", "WETSUIT", "PFD"}
WEIGHT_SENSITIVE = {"PFD", "WETSUIT"}
DIRECTIONS = {"TO_PUT_IN", "FROM_TAKE_OUT"}

PHOTO_FEE_CENTS = 4000
DEPOSIT_PCT = Decimal("0.25")
GUARDIAN_AGE_THRESHOLD = 18
SHUTTLE_BUFFER = timedelta(minutes=30)

COMMITTED_STATES = ("CONFIRMED", "CHECKED_IN", "COMPLETED")

ERROR_HTTP = {
    # auth
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_WAIVER_OWNER": 403,
    # not found
    "ERR_TRIP_NOT_FOUND": 404,
    "ERR_GUIDE_NOT_FOUND": 404,
    "ERR_GUIDE_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_GUEST_NOT_FOUND": 404,
    "ERR_WAIVER_NOT_FOUND": 404,
    "ERR_GEAR_NOT_FOUND": 404,
    "ERR_GEAR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_SHUTTLE_VEHICLE_NOT_FOUND": 404,
    "ERR_SHUTTLE_RUN_NOT_FOUND": 404,
    "ERR_CONDITION_READING_NOT_FOUND": 404,
    # request validation
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_TIME_WINDOW": 400,
    # state
    "ERR_TRIP_NOT_BOOKABLE": 409,
    "ERR_INVALID_TRIP_STATE": 409,
    "ERR_NO_GUIDE_ASSIGNED": 409,
    "ERR_RESERVATION_CANCELLED": 409,
    "ERR_INVALID_RESERVATION_STATE": 409,
    "ERR_NOT_CHECKED_IN": 409,
    "ERR_UNRESOLVED_RESERVATIONS": 409,
    "ERR_UNSETTLED_RESERVATION": 409,
    "ERR_WAIVER_NOT_PENDING": 409,
    "ERR_GEAR_UNAVAILABLE": 409,
    "ERR_INVALID_GEAR_STATE": 409,
    "ERR_GUIDE_IN_USE": 409,
    # safety
    "ERR_GUEST_UNDER_MIN_AGE": 422,
    "ERR_GUARDIAN_REQUIRED": 422,
    "ERR_WEIGHT_OUT_OF_RANGE": 422,
    # referential
    "ERR_GUIDE_CLASS_INSUFFICIENT": 409,
    "ERR_WAIVER_NOT_SIGNED": 409,
    "ERR_GEAR_NOT_ASSIGNED": 409,
    # constraint
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_GUIDE_RATIO_UNMET": 409,
    "ERR_PRIVATE_CONFLICT": 409,
    "ERR_GUIDE_DOUBLE_BOOKED": 409,
    "ERR_SHUTTLE_BUFFER_CONFLICT": 409,
    "ERR_DUPLICATE_GEAR_TYPE": 409,
    # fiscal
    "ERR_DEPOSIT_TOO_LOW": 402,
    # concurrency
    "ERR_STALE_TRIP_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "trips": {},
    "guides": {},
    "guide_assignments": {},
    "reservations": {},
    "guests": {},
    "waivers": {},
    "gear_items": {},
    "gear_assignments": {},
    "shuttle_vehicles": {},
    "shuttle_runs": {},
    "condition_readings": {},
}
_SEQ = count(1)

# Logical clock (§2.10). Startup default; never falls back to wall-clock time.
LOGICAL_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(Z|[+-]\d{2}:\d{2})?$"
)


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    m = ISO_RE.match(s.strip())
    if not m:
        raise ValueError("bad datetime")
    y, mo, d, h, mi, se = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = int((frac + "000000")[:6]) if frac else 0
    dt = datetime(y, mo, d, h, mi, se, micro, tzinfo=timezone.utc)
    tz = m.group(8)
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        oh = int(tz[1:3])
        om = int(tz[4:6])
        dt = dt - sign * timedelta(hours=oh, minutes=om)
    return dt


def fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_str():
    return fmt(LOGICAL_NOW)


# ---------------------------------------------------------------------------
# Response envelope helpers
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_str(),
    }
    if extra:
        m.update(extra)
    return m


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), code


def ok_list(items, limit, offset, total):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_common():
    ts = now_str()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_SEQ),
    }


def new_reading_common():
    return {"id": str(uuid.uuid4()), "created_at": now_str(), "_seq": next(_SEQ)}


def touch(entity):
    entity["updated_at"] = now_str()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Auth / authorization
# ---------------------------------------------------------------------------
def authorize(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.role = role
    return user_id, role


# ---------------------------------------------------------------------------
# Body parsing / field validation
# ---------------------------------------------------------------------------
def get_body(required=True):
    raw = request.get_json(silent=True)
    if raw is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST")
        return {}
    if not isinstance(raw, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return raw


def _present(body, name):
    return name in body and body[name] is not None


def f_str(body, name, required=True):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST")
        return None
    v = body[name]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def f_int(body, name, required=True, minimum=None, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def f_num(body, name, required=True, minimum=None, exclusive_min=None, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST")
    if exclusive_min is not None and v <= exclusive_min:
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def f_bool(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST")
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def f_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST")
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def f_dt(body, name, required=True):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST")
        return None
    v = body[name]
    try:
        parse_iso(v)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST")
    return v


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------
def require(store_key, ident, err):
    e = DB[store_key].get(ident)
    if e is None:
        raise ApiError(err)
    return e


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(store_key, filters):
    limit, offset = pagination_params()
    rows = list(DB[store_key].values())
    for field_name, arg_name in filters:
        val = request.args.get(arg_name)
        if val is not None:
            rows = [r for r in rows if r.get(field_name) == val]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset : offset + limit]
    return ok_list([public(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def rhu(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def group_discount_pct(party_size):
    if party_size >= 8:
        return Decimal("0.15")
    if party_size >= 4:
        return Decimal("0.10")
    return Decimal("0")


def estimated_total(base_rate_cents, party_size, photo_addon):
    disc = group_discount_pct(party_size)
    base = rhu(Decimal(base_rate_cents) * Decimal(party_size) * (Decimal(1) - disc))
    return base + (PHOTO_FEE_CENTS if photo_addon else 0)


def final_total(base_rate_cents, checked_in_count, party_size, photo_addon, gratuity):
    disc = group_discount_pct(party_size)
    base = rhu(Decimal(base_rate_cents) * Decimal(checked_in_count) * (Decimal(1) - disc))
    return base + (PHOTO_FEE_CENTS if photo_addon else 0) + gratuity


def required_deposit(est_total):
    return rhu(Decimal(est_total) * DEPOSIT_PCT)


def required_guides(committed_guests, guide_ratio_max):
    return math.ceil(committed_guests / guide_ratio_max) if guide_ratio_max else 0


def flow_band(trip, flow_cfs):
    if trip["safe_flow_min"] <= flow_cfs <= trip["safe_flow_max"]:
        return "SAFE"
    if trip["safe_flow_max"] < flow_cfs <= trip["marginal_flow_max"]:
        return "MARGINAL"
    return "UNSAFE"


# ---------------------------------------------------------------------------
# Trip aggregate recomputation
# ---------------------------------------------------------------------------
def trip_reservations(trip_id):
    return [r for r in DB["reservations"].values() if r["trip_id"] == trip_id]


def trip_snapshot(t):
    return (
        t["status"],
        t["committed_guests"],
        t["assigned_guide_count"],
        t["deposits_held_cents"],
        t["booking_mode"],
    )


def recompute_trip_aggregates(t):
    rs = trip_reservations(t["id"])
    t["committed_guests"] = sum(
        r["party_size"] for r in rs if r["fulfillment_status"] in COMMITTED_STATES
    )
    t["deposits_held_cents"] = sum(
        r["deposit_cents"] for r in rs if r["payment_status"] in ("DEPOSIT_PAID", "SETTLED")
    )
    t["assigned_guide_count"] = sum(
        1
        for ga in DB["guide_assignments"].values()
        if ga["trip_id"] == t["id"] and ga["status"] == "ASSIGNED"
    )
    t["booking_mode"] = (
        "PRIVATE"
        if any(
            r["booking_type"] == "PRIVATE" and r["fulfillment_status"] in COMMITTED_STATES
            for r in rs
        )
        else "GROUP"
    )


def guests_of_reservation(res_id):
    return [gu for gu in DB["guests"].values() if gu["reservation_id"] == res_id]


def waiver_of_guest(guest_id):
    for w in DB["waivers"].values():
        if w["guest_id"] == guest_id:
            return w
    return None


def guest_gear_assignments(guest_id, status="ASSIGNED"):
    return [
        ga
        for ga in DB["gear_assignments"].values()
        if ga["guest_id"] == guest_id and (status is None or ga["status"] == status)
    ]


def recompute_checked_in_count(res):
    res["checked_in_guest_count"] = sum(
        1 for gu in guests_of_reservation(res["id"]) if gu["status"] == "CHECKED_IN"
    )


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def release_gear_assignment(ga):
    if ga["status"] == "ASSIGNED":
        ga["status"] = "RELEASED"
        touch(ga)
        item = DB["gear_items"].get(ga["gear_item_id"])
        if item is not None and item["status"] == "ASSIGNED":
            item["status"] = "AVAILABLE"
            touch(item)


def remove_guest_internal(guest):
    """Guest -> REMOVED: release gear, void waiver, recompute reservation count."""
    if guest["status"] == "REMOVED":
        return
    guest["status"] = "REMOVED"
    touch(guest)
    for ga in guest_gear_assignments(guest["id"], "ASSIGNED"):
        release_gear_assignment(ga)
    w = waiver_of_guest(guest["id"])
    if w is not None and w["status"] in ("PENDING", "SIGNED"):
        w["status"] = "VOID"
        touch(w)
    res = DB["reservations"].get(guest["reservation_id"])
    if res is not None:
        recompute_checked_in_count(res)


def cancel_reservation_internal(res):
    """Cascade L2: cancel one reservation, release gear/guests/waivers, refund."""
    res["fulfillment_status"] = "CANCELLED"
    for guest in guests_of_reservation(res["id"]):
        if guest["status"] != "REMOVED":
            remove_guest_internal(guest)
    if res["payment_status"] in ("DEPOSIT_PAID", "SETTLED"):
        res["payment_status"] = "REFUNDED"
    recompute_checked_in_count(res)
    touch(res)


def cancel_trip_cascade(trip):
    """Cascade L1: unwind an entire trip."""
    for res in trip_reservations(trip["id"]):
        if res["fulfillment_status"] in ("PENDING", "CONFIRMED", "CHECKED_IN"):
            res["fulfillment_status"] = "CANCELLED"
            if res["payment_status"] in ("DEPOSIT_PAID", "SETTLED"):
                res["payment_status"] = "REFUNDED"
            for guest in guests_of_reservation(res["id"]):
                if guest["status"] != "REMOVED":
                    remove_guest_internal(guest)
            recompute_checked_in_count(res)
            touch(res)
    for ga in DB["guide_assignments"].values():
        if ga["trip_id"] == trip["id"] and ga["status"] == "ASSIGNED":
            ga["status"] = "RELEASED"
            touch(ga)
    for run in DB["shuttle_runs"].values():
        if run["trip_id"] == trip["id"] and run["status"] == "SCHEDULED":
            run["status"] = "CANCELLED"
            touch(run)


# ---------------------------------------------------------------------------
# Gratuity distribution
# ---------------------------------------------------------------------------
def assigned_guides_ordered(trip_id):
    guides = [
        ga
        for ga in DB["guide_assignments"].values()
        if ga["trip_id"] == trip_id and ga["status"] == "ASSIGNED"
    ]
    guides.sort(key=lambda ga: (ga["created_at"], ga["_seq"]))
    return guides


def gratuity_pool(trip_id):
    return sum(
        r["gratuity_cents"]
        for r in trip_reservations(trip_id)
        if r["payment_status"] == "SETTLED"
    )


def distribute_provisional(trip):
    pool = gratuity_pool(trip["id"])
    guides = assigned_guides_ordered(trip["id"])
    n = len(guides)
    if n == 0:
        return
    base = pool // n
    remainder = pool - base * n
    for i, ga in enumerate(guides):
        share = base + (1 if i < remainder else 0)
        if ga["provisional_gratuity_share_cents"] != share:
            ga["provisional_gratuity_share_cents"] = share
            touch(ga)


def distribute_final(trip):
    pool = gratuity_pool(trip["id"])
    guides = assigned_guides_ordered(trip["id"])
    total_weight = sum(ROLE_WEIGHT[ga["role"]] for ga in guides)
    if total_weight == 0:
        return
    raw = []
    for ga in guides:
        raw.append(pool * ROLE_WEIGHT[ga["role"]] // total_weight)
    remainder = pool - sum(raw)
    for i, ga in enumerate(guides):
        share = raw[i] + (1 if i < remainder else 0)
        if ga["final_gratuity_share_cents"] != share:
            ga["final_gratuity_share_cents"] = share
            touch(ga)


# ===========================================================================
# ROUTES — RiverTrip
# ===========================================================================
@app.route("/trips", methods=["POST"])
def create_trip():
    authorize({"OutfitterManager"})
    body = get_body()
    river_name = f_str(body, "river_name")
    difficulty_class = f_enum(body, "difficulty_class", DIFFICULTY_CLASSES)
    trip_date = f_dt(body, "trip_date")
    end_time = f_dt(body, "end_time")
    put_in = f_str(body, "put_in_location")
    take_out = f_str(body, "take_out_location")
    max_capacity = f_int(body, "max_capacity", minimum=1)
    guide_ratio_max = f_int(body, "guide_ratio_max", minimum=1)
    base_rate_cents = f_int(body, "base_rate_cents", minimum=0)
    min_age = f_int(body, "min_age", required=False, minimum=0, default=0)
    safe_flow_min = f_num(body, "safe_flow_min")
    safe_flow_max = f_num(body, "safe_flow_max")
    marginal_flow_max = f_num(body, "marginal_flow_max")
    if parse_iso(end_time) <= parse_iso(trip_date):
        raise ApiError("ERR_INVALID_TIME_WINDOW")

    t = new_common()
    t.update(
        {
            "river_name": river_name,
            "difficulty_class": difficulty_class,
            "trip_date": trip_date,
            "end_time": end_time,
            "put_in_location": put_in,
            "take_out_location": take_out,
            "max_capacity": max_capacity,
            "guide_ratio_max": guide_ratio_max,
            "base_rate_cents": base_rate_cents,
            "min_age": min_age,
            "safe_flow_min": safe_flow_min,
            "safe_flow_max": safe_flow_max,
            "marginal_flow_max": marginal_flow_max,
            "booking_mode": "GROUP",
            "committed_guests": 0,
            "assigned_guide_count": 0,
            "deposits_held_cents": 0,
            "status": "SCHEDULED",
        }
    )
    DB["trips"][t["id"]] = t
    return ok_object(public(t), 201)


@app.route("/trips", methods=["GET"])
def list_trips():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer", "Guest"})
    return list_response("trips", [("status", "status")])


@app.route("/trips/<tid>", methods=["GET"])
def get_trip(tid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer", "Guest"})
    t = require("trips", tid, "ERR_TRIP_NOT_FOUND")
    return ok_object(public(t))


@app.route("/trips/<tid>/open", methods=["POST"])
def open_trip(tid):
    authorize({"OutfitterManager"})
    t = require("trips", tid, "ERR_TRIP_NOT_FOUND")
    if t["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TRIP_STATE")
    if t["assigned_guide_count"] < 1:
        raise ApiError("ERR_NO_GUIDE_ASSIGNED")
    t["status"] = "OPEN"
    touch(t)
    return ok_object(public(t))


@app.route("/trips/<tid>/complete", methods=["POST"])
def complete_trip(tid):
    authorize({"OutfitterManager"})
    t = require("trips", tid, "ERR_TRIP_NOT_FOUND")
    if t["status"] not in ("OPEN", "FULL"):
        raise ApiError("ERR_INVALID_TRIP_STATE")
    rs = trip_reservations(tid)
    if any(r["fulfillment_status"] == "PENDING" for r in rs):
        raise ApiError("ERR_UNRESOLVED_RESERVATIONS")
    for r in rs:
        if r["fulfillment_status"] == "CHECKED_IN" and r["payment_status"] != "SETTLED":
            raise ApiError("ERR_UNSETTLED_RESERVATION")
    for r in rs:
        if r["fulfillment_status"] == "CHECKED_IN":
            r["fulfillment_status"] = "COMPLETED"
            touch(r)
    distribute_final(t)
    before = trip_snapshot(t)
    t["status"] = "COMPLETED"
    recompute_trip_aggregates(t)
    if trip_snapshot(t) != before:
        touch(t)
    return ok_object(public(t))


@app.route("/trips/<tid>/cancel", methods=["POST"])
def cancel_trip(tid):
    authorize({"SafetyOfficer"})
    t = require("trips", tid, "ERR_TRIP_NOT_FOUND")
    if t["status"] not in ("SCHEDULED", "OPEN", "FULL", "WEATHER_HOLD"):
        raise ApiError("ERR_INVALID_TRIP_STATE")
    before = trip_snapshot(t)
    t["status"] = "CANCELLED"
    cancel_trip_cascade(t)
    recompute_trip_aggregates(t)
    if trip_snapshot(t) != before:
        touch(t)
    return ok_object(public(t))


# ===========================================================================
# ROUTES — Guide
# ===========================================================================
@app.route("/guides", methods=["POST"])
def create_guide():
    authorize({"OutfitterManager"})
    body = get_body()
    full_name = f_str(body, "full_name")
    max_class = f_enum(body, "max_class", DIFFICULTY_CLASSES)
    guide = new_common()
    guide.update({"full_name": full_name, "max_class": max_class, "status": "ACTIVE"})
    DB["guides"][guide["id"]] = guide
    return ok_object(public(guide), 201)


@app.route("/guides", methods=["GET"])
def list_guides():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    return list_response("guides", [("status", "status")])


@app.route("/guides/<gid>", methods=["GET"])
def get_guide(gid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    guide = require("guides", gid, "ERR_GUIDE_NOT_FOUND")
    return ok_object(public(guide))


@app.route("/guides/<gid>/deactivate", methods=["POST"])
def deactivate_guide(gid):
    authorize({"OutfitterManager"})
    guide = require("guides", gid, "ERR_GUIDE_NOT_FOUND")
    in_use = False
    for ga in DB["guide_assignments"].values():
        if ga["guide_id"] == gid and ga["status"] == "ASSIGNED":
            trip = DB["trips"].get(ga["trip_id"])
            if trip is not None and trip["status"] not in ("CANCELLED", "COMPLETED"):
                in_use = True
                break
    if in_use:
        raise ApiError("ERR_GUIDE_IN_USE")
    if guide["status"] == "ACTIVE":
        guide["status"] = "INACTIVE"
        touch(guide)
    return ok_object(public(guide))


# ===========================================================================
# ROUTES — GuideAssignment
# ===========================================================================
@app.route("/guide-assignments", methods=["POST"])
def create_guide_assignment():
    authorize({"OutfitterManager"})
    body = get_body()
    trip_id = f_str(body, "trip_id")
    guide_id = f_str(body, "guide_id")
    role = f_enum(body, "role", GUIDE_ROLES)
    trip = require("trips", trip_id, "ERR_TRIP_NOT_FOUND")
    guide = require("guides", guide_id, "ERR_GUIDE_NOT_FOUND")
    # referential (priority 6): certification class
    if CLASS_ORDER[guide["max_class"]] < CLASS_ORDER[trip["difficulty_class"]]:
        raise ApiError("ERR_GUIDE_CLASS_INSUFFICIENT")
    # constraint (priority 7): temporal double-booking
    ts_start = parse_iso(trip["trip_date"])
    ts_end = parse_iso(trip["end_time"])
    for ga in DB["guide_assignments"].values():
        if ga["guide_id"] != guide_id or ga["status"] != "ASSIGNED":
            continue
        if ga["trip_id"] == trip_id:
            continue
        other = DB["trips"].get(ga["trip_id"])
        if other is None:
            continue
        o_start = parse_iso(other["trip_date"])
        o_end = parse_iso(other["end_time"])
        if ts_start < o_end and o_start < ts_end:
            raise ApiError("ERR_GUIDE_DOUBLE_BOOKED")

    ga = new_common()
    ga.update(
        {
            "trip_id": trip_id,
            "guide_id": guide_id,
            "role": role,
            "provisional_gratuity_share_cents": 0,
            "final_gratuity_share_cents": 0,
            "status": "ASSIGNED",
        }
    )
    DB["guide_assignments"][ga["id"]] = ga
    before = trip_snapshot(trip)
    recompute_trip_aggregates(trip)
    if trip_snapshot(trip) != before:
        touch(trip)
    return ok_object(public(ga), 201)


@app.route("/guide-assignments", methods=["GET"])
def list_guide_assignments():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    return list_response(
        "guide_assignments",
        [("trip_id", "trip_id"), ("guide_id", "guide_id"), ("status", "status")],
    )


@app.route("/guide-assignments/<gaid>", methods=["GET"])
def get_guide_assignment(gaid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    ga = require("guide_assignments", gaid, "ERR_GUIDE_ASSIGNMENT_NOT_FOUND")
    return ok_object(public(ga))


@app.route("/guide-assignments/<gaid>/release", methods=["POST"])
def release_guide_assignment(gaid):
    authorize({"OutfitterManager"})
    ga = require("guide_assignments", gaid, "ERR_GUIDE_ASSIGNMENT_NOT_FOUND")
    if ga["status"] == "ASSIGNED":
        trip = DB["trips"].get(ga["trip_id"])
        if trip is not None:
            rs = trip_reservations(trip["id"])
            has_checked_in = any(r["fulfillment_status"] == "CHECKED_IN" for r in rs)
            if has_checked_in:
                committed = sum(
                    r["party_size"] for r in rs if r["fulfillment_status"] in COMMITTED_STATES
                )
                need = required_guides(committed, trip["guide_ratio_max"])
                if (trip["assigned_guide_count"] - 1) < need:
                    raise ApiError("ERR_GUIDE_RATIO_UNMET")
        ga["status"] = "RELEASED"
        touch(ga)
        if trip is not None:
            before = trip_snapshot(trip)
            recompute_trip_aggregates(trip)
            if trip_snapshot(trip) != before:
                touch(trip)
    return ok_object(public(ga))


# ===========================================================================
# ROUTES — Reservation
# ===========================================================================
@app.route("/reservations", methods=["POST"])
def create_reservation():
    authorize({"Reservationist"})
    body = get_body()
    trip_id = f_str(body, "trip_id")
    booking_type = f_enum(body, "booking_type", BOOKING_TYPES)
    party_size = f_int(body, "party_size", minimum=1)
    photo_addon = f_bool(body, "photo_addon", required=False, default=False)
    deposit_cents = f_int(body, "deposit_cents", minimum=0)
    expected_trip_version = f_int(body, "expected_trip_version")
    trip = require("trips", trip_id, "ERR_TRIP_NOT_FOUND")
    # OCC (priority 9) — last check
    if expected_trip_version != trip["version"]:
        raise ApiError("ERR_STALE_TRIP_VERSION")

    est = estimated_total(trip["base_rate_cents"], party_size, photo_addon)
    res = new_common()
    res.update(
        {
            "trip_id": trip_id,
            "booking_type": booking_type,
            "party_size": party_size,
            "photo_addon": photo_addon,
            "deposit_cents": deposit_cents,
            "gratuity_cents": 0,
            "estimated_total_cents": est,
            "final_total_cents": None,
            "payment_status": "UNPAID",
            "fulfillment_status": "PENDING",
            "checked_in_guest_count": 0,
        }
    )
    DB["reservations"][res["id"]] = res
    touch(trip)  # booking advances RiverTrip.version by one (§2.9)
    return ok_object(public(res), 201)


@app.route("/reservations", methods=["GET"])
def list_reservations():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer", "Guest"})
    return list_response(
        "reservations",
        [
            ("trip_id", "trip_id"),
            ("payment_status", "payment_status"),
            ("fulfillment_status", "fulfillment_status"),
        ],
    )


@app.route("/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer", "Guest"})
    res = require("reservations", rid, "ERR_RESERVATION_NOT_FOUND")
    return ok_object(public(res))


@app.route("/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    authorize({"Reservationist"})
    res = require("reservations", rid, "ERR_RESERVATION_NOT_FOUND")
    # state: reservation own fulfillment must be PENDING
    if res["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_RESERVATION_CANCELLED")
    if res["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_RESERVATION_STATE")
    trip = DB["trips"][res["trip_id"]]
    if trip["status"] not in ("OPEN", "FULL"):
        raise ApiError("ERR_TRIP_NOT_BOOKABLE")
    # constraint (priority 7): capacity then private
    if trip["committed_guests"] + res["party_size"] > trip["max_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED")
    others = [
        o
        for o in trip_reservations(trip["id"])
        if o["id"] != res["id"] and o["fulfillment_status"] in ("CONFIRMED", "CHECKED_IN")
    ]
    if res["booking_type"] == "PRIVATE":
        if others:
            raise ApiError("ERR_PRIVATE_CONFLICT")
    else:
        if any(o["booking_type"] == "PRIVATE" for o in others):
            raise ApiError("ERR_PRIVATE_CONFLICT")

    res["fulfillment_status"] = "CONFIRMED"
    touch(res)
    before = trip_snapshot(trip)
    recompute_trip_aggregates(trip)
    if trip["status"] == "OPEN" and (
        trip["committed_guests"] >= trip["max_capacity"] or res["booking_type"] == "PRIVATE"
    ):
        trip["status"] = "FULL"
    if trip_snapshot(trip) != before:
        touch(trip)
    return ok_object(public(res))


@app.route("/reservations/<rid>/pay-deposit", methods=["POST"])
def pay_deposit(rid):
    authorize({"Reservationist"})
    res = require("reservations", rid, "ERR_RESERVATION_NOT_FOUND")
    if res["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_RESERVATION_CANCELLED")
    if res["payment_status"] != "UNPAID":
        raise ApiError("ERR_INVALID_RESERVATION_STATE")
    if res["deposit_cents"] < required_deposit(res["estimated_total_cents"]):
        raise ApiError("ERR_DEPOSIT_TOO_LOW")
    res["payment_status"] = "DEPOSIT_PAID"
    touch(res)
    trip = DB["trips"][res["trip_id"]]
    before = trip_snapshot(trip)
    recompute_trip_aggregates(trip)
    if trip_snapshot(trip) != before:
        touch(trip)
    return ok_object(public(res))


@app.route("/reservations/<rid>/check-in", methods=["POST"])
def check_in_reservation(rid):
    authorize({"Reservationist"})
    res = require("reservations", rid, "ERR_RESERVATION_NOT_FOUND")
    if res["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_RESERVATION_CANCELLED")
    if res["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_RESERVATION_STATE")
    trip = DB["trips"][res["trip_id"]]
    if trip["status"] not in ("OPEN", "FULL"):
        raise ApiError("ERR_TRIP_NOT_BOOKABLE")
    active_guests = [gu for gu in guests_of_reservation(res["id"]) if gu["status"] != "REMOVED"]
    # referential (priority 6): waivers signed, then PFD gear assigned
    for gu in active_guests:
        w = waiver_of_guest(gu["id"])
        if w is None or w["status"] != "SIGNED":
            raise ApiError("ERR_WAIVER_NOT_SIGNED")
    for gu in active_guests:
        has_pfd = False
        for ga in guest_gear_assignments(gu["id"], "ASSIGNED"):
            item = DB["gear_items"].get(ga["gear_item_id"])
            if item is not None and item["gear_type"] == "PFD":
                has_pfd = True
                break
        if not has_pfd:
            raise ApiError("ERR_GEAR_NOT_ASSIGNED")
    # constraint (priority 7): guide ratio
    need = required_guides(trip["committed_guests"], trip["guide_ratio_max"])
    if trip["assigned_guide_count"] < need:
        raise ApiError("ERR_GUIDE_RATIO_UNMET")

    for gu in active_guests:
        if gu["status"] == "BOOKED":
            gu["status"] = "CHECKED_IN"
            touch(gu)
    res["fulfillment_status"] = "CHECKED_IN"
    recompute_checked_in_count(res)
    touch(res)
    return ok_object(public(res))


@app.route("/reservations/<rid>/settle", methods=["POST"])
def settle_reservation(rid):
    authorize({"Reservationist"})
    body = get_body()
    gratuity_cents = f_int(body, "gratuity_cents", minimum=0)
    res = require("reservations", rid, "ERR_RESERVATION_NOT_FOUND")
    if res["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_RESERVATION_CANCELLED")
    if res["fulfillment_status"] != "CHECKED_IN":
        raise ApiError("ERR_NOT_CHECKED_IN")
    if res["payment_status"] != "DEPOSIT_PAID":
        raise ApiError("ERR_INVALID_RESERVATION_STATE")
    trip = DB["trips"][res["trip_id"]]
    res["gratuity_cents"] = gratuity_cents
    res["final_total_cents"] = final_total(
        trip["base_rate_cents"],
        res["checked_in_guest_count"],
        res["party_size"],
        res["photo_addon"],
        gratuity_cents,
    )
    res["payment_status"] = "SETTLED"
    touch(res)
    distribute_provisional(trip)
    return ok_object(public(res))


@app.route("/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    authorize({"Reservationist"})
    res = require("reservations", rid, "ERR_RESERVATION_NOT_FOUND")
    if res["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_RESERVATION_CANCELLED")
    if res["fulfillment_status"] not in ("PENDING", "CONFIRMED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_RESERVATION_STATE")
    trip = DB["trips"][res["trip_id"]]
    cancel_reservation_internal(res)
    before = trip_snapshot(trip)
    recompute_trip_aggregates(trip)
    if (
        trip["status"] == "FULL"
        and trip["committed_guests"] < trip["max_capacity"]
        and trip["booking_mode"] == "GROUP"
    ):
        trip["status"] = "OPEN"
    if trip_snapshot(trip) != before:
        touch(trip)
    return ok_object(public(res))


# ===========================================================================
# ROUTES — Guest
# ===========================================================================
@app.route("/guests", methods=["POST"])
def create_guest():
    authorize({"Reservationist"})
    body = get_body()
    reservation_id = f_str(body, "reservation_id")
    full_name = f_str(body, "full_name")
    age = f_int(body, "age", minimum=0)
    weight_lbs = f_num(body, "weight_lbs", exclusive_min=0)
    res = require("reservations", reservation_id, "ERR_RESERVATION_NOT_FOUND")
    trip = DB["trips"][res["trip_id"]]
    if age < trip["min_age"]:
        raise ApiError("ERR_GUEST_UNDER_MIN_AGE")

    guest = new_common()
    guest.update(
        {
            "reservation_id": reservation_id,
            "full_name": full_name,
            "age": age,
            "weight_lbs": weight_lbs,
            "status": "BOOKED",
        }
    )
    DB["guests"][guest["id"]] = guest
    waiver = new_common()
    waiver.update(
        {
            "guest_id": guest["id"],
            "guardian_required": age < GUARDIAN_AGE_THRESHOLD,
            "guardian_name": None,
            "status": "PENDING",
        }
    )
    DB["waivers"][waiver["id"]] = waiver
    return ok_object(public(guest), 201)


@app.route("/guests", methods=["GET"])
def list_guests():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer", "Guest"})
    return list_response(
        "guests", [("reservation_id", "reservation_id"), ("status", "status")]
    )


@app.route("/guests/<guid>", methods=["GET"])
def get_guest(guid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer", "Guest"})
    guest = require("guests", guid, "ERR_GUEST_NOT_FOUND")
    return ok_object(public(guest))


@app.route("/guests/<guid>/remove", methods=["POST"])
def remove_guest(guid):
    authorize({"Reservationist"})
    guest = require("guests", guid, "ERR_GUEST_NOT_FOUND")
    if guest["status"] != "REMOVED":
        remove_guest_internal(guest)
    return ok_object(public(guest))


# ===========================================================================
# ROUTES — Waiver
# ===========================================================================
@app.route("/waivers", methods=["GET"])
def list_waivers():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer", "Guest"})
    return list_response("waivers", [("guest_id", "guest_id"), ("status", "status")])


@app.route("/waivers/<wid>", methods=["GET"])
def get_waiver(wid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer", "Guest"})
    w = require("waivers", wid, "ERR_WAIVER_NOT_FOUND")
    return ok_object(public(w))


@app.route("/waivers/<wid>/sign", methods=["POST"])
def sign_waiver(wid):
    user_id, _ = authorize({"Guest"})
    body = get_body(required=False)
    guardian_name = f_str(body, "guardian_name", required=False)
    w = require("waivers", wid, "ERR_WAIVER_NOT_FOUND")
    if w["guest_id"] != user_id:
        raise ApiError("ERR_NOT_WAIVER_OWNER")
    if w["status"] != "PENDING":
        raise ApiError("ERR_WAIVER_NOT_PENDING")
    if w["guardian_required"] and not guardian_name:
        raise ApiError("ERR_GUARDIAN_REQUIRED")
    if guardian_name is not None:
        w["guardian_name"] = guardian_name
    w["status"] = "SIGNED"
    touch(w)
    return ok_object(public(w))


# ===========================================================================
# ROUTES — GearItem
# ===========================================================================
@app.route("/gear-items", methods=["POST"])
def create_gear_item():
    authorize({"OutfitterManager"})
    body = get_body()
    gear_type = f_enum(body, "gear_type", GEAR_TYPES)
    size_label = f_str(body, "size_label")
    min_weight = f_num(body, "min_weight_lbs", required=False, default=0)
    max_weight = f_num(body, "max_weight_lbs", required=False, default=100000)
    item = new_common()
    item.update(
        {
            "gear_type": gear_type,
            "size_label": size_label,
            "min_weight_lbs": min_weight,
            "max_weight_lbs": max_weight,
            "status": "AVAILABLE",
        }
    )
    DB["gear_items"][item["id"]] = item
    return ok_object(public(item), 201)


@app.route("/gear-items", methods=["GET"])
def list_gear_items():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    return list_response("gear_items", [("gear_type", "gear_type"), ("status", "status")])


@app.route("/gear-items/<giid>", methods=["GET"])
def get_gear_item(giid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    item = require("gear_items", giid, "ERR_GEAR_NOT_FOUND")
    return ok_object(public(item))


@app.route("/gear-items/<giid>/retire", methods=["POST"])
def retire_gear_item(giid):
    authorize({"OutfitterManager"})
    item = require("gear_items", giid, "ERR_GEAR_NOT_FOUND")
    if item["status"] != "AVAILABLE":
        raise ApiError("ERR_GEAR_UNAVAILABLE")
    item["status"] = "OUT_OF_SERVICE"
    touch(item)
    return ok_object(public(item))


# ===========================================================================
# ROUTES — GearAssignment
# ===========================================================================
@app.route("/gear-assignments", methods=["POST"])
def create_gear_assignment():
    authorize({"Reservationist"})
    body = get_body()
    gear_item_id = f_str(body, "gear_item_id")
    guest_id = f_str(body, "guest_id")
    trip_id = f_str(body, "trip_id")
    item = require("gear_items", gear_item_id, "ERR_GEAR_NOT_FOUND")
    guest = require("guests", guest_id, "ERR_GUEST_NOT_FOUND")
    require("trips", trip_id, "ERR_TRIP_NOT_FOUND")
    # state (priority 4): gear must be AVAILABLE
    if item["status"] != "AVAILABLE":
        raise ApiError("ERR_GEAR_UNAVAILABLE")
    # safety (priority 5): weight range for weight-sensitive gear
    if item["gear_type"] in WEIGHT_SENSITIVE:
        if not (item["min_weight_lbs"] <= guest["weight_lbs"] <= item["max_weight_lbs"]):
            raise ApiError("ERR_WEIGHT_OUT_OF_RANGE")
    # constraint (priority 7): duplicate gear type for the guest
    for ga in guest_gear_assignments(guest_id, "ASSIGNED"):
        existing = DB["gear_items"].get(ga["gear_item_id"])
        if existing is not None and existing["gear_type"] == item["gear_type"]:
            raise ApiError("ERR_DUPLICATE_GEAR_TYPE")

    ga = new_common()
    ga.update(
        {
            "gear_item_id": gear_item_id,
            "guest_id": guest_id,
            "trip_id": trip_id,
            "status": "ASSIGNED",
        }
    )
    DB["gear_assignments"][ga["id"]] = ga
    item["status"] = "ASSIGNED"
    touch(item)
    return ok_object(public(ga), 201)


@app.route("/gear-assignments", methods=["GET"])
def list_gear_assignments():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    return list_response(
        "gear_assignments",
        [
            ("gear_item_id", "gear_item_id"),
            ("guest_id", "guest_id"),
            ("trip_id", "trip_id"),
            ("status", "status"),
        ],
    )


@app.route("/gear-assignments/<gaid>", methods=["GET"])
def get_gear_assignment(gaid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    ga = require("gear_assignments", gaid, "ERR_GEAR_ASSIGNMENT_NOT_FOUND")
    return ok_object(public(ga))


@app.route("/gear-assignments/<gaid>/release", methods=["POST"])
def release_gear_assignment_route(gaid):
    authorize({"Reservationist"})
    ga = require("gear_assignments", gaid, "ERR_GEAR_ASSIGNMENT_NOT_FOUND")
    if ga["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_GEAR_STATE")
    release_gear_assignment(ga)
    return ok_object(public(ga))


# ===========================================================================
# ROUTES — ShuttleVehicle
# ===========================================================================
@app.route("/shuttle-vehicles", methods=["POST"])
def create_shuttle_vehicle():
    authorize({"OutfitterManager"})
    body = get_body()
    name = f_str(body, "name")
    seat_capacity = f_int(body, "seat_capacity", minimum=1)
    v = new_common()
    v.update({"name": name, "seat_capacity": seat_capacity})
    DB["shuttle_vehicles"][v["id"]] = v
    return ok_object(public(v), 201)


@app.route("/shuttle-vehicles", methods=["GET"])
def list_shuttle_vehicles():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    return list_response("shuttle_vehicles", [])


@app.route("/shuttle-vehicles/<svid>", methods=["GET"])
def get_shuttle_vehicle(svid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    v = require("shuttle_vehicles", svid, "ERR_SHUTTLE_VEHICLE_NOT_FOUND")
    return ok_object(public(v))


# ===========================================================================
# ROUTES — ShuttleRun
# ===========================================================================
@app.route("/shuttle-runs", methods=["POST"])
def create_shuttle_run():
    authorize({"OutfitterManager"})
    body = get_body()
    trip_id = f_str(body, "trip_id")
    shuttle_vehicle_id = f_str(body, "shuttle_vehicle_id")
    direction = f_enum(body, "direction", DIRECTIONS)
    depart_time = f_dt(body, "depart_time")
    arrive_time = f_dt(body, "arrive_time")
    d = parse_iso(depart_time)
    a = parse_iso(arrive_time)
    if a <= d:
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    require("trips", trip_id, "ERR_TRIP_NOT_FOUND")
    require("shuttle_vehicles", shuttle_vehicle_id, "ERR_SHUTTLE_VEHICLE_NOT_FOUND")
    # constraint (priority 7): vehicle turnaround buffer
    for run in DB["shuttle_runs"].values():
        if run["shuttle_vehicle_id"] != shuttle_vehicle_id or run["status"] != "SCHEDULED":
            continue
        ed = parse_iso(run["depart_time"])
        ea = parse_iso(run["arrive_time"])
        if d >= ea:
            gap = d - ea
        elif ed >= a:
            gap = ed - a
        else:
            gap = timedelta(seconds=-1)  # overlap
        if gap < SHUTTLE_BUFFER:
            raise ApiError("ERR_SHUTTLE_BUFFER_CONFLICT")

    run = new_common()
    run.update(
        {
            "trip_id": trip_id,
            "shuttle_vehicle_id": shuttle_vehicle_id,
            "direction": direction,
            "depart_time": depart_time,
            "arrive_time": arrive_time,
            "status": "SCHEDULED",
        }
    )
    DB["shuttle_runs"][run["id"]] = run
    return ok_object(public(run), 201)


@app.route("/shuttle-runs", methods=["GET"])
def list_shuttle_runs():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    return list_response(
        "shuttle_runs",
        [
            ("trip_id", "trip_id"),
            ("shuttle_vehicle_id", "shuttle_vehicle_id"),
            ("status", "status"),
        ],
    )


@app.route("/shuttle-runs/<srid>", methods=["GET"])
def get_shuttle_run(srid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    run = require("shuttle_runs", srid, "ERR_SHUTTLE_RUN_NOT_FOUND")
    return ok_object(public(run))


@app.route("/shuttle-runs/<srid>/cancel", methods=["POST"])
def cancel_shuttle_run(srid):
    authorize({"OutfitterManager"})
    run = require("shuttle_runs", srid, "ERR_SHUTTLE_RUN_NOT_FOUND")
    if run["status"] == "SCHEDULED":
        run["status"] = "CANCELLED"
        touch(run)
    return ok_object(public(run))


# ===========================================================================
# ROUTES — RiverConditionReading
# ===========================================================================
@app.route("/condition-readings", methods=["POST"])
def create_condition_reading():
    authorize({"SafetyOfficer"})
    body = get_body()
    trip_id = f_str(body, "trip_id")
    flow_cfs = f_num(body, "flow_cfs")
    reading_time = f_dt(body, "reading_time")
    trip = require("trips", trip_id, "ERR_TRIP_NOT_FOUND")

    band = flow_band(trip, flow_cfs)
    reading = new_reading_common()
    reading.update(
        {
            "trip_id": trip_id,
            "flow_cfs": flow_cfs,
            "reading_time": reading_time,
            "resulting_band": band,
        }
    )
    DB["condition_readings"][reading["id"]] = reading

    # Drive trip posture automatically.
    if band == "SAFE":
        if trip["status"] == "WEATHER_HOLD":
            before = trip_snapshot(trip)
            trip["status"] = "OPEN"
            recompute_trip_aggregates(trip)
            if trip_snapshot(trip) != before:
                touch(trip)
    elif band == "MARGINAL":
        if trip["status"] in ("OPEN", "FULL"):
            before = trip_snapshot(trip)
            trip["status"] = "WEATHER_HOLD"
            recompute_trip_aggregates(trip)
            if trip_snapshot(trip) != before:
                touch(trip)
    else:  # UNSAFE
        if trip["status"] in ("SCHEDULED", "OPEN", "FULL", "WEATHER_HOLD"):
            before = trip_snapshot(trip)
            trip["status"] = "CANCELLED"
            cancel_trip_cascade(trip)
            recompute_trip_aggregates(trip)
            if trip_snapshot(trip) != before:
                touch(trip)

    return ok_object(public(reading), 201)


@app.route("/condition-readings", methods=["GET"])
def list_condition_readings():
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    return list_response("condition_readings", [("trip_id", "trip_id")])


@app.route("/condition-readings/<crid>", methods=["GET"])
def get_condition_reading(crid):
    authorize({"OutfitterManager", "Reservationist", "SafetyOfficer"})
    reading = require("condition_readings", crid, "ERR_CONDITION_READING_NOT_FOUND")
    return ok_object(public(reading))


# ===========================================================================
# ROUTES — Logical clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global LOGICAL_NOW
    authorize({"OutfitterManager"})
    body = get_body()
    to_iso = f_dt(body, "to_iso8601")
    LOGICAL_NOW = parse_iso(to_iso)
    return ok_object({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress, a robust pure-Python WSGI server. The werkzeug dev
    # server's threaded mode has a known keep-alive race under concurrent load
    # that surfaces as intermittent BadStatusLine/ConnectionError on the client
    # side; waitress avoids it.
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
