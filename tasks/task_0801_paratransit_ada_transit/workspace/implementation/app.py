"""
Paratransit / ADA Complementary Transit API (task_0801).

Single-file Flask implementation with in-memory storage only. The store is
rebuilt empty on every process start; the test harness restarts this server via
start.sh before every individual test (--isolation per-test-server).
"""

import os
import math
import random
import string
import threading
from datetime import datetime, timedelta, timezone

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CROSS_ZONE_SURCHARGE_CENTS = 150
FARE_CAP_MULTIPLIER = 2
COMPANION_FARE_CENTS = 275

ROLLING_WINDOW_DAYS = 30
WARNING_THRESHOLD_POINTS = 3
SUSPENSION_THRESHOLD_POINTS = 6
TIER1_SUSPENSION_DAYS = 7
TIER2_SUSPENSION_DAYS = 15
TIER3_SUSPENSION_DAYS = 30

NO_SHOW_POINTS = 3
LATE_CANCEL_POINTS = 1

R_MILES = 3958.7613
PICKUP_WINDOW_MINUTES = 30
TURNAROUND_BUFFER_MINUTES = 15

CERT_VALIDITY_DAYS = 1095
TRIP_DURATION_MINUTES = 60
LATE_CANCEL_LEAD_HOURS = 2

DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

ROLES = {"Rider", "Dispatcher", "Driver", "EligibilitySpecialist", "Admin"}
MOBILITY_DEVICES = {"NONE", "CANE", "WALKER", "MANUAL_WHEELCHAIR", "POWER_WHEELCHAIR", "SCOOTER"}
APPLICATION_TYPES = {"NEW", "RECERT"}
COMPLETE_OUTCOMES = {"PASS_UNCONDITIONAL", "PASS_CONDITIONAL", "FAIL"}
DAYS_OF_WEEK = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}

TRIP_TERMINAL = {"COMPLETED", "CANCELLED", "LATE_CANCELLED", "NO_SHOW", "CANCELLED_BY_SYSTEM"}
TRIP_HOLDING = {"SCHEDULED", "EN_ROUTE", "PICKED_UP"}  # occupy run capacity

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.riders = {}
        self.zones = {}
        self.applications = {}
        self.assessments = {}
        self.trips = {}
        self.offers = {}
        self.subscriptions = {}
        self.runs = {}
        self.penalties = {}
        self._seq = 0
        self.clock = parse_dt(DEFAULT_CLOCK)

    def next_seq(self):
        self._seq += 1
        return self._seq


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def clock_now():
    return db.clock


# ---------------------------------------------------------------------------
# Errors + response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") +
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


