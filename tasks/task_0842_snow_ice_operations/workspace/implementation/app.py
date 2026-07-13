"""
Snow & Ice Operations API — single-file Flask implementation.

In-memory only. The store starts empty on every boot; no entity is ever seeded.
All timestamps come from a settable logical clock (default 2026-03-01T00:00:00Z).
"""
import json
import os
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, request, Response

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Decimal helpers (money & material precision)
# ---------------------------------------------------------------------------
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

Q_INT = Decimal("1")
Q_2 = Decimal("0.01")


def d(v):
    return Decimal(str(v))


def round_half_up_int(x):
    return int(Decimal(x).quantize(Q_INT, rounding=ROUND_HALF_UP))


def round_half_up_2(x):
    return Decimal(x).quantize(Q_2, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Constants (from scaffold §1.3)
# ---------------------------------------------------------------------------
BASE_RATE_TONS_PER_LANE_MILE = Decimal("0.15")
TIER_MULT = {"ARTERIAL": Decimal("1.0"), "RESIDENTIAL": Decimal("0.6")}

DAILY_OT_THRESHOLD_HOURS = Decimal("8.0")
STORM_OT_THRESHOLD_HOURS = Decimal("6.0")
STANDARD_OT_MULTIPLIER = Decimal("1.5")
STORM_OT_MULTIPLIER = Decimal("2.0")
STANDARD_CALLOUT_MIN_HOURS = Decimal("2.0")
STORM_CALLOUT_MIN_HOURS = Decimal("3.0")

SALT_UNIT_COST_CENTS = Decimal("8500")   # per ton
BRINE_UNIT_COST_CENTS = Decimal("25")    # per gallon

OPERATOR_REST_BUFFER = timedelta(hours=8)

ROLES = {"DispatchSupervisor", "Operator", "YardManager", "CitizenServices"}
ALL_ROLES = list(ROLES)


def temperature_factor(temp_f):
    t = Decimal(temp_f)
    if t >= 30:
        return Decimal("0.8")
    elif t >= 20:
        return Decimal("1.0")
    elif t >= 10:
        return Decimal("1.3")
    else:
        return Decimal("1.6")


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.depots = {}
        self.vehicles = {}
        self.operators = {}
        self.routes = {}
        self.storms = {}
        self.assignments = {}
        self.applications = {}
        self.callouts = {}
        self.complaints = {}
        self.cost_reports = {}
        self.seq = 0
        self.clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Datetime formatting / parsing
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime")
    raw = s.strip()
    txt = raw
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime: %s" % raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Errors & response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": fmt_dt(now())}
    if extra:
        m.update(extra)
    return m


def _send(body, status):
    return Response(json.dumps(body), status=status, mimetype="application/json")


def ok(data, status=200, response_type="object", meta_extra=None):
    return _send(
        {"meta": _meta(meta_extra), "response_type": response_type, "data": data},
        status,
    )