def err_response(e: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def _handle_404(e):
    return err_response(ApiError("ERR_INVALID_REQUEST", 400, "Unknown route"))


@app.errorhandler(405)
def _handle_405(e):
    return err_response(ApiError("ERR_INVALID_REQUEST", 400, "Method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return err_response(e)
    return err_response(ApiError("ERR_INVALID_REQUEST", 400, "Bad request: %s" % e))


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role %s not permitted" % role)


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Body must be a JSON object")
    return data


def require_present(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % f)


def as_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be a non-empty string" % field)
    return v


def as_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be a number" % field)
    return v


def as_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % field)
    return v


def as_bool(body, field, default=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be a boolean" % field)
    return v


def check_datetime(body, field):
    try:
        parse_dt(body.get(field))
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an ISO-8601 datetime" % field)


def check_coord(lat, lng):
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        raise ApiError("ERR_OUT_OF_RANGE", 422, "Coordinates out of range")


def new_id():
    import uuid
    return str(uuid.uuid4())


def stamp_new(entity, audited=True):
    now = fmt_dt(clock_now())
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["_seq"] = db.next_seq()
    if audited:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def bump(entity):
    entity["updated_at"] = fmt_dt(clock_now())
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_rider(rid):
    r = db.riders.get(rid)
    if r is None:
        raise ApiError("ERR_RIDER_NOT_FOUND", 404, "Rider not found")
    return r


def get_zone(zid):
    z = db.zones.get(zid)
    if z is None:
        raise ApiError("ERR_ZONE_NOT_FOUND", 404, "Service zone not found")
    return z


def get_application(aid):
    a = db.applications.get(aid)
    if a is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Eligibility application not found")
    return a


def get_assessment(aid):
    a = db.assessments.get(aid)
    if a is None:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND", 404, "Functional assessment not found")
    return a


def get_trip(tid):
    t = db.trips.get(tid)
    if t is None:
        raise ApiError("ERR_TRIP_NOT_FOUND", 404, "Trip reservation not found")
    return t


def get_subscription(sid):
    s = db.subscriptions.get(sid)
    if s is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription trip not found")
    return s


def get_run(rid):
    r = db.runs.get(rid)
    if r is None:
        raise ApiError("ERR_RUN_NOT_FOUND", 404, "Vehicle run not found")
    return r


def get_penalty(pid):
    p = db.penalties.get(pid)
    if p is None:
        raise ApiError("ERR_PENALTY_NOT_FOUND", 404, "Penalty event not found")
    return p


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def pagination():
    def parse_int_param(name, default, minimum, maximum):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid %s" % name)
        if minimum is not None and v < minimum:
            v = minimum
        if maximum is not None and v > maximum:
            v = maximum
        return v

    limit = parse_int_param("limit", 10, 1, 100)
    offset = parse_int_param("offset", 0, 0, None)
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    rows = sorted(rows, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def penalty_totals(rider_id):
    clock = clock_now()
    window_start = clock - timedelta(days=ROLLING_WINDOW_DAYS)
    rolling = 0
    lifetime = 0
    for p in db.penalties.values():
        if p["rider_id"] != rider_id or p["status"] != "ACTIVE":
            continue
        lifetime += p["points"]
        if parse_dt(p["occurred_at"]) >= window_start:
            rolling += p["points"]
    return rolling, lifetime


def penalty_tier_for(rolling):
    if rolling >= SUSPENSION_THRESHOLD_POINTS:
        return "SUSPENDED"
    if rolling >= WARNING_THRESHOLD_POINTS:
        return "WARNING"
    return "NONE"


def serialize_rider(r):
    rolling, lifetime = penalty_totals(r["id"])
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "phone": r["phone"],
        "email": r["email"],
        "home_lat": r["home_lat"],
        "home_lng": r["home_lng"],
        "mobility_device": r["mobility_device"],
        "requires_pca": r["requires_pca"],
        "eligibility_status": r["eligibility_status"],
        "certification_expires_at": r["certification_expires_at"],
        "account_status": r["account_status"],
        "suspension_until": r["suspension_until"],
        "prior_suspension_count": r["prior_suspension_count"],
        "no_show_points_rolling": rolling,
        "no_show_points_lifetime": lifetime,
        "penalty_tier": penalty_tier_for(rolling),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_zone(z):
    return {
        "id": z["id"],
        "zone_code": z["zone_code"],
        "name": z["name"],
        "center_lat": z["center_lat"],
        "center_lng": z["center_lng"],
        "service_radius_miles": z["service_radius_miles"],
        "base_fare_cents": z["base_fare_cents"],
        "fixed_route_fare_cents": z["fixed_route_fare_cents"],
        "created_at": z["created_at"],
    }


def serialize_application(a):
    return {
        "id": a["id"],
        "rider_id": a["rider_id"],
        "application_type": a["application_type"],
        "status": a["status"],
        "assessment_outcome": a["assessment_outcome"],
        "certified_category": a["certified_category"],
        "certification_valid_until": a["certification_valid_until"],
        "appeal_count": a["appeal_count"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_assessment(a):
    return {
        "id": a["id"],
        "application_id": a["application_id"],
        "scheduled_at": a["scheduled_at"],
        "status": a["status"],
        "outcome": a["outcome"],
        "assessed_mobility_device": a["assessed_mobility_device"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_trip(t):
    return {
        "id": t["id"],
        "rider_id": t["rider_id"],
        "subscription_trip_id": t["subscription_trip_id"],
        "pickup_zone_id": t["pickup_zone_id"],
        "dropoff_zone_id": t["dropoff_zone_id"],
        "pickup_lat": t["pickup_lat"],
        "pickup_lng": t["pickup_lng"],
        "dropoff_lat": t["dropoff_lat"],
        "dropoff_lng": t["dropoff_lng"],
        "requested_pickup_at": t["requested_pickup_at"],
        "needs_wheelchair": t["needs_wheelchair"],
        "num_companions": t["num_companions"],
        "has_pca": t["has_pca"],
        "status": t["status"],
        "current_offer_pickup_at": t["current_offer_pickup_at"],
        "offer_round": t["offer_round"],
        "assigned_run_id": t["assigned_run_id"],
        "scheduled_pickup_at": t["scheduled_pickup_at"],
        "scheduled_dropoff_at": t["scheduled_dropoff_at"],
        "estimated_fare_cents": t["estimated_fare_cents"],
        "final_fare_cents": t["final_fare_cents"],
        "on_time": t["on_time"],
        "late_cancel": t["late_cancel"],
        "actual_pickup_at": t.get("actual_pickup_at"),
        "actual_pickup_zone_id": t.get("actual_pickup_zone_id"),
        "actual_dropoff_at": t.get("actual_dropoff_at"),
        "actual_dropoff_zone_id": t.get("actual_dropoff_zone_id"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_offer(o):
    return {
        "id": o["id"],
        "trip_id": o["trip_id"],
        "offered_by": o["offered_by"],
        "proposed_pickup_at": o["proposed_pickup_at"],
        "round_number": o["round_number"],
        "created_at": o["created_at"],
    }


def serialize_subscription(s):
    return {
        "id": s["id"],
        "rider_id": s["rider_id"],
        "pickup_zone_id": s["pickup_zone_id"],
        "dropoff_zone_id": s["dropoff_zone_id"],
        "pickup_lat": s["pickup_lat"],
        "pickup_lng": s["pickup_lng"],
        "dropoff_lat": s["dropoff_lat"],
        "dropoff_lng": s["dropoff_lng"],
        "day_of_week": s["day_of_week"],
        "pickup_time_utc": s["pickup_time_utc"],
        "needs_wheelchair": s["needs_wheelchair"],
        "num_companions": s["num_companions"],
        "has_pca": s["has_pca"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_run(r):
    amb, wc = run_availability(r)
    return {
        "id": r["id"],
        "service_zone_id": r["service_zone_id"],
        "service_date": r["service_date"],
        "total_ambulatory_seats": r["total_ambulatory_seats"],
        "total_wheelchair_positions": r["total_wheelchair_positions"],
        "available_ambulatory_seats": amb,
        "available_wheelchair_positions": wc,
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_penalty(p):
    return {
        "id": p["id"],
        "rider_id": p["rider_id"],
        "trip_id": p["trip_id"],
        "event_type": p["event_type"],
        "points": p["points"],
        "status": p["status"],
        "occurred_at": p["occurred_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


# ---------------------------------------------------------------------------
# Capacity / geometry helpers
# ---------------------------------------------------------------------------
def haversine_miles(lat1, lng1, lat2, lng2):
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlambda / 2) ** 2
    return 2 * R_MILES * math.asin(math.sqrt(a))


def in_service_area(zone, lat, lng):
    dist = haversine_miles(zone["center_lat"], zone["center_lng"], lat, lng)
    return dist <= zone["service_radius_miles"]


def amb_demand(t):
    d = 0 if t["needs_wheelchair"] else 1
    d += t.get("num_companions", 0) or 0
    d += 1 if t.get("has_pca") else 0
    return d


def wc_demand(t):
    return 1 if t["needs_wheelchair"] else 0


def held_trips_for_run(run_id, exclude_trip_id=None):
    out = []
    for t in db.trips.values():
        if t["assigned_run_id"] == run_id and t["status"] in TRIP_HOLDING:
            if exclude_trip_id and t["id"] == exclude_trip_id:
                continue
            if t["scheduled_pickup_at"] and t["scheduled_dropoff_at"]:
                out.append(t)
    return out


def peak_demand(trips, demand_fn, restrict=None):
    """Max concurrent demand (closed intervals) across trips.

    If restrict=(s, e) is given, only sample instants within [s, e]."""
    intervals = []
    for t in trips:
        d = demand_fn(t)
        if d <= 0:
            continue
        s = parse_dt(t["scheduled_pickup_at"])
        e = parse_dt(t["scheduled_dropoff_at"])
        intervals.append((s, e, d))
    if not intervals:
        return 0
    candidates = set()
    for s, e, _ in intervals:
        candidates.add(s)
        candidates.add(e)
    if restrict is not None:
        rs, re = restrict
        candidates = {c for c in candidates if rs <= c <= re}
        candidates.add(rs)
    peak = 0
    for c in candidates:
        active = sum(d for s, e, d in intervals if s <= c <= e)
        if active > peak:
            peak = active
    return peak


def run_availability(run):
    held = held_trips_for_run(run["id"])
    peak_amb = peak_demand(held, amb_demand)
    peak_wc = peak_demand(held, wc_demand)
    return (run["total_ambulatory_seats"] - peak_amb,
            run["total_wheelchair_positions"] - peak_wc)


# ---------------------------------------------------------------------------
# Rider booking-eligibility gate
# ---------------------------------------------------------------------------
def check_booking_gates(rider, check_suspension, check_expiry):
    allowed = {"FULL", "CONDITIONAL"}
    if check_suspension:
        # Let a suspended-but-certified rider through the eligibility gate so the
        # dedicated suspension gate reports ERR_RIDER_SUSPENDED (priority 8).
        allowed = allowed | {"SUSPENDED"}
    if rider["eligibility_status"] not in allowed:
        raise ApiError("ERR_RIDER_NOT_ELIGIBLE", 409, "Rider is not eligible to book")
    if check_suspension and rider["account_status"] == "SUSPENDED":
        raise ApiError("ERR_RIDER_SUSPENDED", 409, "Rider is under a no-show suspension")
    if check_expiry:
        exp = rider["certification_expires_at"]
        if exp is None or parse_dt(exp) <= clock_now():
            raise ApiError("ERR_ELIGIBILITY_EXPIRED", 409, "Rider certification has lapsed")


# ---------------------------------------------------------------------------
# Penalty recomputation + suspension
# ---------------------------------------------------------------------------
def create_penalty(rider_id, trip_id, event_type, points):
    p = {
        "rider_id": rider_id,
        "trip_id": trip_id,
        "event_type": event_type,
        "points": points,
        "status": "ACTIVE",
        "occurred_at": fmt_dt(clock_now()),
    }
    stamp_new(p, audited=True)
    db.penalties[p["id"]] = p
    return p


def release_run_capacity(trip):
    """When a holding trip leaves, bump its run version (capacity auto-recomputes)."""
    run_id = trip.get("assigned_run_id")
    if run_id and run_id in db.runs:
        bump(db.runs[run_id])


# ---------------------------------------------------------------------------
# Routes: logical clock + config
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin"})
        body = get_body()
        require_present(body, ["to_iso8601"])
        check_datetime(body, "to_iso8601")
        db.clock = parse_dt(body["to_iso8601"])
        return ok({"current_utc": fmt_dt(db.clock)}, 200)


@app.route("/service-zones", methods=["POST"])
def create_zone():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin"})
        body = get_body()
        require_present(body, ["zone_code", "name", "center_lat", "center_lng",
                               "base_fare_cents", "fixed_route_fare_cents"])
        zone_code = as_str(body, "zone_code")
        name = as_str(body, "name")
        center_lat = as_number(body, "center_lat")
        center_lng = as_number(body, "center_lng")
        base_fare = as_int(body, "base_fare_cents")
        fixed_fare = as_int(body, "fixed_route_fare_cents")
        radius = 0.75
        if body.get("service_radius_miles") is not None:
            radius = as_number(body, "service_radius_miles")
        check_coord(center_lat, center_lng)
        if base_fare < 0 or fixed_fare < 0 or radius < 0:
            raise ApiError("ERR_OUT_OF_RANGE", 422, "Negative fare or radius")
        for z in db.zones.values():
            if z["zone_code"] == zone_code:
                raise ApiError("ERR_INVALID_REQUEST", 400, "zone_code must be unique")
        z = {
            "zone_code": zone_code, "name": name,
            "center_lat": center_lat, "center_lng": center_lng,
            "service_radius_miles": radius,
            "base_fare_cents": base_fare, "fixed_route_fare_cents": fixed_fare,
        }
        stamp_new(z, audited=False)
        db.zones[z["id"]] = z
        return ok(serialize_zone(z), 201)


# ---------------------------------------------------------------------------
# Routes: riders
# ---------------------------------------------------------------------------
@app.route("/riders", methods=["POST"])
def create_rider():
    with LOCK:
        _, role = auth()
        require_roles(role, {"EligibilitySpecialist", "Admin"})
        body = get_body()
        require_present(body, ["full_name", "phone", "email", "home_lat", "home_lng"])
        full_name = as_str(body, "full_name")
        phone = as_str(body, "phone")
        email = as_str(body, "email")
        home_lat = as_number(body, "home_lat")
        home_lng = as_number(body, "home_lng")
        mobility = body.get("mobility_device", "NONE")
        if mobility is None:
            mobility = "NONE"
        if mobility not in MOBILITY_DEVICES:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid mobility_device")
        requires_pca = as_bool(body, "requires_pca", False)
        check_coord(home_lat, home_lng)
        r = {
            "full_name": full_name, "phone": phone, "email": email,
            "home_lat": home_lat, "home_lng": home_lng,
            "mobility_device": mobility, "requires_pca": requires_pca,
            "eligibility_status": "UNCERTIFIED",
            "certification_expires_at": None,
            "account_status": "ACTIVE",
            "suspension_until": None,
            "prior_suspension_count": 0,
        }
        stamp_new(r, audited=True)
        db.riders[r["id"]] = r
        return ok(serialize_rider(r), 201)


@app.route("/riders/<rid>", methods=["GET"])
def read_rider(rid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "Dispatcher", "Driver", "EligibilitySpecialist", "Rider"})
        r = get_rider(rid)
        return ok(serialize_rider(r), 200)


# ---------------------------------------------------------------------------
# Routes: eligibility applications
# ---------------------------------------------------------------------------
@app.route("/eligibility-applications", methods=["POST"])
def create_application():
    with LOCK:
        _, role = auth()
        require_roles(role, {"EligibilitySpecialist"})
        body = get_body()
        require_present(body, ["rider_id"])
        rider_id = as_str(body, "rider_id")
        app_type = body.get("application_type", "NEW")
        if app_type is None:
            app_type = "NEW"
        if app_type not in APPLICATION_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid application_type")
        get_rider(rider_id)
        for a in db.applications.values():
            if a["rider_id"] == rider_id and a["status"] != "CERTIFIED":
                raise ApiError("ERR_DUPLICATE_ACTIVE_APPLICATION", 409,
                               "Rider already has a non-terminal application")
        a = {
            "rider_id": rider_id,
            "application_type": app_type,
            "status": "SUBMITTED",
            "assessment_outcome": None,
            "certified_category": None,
            "certification_valid_until": None,
            "appeal_count": 0,
        }
        stamp_new(a, audited=True)
        db.applications[a["id"]] = a
        return ok(serialize_application(a), 201)


@app.route("/eligibility-applications/<aid>", methods=["GET"])
def read_application(aid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "EligibilitySpecialist", "Rider"})
        return ok(serialize_application(get_application(aid)), 200)


@app.route("/eligibility-applications", methods=["GET"])
def list_applications():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "EligibilitySpecialist", "Rider"})
        rows = list(db.applications.values())
        rider_id = request.args.get("rider_id")
        status = request.args.get("status")
        if rider_id is not None:
            rows = [a for a in rows if a["rider_id"] == rider_id]
        if status is not None:
            rows = [a for a in rows if a["status"] == status]
        return paginate(rows, serialize_application)


@app.route("/eligibility-applications/<aid>/certify", methods=["POST"])
def certify_application(aid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"EligibilitySpecialist"})
        a = get_application(aid)
        if a["status"] != "ASSESSED" or a["assessment_outcome"] not in ("PASS_UNCONDITIONAL", "PASS_CONDITIONAL"):
            raise ApiError("ERR_INVALID_STATE", 409, "Application cannot be certified")
        a["status"] = "CERTIFIED"
        a["certified_category"] = "UNCONDITIONAL" if a["assessment_outcome"] == "PASS_UNCONDITIONAL" else "CONDITIONAL"
        valid_until = fmt_dt(clock_now() + timedelta(days=CERT_VALIDITY_DAYS))
        a["certification_valid_until"] = valid_until
        bump(a)
        rider = db.riders.get(a["rider_id"])
        if rider:
            rider["eligibility_status"] = "FULL" if a["certified_category"] == "UNCONDITIONAL" else "CONDITIONAL"
            rider["certification_expires_at"] = valid_until
            bump(rider)
        return ok(serialize_application(a), 200)


@app.route("/eligibility-applications/<aid>/deny", methods=["POST"])
def deny_application(aid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"EligibilitySpecialist"})
        a = get_application(aid)
        if a["status"] != "ASSESSED" or a["assessment_outcome"] != "FAIL":
            raise ApiError("ERR_INVALID_STATE", 409, "Application cannot be denied")
        a["status"] = "DENIED"
        bump(a)
        return ok(serialize_application(a), 200)


@app.route("/eligibility-applications/<aid>/appeal", methods=["POST"])
def appeal_application(aid):
    with LOCK:
        user_id, role = auth()
        require_roles(role, {"EligibilitySpecialist", "Rider"})
        a = get_application(aid)
        if role == "Rider" and a["rider_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "Rider does not own this application")
        if a["status"] != "DENIED":
            raise ApiError("ERR_INVALID_STATE", 409, "Only a denied application can be appealed")
        a["status"] = "APPEALED"
        a["appeal_count"] += 1
        bump(a)
        return ok(serialize_application(a), 200)


# ---------------------------------------------------------------------------
# Routes: functional assessments
# ---------------------------------------------------------------------------
@app.route("/functional-assessments", methods=["POST"])
def create_assessment():
    with LOCK:
        _, role = auth()
        require_roles(role, {"EligibilitySpecialist"})
        body = get_body()
        require_present(body, ["application_id", "scheduled_at"])
        application_id = as_str(body, "application_id")
        check_datetime(body, "scheduled_at")
        a = get_application(application_id)
        if a["status"] not in ("SUBMITTED", "APPEALED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Application is not open for assessment scheduling")
        fa = {
            "application_id": application_id,
            "scheduled_at": body["scheduled_at"],
            "status": "SCHEDULED",
            "outcome": "PENDING",
            "assessed_mobility_device": None,
        }
        stamp_new(fa, audited=True)
        db.assessments[fa["id"]] = fa
        a["status"] = "ASSESSMENT_SCHEDULED"
        bump(a)
        return ok(serialize_assessment(fa), 201)


@app.route("/functional-assessments/<fid>", methods=["GET"])
def read_assessment(fid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "EligibilitySpecialist", "Rider"})
        return ok(serialize_assessment(get_assessment(fid)), 200)


@app.route("/functional-assessments", methods=["GET"])
def list_assessments():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "EligibilitySpecialist", "Rider"})
        rows = list(db.assessments.values())
        application_id = request.args.get("application_id")
        if application_id is not None:
            rows = [f for f in rows if f["application_id"] == application_id]
        return paginate(rows, serialize_assessment)


@app.route("/functional-assessments/<fid>/complete", methods=["POST"])
def complete_assessment(fid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"EligibilitySpecialist"})
        body = get_body()
        require_present(body, ["outcome", "assessed_mobility_device"])
        outcome = body.get("outcome")
        if outcome not in COMPLETE_OUTCOMES:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid outcome")
        device = body.get("assessed_mobility_device")
        if device not in MOBILITY_DEVICES:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid assessed_mobility_device")
        fa = get_assessment(fid)
        a = db.applications.get(fa["application_id"])
        if fa["status"] != "SCHEDULED" or a is None or a["status"] != "ASSESSMENT_SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409, "Assessment cannot be completed")
        fa["status"] = "COMPLETED"
        fa["outcome"] = outcome
        fa["assessed_mobility_device"] = device
        bump(fa)
        a["status"] = "ASSESSED"
        a["assessment_outcome"] = outcome
        bump(a)
        return ok(serialize_assessment(fa), 200)


# ---------------------------------------------------------------------------
# Routes: trip reservations
# ---------------------------------------------------------------------------
def _validate_trip_geometry_and_capacity_fields(body):
    pickup_lat = as_number(body, "pickup_lat")
    pickup_lng = as_number(body, "pickup_lng")
    dropoff_lat = as_number(body, "dropoff_lat")
    dropoff_lng = as_number(body, "dropoff_lng")
    check_coord(pickup_lat, pickup_lng)
    check_coord(dropoff_lat, dropoff_lng)
    num_companions = 0
    if body.get("num_companions") is not None:
        num_companions = as_int(body, "num_companions")
        if num_companions < 0:
            raise ApiError("ERR_OUT_OF_RANGE", 422, "num_companions must be non-negative")
    needs_wheelchair = as_bool(body, "needs_wheelchair", False)
    has_pca = as_bool(body, "has_pca", False)
    return pickup_lat, pickup_lng, dropoff_lat, dropoff_lng, num_companions, needs_wheelchair, has_pca


@app.route("/trip-reservations", methods=["POST"])
def create_trip():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Rider"})
        body = get_body()
        require_present(body, ["rider_id", "pickup_zone_id", "dropoff_zone_id",
                               "pickup_lat", "pickup_lng", "dropoff_lat", "dropoff_lng",
                               "requested_pickup_at"])
        rider_id = as_str(body, "rider_id")
        pickup_zone_id = as_str(body, "pickup_zone_id")
        dropoff_zone_id = as_str(body, "dropoff_zone_id")
        check_datetime(body, "requested_pickup_at")
        (pickup_lat, pickup_lng, dropoff_lat, dropoff_lng,
         num_companions, needs_wheelchair, has_pca) = _validate_trip_geometry_and_capacity_fields(body)
        # existence, left-to-right
        rider = get_rider(rider_id)
        pickup_zone = get_zone(pickup_zone_id)
        dropoff_zone = get_zone(dropoff_zone_id)
        # eligibility gates
        check_booking_gates(rider, check_suspension=True, check_expiry=True)
        # service area
        if not in_service_area(pickup_zone, pickup_lat, pickup_lng) or \
           not in_service_area(dropoff_zone, dropoff_lat, dropoff_lng):
            raise ApiError("ERR_OUTSIDE_SERVICE_AREA", 422, "Pickup or dropoff outside service area")
        t = _new_trip_dict(rider_id, None, pickup_zone_id, dropoff_zone_id,
                           pickup_lat, pickup_lng, dropoff_lat, dropoff_lng,
                           body["requested_pickup_at"], needs_wheelchair, num_companions, has_pca)
        db.trips[t["id"]] = t
        return ok(serialize_trip(t), 201)


def _new_trip_dict(rider_id, subscription_trip_id, pickup_zone_id, dropoff_zone_id,
                   pickup_lat, pickup_lng, dropoff_lat, dropoff_lng,
                   requested_pickup_at, needs_wheelchair, num_companions, has_pca):
    t = {
        "rider_id": rider_id,
        "subscription_trip_id": subscription_trip_id,
        "pickup_zone_id": pickup_zone_id,
        "dropoff_zone_id": dropoff_zone_id,
        "pickup_lat": pickup_lat, "pickup_lng": pickup_lng,
        "dropoff_lat": dropoff_lat, "dropoff_lng": dropoff_lng,
        "requested_pickup_at": requested_pickup_at,
        "needs_wheelchair": needs_wheelchair,
        "num_companions": num_companions,
        "has_pca": has_pca,
        "status": "REQUESTED",
        "current_offer_pickup_at": None,
        "offer_round": 0,
        "assigned_run_id": None,
        "scheduled_pickup_at": None,
        "scheduled_dropoff_at": None,
        "estimated_fare_cents": None,
        "final_fare_cents": None,
        "on_time": None,
        "late_cancel": False,
        "actual_pickup_at": None,
        "actual_pickup_zone_id": None,
        "actual_dropoff_at": None,
        "actual_dropoff_zone_id": None,
    }
    stamp_new(t, audited=True)
    return t


@app.route("/trip-reservations/<tid>", methods=["GET"])
def read_trip(tid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "Dispatcher", "Driver", "EligibilitySpecialist", "Rider"})
        return ok(serialize_trip(get_trip(tid)), 200)


@app.route("/trip-reservations", methods=["GET"])
def list_trips():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "Dispatcher", "Driver", "EligibilitySpecialist", "Rider"})
        rows = list(db.trips.values())
        for key in ("rider_id", "pickup_zone_id", "dropoff_zone_id", "subscription_trip_id", "status"):
            val = request.args.get(key)
            if val is not None:
                rows = [t for t in rows if t[key] == val]
        return paginate(rows, serialize_trip)


def compute_fare(pickup_zone, dropoff_zone, num_companions):
    if pickup_zone["id"] == dropoff_zone["id"]:
        base = pickup_zone["base_fare_cents"]
    else:
        base = max(pickup_zone["base_fare_cents"], dropoff_zone["base_fare_cents"]) + CROSS_ZONE_SURCHARGE_CENTS
    capped = min(base, FARE_CAP_MULTIPLIER * pickup_zone["fixed_route_fare_cents"])
    return capped + COMPANION_FARE_CENTS * num_companions


@app.route("/trip-reservations/<tid>/offer", methods=["POST"])
def offer_trip(tid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Dispatcher"})
        body = get_body()
        require_present(body, ["proposed_pickup_at"])
        check_datetime(body, "proposed_pickup_at")
        t = get_trip(tid)
        if t["status"] not in ("REQUESTED", "COUNTERED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Trip cannot be offered from its current state")
        _record_offer(t, "DISPATCHER", body["proposed_pickup_at"])
        return ok(serialize_trip(t), 200)


@app.route("/trip-reservations/<tid>/counter", methods=["POST"])
def counter_trip(tid):
    with LOCK:
        user_id, role = auth()
        require_roles(role, {"Rider"})
        body = get_body()
        require_present(body, ["proposed_pickup_at"])
        check_datetime(body, "proposed_pickup_at")
        t = get_trip(tid)
        if t["rider_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "Rider does not own this trip")
        if t["status"] != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", 409, "Trip cannot be countered from its current state")
        _record_offer(t, "RIDER", body["proposed_pickup_at"])
        return ok(serialize_trip(t), 200)


def _record_offer(t, offered_by, proposed_pickup_at):
    t["offer_round"] += 1
    t["current_offer_pickup_at"] = proposed_pickup_at
    t["status"] = "COUNTERED" if offered_by == "RIDER" else "OFFERED"
    o = {
        "trip_id": t["id"],
        "offered_by": offered_by,
        "proposed_pickup_at": proposed_pickup_at,
        "round_number": t["offer_round"],
    }
    stamp_new(o, audited=False)
    db.offers[o["id"]] = o
    bump(t)


@app.route("/trip-reservations/<tid>/accept", methods=["POST"])
def accept_trip(tid):
    with LOCK:
        user_id, role = auth()
        require_roles(role, {"Rider"})
        body = get_body()
        require_present(body, ["run_id", "expected_run_version"])
        run_id = as_str(body, "run_id")
        expected_version = as_int(body, "expected_run_version")
        t = get_trip(tid)
        if t["rider_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "Rider does not own this trip")
        run = get_run(run_id)
        rider = db.riders.get(t["rider_id"])
        # ordered checks per PRD 3.6
        if t["status"] != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", 409, "Trip must be OFFERED to accept")
        if rider["account_status"] == "SUSPENDED":
            raise ApiError("ERR_RIDER_SUSPENDED", 409, "Rider is suspended")
        if run["status"] not in ("PLANNED", "OPEN"):
            raise ApiError("ERR_RUN_NOT_OPEN", 409, "Vehicle run is not open for booking")
        if expected_version != run["version"]:
            raise ApiError("ERR_STALE_RUN_VERSION", 412, "Run version is stale")

        sched_pickup = parse_dt(t["current_offer_pickup_at"])
        sched_dropoff = sched_pickup + timedelta(minutes=TRIP_DURATION_MINUTES)
        candidate = {
            "needs_wheelchair": t["needs_wheelchair"],
            "num_companions": t["num_companions"],
            "has_pca": t["has_pca"],
            "scheduled_pickup_at": fmt_dt(sched_pickup),
            "scheduled_dropoff_at": fmt_dt(sched_dropoff),
        }
        held = held_trips_for_run(run_id, exclude_trip_id=t["id"])
        restrict = (sched_pickup, sched_dropoff)
        # wheelchair capacity
        if t["needs_wheelchair"]:
            peak_wc = peak_demand(held + [candidate], wc_demand, restrict=restrict)
            if peak_wc > run["total_wheelchair_positions"]:
                raise ApiError("ERR_NO_WHEELCHAIR_CAPACITY", 409, "No wheelchair position available")
        # ambulatory capacity
        peak_amb = peak_demand(held + [candidate], amb_demand, restrict=restrict)
        if peak_amb > run["total_ambulatory_seats"]:
            raise ApiError("ERR_NO_SEAT_CAPACITY", 409, "No ambulatory seats available")
        # rider overlap
        _check_rider_overlap(t, sched_pickup, sched_dropoff)

        # commit
        pickup_zone = db.zones.get(t["pickup_zone_id"])
        dropoff_zone = db.zones.get(t["dropoff_zone_id"])
        t["status"] = "SCHEDULED"
        t["scheduled_pickup_at"] = t["current_offer_pickup_at"]
        t["scheduled_dropoff_at"] = fmt_dt(sched_dropoff)
        t["assigned_run_id"] = run_id
        t["estimated_fare_cents"] = compute_fare(pickup_zone, dropoff_zone, t["num_companions"])
        bump(t)
        bump(run)
        return ok(serialize_trip(t), 200)


def _check_rider_overlap(trip, sched_pickup, sched_dropoff):
    buf = timedelta(minutes=TURNAROUND_BUFFER_MINUTES)
    new_start = sched_pickup - buf
    new_end = sched_dropoff + buf
    for other in db.trips.values():
        if other["id"] == trip["id"]:
            continue
        if other["rider_id"] != trip["rider_id"]:
            continue
        if other["status"] in TRIP_TERMINAL:
            continue
        if not other["scheduled_pickup_at"] or not other["scheduled_dropoff_at"]:
            continue
        o_start = parse_dt(other["scheduled_pickup_at"]) - buf
        o_end = parse_dt(other["scheduled_dropoff_at"]) + buf
        if new_start <= o_end and o_start <= new_end:
            raise ApiError("ERR_RIDER_TRIP_OVERLAP", 409, "Rider has an overlapping trip")


@app.route("/trip-reservations/<tid>/cancel", methods=["POST"])
def cancel_trip(tid):
    with LOCK:
        user_id, role = auth()
        require_roles(role, {"Rider"})
        t = get_trip(tid)
        if t["rider_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "Rider does not own this trip")
        status = t["status"]
        if status in ("REQUESTED", "OFFERED", "COUNTERED"):
            t["status"] = "CANCELLED"
            bump(t)
            return ok(serialize_trip(t), 200)
        if status == "SCHEDULED":
            lead = parse_dt(t["scheduled_pickup_at"]) - clock_now()
            if lead >= timedelta(hours=LATE_CANCEL_LEAD_HOURS):
                t["status"] = "CANCELLED"
                bump(t)
                release_run_capacity(t)
            else:
                t["status"] = "LATE_CANCELLED"
                t["late_cancel"] = True
                bump(t)
                create_penalty(t["rider_id"], t["id"], "LATE_CANCEL", LATE_CANCEL_POINTS)
                release_run_capacity(t)
            return ok(serialize_trip(t), 200)
        raise ApiError("ERR_INVALID_STATE", 409, "Trip cannot be cancelled from its current state")


@app.route("/trip-reservations/<tid>/pickup", methods=["POST"])
def pickup_trip(tid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Driver"})
        body = get_body()
        require_present(body, ["actual_pickup_at", "actual_pickup_zone_id"])
        check_datetime(body, "actual_pickup_at")
        actual_pickup_zone_id = as_str(body, "actual_pickup_zone_id")
        t = get_trip(tid)
        get_zone(actual_pickup_zone_id)
        if t["status"] not in ("SCHEDULED", "EN_ROUTE"):
            raise ApiError("ERR_INVALID_STATE", 409, "Trip cannot be picked up from its current state")
        actual = parse_dt(body["actual_pickup_at"])
        window_start = parse_dt(t["scheduled_pickup_at"])
        window_end = window_start + timedelta(minutes=PICKUP_WINDOW_MINUTES)
        t["on_time"] = (actual >= window_start) and (actual <= window_end)
        t["actual_pickup_at"] = body["actual_pickup_at"]
        t["actual_pickup_zone_id"] = actual_pickup_zone_id
        t["status"] = "PICKED_UP"
        bump(t)
        return ok(serialize_trip(t), 200)


@app.route("/trip-reservations/<tid>/dropoff", methods=["POST"])
def dropoff_trip(tid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Driver"})
        body = get_body()
        require_present(body, ["actual_dropoff_at", "actual_dropoff_zone_id"])
        check_datetime(body, "actual_dropoff_at")
        actual_dropoff_zone_id = as_str(body, "actual_dropoff_zone_id")
        t = get_trip(tid)
        dropoff_zone = get_zone(actual_dropoff_zone_id)
        if t["status"] != "PICKED_UP":
            raise ApiError("ERR_INVALID_STATE", 409, "Trip must be PICKED_UP to drop off")
        pickup_zone = db.zones.get(t.get("actual_pickup_zone_id")) or db.zones.get(t["pickup_zone_id"])
        t["actual_dropoff_at"] = body["actual_dropoff_at"]
        t["actual_dropoff_zone_id"] = actual_dropoff_zone_id
        t["final_fare_cents"] = compute_fare(pickup_zone, dropoff_zone, t["num_companions"])
        t["status"] = "COMPLETED"
        bump(t)
        release_run_capacity(t)
        return ok(serialize_trip(t), 200)


@app.route("/trip-reservations/<tid>/no-show", methods=["POST"])
def no_show_trip(tid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Driver", "Dispatcher"})
        t = get_trip(tid)
        if t["status"] not in ("SCHEDULED", "EN_ROUTE"):
            raise ApiError("ERR_INVALID_STATE", 409, "Trip cannot be marked no-show from its current state")
        rider = db.riders.get(t["rider_id"])
        # hop 0: transition + own capacity release
        t["status"] = "NO_SHOW"
        bump(t)
        # hop 1: penalty
        create_penalty(t["rider_id"], t["id"], "NO_SHOW", NO_SHOW_POINTS)
        # hop 2: recompute rolling; maybe suspend
        rolling, _ = penalty_totals(rider["id"])
        if rolling >= SUSPENSION_THRESHOLD_POINTS:
            prior = rider["prior_suspension_count"]
            if prior == 0:
                days = TIER1_SUSPENSION_DAYS
            elif prior == 1:
                days = TIER2_SUSPENSION_DAYS
            else:
                days = TIER3_SUSPENSION_DAYS
            rider["account_status"] = "SUSPENDED"
            rider["eligibility_status"] = "SUSPENDED"
            rider["suspension_until"] = fmt_dt(clock_now() + timedelta(days=days))
            rider["prior_suspension_count"] = prior + 1
            bump(rider)
            # hop 3 + 4: system-cancel other non-terminal trips
            for other in list(db.trips.values()):
                if other["id"] == t["id"]:
                    continue
                if other["rider_id"] != rider["id"]:
                    continue
                if other["status"] in TRIP_TERMINAL:
                    continue
                held = other["status"] in TRIP_HOLDING
                other["status"] = "CANCELLED_BY_SYSTEM"
                bump(other)
                if held:
                    release_run_capacity(other)
        # this trip's own capacity release
        release_run_capacity(t)
        return ok(serialize_trip(t), 200)


@app.route("/trip-reservations/<tid>/offers", methods=["GET"])
def list_offers(tid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "Dispatcher", "Driver", "EligibilitySpecialist", "Rider"})
        get_trip(tid)
        rows = [o for o in db.offers.values() if o["trip_id"] == tid]
        return paginate(rows, serialize_offer)


# ---------------------------------------------------------------------------
# Routes: subscription trips
# ---------------------------------------------------------------------------
@app.route("/subscription-trips", methods=["POST"])
def create_subscription():
    with LOCK:
        user_id, role = auth()
        require_roles(role, {"Rider"})
        body = get_body()
        require_present(body, ["rider_id", "pickup_zone_id", "dropoff_zone_id",
                               "pickup_lat", "pickup_lng", "dropoff_lat", "dropoff_lng",
                               "day_of_week", "pickup_time_utc"])
        rider_id = as_str(body, "rider_id")
        pickup_zone_id = as_str(body, "pickup_zone_id")
        dropoff_zone_id = as_str(body, "dropoff_zone_id")
        day_of_week = body.get("day_of_week")
        if day_of_week not in DAYS_OF_WEEK:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid day_of_week")
        pickup_time_utc = as_str(body, "pickup_time_utc")
        (pickup_lat, pickup_lng, dropoff_lat, dropoff_lng,
         num_companions, needs_wheelchair, has_pca) = _validate_trip_geometry_and_capacity_fields(body)
        rider = get_rider(rider_id)
        if rider["id"] != user_id:
            raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "Rider does not own this subscription")
        pickup_zone = get_zone(pickup_zone_id)
        dropoff_zone = get_zone(dropoff_zone_id)
        check_booking_gates(rider, check_suspension=False, check_expiry=False)
        if not in_service_area(pickup_zone, pickup_lat, pickup_lng) or \
           not in_service_area(dropoff_zone, dropoff_lat, dropoff_lng):
            raise ApiError("ERR_OUTSIDE_SERVICE_AREA", 422, "Pickup or dropoff outside service area")
        s = {
            "rider_id": rider_id,
            "pickup_zone_id": pickup_zone_id, "dropoff_zone_id": dropoff_zone_id,
            "pickup_lat": pickup_lat, "pickup_lng": pickup_lng,
            "dropoff_lat": dropoff_lat, "dropoff_lng": dropoff_lng,
            "day_of_week": day_of_week, "pickup_time_utc": pickup_time_utc,
            "needs_wheelchair": needs_wheelchair, "num_companions": num_companions,
            "has_pca": has_pca, "status": "ACTIVE",
        }
        stamp_new(s, audited=True)
        db.subscriptions[s["id"]] = s
        return ok(serialize_subscription(s), 201)


@app.route("/subscription-trips/<sid>", methods=["GET"])
def read_subscription(sid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "Dispatcher", "EligibilitySpecialist", "Rider"})
        return ok(serialize_subscription(get_subscription(sid)), 200)


@app.route("/subscription-trips", methods=["GET"])
def list_subscriptions():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "Dispatcher", "EligibilitySpecialist", "Rider"})
        rows = list(db.subscriptions.values())
        for key in ("rider_id", "pickup_zone_id", "dropoff_zone_id"):
            val = request.args.get(key)
            if val is not None:
                rows = [s for s in rows if s[key] == val]
        return paginate(rows, serialize_subscription)


@app.route("/subscription-trips/<sid>/instantiate", methods=["POST"])
def instantiate_subscription(sid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Dispatcher"})
        body = get_body()
        require_present(body, ["service_date", "requested_pickup_at"])
        as_str(body, "service_date")
        check_datetime(body, "requested_pickup_at")
        s = get_subscription(sid)
        if s["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Subscription is not active")
        rider = db.riders.get(s["rider_id"])
        if rider is None:
            raise ApiError("ERR_RIDER_NOT_FOUND", 404, "Rider not found")
        pickup_zone = get_zone(s["pickup_zone_id"])
        dropoff_zone = get_zone(s["dropoff_zone_id"])
        check_booking_gates(rider, check_suspension=True, check_expiry=True)
        if not in_service_area(pickup_zone, s["pickup_lat"], s["pickup_lng"]) or \
           not in_service_area(dropoff_zone, s["dropoff_lat"], s["dropoff_lng"]):
            raise ApiError("ERR_OUTSIDE_SERVICE_AREA", 422, "Pickup or dropoff outside service area")
        t = _new_trip_dict(s["rider_id"], s["id"], s["pickup_zone_id"], s["dropoff_zone_id"],
                           s["pickup_lat"], s["pickup_lng"], s["dropoff_lat"], s["dropoff_lng"],
                           body["requested_pickup_at"], s["needs_wheelchair"], s["num_companions"], s["has_pca"])
        db.trips[t["id"]] = t
        return ok(serialize_trip(t), 201)


# ---------------------------------------------------------------------------
# Routes: vehicle runs
# ---------------------------------------------------------------------------
@app.route("/vehicle-runs", methods=["POST"])
def create_run():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Dispatcher"})
        body = get_body()
        require_present(body, ["service_zone_id", "service_date",
                               "total_ambulatory_seats", "total_wheelchair_positions"])
        service_zone_id = as_str(body, "service_zone_id")
        service_date = as_str(body, "service_date")
        total_amb = as_int(body, "total_ambulatory_seats")
        total_wc = as_int(body, "total_wheelchair_positions")
        if total_amb < 0 or total_wc < 0:
            raise ApiError("ERR_OUT_OF_RANGE", 422, "Seat/position counts must be non-negative")
        get_zone(service_zone_id)
        r = {
            "service_zone_id": service_zone_id,
            "service_date": service_date,
            "total_ambulatory_seats": total_amb,
            "total_wheelchair_positions": total_wc,
            "status": "PLANNED",
        }
        stamp_new(r, audited=True)
        db.runs[r["id"]] = r
        return ok(serialize_run(r), 201)


@app.route("/vehicle-runs/<rid>", methods=["GET"])
def read_run(rid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "Dispatcher", "Driver"})
        return ok(serialize_run(get_run(rid)), 200)


@app.route("/vehicle-runs", methods=["GET"])
def list_runs():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "Dispatcher", "Driver"})
        rows = list(db.runs.values())
        for key in ("service_zone_id", "service_date"):
            val = request.args.get(key)
            if val is not None:
                rows = [r for r in rows if r[key] == val]
        return paginate(rows, serialize_run)


@app.route("/vehicle-runs/<rid>/manifest", methods=["GET"])
def run_manifest(rid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "Dispatcher", "Driver"})
        get_run(rid)
        rows = [t for t in db.trips.values() if t["assigned_run_id"] == rid]
        return paginate(rows, serialize_trip)


@app.route("/vehicle-runs/<rid>/open", methods=["POST"])
def open_run(rid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Dispatcher"})
        r = get_run(rid)
        if r["status"] != "PLANNED":
            raise ApiError("ERR_INVALID_STATE", 409, "Run must be PLANNED to open")
        r["status"] = "OPEN"
        bump(r)
        return ok(serialize_run(r), 200)


@app.route("/vehicle-runs/<rid>/dispatch", methods=["POST"])
def dispatch_run(rid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Dispatcher"})
        r = get_run(rid)
        if r["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Run must be OPEN to dispatch")
        r["status"] = "DISPATCHED"
        for t in db.trips.values():
            if t["assigned_run_id"] == rid and t["status"] == "SCHEDULED":
                t["status"] = "EN_ROUTE"
                bump(t)
        bump(r)
        return ok(serialize_run(r), 200)


# ---------------------------------------------------------------------------
# Routes: penalty events
# ---------------------------------------------------------------------------
@app.route("/penalty-events/<pid>", methods=["GET"])
def read_penalty(pid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "EligibilitySpecialist", "Rider"})
        return ok(serialize_penalty(get_penalty(pid)), 200)


@app.route("/penalty-events", methods=["GET"])
def list_penalties():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "EligibilitySpecialist", "Rider"})
        rows = list(db.penalties.values())
        for key in ("rider_id", "trip_id"):
            val = request.args.get(key)
            if val is not None:
                rows = [p for p in rows if p[key] == val]
        return paginate(rows, serialize_penalty)


@app.route("/penalty-events/<pid>/waive", methods=["POST"])
def waive_penalty(pid):
    with LOCK:
        _, role = auth()
        require_roles(role, {"EligibilitySpecialist"})
        p = get_penalty(pid)
        if p["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Only an active penalty can be waived")
        p["status"] = "VOIDED"
        bump(p)
        rider = db.riders.get(p["rider_id"])
        if rider:
            bump(rider)  # totals recomputed on read; touch rider audit fields
        return ok(serialize_penalty(p), 200)


# ---------------------------------------------------------------------------
# Routes: reports
# ---------------------------------------------------------------------------
@app.route("/reports/on-time-performance", methods=["GET"])
def otp_report():
    with LOCK:
        _, role = auth()
        require_roles(role, {"Admin", "Dispatcher"})
        service_zone_id = request.args.get("service_zone_id")
        service_date = request.args.get("service_date")
        total_pickups = 0
        on_time_pickups = 0
        for t in db.trips.values():
            if t["on_time"] is None:
                continue
            if service_zone_id is not None or service_date is not None:
                run = db.runs.get(t.get("assigned_run_id"))
                if run is None:
                    continue
                if service_zone_id is not None and run["service_zone_id"] != service_zone_id:
                    continue
                if service_date is not None and run["service_date"] != service_date:
                    continue
            total_pickups += 1
            if t["on_time"]:
                on_time_pickups += 1
        if total_pickups == 0:
            otp_pct = 0.0
        else:
            from decimal import Decimal, ROUND_HALF_UP
            raw = Decimal(on_time_pickups) / Decimal(total_pickups) * Decimal(100)
            otp_pct = float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        return ok({
            "total_pickups": total_pickups,
            "on_time_pickups": on_time_pickups,
            "otp_pct": otp_pct,
        }, 200)


# ---------------------------------------------------------------------------
# Store init + main
# ---------------------------------------------------------------------------
db = Store()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