def ok_list(items, total, limit, offset):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    }
    return ok(items, 200, "array", meta_extra)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _send(body, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return _send(body, 404)


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"},
    }
    return _send(body, 404)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require(roles):
    """Validate auth headers and role membership. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing X-User-ID or X-User-Role")
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role %s not permitted" % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "body must be a JSON object")
    return b


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: %s" % f)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "field %s must be a non-empty string" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field %s must be a string" % field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, "field %s not in %s" % (field, sorted(allowed)))
    return v


def as_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field %s must be a number" % field)
    return d(v)


def as_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field %s must be an integer" % field)
    return v


# ---------------------------------------------------------------------------
# Common-field lifecycle
# ---------------------------------------------------------------------------
def base_record(with_version=True):
    ts = now()
    rec = {"id": new_id(), "created_at": ts, "_seq": db.next_seq()}
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now()
    if "version" in rec:
        rec["version"] += 1


def common_out(rec, has_version=True):
    out = {"id": rec["id"], "created_at": fmt_dt(rec["created_at"])}
    if has_version:
        out["updated_at"] = fmt_dt(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def num_out(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def depot_out(r):
    o = common_out(r)
    o.update({
        "name": r["name"],
        "salt_tons_on_hand": num_out(r["salt_tons_on_hand"]),
        "brine_gallons_on_hand": num_out(r["brine_gallons_on_hand"]),
        "initial_salt_tons": num_out(r["initial_salt_tons"]),
        "initial_brine_gallons": num_out(r["initial_brine_gallons"]),
    })
    return o


def vehicle_out(r):
    o = common_out(r)
    o.update({
        "home_depot_id": r["home_depot_id"],
        "unit_number": r["unit_number"],
        "vehicle_type": r["vehicle_type"],
        "has_spreader": r["has_spreader"],
        "status": r["status"],
    })
    return o


def operator_out(r):
    o = common_out(r)
    o.update({
        "full_name": r["full_name"],
        "badge_number": r["badge_number"],
        "cdl_class": r["cdl_class"],
        "hourly_rate_cents": r["hourly_rate_cents"],
        "regular_hours_accrued": num_out(r["regular_hours_accrued"]),
        "overtime_hours_accrued": num_out(r["overtime_hours_accrued"]),
    })
    return o


def route_out(r):
    o = common_out(r)
    o.update({
        "name": r["name"],
        "tier": r["tier"],
        "lane_miles": num_out(r["lane_miles"]),
        "zone": r["zone"],
    })
    return o


def storm_out(r):
    o = common_out(r)
    o.update({
        "name": r["name"],
        "severity": r["severity"],
        "forecast_start_at": r["forecast_start_at"],
        "forecast_end_at": r["forecast_end_at"],
        "operational_status": r["operational_status"],
        "billing_status": r["billing_status"],
        "closed_at": fmt_dt(r["closed_at"]) if r["closed_at"] else None,
    })
    return o


def assignment_out(r):
    o = common_out(r)
    o.update({
        "storm_event_id": r["storm_event_id"],
        "route_id": r["route_id"],
        "vehicle_id": r["vehicle_id"],
        "operator_id": r["operator_id"],
        "assignment_type": r["assignment_type"],
        "window_start_at": r["window_start_at"],
        "window_end_at": r["window_end_at"],
        "planned_material_tons": num_out(r["planned_material_tons"]),
        "status": r["status"],
        "last_lat": num_out(r["last_lat"]),
        "last_lon": num_out(r["last_lon"]),
        "last_ping_at": fmt_dt(r["last_ping_at"]) if r["last_ping_at"] else None,
        "plow_down": r["plow_down"],
    })
    return o


def application_out(r):
    o = common_out(r)
    o.update({
        "route_assignment_id": r["route_assignment_id"],
        "depot_id": r["depot_id"],
        "material_type": r["material_type"],
        "salt_tons": num_out(r["salt_tons"]),
        "brine_gallons": num_out(r["brine_gallons"]),
        "lane_miles_treated": num_out(r["lane_miles_treated"]),
        "pavement_temp_f": num_out(r["pavement_temp_f"]),
        "recommended_salt_tons": num_out(r["recommended_salt_tons"]),
        "applied_at": fmt_dt(r["applied_at"]) if r["applied_at"] else None,
        "status": r["status"],
    })
    return o


def callout_out(r):
    o = common_out(r)
    o.update({
        "storm_event_id": r["storm_event_id"],
        "operator_id": r["operator_id"],
        "window_start_at": r["window_start_at"],
        "window_end_at": r["window_end_at"],
        "hours_worked": num_out(r["hours_worked"]),
        "pay_mode": r["pay_mode"],
        "regular_hours": num_out(r["regular_hours"]),
        "overtime_hours": num_out(r["overtime_hours"]),
        "pay_cents": r["pay_cents"],
        "status": r["status"],
    })
    return o


def complaint_out(r):
    o = common_out(r)
    o.update({
        "route_id": r["route_id"],
        "storm_event_id": r["storm_event_id"],
        "address": r["address"],
        "complaint_type": r["complaint_type"],
        "missed_street_confirmed": r["missed_street_confirmed"],
        "reported_at": fmt_dt(r["reported_at"]) if r["reported_at"] else None,
        "status": r["status"],
    })
    return o


def cost_report_out(r):
    o = common_out(r, has_version=False)
    o.update({
        "storm_event_id": r["storm_event_id"],
        "variant": r["variant"],
        "total_material_cost_cents": r["total_material_cost_cents"],
        "total_labor_cost_cents": r["total_labor_cost_cents"],
        "total_cost_cents": r["total_cost_cents"],
        "generated_at": fmt_dt(r["generated_at"]),
    })
    return o


# ---------------------------------------------------------------------------
# Lookup helpers (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def find(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    return rec


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(records):
    limit, offset = parse_pagination()
    records = sorted(records, key=lambda r: r["_seq"])
    total = len(records)
    page = records[offset:offset + limit]
    return page, total, limit, offset


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require({"DispatchSupervisor"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    db.clock = parse_dt(body["to_iso8601"])
    return ok({}, 200)


# ===========================================================================
# Depot
# ===========================================================================
@app.route("/depots", methods=["POST"])
def create_depot():
    require({"YardManager"})
    body = get_body()
    require_fields(body, ["name", "salt_tons_on_hand", "brine_gallons_on_hand"])
    name = require_str(body, "name")
    salt = as_number(body, "salt_tons_on_hand")
    brine = as_number(body, "brine_gallons_on_hand")
    if salt < 0 or brine < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "inventory must be >= 0")
    r = base_record()
    r.update({
        "name": name,
        "salt_tons_on_hand": salt,
        "brine_gallons_on_hand": brine,
        "initial_salt_tons": salt,
        "initial_brine_gallons": brine,
    })
    db.depots[r["id"]] = r
    return ok(depot_out(r), 201)


@app.route("/depots/<_id>", methods=["GET"])
def get_depot(_id):
    require(ROLES)
    return ok(depot_out(find(db.depots, _id)))


# ===========================================================================
# Vehicle
# ===========================================================================
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    require({"YardManager"})
    body = get_body()
    require_fields(body, ["home_depot_id", "unit_number", "vehicle_type"])
    home_depot_id = require_str(body, "home_depot_id")
    find(db.depots, home_depot_id)  # existence (FK)
    unit_number = require_str(body, "unit_number")
    vehicle_type = require_enum(body, "vehicle_type", {"PLOW", "SPREADER", "COMBO"})
    status = "AVAILABLE"
    if body.get("status") is not None:
        status = require_enum(body, "status", {"AVAILABLE", "ASSIGNED", "OUT_OF_SERVICE"})
    r = base_record()
    r.update({
        "home_depot_id": home_depot_id,
        "unit_number": unit_number,
        "vehicle_type": vehicle_type,
        "has_spreader": vehicle_type in {"SPREADER", "COMBO"},
        "status": status,
    })
    db.vehicles[r["id"]] = r
    return ok(vehicle_out(r), 201)


@app.route("/vehicles/<_id>", methods=["GET"])
def get_vehicle(_id):
    require(ROLES)
    return ok(vehicle_out(find(db.vehicles, _id)))


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    require(ROLES)
    home_depot_id = request.args.get("home_depot_id")
    status = request.args.get("status")
    recs = [v for v in db.vehicles.values()
            if (home_depot_id is None or v["home_depot_id"] == home_depot_id)
            and (status is None or v["status"] == status)]
    page, total, limit, offset = paginate(recs)
    return ok_list([vehicle_out(v) for v in page], total, limit, offset)


# ===========================================================================
# Operator
# ===========================================================================
@app.route("/operators", methods=["POST"])
def create_operator():
    require({"YardManager"})
    body = get_body()
    require_fields(body, ["full_name", "badge_number", "cdl_class", "hourly_rate_cents"])
    full_name = require_str(body, "full_name")
    badge_number = require_str(body, "badge_number")
    cdl_class = require_enum(body, "cdl_class", {"A", "B", "C"})
    hourly_rate_cents = as_int(body, "hourly_rate_cents")
    if hourly_rate_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "hourly_rate_cents must be > 0")
    r = base_record()
    r.update({
        "full_name": full_name,
        "badge_number": badge_number,
        "cdl_class": cdl_class,
        "hourly_rate_cents": hourly_rate_cents,
        "regular_hours_accrued": Decimal("0"),
        "overtime_hours_accrued": Decimal("0"),
    })
    db.operators[r["id"]] = r
    return ok(operator_out(r), 201)


@app.route("/operators/<_id>", methods=["GET"])
def get_operator(_id):
    require(ROLES)
    return ok(operator_out(find(db.operators, _id)))


# ===========================================================================
# Route
# ===========================================================================
@app.route("/routes", methods=["POST"])
def create_route():
    require({"DispatchSupervisor"})
    body = get_body()
    require_fields(body, ["name", "tier", "lane_miles", "zone"])
    name = require_str(body, "name")
    tier = require_enum(body, "tier", {"ARTERIAL", "RESIDENTIAL"})
    lane_miles = as_number(body, "lane_miles")
    if lane_miles <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "lane_miles must be > 0")
    zone = require_str(body, "zone")
    r = base_record()
    r.update({"name": name, "tier": tier, "lane_miles": lane_miles, "zone": zone})
    db.routes[r["id"]] = r
    return ok(route_out(r), 201)


@app.route("/routes/<_id>", methods=["GET"])
def get_route(_id):
    require(ROLES)
    return ok(route_out(find(db.routes, _id)))


# ===========================================================================
# StormEvent
# ===========================================================================
@app.route("/storm-events", methods=["POST"])
def create_storm():
    require({"DispatchSupervisor"})
    body = get_body()
    require_fields(body, ["name", "severity", "forecast_start_at", "forecast_end_at"])
    name = require_str(body, "name")
    severity = require_enum(body, "severity", {"LIGHT", "MODERATE", "SEVERE", "EMERGENCY"})
    fs_raw = require_str(body, "forecast_start_at")
    fe_raw = require_str(body, "forecast_end_at")
    parse_dt(fs_raw)
    parse_dt(fe_raw)
    r = base_record()
    r.update({
        "name": name,
        "severity": severity,
        "forecast_start_at": fs_raw,
        "forecast_end_at": fe_raw,
        "operational_status": "PLANNED",
        "billing_status": "OPEN",
        "closed_at": None,
    })
    db.storms[r["id"]] = r
    return ok(storm_out(r), 201)


@app.route("/storm-events/<_id>", methods=["GET"])
def get_storm(_id):
    require(ROLES)
    return ok(storm_out(find(db.storms, _id)))


@app.route("/storm-events/<_id>/activate", methods=["POST"])
def activate_storm(_id):
    require({"DispatchSupervisor"})
    s = find(db.storms, _id)
    if s["operational_status"] == "CLOSED":
        raise ApiError("ERR_STORM_ALREADY_CLOSED", 409, "storm already closed")
    if s["operational_status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "storm not PLANNED")
    s["operational_status"] = "ACTIVE"
    touch(s)
    return ok(storm_out(s))


@app.route("/storm-events/<_id>/close", methods=["POST"])
def close_storm(_id):
    require({"DispatchSupervisor"})
    s = find(db.storms, _id)
    if s["operational_status"] == "CLOSED":
        raise ApiError("ERR_STORM_ALREADY_CLOSED", 409, "storm already closed")
    if s["operational_status"] != "ACTIVE":
        raise ApiError("ERR_STORM_NOT_ACTIVE", 409, "storm not ACTIVE")
    s["operational_status"] = "CLOSED"
    s["closed_at"] = now()
    # CASCADE hop-1: assignments of this storm
    for a in db.assignments.values():
        if a["storm_event_id"] != s["id"]:
            continue
        if a["status"] == "IN_PROGRESS":
            a["status"] = "COMPLETED"
            touch(a)
            _release_vehicle(a["vehicle_id"])
        elif a["status"] == "PLANNED":
            a["status"] = "CANCELLED"
            touch(a)
    touch(s)
    return ok(storm_out(s))


@app.route("/storm-events/<_id>/finalize-billing", methods=["POST"])
def finalize_billing(_id):
    require({"DispatchSupervisor"})
    s = find(db.storms, _id)
    if s["operational_status"] != "CLOSED":
        raise ApiError("ERR_STORM_NOT_CLOSED", 409, "storm not CLOSED")
    if s["billing_status"] != "OPEN":
        raise ApiError("ERR_BILLING_NOT_OPEN", 409, "billing not OPEN")
    s["billing_status"] = "FINALIZED"
    touch(s)
    return ok(storm_out(s))


def _release_vehicle(vehicle_id):
    v = db.vehicles.get(vehicle_id)
    if v is not None and v["status"] == "ASSIGNED":
        v["status"] = "AVAILABLE"
        touch(v)


# ===========================================================================
# RouteAssignment
# ===========================================================================
def _windows_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end): overlap iff a_start < b_end and b_start < a_end
    return a_start < b_end and b_start < a_end


@app.route("/storm-events/<_id>/assignments", methods=["POST"])
def create_assignment(_id):
    require({"DispatchSupervisor"})
    s = find(db.storms, _id)  # existence: storm (path)
    body = get_body()
    # existence: body FKs left-to-right (route, vehicle, operator) — only when present
    route_id = body.get("route_id")
    vehicle_id = body.get("vehicle_id")
    operator_id = body.get("operator_id")
    if isinstance(route_id, str) and route_id:
        route = find(db.routes, route_id)
    else:
        route = None
    if isinstance(vehicle_id, str) and vehicle_id:
        vehicle = find(db.vehicles, vehicle_id)
    else:
        vehicle = None
    if isinstance(operator_id, str) and operator_id:
        operator = find(db.operators, operator_id)
    else:
        operator = None
    # body well-formedness
    require_fields(body, ["route_id", "vehicle_id", "operator_id", "assignment_type",
                          "window_start_at", "window_end_at", "planned_material_tons",
                          "expected_storm_event_version"])
    assignment_type = require_enum(body, "assignment_type", {"PRETREAT", "PLOWING"})
    ws_raw = require_str(body, "window_start_at")
    we_raw = require_str(body, "window_end_at")
    ws = parse_dt(ws_raw)
    we = parse_dt(we_raw)
    planned_tons = as_number(body, "planned_material_tons")
    if planned_tons < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "planned_material_tons must be >= 0")
    expected_version = as_int(body, "expected_storm_event_version")

    # priority 6 — state: storm operational status + route-already-active
    if s["operational_status"] == "CLOSED":
        raise ApiError("ERR_STORM_ALREADY_CLOSED", 409, "storm already closed")
    if s["operational_status"] not in {"PLANNED", "ACTIVE"}:
        raise ApiError("ERR_INVALID_STATE", 409, "storm not plannable")
    for a in db.assignments.values():
        if (a["storm_event_id"] == s["id"] and a["route_id"] == route_id
                and a["status"] == "IN_PROGRESS"):
            raise ApiError("ERR_ROUTE_ALREADY_ACTIVE", 409, "route already actively serviced")

    # priority 7 — vehicle safety
    if vehicle["status"] == "OUT_OF_SERVICE":
        raise ApiError("ERR_VEHICLE_OUT_OF_SERVICE", 422, "vehicle out of service")
    if assignment_type == "PLOWING" and not vehicle["has_spreader"]:
        raise ApiError("ERR_VEHICLE_MISSING_SPREADER", 422, "vehicle lacks spreader")

    # priority 8 — operator on call
    on_call = any(c["storm_event_id"] == s["id"] and c["operator_id"] == operator_id
                  and c["status"] in {"ISSUED", "COMPLETED"} for c in db.callouts.values())
    if not on_call:
        raise ApiError("ERR_OPERATOR_NOT_ON_CALL", 409, "operator has no active callout for this storm")

    # priority 9 — vehicle double-booking
    for a in db.assignments.values():
        if (a["vehicle_id"] == vehicle_id and a["status"] in {"PLANNED", "IN_PROGRESS"}
                and _windows_overlap(ws, we, a["_ws"], a["_we"])):
            raise ApiError("ERR_VEHICLE_DOUBLE_BOOKED", 409, "vehicle window overlaps another assignment")

    # priority 11 — window validity
    if not (we > ws):
        raise ApiError("ERR_INVALID_WINDOW", 422, "window_end_at must be after window_start_at")

    # priority 12 — OCC
    if expected_version != s["version"]:
        raise ApiError("ERR_STALE_STORM_VERSION", 412, "expected_storm_event_version mismatch")

    # supersede prior PLANNED assignment for same (storm, route)
    for a in db.assignments.values():
        if (a["storm_event_id"] == s["id"] and a["route_id"] == route_id
                and a["status"] == "PLANNED"):
            a["status"] = "SUPERSEDED"
            touch(a)

    r = base_record()
    r.update({
        "storm_event_id": s["id"],
        "route_id": route_id,
        "vehicle_id": vehicle_id,
        "operator_id": operator_id,
        "assignment_type": assignment_type,
        "window_start_at": ws_raw,
        "window_end_at": we_raw,
        "_ws": ws,
        "_we": we,
        "planned_material_tons": planned_tons,
        "status": "PLANNED",
        "last_lat": None,
        "last_lon": None,
        "last_ping_at": None,
        "plow_down": False,
    })
    db.assignments[r["id"]] = r
    touch(s)  # storm version increments on successful create
    return ok(assignment_out(r), 201)


@app.route("/storm-events/<_id>/assignments", methods=["GET"])
def list_storm_assignments(_id):
    require(ROLES)
    find(db.storms, _id)
    status = request.args.get("status")
    recs = [a for a in db.assignments.values()
            if a["storm_event_id"] == _id and (status is None or a["status"] == status)]
    page, total, limit, offset = paginate(recs)
    return ok_list([assignment_out(a) for a in page], total, limit, offset)


@app.route("/assignments/<_id>", methods=["GET"])
def get_assignment(_id):
    require(ROLES)
    return ok(assignment_out(find(db.assignments, _id)))


@app.route("/assignments", methods=["GET"])
def list_assignments():
    require(ROLES)
    route_id = request.args.get("route_id")
    vehicle_id = request.args.get("vehicle_id")
    operator_id = request.args.get("operator_id")
    status = request.args.get("status")
    recs = [a for a in db.assignments.values()
            if (route_id is None or a["route_id"] == route_id)
            and (vehicle_id is None or a["vehicle_id"] == vehicle_id)
            and (operator_id is None or a["operator_id"] == operator_id)
            and (status is None or a["status"] == status)]
    page, total, limit, offset = paginate(recs)
    return ok_list([assignment_out(a) for a in page], total, limit, offset)


@app.route("/assignments/<_id>/start", methods=["POST"])
def start_assignment(_id):
    require({"DispatchSupervisor"})
    a = find(db.assignments, _id)
    if a["status"] != "PLANNED":
        raise ApiError("ERR_ASSIGNMENT_NOT_PLANNED", 409, "assignment not PLANNED")
    s = db.storms.get(a["storm_event_id"])
    if s is None or s["operational_status"] != "ACTIVE":
        raise ApiError("ERR_STORM_NOT_ACTIVE", 409, "owning storm not ACTIVE")
    v = db.vehicles.get(a["vehicle_id"])
    if v is None or v["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "vehicle not AVAILABLE")
    a["status"] = "IN_PROGRESS"
    touch(a)
    v["status"] = "ASSIGNED"
    touch(v)
    return ok(assignment_out(a))


@app.route("/assignments/<_id>/complete", methods=["POST"])
def complete_assignment(_id):
    require({"DispatchSupervisor"})
    a = find(db.assignments, _id)
    if a["status"] != "IN_PROGRESS":
        raise ApiError("ERR_ASSIGNMENT_NOT_IN_PROGRESS", 409, "assignment not IN_PROGRESS")
    a["status"] = "COMPLETED"
    touch(a)
    _release_vehicle(a["vehicle_id"])
    return ok(assignment_out(a))


@app.route("/assignments/<_id>/cancel", methods=["POST"])
def cancel_assignment(_id):
    require({"DispatchSupervisor"})
    a = find(db.assignments, _id)
    if a["status"] not in {"PLANNED", "IN_PROGRESS"}:
        raise ApiError("ERR_INVALID_STATE", 409, "assignment not cancellable")
    was_in_progress = a["status"] == "IN_PROGRESS"
    a["status"] = "CANCELLED"
    touch(a)
    if was_in_progress:
        # cascade: void recorded applications (each credits its depot)
        for app_rec in db.applications.values():
            if app_rec["route_assignment_id"] == a["id"] and app_rec["status"] == "RECORDED":
                _void_application(app_rec)
        _release_vehicle(a["vehicle_id"])
    return ok(assignment_out(a))


@app.route("/assignments/<_id>/avl-ping", methods=["POST"])
def avl_ping(_id):
    user_id, _ = require({"Operator"})
    a = find(db.assignments, _id)
    body = get_body()
    require_fields(body, ["lat", "lon"])
    lat = as_number(body, "lat")
    lon = as_number(body, "lon")
    plow_down = body.get("plow_down", False)
    if not isinstance(plow_down, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "plow_down must be a boolean")
    # ownership (priority 5)
    if a["operator_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "operator does not own this assignment")
    # state (priority 6)
    if a["status"] != "IN_PROGRESS":
        raise ApiError("ERR_ASSIGNMENT_NOT_IN_PROGRESS", 409, "assignment not IN_PROGRESS")
    a["last_lat"] = lat
    a["last_lon"] = lon
    a["plow_down"] = plow_down
    a["last_ping_at"] = now()
    touch(a)
    return ok(assignment_out(a))


# ===========================================================================
# MaterialApplication
# ===========================================================================
def _void_application(app_rec):
    app_rec["status"] = "VOIDED"
    depot = db.depots.get(app_rec["depot_id"])
    if depot is not None:
        if app_rec["material_type"] == "SALT":
            depot["salt_tons_on_hand"] = depot["salt_tons_on_hand"] + app_rec["salt_tons"]
        else:
            depot["brine_gallons_on_hand"] = depot["brine_gallons_on_hand"] + app_rec["brine_gallons"]
        touch(depot)
    touch(app_rec)


@app.route("/assignments/<_id>/applications", methods=["POST"])
def create_application(_id):
    user_id, _ = require({"Operator"})
    a = find(db.assignments, _id)  # existence: assignment (path)
    body = get_body()
    depot_id = body.get("depot_id")
    if isinstance(depot_id, str) and depot_id:
        depot = find(db.depots, depot_id)  # existence: depot (FK)
    else:
        depot = None
    # body well-formedness
    require_fields(body, ["depot_id", "material_type", "lane_miles_treated", "pavement_temp_f"])
    material_type = require_enum(body, "material_type", {"SALT", "BRINE"})
    lane_miles_treated = as_number(body, "lane_miles_treated")
    if lane_miles_treated <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "lane_miles_treated must be > 0")
    pavement_temp_f = as_number(body, "pavement_temp_f")
    salt_tons = Decimal("0")
    brine_gallons = Decimal("0")
    if material_type == "SALT":
        if body.get("salt_tons") is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "salt_tons required for SALT")
        salt_tons = as_number(body, "salt_tons")
        if body.get("brine_gallons") is not None and as_number(body, "brine_gallons") != 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "brine_gallons must be 0 for SALT")
        if salt_tons < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "salt_tons must be >= 0")
    else:  # BRINE
        if body.get("brine_gallons") is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "brine_gallons required for BRINE")
        brine_gallons = as_number(body, "brine_gallons")
        if body.get("salt_tons") is not None and as_number(body, "salt_tons") != 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "salt_tons must be 0 for BRINE")
        if brine_gallons < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "brine_gallons must be >= 0")

    # ownership (priority 5)
    if a["operator_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "operator does not own this assignment")
    # state (priority 6)
    if a["status"] != "IN_PROGRESS":
        raise ApiError("ERR_ASSIGNMENT_NOT_IN_PROGRESS", 409, "assignment not IN_PROGRESS")
    # fiscal (priority 13)
    if material_type == "SALT":
        if depot["salt_tons_on_hand"] < salt_tons:
            raise ApiError("ERR_INSUFFICIENT_MATERIAL", 409, "insufficient salt")
    else:
        if depot["brine_gallons_on_hand"] < brine_gallons:
            raise ApiError("ERR_INSUFFICIENT_MATERIAL", 409, "insufficient brine")

    # compute recommendation (reads owning route tier)
    route = db.routes.get(a["route_id"])
    tier_mult = TIER_MULT.get(route["tier"], Decimal("1.0")) if route else Decimal("1.0")
    recommended = round_half_up_2(
        lane_miles_treated * BASE_RATE_TONS_PER_LANE_MILE
        * temperature_factor(pavement_temp_f) * tier_mult)

    # debit inventory
    if material_type == "SALT":
        depot["salt_tons_on_hand"] = depot["salt_tons_on_hand"] - salt_tons
    else:
        depot["brine_gallons_on_hand"] = depot["brine_gallons_on_hand"] - brine_gallons
    touch(depot)

    r = base_record()
    r.update({
        "route_assignment_id": a["id"],
        "depot_id": depot_id,
        "material_type": material_type,
        "salt_tons": salt_tons,
        "brine_gallons": brine_gallons,
        "lane_miles_treated": lane_miles_treated,
        "pavement_temp_f": pavement_temp_f,
        "recommended_salt_tons": recommended,
        "applied_at": now(),
        "status": "RECORDED",
    })
    db.applications[r["id"]] = r
    return ok(application_out(r), 201)


@app.route("/assignments/<_id>/applications", methods=["GET"])
def list_assignment_applications(_id):
    require(ROLES)
    find(db.assignments, _id)
    status = request.args.get("status")
    recs = [ap for ap in db.applications.values()
            if ap["route_assignment_id"] == _id and (status is None or ap["status"] == status)]
    page, total, limit, offset = paginate(recs)
    return ok_list([application_out(ap) for ap in page], total, limit, offset)


@app.route("/material-applications/<_id>", methods=["GET"])
def get_application(_id):
    require(ROLES)
    return ok(application_out(find(db.applications, _id)))


@app.route("/material-applications", methods=["GET"])
def list_applications():
    require(ROLES)
    depot_id = request.args.get("depot_id")
    route_assignment_id = request.args.get("route_assignment_id")
    status = request.args.get("status")
    recs = [ap for ap in db.applications.values()
            if (depot_id is None or ap["depot_id"] == depot_id)
            and (route_assignment_id is None or ap["route_assignment_id"] == route_assignment_id)
            and (status is None or ap["status"] == status)]
    page, total, limit, offset = paginate(recs)
    return ok_list([application_out(ap) for ap in page], total, limit, offset)


@app.route("/material-applications/<_id>/void", methods=["POST"])
def void_application(_id):
    require({"DispatchSupervisor"})
    ap = find(db.applications, _id)
    if ap["status"] != "RECORDED":
        raise ApiError("ERR_APPLICATION_ALREADY_VOIDED", 409, "application already voided")
    _void_application(ap)
    return ok(application_out(ap))


# ===========================================================================
# Callout
# ===========================================================================
@app.route("/storm-events/<_id>/callouts", methods=["POST"])
def create_callout(_id):
    require({"DispatchSupervisor"})
    s = find(db.storms, _id)  # existence: storm (path)
    body = get_body()
    operator_id = body.get("operator_id")
    if isinstance(operator_id, str) and operator_id:
        find(db.operators, operator_id)  # existence: operator (FK)
    require_fields(body, ["operator_id", "window_start_at", "window_end_at"])
    ws_raw = require_str(body, "window_start_at")
    we_raw = require_str(body, "window_end_at")
    ws = parse_dt(ws_raw)
    we = parse_dt(we_raw)
    # window validity (PRD §3.3: first guard)
    if not (we > ws):
        raise ApiError("ERR_INVALID_WINDOW", 422, "window_end_at must be after window_start_at")
    # rest buffer (PRD §3.3: second guard)
    for c in db.callouts.values():
        if c["operator_id"] != operator_id or c["status"] not in {"ISSUED", "COMPLETED"}:
            continue
        ok_gap = (ws >= c["_we"] + OPERATOR_REST_BUFFER) or (c["_ws"] >= we + OPERATOR_REST_BUFFER)
        if not ok_gap:
            raise ApiError("ERR_OPERATOR_REST_VIOLATION", 409, "operator rest buffer violated")
    r = base_record()
    r.update({
        "storm_event_id": s["id"],
        "operator_id": operator_id,
        "window_start_at": ws_raw,
        "window_end_at": we_raw,
        "_ws": ws,
        "_we": we,
        "hours_worked": Decimal("0"),
        "pay_mode": None,
        "regular_hours": Decimal("0"),
        "overtime_hours": Decimal("0"),
        "pay_cents": 0,
        "status": "ISSUED",
    })
    db.callouts[r["id"]] = r
    return ok(callout_out(r), 201)


@app.route("/storm-events/<_id>/callouts", methods=["GET"])
def list_storm_callouts(_id):
    require(ROLES)
    find(db.storms, _id)
    status = request.args.get("status")
    recs = [c for c in db.callouts.values()
            if c["storm_event_id"] == _id and (status is None or c["status"] == status)]
    page, total, limit, offset = paginate(recs)
    return ok_list([callout_out(c) for c in page], total, limit, offset)


@app.route("/callouts/<_id>", methods=["GET"])
def get_callout(_id):
    require(ROLES)
    return ok(callout_out(find(db.callouts, _id)))


@app.route("/callouts", methods=["GET"])
def list_callouts():
    require(ROLES)
    operator_id = request.args.get("operator_id")
    status = request.args.get("status")
    recs = [c for c in db.callouts.values()
            if (operator_id is None or c["operator_id"] == operator_id)
            and (status is None or c["status"] == status)]
    page, total, limit, offset = paginate(recs)
    return ok_list([callout_out(c) for c in page], total, limit, offset)


@app.route("/callouts/<_id>/complete", methods=["POST"])
def complete_callout(_id):
    user_id, _ = require({"Operator"})
    c = find(db.callouts, _id)
    body = get_body()
    require_fields(body, ["hours_worked"])
    hours_worked = as_number(body, "hours_worked")
    if hours_worked < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "hours_worked must be >= 0")
    # ownership (priority 5)
    if c["operator_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "operator does not own this callout")
    # state (priority 6)
    if c["status"] != "ISSUED":
        raise ApiError("ERR_CALLOUT_NOT_ISSUED", 409, "callout not ISSUED")

    storm = db.storms.get(c["storm_event_id"])
    operator = db.operators.get(c["operator_id"])
    severity = storm["severity"] if storm else "LIGHT"
    storm_mode = severity in {"SEVERE", "EMERGENCY"}
    if storm_mode:
        pay_mode = "STORM_MODE"
        threshold = STORM_OT_THRESHOLD_HOURS
        ot_mult = STORM_OT_MULTIPLIER
        min_hours = STORM_CALLOUT_MIN_HOURS
    else:
        pay_mode = "STANDARD"
        threshold = DAILY_OT_THRESHOLD_HOURS
        ot_mult = STANDARD_OT_MULTIPLIER
        min_hours = STANDARD_CALLOUT_MIN_HOURS
    paid_hours = max(hours_worked, min_hours)
    regular_hours = min(paid_hours, threshold)
    overtime_hours = max(Decimal("0"), paid_hours - threshold)
    rate = Decimal(operator["hourly_rate_cents"])
    pay_cents = round_half_up_int(regular_hours * rate + overtime_hours * rate * ot_mult)

    c["hours_worked"] = hours_worked
    c["pay_mode"] = pay_mode
    c["regular_hours"] = regular_hours
    c["overtime_hours"] = overtime_hours
    c["pay_cents"] = pay_cents
    c["status"] = "COMPLETED"
    touch(c)
    # ledger credit
    operator["regular_hours_accrued"] = operator["regular_hours_accrued"] + regular_hours
    operator["overtime_hours_accrued"] = operator["overtime_hours_accrued"] + overtime_hours
    touch(operator)
    return ok(callout_out(c))


@app.route("/callouts/<_id>/cancel", methods=["POST"])
def cancel_callout(_id):
    require({"DispatchSupervisor"})
    c = find(db.callouts, _id)
    if c["status"] == "CANCELLED":
        raise ApiError("ERR_CALLOUT_NOT_CANCELLABLE", 409, "callout already cancelled")
    if c["status"] not in {"ISSUED", "COMPLETED"}:
        raise ApiError("ERR_INVALID_STATE", 409, "callout not cancellable")
    was_completed = c["status"] == "COMPLETED"
    c["status"] = "CANCELLED"
    touch(c)
    if was_completed:
        operator = db.operators.get(c["operator_id"])
        if operator is not None:
            operator["regular_hours_accrued"] = operator["regular_hours_accrued"] - c["regular_hours"]
            operator["overtime_hours_accrued"] = operator["overtime_hours_accrued"] - c["overtime_hours"]
            touch(operator)
    return ok(callout_out(c))


# ===========================================================================
# Complaint
# ===========================================================================
@app.route("/complaints", methods=["POST"])
def create_complaint():
    require({"CitizenServices"})
    body = get_body()
    route_id = body.get("route_id")
    storm_event_id = body.get("storm_event_id")
    if isinstance(route_id, str) and route_id:
        find(db.routes, route_id)
    if isinstance(storm_event_id, str) and storm_event_id:
        find(db.storms, storm_event_id)
    require_fields(body, ["route_id", "storm_event_id", "address", "complaint_type"])
    address = require_str(body, "address")
    complaint_type = require_enum(body, "complaint_type",
                                  {"MISSED_STREET", "ICY_CONDITIONS", "PROPERTY_DAMAGE"})
    r = base_record()
    r.update({
        "route_id": route_id,
        "storm_event_id": storm_event_id,
        "address": address,
        "complaint_type": complaint_type,
        "missed_street_confirmed": False,
        "reported_at": now(),
        "status": "OPEN",
    })
    db.complaints[r["id"]] = r
    return ok(complaint_out(r), 201)


@app.route("/complaints/<_id>", methods=["GET"])
def get_complaint(_id):
    require(ROLES)
    return ok(complaint_out(find(db.complaints, _id)))


@app.route("/complaints", methods=["GET"])
def list_complaints():
    require(ROLES)
    route_id = request.args.get("route_id")
    storm_event_id = request.args.get("storm_event_id")
    status = request.args.get("status")
    recs = [c for c in db.complaints.values()
            if (route_id is None or c["route_id"] == route_id)
            and (storm_event_id is None or c["storm_event_id"] == storm_event_id)
            and (status is None or c["status"] == status)]
    page, total, limit, offset = paginate(recs)
    return ok_list([complaint_out(c) for c in page], total, limit, offset)


@app.route("/complaints/<_id>/investigate", methods=["POST"])
def investigate_complaint(_id):
    require({"CitizenServices"})
    c = find(db.complaints, _id)
    body = get_body()
    confirm_missed = body.get("confirm_missed", False)
    if not isinstance(confirm_missed, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "confirm_missed must be a boolean")
    if c["status"] not in {"OPEN", "REOPENED"}:
        raise ApiError("ERR_COMPLAINT_INVALID_STATE", 409, "complaint not OPEN/REOPENED")
    c["status"] = "INVESTIGATING"
    c["missed_street_confirmed"] = confirm_missed
    touch(c)
    return ok(complaint_out(c))


@app.route("/complaints/<_id>/resolve", methods=["POST"])
def resolve_complaint(_id):
    require({"CitizenServices"})
    c = find(db.complaints, _id)
    if c["status"] != "INVESTIGATING":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE", 409, "complaint not INVESTIGATING")
    c["status"] = "RESOLVED"
    touch(c)
    return ok(complaint_out(c))


@app.route("/complaints/<_id>/reopen", methods=["POST"])
def reopen_complaint(_id):
    require({"CitizenServices"})
    c = find(db.complaints, _id)
    if c["status"] != "RESOLVED":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE", 409, "complaint not RESOLVED")
    c["status"] = "REOPENED"
    touch(c)
    return ok(complaint_out(c))


# ===========================================================================
# CostReport
# ===========================================================================
def _window_hours(ws, we):
    return Decimal(str((we - ws).total_seconds())) / Decimal("3600")


@app.route("/storm-events/<_id>/cost-reports", methods=["POST"])
def create_cost_report(_id):
    require({"DispatchSupervisor"})
    s = find(db.storms, _id)
    body = get_body()
    require_fields(body, ["variant"])
    variant = require_enum(body, "variant", {"ESTIMATE", "ACTUAL"})

    material_total = 0
    labor_total = 0
    if variant == "ACTUAL":
        for ap in db.applications.values():
            a = db.assignments.get(ap["route_assignment_id"])
            if a is None or a["storm_event_id"] != s["id"]:
                continue
            if ap["status"] != "RECORDED":
                continue
            if ap["material_type"] == "SALT":
                material_total += round_half_up_int(ap["salt_tons"] * SALT_UNIT_COST_CENTS)
            else:
                material_total += round_half_up_int(ap["brine_gallons"] * BRINE_UNIT_COST_CENTS)
        for c in db.callouts.values():
            if c["storm_event_id"] == s["id"] and c["status"] == "COMPLETED":
                labor_total += c["pay_cents"]
    else:  # ESTIMATE
        for a in db.assignments.values():
            if a["storm_event_id"] == s["id"] and a["status"] in {"PLANNED", "IN_PROGRESS", "COMPLETED"}:
                material_total += round_half_up_int(a["planned_material_tons"] * SALT_UNIT_COST_CENTS)
        for c in db.callouts.values():
            if c["storm_event_id"] == s["id"] and c["status"] in {"ISSUED", "COMPLETED"}:
                operator = db.operators.get(c["operator_id"])
                rate = Decimal(operator["hourly_rate_cents"]) if operator else Decimal("0")
                hours = _window_hours(c["_ws"], c["_we"])
                labor_total += round_half_up_int(hours * rate)

    total = material_total + labor_total
    ts = now()
    r = {"id": new_id(), "created_at": ts, "_seq": db.next_seq()}
    r.update({
        "storm_event_id": s["id"],
        "variant": variant,
        "total_material_cost_cents": material_total,
        "total_labor_cost_cents": labor_total,
        "total_cost_cents": total,
        "generated_at": ts,
    })
    db.cost_reports[r["id"]] = r
    return ok(cost_report_out(r), 201)


@app.route("/storm-events/<_id>/cost-reports", methods=["GET"])
def list_cost_reports(_id):
    require(ROLES)
    find(db.storms, _id)
    variant = request.args.get("variant")
    recs = [c for c in db.cost_reports.values()
            if c["storm_event_id"] == _id and (variant is None or c["variant"] == variant)]
    page, total, limit, offset = paginate(recs)
    return ok_list([cost_report_out(c) for c in page], total, limit, offset)


# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
