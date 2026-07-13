"""Beach & Lifeguard Operations API — Python + Flask, in-memory only.

Boots empty on every process start. Storage is process-local dicts.
"""
import os
import random
import string
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import Flask, request, jsonify

getcontext().prec = 50

app = Flask(__name__)
app.url_map.strict_slashes = False

UTC = timezone.utc

# --------------------------------------------------------------------------
# Roles / constants
# --------------------------------------------------------------------------
ROLE_CAPTAIN = "BeachCaptain"
ROLE_LIFEGUARD = "Lifeguard"
ROLE_INSPECTOR = "WaterQualityInspector"
ROLE_CLERK = "ParkingClerk"
ROLE_PUBLIC = "Public"
ALL_ROLES = {ROLE_CAPTAIN, ROLE_LIFEGUARD, ROLE_INSPECTOR, ROLE_CLERK, ROLE_PUBLIC}

ADVISORY_THRESHOLD_MPN = 35
CLOSURE_THRESHOLD_MPN = 104
GEOMEAN_WINDOW_DAYS = 30

WEEKEND_MULT = Decimal("1.5")
WEEKDAY_MULT = Decimal("1.0")
OVERSIZED_DAILY_SURCHARGE_CENTS = 2000
RESIDENT_DISCOUNT_RATE = Decimal("0.5")
SEASON_BASE_RESIDENT_CENTS = 15000
SEASON_BASE_NONRESIDENT_CENTS = 30000
OVERSIZED_SEASON_SURCHARGE_CENTS = 5000
TOWN_SURCHARGE_RATE = Decimal("0.085")

# --------------------------------------------------------------------------
# In-memory state
# --------------------------------------------------------------------------
STATE = {
    "clock": datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC),
    "seq": 0,
    "beaches": {},
    "zones": {},
    "towers": {},
    "lifeguards": {},
    "shifts": {},
    "incidents": {},
    "samples": {},
    "advisories": {},
    "lots": {},
    "passes": {},
}


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def new_id():
    import uuid
    return str(uuid.uuid4())


def wall_now_str():
    return format_dt(datetime.now(UTC))


def clock_now():
    return STATE["clock"]


def format_dt(dt):
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": wall_now_str(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, limit, offset, total, status=200):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_body(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return error_body("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _handle_405(e):
    return error_body("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(500)
def _handle_500(e):
    return error_body("ERR_INVALID_REQUEST", "Internal error", 500)


# --------------------------------------------------------------------------
# Auth / RBAC
# --------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# --------------------------------------------------------------------------
# Body / field validation helpers
# --------------------------------------------------------------------------
def body_json():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return raw


def require_present(body, field):
    if field not in body or body[field] is None:
        err("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    v = require_present(body, field)
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % field)
    return v


def require_int(body, field):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % field)
    return v


def require_enum(body, field, allowed):
    v = require_present(body, field)
    if v not in allowed:
        err("ERR_INVALID_REQUEST", 400, "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def require_dt(body, field):
    v = require_str(body, field)
    try:
        parse_dt(v)
    except Exception:
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an ISO 8601 datetime" % field)
    return v


def opt_int(body, field, default):
    if body.get(field) is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % field)
    return v


def opt_bool(body, field, default):
    if body.get(field) is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a boolean" % field)
    return v


def opt_str(body, field, default=None):
    if body.get(field) is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % field)
    return v


def opt_enum(body, field, allowed, default):
    if body.get(field) is None:
        return default
    v = body[field]
    if v not in allowed:
        err("ERR_INVALID_REQUEST", 400, "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


# --------------------------------------------------------------------------
# Store helpers
# --------------------------------------------------------------------------
def get_or_404(store, rid):
    obj = STATE[store].get(rid)
    if obj is None:
        err("ERR_RESOURCE_NOT_FOUND", 404, "%s not found" % rid)
    return obj


def check_fk(store, rid):
    if rid not in STATE[store]:
        err("ERR_RESOURCE_NOT_FOUND", 404, "%s not found" % rid)


def base_common():
    return {
        "id": new_id(),
        "created_at": wall_now_str(),
        "updated_at": wall_now_str(),
        "version": 1,
        "_seq": next_seq(),
    }


def touch(obj):
    obj["updated_at"] = wall_now_str()
    obj["version"] = obj.get("version", 1) + 1


def serialize(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def get_pagination():
    def as_int(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "%s must be an integer" % name)

    limit = as_int("limit", 10)
    offset = as_int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(store, predicate=None):
    limit, offset = get_pagination()
    rows = [o for o in STATE[store].values() if (predicate is None or predicate(o))]
    rows.sort(key=lambda o: o["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_array([serialize(o) for o in page], limit, offset, total)


# --------------------------------------------------------------------------
# Derived-field recomputation
# --------------------------------------------------------------------------
def zone_tower_ids(zone_id):
    return {t["id"] for t in STATE["towers"].values() if t["zone_id"] == zone_id}


def recompute_on_duty(zone):
    tids = zone_tower_ids(zone["id"])
    cnt = sum(
        1 for s in STATE["shifts"].values()
        if s["tower_id"] in tids and s["status"] in ("ON_DUTY", "ON_BREAK")
    )
    changed = cnt != zone["on_duty_guard_count"]
    zone["on_duty_guard_count"] = cnt
    return changed


def recompute_available(lot):
    active = sum(
        1 for p in STATE["passes"].values()
        if p["lot_id"] == lot["id"] and p["status"] == "ACTIVE"
    )
    lot["available_spaces"] = lot["total_spaces"] - active


def has_active_closure(zone_id):
    return any(
        a for a in STATE["advisories"].values()
        if a["zone_id"] == zone_id and a["level"] == "CLOSURE" and a["status"] == "ACTIVE"
    )


# --------------------------------------------------------------------------
# Calculations
# --------------------------------------------------------------------------
def bacteria_assessment(zone_id, basis):
    samples = [s for s in STATE["samples"].values() if s["zone_id"] == zone_id]
    if basis == "SINGLE_SAMPLE":
        if not samples:
            return 0, "NONE"
        latest = max(samples, key=lambda s: (parse_dt(s["sampled_at"]), s["_seq"]))
        assessed = latest["enterococci_mpn"]  # raw integer
    else:  # GEOMEAN_30DAY
        now = clock_now()
        window_start = now - timedelta(days=GEOMEAN_WINDOW_DAYS)
        window = [
            s for s in samples
            if window_start <= parse_dt(s["sampled_at"]) <= now
        ]
        if not window:
            return 0, "NONE"
        prod = Decimal(1)
        for s in window:
            prod *= Decimal(int(s["enterococci_mpn"]))
        n = len(window)
        gm = prod ** (Decimal(1) / Decimal(n))
        assessed = float(gm.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    val = assessed
    if val >= CLOSURE_THRESHOLD_MPN:
        level = "CLOSURE"
    elif val >= ADVISORY_THRESHOLD_MPN:
        level = "ADVISORY"
    else:
        level = "NONE"
    return assessed, level


def compute_parking_fee(lot, vehicle_type, pass_type, is_resident):
    if pass_type == "DAILY":
        wd = clock_now().date().weekday()  # Mon=0 .. Sun=6
        weekend = wd in (5, 6)
        base_mult = WEEKEND_MULT if weekend else WEEKDAY_MULT
        surcharge = Decimal(OVERSIZED_DAILY_SURCHARGE_CENTS) if vehicle_type == "OVERSIZED" else Decimal(0)
        discount = RESIDENT_DISCOUNT_RATE if is_resident else Decimal(0)
        amt = (Decimal(lot["daily_rate_cents"]) * base_mult + surcharge) * (Decimal(1) - discount)
        return int(amt.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:  # SEASON
        base = SEASON_BASE_RESIDENT_CENTS if is_resident else SEASON_BASE_NONRESIDENT_CENTS
        if vehicle_type == "OVERSIZED":
            base += OVERSIZED_SEASON_SURCHARGE_CENTS
        return base


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# --------------------------------------------------------------------------
# Logical clock control
# --------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {ROLE_CAPTAIN})
    body = body_json()
    to_iso = require_str(body, "to_iso8601")
    try:
        STATE["clock"] = parse_dt(to_iso)
    except Exception:
        err("ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO 8601 datetime")
    return ok_object({"now": format_dt(STATE["clock"])}, 200)


# --------------------------------------------------------------------------
# Beach
# --------------------------------------------------------------------------
@app.route("/beach-ops/beaches", methods=["POST"])
def create_beach():
    _, role = authenticate()
    authorize(role, {ROLE_CAPTAIN})
    body = body_json()
    name = require_str(body, "name")
    town_code = require_str(body, "town_code")
    start = require_str(body, "season_start_date")
    end = require_str(body, "season_end_date")
    if not (end > start):
        err("ERR_SEASON_DATES_INVALID", 422, "season_end_date must be after season_start_date")
    obj = base_common()
    obj.update({
        "name": name,
        "town_code": town_code,
        "season_start_date": start,
        "season_end_date": end,
    })
    STATE["beaches"][obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@app.route("/beach-ops/beaches/<beach_id>", methods=["GET"])
def get_beach(beach_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    obj = get_or_404("beaches", beach_id)
    return ok_object(serialize(obj), 200)


@app.route("/beach-ops/beaches/<beach_id>/seasonal-report", methods=["GET"])
def seasonal_report(beach_id):
    _, role = authenticate()
    authorize(role, {ROLE_CAPTAIN, ROLE_PUBLIC})
    beach = get_or_404("beaches", beach_id)

    zone_ids = {z["id"] for z in STATE["zones"].values() if z["beach_id"] == beach_id}
    incidents = [i for i in STATE["incidents"].values() if i["zone_id"] in zone_ids]
    total_incidents = len(incidents)
    rescue_count = sum(1 for i in incidents if i["type"] == "RESCUE")
    ems_escalations = sum(1 for i in incidents if i.get("_escalated"))
    total_water_samples = sum(1 for s in STATE["samples"].values() if s["zone_id"] in zone_ids)
    active_closures = sum(1 for zid in zone_ids if has_active_closure(zid))

    # Parking revenue: per-pass town surcharge, rounded per pass, then summed.
    lot_ids = {l["id"] for l in STATE["lots"].values() if l["beach_id"] == beach_id}
    total_parking_revenue_cents = 0
    for p in STATE["passes"].values():
        if p["lot_id"] in lot_ids and p["status"] == "ACTIVE":
            line = (Decimal(p["fee_cents"]) * (Decimal(1) + TOWN_SURCHARGE_RATE)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
            total_parking_revenue_cents += int(line)

    # Coverage over shifts whose tower's zone belongs to this beach.
    beach_tower_ids = set()
    for t in STATE["towers"].values():
        z = STATE["zones"].get(t["zone_id"])
        if z is not None and z["beach_id"] == beach_id:
            beach_tower_ids.add(t["id"])

    scheduled_coverage_minutes = 0
    actual_coverage_minutes = 0
    for s in STATE["shifts"].values():
        if s["tower_id"] not in beach_tower_ids:
            continue
        if s["status"] != "CANCELLED":
            secs = (parse_dt(s["scheduled_end"]) - parse_dt(s["scheduled_start"])).total_seconds()
            scheduled_coverage_minutes += int(secs // 60)
        if s.get("clock_in_at"):
            end = parse_dt(s["clock_out_at"]) if s.get("clock_out_at") else clock_now()
            secs = (end - parse_dt(s["clock_in_at"])).total_seconds()
            actual_coverage_minutes += int(secs // 60)

    report = {
        "total_incidents": total_incidents,
        "rescue_count": rescue_count,
        "ems_escalations": ems_escalations,
        "total_water_samples": total_water_samples,
        "active_closures": active_closures,
        "total_parking_revenue_cents": total_parking_revenue_cents,
        "scheduled_coverage_minutes": scheduled_coverage_minutes,
        "actual_coverage_minutes": actual_coverage_minutes,
    }
    return ok_object(report, 200)


# --------------------------------------------------------------------------
# Zone
# --------------------------------------------------------------------------
@app.route("/beach-ops/zones", methods=["POST"])
def create_zone():
    _, role = authenticate()
    authorize(role, {ROLE_CAPTAIN})
    body = body_json()
    if body.get("beach_id") is not None:
        check_fk("beaches", body["beach_id"])
    beach_id = require_str(body, "beach_id")
    name = require_str(body, "name")
    min_guards = opt_int(body, "min_guards_required", 1)
    obj = base_common()
    obj.update({
        "beach_id": beach_id,
        "name": name,
        "min_guards_required": min_guards,
        "flag_status": "RED",
        "water_status": "OPEN",
        "rip_current_level": "LOW",
        "on_duty_guard_count": 0,
        "weather_note": "",
    })
    STATE["zones"][obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@app.route("/beach-ops/zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    obj = get_or_404("zones", zone_id)
    return ok_object(serialize(obj), 200)


@app.route("/beach-ops/zones", methods=["GET"])
def list_zones():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    beach_id = request.args.get("beach_id")
    return list_response("zones", lambda z: beach_id is None or z["beach_id"] == beach_id)


@app.route("/beach-ops/zones/<zone_id>/flag", methods=["POST"])
def set_flag(zone_id):
    _, role = authenticate()
    authorize(role, {ROLE_CAPTAIN})
    zone = get_or_404("zones", zone_id)
    body = body_json()
    target = require_enum(body, "flag_status", {"GREEN", "YELLOW", "RED", "BLACK"})
    cur = zone["flag_status"]
    legal = {
        ("RED", "GREEN"),
        ("GREEN", "YELLOW"),
        ("YELLOW", "GREEN"),
        ("GREEN", "RED"),
        ("YELLOW", "RED"),
    }
    if (cur, target) not in legal:
        err("ERR_INVALID_STATE", 409, "Illegal flag transition %s -> %s" % (cur, target))
    if target in ("GREEN", "YELLOW"):
        if zone["water_status"] != "OPEN" or has_active_closure(zone_id):
            err("ERR_ZONE_UNDER_CLOSURE", 409, "Zone is under an active closure")
        if zone["rip_current_level"] == "HIGH":
            err("ERR_RIP_CURRENT_UNSAFE", 409, "Rip current is HIGH")
        if zone["on_duty_guard_count"] < zone["min_guards_required"]:
            err("ERR_ZONE_UNDERSTAFFED", 409, "Zone is understaffed")
    zone["flag_status"] = target
    touch(zone)
    return ok_object(serialize(zone), 200)


@app.route("/beach-ops/zones/<zone_id>/conditions", methods=["POST"])
def set_conditions(zone_id):
    _, role = authenticate()
    authorize(role, {ROLE_CAPTAIN})
    zone = get_or_404("zones", zone_id)
    body = body_json()
    rip = require_enum(body, "rip_current_level", {"LOW", "MODERATE", "HIGH"})
    note = opt_str(body, "weather_note", None)
    zone["rip_current_level"] = rip
    if "weather_note" in body and body["weather_note"] is not None:
        zone["weather_note"] = note
    if rip == "HIGH" and zone["flag_status"] in ("GREEN", "YELLOW"):
        zone["flag_status"] = "RED"
    touch(zone)
    return ok_object(serialize(zone), 200)


@app.route("/beach-ops/zones/<zone_id>/advisories", methods=["POST"])
def create_advisory(zone_id):
    _, role = authenticate()
    authorize(role, {ROLE_INSPECTOR})
    zone = get_or_404("zones", zone_id)
    body = body_json()
    basis = require_enum(body, "basis", {"SINGLE_SAMPLE", "GEOMEAN_30DAY"})
    expected = require_int(body, "expected_zone_version")
    reason = opt_str(body, "reason", None)
    if expected != zone["version"]:
        err("ERR_STALE_VERSION", 412, "expected_zone_version does not match current zone version")

    assessed, level = bacteria_assessment(zone_id, basis)

    adv = base_common()
    adv.update({
        "zone_id": zone_id,
        "basis": basis,
        "level": level,
        "assessed_value": assessed,
        "status": "ACTIVE",
        "reason": reason,
        "issued_at": format_dt(clock_now()),
    })

    # Supersede prior ACTIVE advisory for the zone.
    for a in STATE["advisories"].values():
        if a["zone_id"] == zone_id and a["status"] == "ACTIVE":
            a["status"] = "SUPERSEDED"
            touch(a)

    STATE["advisories"][adv["id"]] = adv

    # Closure cascade.
    if level == "CLOSURE":
        zone["flag_status"] = "BLACK"
        zone["water_status"] = "CLOSED"
        tids = zone_tower_ids(zone_id)
        for s in STATE["shifts"].values():
            if s["tower_id"] in tids and s["status"] == "SCHEDULED":
                s["status"] = "CANCELLED"
                touch(s)

    # Issuance always mutates the zone version exactly once.
    touch(zone)
    return ok_object(serialize(adv), 201)


# --------------------------------------------------------------------------
# Tower
# --------------------------------------------------------------------------
@app.route("/beach-ops/towers", methods=["POST"])
def create_tower():
    _, role = authenticate()
    authorize(role, {ROLE_CAPTAIN})
    body = body_json()
    if body.get("zone_id") is not None:
        check_fk("zones", body["zone_id"])
    zone_id = require_str(body, "zone_id")
    label = require_str(body, "label")
    max_guards = opt_int(body, "max_concurrent_guards", 2)
    obj = base_common()
    obj.update({
        "zone_id": zone_id,
        "label": label,
        "max_concurrent_guards": max_guards,
        "status": "OPEN",
    })
    STATE["towers"][obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@app.route("/beach-ops/towers/<tower_id>", methods=["GET"])
def get_tower(tower_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    obj = get_or_404("towers", tower_id)
    return ok_object(serialize(obj), 200)


@app.route("/beach-ops/towers", methods=["GET"])
def list_towers():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    zone_id = request.args.get("zone_id")
    return list_response("towers", lambda t: zone_id is None or t["zone_id"] == zone_id)


@app.route("/beach-ops/towers/<tower_id>/status", methods=["POST"])
def set_tower_status(tower_id):
    _, role = authenticate()
    authorize(role, {ROLE_CAPTAIN})
    tower = get_or_404("towers", tower_id)
    body = body_json()
    target = require_enum(body, "status", {"OPEN", "OFFLINE"})
    tower["status"] = target
    touch(tower)
    return ok_object(serialize(tower), 200)


# --------------------------------------------------------------------------
# Lifeguard
# --------------------------------------------------------------------------
@app.route("/beach-ops/lifeguards", methods=["POST"])
def create_lifeguard():
    _, role = authenticate()
    authorize(role, {ROLE_CAPTAIN})
    body = body_json()
    if body.get("beach_id") is not None:
        check_fk("beaches", body["beach_id"])
    beach_id = require_str(body, "beach_id")
    name = require_str(body, "name")
    cert = require_enum(body, "certification_level", {"JUNIOR", "SENIOR", "CAPTAIN"})
    emp = require_str(body, "employee_ref")
    obj = base_common()
    obj.update({
        "beach_id": beach_id,
        "name": name,
        "certification_level": cert,
        "employee_ref": emp,
    })
    STATE["lifeguards"][obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@app.route("/beach-ops/lifeguards/<lifeguard_id>", methods=["GET"])
def get_lifeguard(lifeguard_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    obj = get_or_404("lifeguards", lifeguard_id)
    return ok_object(serialize(obj), 200)


@app.route("/beach-ops/lifeguards", methods=["GET"])
def list_lifeguards():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    beach_id = request.args.get("beach_id")
    return list_response("lifeguards", lambda l: beach_id is None or l["beach_id"] == beach_id)


# --------------------------------------------------------------------------
# Shift
# --------------------------------------------------------------------------
def _shift_intervals_for_tower(tower_id, exclude_id=None):
    out = []
    for s in STATE["shifts"].values():
        if s["tower_id"] != tower_id or s["status"] == "CANCELLED":
            continue
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        out.append((parse_dt(s["scheduled_start"]), parse_dt(s["scheduled_end"])))
    return out


@app.route("/beach-ops/shifts", methods=["POST"])
def create_shift():
    _, role = authenticate()
    authorize(role, {ROLE_CAPTAIN})
    body = body_json()
    # FK existence, left to right.
    if body.get("lifeguard_id") is not None:
        check_fk("lifeguards", body["lifeguard_id"])
    if body.get("tower_id") is not None:
        check_fk("towers", body["tower_id"])
    lifeguard_id = require_str(body, "lifeguard_id")
    tower_id = require_str(body, "tower_id")
    start = require_dt(body, "scheduled_start")
    end = require_dt(body, "scheduled_end")

    s_start = parse_dt(start)
    s_end = parse_dt(end)
    # Domain checks in order: window -> tower online -> double-booked -> capacity.
    if not (s_end > s_start):
        err("ERR_SHIFT_WINDOW_INVALID", 422, "scheduled_end must be after scheduled_start")

    tower = STATE["towers"][tower_id]
    if tower["status"] != "OPEN":
        err("ERR_TOWER_OFFLINE", 409, "Tower is OFFLINE")

    # Double booking for the same lifeguard (half-open overlap).
    for s in STATE["shifts"].values():
        if s["lifeguard_id"] != lifeguard_id or s["status"] == "CANCELLED":
            continue
        o_start = parse_dt(s["scheduled_start"])
        o_end = parse_dt(s["scheduled_end"])
        if s_start < o_end and o_start < s_end:
            err("ERR_LIFEGUARD_DOUBLE_BOOKED", 409, "Lifeguard is double-booked")

    # Tower capacity: max concurrent non-cancelled shifts within the interval.
    existing = _shift_intervals_for_tower(tower_id)
    candidates = [s_start] + [st for (st, en) in existing if s_start <= st < s_end]
    max_overlap = 0
    for pt in candidates:
        cover = sum(1 for (st, en) in existing if st <= pt < en)
        if cover > max_overlap:
            max_overlap = cover
    if max_overlap + 1 > tower["max_concurrent_guards"]:
        err("ERR_TOWER_CAPACITY_EXCEEDED", 409, "Tower capacity exceeded")

    obj = base_common()
    obj.update({
        "lifeguard_id": lifeguard_id,
        "tower_id": tower_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "SCHEDULED",
        "clock_in_at": None,
        "clock_out_at": None,
    })
    STATE["shifts"][obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@app.route("/beach-ops/shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    obj = get_or_404("shifts", shift_id)
    return ok_object(serialize(obj), 200)


@app.route("/beach-ops/shifts", methods=["GET"])
def list_shifts():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    lifeguard_id = request.args.get("lifeguard_id")
    tower_id = request.args.get("tower_id")

    def pred(s):
        if lifeguard_id is not None and s["lifeguard_id"] != lifeguard_id:
            return False
        if tower_id is not None and s["tower_id"] != tower_id:
            return False
        return True

    return list_response("shifts", pred)


@app.route("/beach-ops/shifts/<shift_id>/transitions", methods=["POST"])
def shift_transition(shift_id):
    _, role = authenticate()
    authorize(role, {ROLE_LIFEGUARD, ROLE_CAPTAIN})
    shift = get_or_404("shifts", shift_id)
    body = body_json()
    action = require_enum(body, "action", {"CLOCK_IN", "BREAK", "RESUME", "CLOCK_OUT", "CANCEL"})

    # Per-action role refinement.
    if action == "CANCEL":
        if role != ROLE_CAPTAIN:
            err("ERR_UNAUTHORIZED", 403, "Only BeachCaptain may cancel a shift")
    else:
        if role != ROLE_LIFEGUARD:
            err("ERR_UNAUTHORIZED", 403, "Only Lifeguard may drive the duty clock")

    cur = shift["status"]

    if action == "CLOCK_IN":
        if cur != "SCHEDULED":
            err("ERR_INVALID_STATE", 409, "Cannot clock in from %s" % cur)
        tower = STATE["towers"][shift["tower_id"]]
        if tower["status"] != "OPEN":
            err("ERR_TOWER_OFFLINE", 409, "Tower is OFFLINE")
        shift["status"] = "ON_DUTY"
        shift["clock_in_at"] = format_dt(clock_now())
        touch(shift)
        zone = STATE["zones"].get(tower["zone_id"])
        if zone is not None and recompute_on_duty(zone):
            touch(zone)

    elif action == "BREAK":
        if cur != "ON_DUTY":
            err("ERR_INVALID_STATE", 409, "Cannot take break from %s" % cur)
        shift["status"] = "ON_BREAK"
        touch(shift)

    elif action == "RESUME":
        if cur != "ON_BREAK":
            err("ERR_INVALID_STATE", 409, "Cannot resume from %s" % cur)
        shift["status"] = "ON_DUTY"
        touch(shift)

    elif action == "CLOCK_OUT":
        if cur not in ("ON_DUTY", "ON_BREAK"):
            err("ERR_INVALID_STATE", 409, "Cannot clock out from %s" % cur)
        shift["status"] = "OFF_DUTY"
        shift["clock_out_at"] = format_dt(clock_now())
        touch(shift)
        tower = STATE["towers"][shift["tower_id"]]
        zone = STATE["zones"].get(tower["zone_id"])
        if zone is not None:
            changed = recompute_on_duty(zone)
            flag_changed = False
            if (zone["on_duty_guard_count"] < zone["min_guards_required"]
                    and zone["flag_status"] in ("GREEN", "YELLOW")):
                zone["flag_status"] = "RED"
                flag_changed = True
            if changed or flag_changed:
                touch(zone)

    elif action == "CANCEL":
        if cur != "SCHEDULED":
            err("ERR_INVALID_STATE", 409, "Cannot cancel from %s" % cur)
        shift["status"] = "CANCELLED"
        touch(shift)

    return ok_object(serialize(shift), 200)


# --------------------------------------------------------------------------
# Incident
# --------------------------------------------------------------------------
@app.route("/beach-ops/incidents", methods=["POST"])
def create_incident():
    _, role = authenticate()
    authorize(role, {ROLE_LIFEGUARD})
    body = body_json()
    if body.get("zone_id") is not None:
        check_fk("zones", body["zone_id"])
    if body.get("lifeguard_id") is not None:
        check_fk("lifeguards", body["lifeguard_id"])
    zone_id = require_str(body, "zone_id")
    itype = require_enum(body, "type", {"RESCUE", "MEDICAL", "LOST_CHILD", "FIRST_AID"})
    occurred_at = require_dt(body, "occurred_at")
    description = require_str(body, "description")
    severity = opt_enum(body, "severity", {"LOW", "MODERATE", "CRITICAL"}, "LOW")
    victim_count = opt_int(body, "victim_count", 1)
    lifeguard_id = opt_str(body, "lifeguard_id", None)

    obj = base_common()
    obj.update({
        "zone_id": zone_id,
        "lifeguard_id": lifeguard_id,
        "type": itype,
        "severity": severity,
        "occurred_at": occurred_at,
        "victim_count": victim_count,
        "description": description,
        "status": "OPEN",
        "ems_transported": None,
        "ems_hospital": None,
        "ems_unit": None,
        "ems_narrative": None,
        "_escalated": False,
    })
    STATE["incidents"][obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@app.route("/beach-ops/incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    obj = get_or_404("incidents", incident_id)
    return ok_object(serialize(obj), 200)


@app.route("/beach-ops/incidents", methods=["GET"])
def list_incidents():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    zone_id = request.args.get("zone_id")
    lifeguard_id = request.args.get("lifeguard_id")

    def pred(i):
        if zone_id is not None and i["zone_id"] != zone_id:
            return False
        if lifeguard_id is not None and i["lifeguard_id"] != lifeguard_id:
            return False
        return True

    return list_response("incidents", pred)


@app.route("/beach-ops/incidents/<incident_id>/transitions", methods=["POST"])
def incident_transition(incident_id):
    _, role = authenticate()
    authorize(role, {ROLE_LIFEGUARD})
    incident = get_or_404("incidents", incident_id)
    body = body_json()
    action = require_enum(body, "action", {"RESOLVE_ON_SCENE", "ESCALATE_EMS", "REUNITE", "CLOSE"})
    cur = incident["status"]

    if action == "RESOLVE_ON_SCENE":
        if cur != "OPEN":
            err("ERR_INVALID_STATE", 409, "Cannot resolve from %s" % cur)
        incident["status"] = "RESOLVED_ON_SCENE"
        touch(incident)

    elif action == "ESCALATE_EMS":
        if cur != "OPEN":
            err("ERR_INVALID_STATE", 409, "Cannot escalate from %s" % cur)
        for f in ("ems_hospital", "ems_unit", "ems_narrative", "ems_transported"):
            if body.get(f) is None:
                err("ERR_EMS_DETAILS_REQUIRED", 422, "ESCALATE_EMS requires all EMS handoff fields")
        if not isinstance(body["ems_transported"], bool):
            err("ERR_EMS_DETAILS_REQUIRED", 422, "ems_transported must be a boolean")
        incident["ems_hospital"] = body["ems_hospital"]
        incident["ems_unit"] = body["ems_unit"]
        incident["ems_narrative"] = body["ems_narrative"]
        incident["ems_transported"] = body["ems_transported"]
        incident["status"] = "ESCALATED_EMS"
        incident["_escalated"] = True
        touch(incident)

    elif action == "REUNITE":
        if cur != "OPEN":
            err("ERR_INVALID_STATE", 409, "Cannot reunite from %s" % cur)
        if incident["type"] != "LOST_CHILD":
            err("ERR_INCIDENT_TYPE_MISMATCH", 422, "REUNITE only valid on LOST_CHILD incidents")
        incident["status"] = "REUNITED"
        touch(incident)

    elif action == "CLOSE":
        if cur not in ("RESOLVED_ON_SCENE", "ESCALATED_EMS", "REUNITED"):
            err("ERR_INVALID_STATE", 409, "Cannot close from %s" % cur)
        incident["status"] = "CLOSED"
        touch(incident)

    return ok_object(serialize(incident), 200)


# --------------------------------------------------------------------------
# Water-quality samples
# --------------------------------------------------------------------------
@app.route("/beach-ops/water-quality-samples", methods=["POST"])
def create_sample():
    _, role = authenticate()
    authorize(role, {ROLE_INSPECTOR})
    body = body_json()
    if body.get("zone_id") is not None:
        check_fk("zones", body["zone_id"])
    zone_id = require_str(body, "zone_id")
    mpn = require_int(body, "enterococci_mpn")
    if mpn < 0:
        err("ERR_INVALID_REQUEST", 400, "enterococci_mpn must be >= 0")
    sampled_at = require_dt(body, "sampled_at")
    lab_ref = require_str(body, "lab_ref")
    technician = require_str(body, "technician")

    obj = {
        "id": new_id(),
        "created_at": wall_now_str(),
        "_seq": next_seq(),
        "zone_id": zone_id,
        "enterococci_mpn": mpn,
        "sampled_at": sampled_at,
        "lab_ref": lab_ref,
        "technician": technician,
    }
    STATE["samples"][obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@app.route("/beach-ops/water-quality-samples/<sample_id>", methods=["GET"])
def get_sample(sample_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    obj = get_or_404("samples", sample_id)
    return ok_object(serialize(obj), 200)


@app.route("/beach-ops/water-quality-samples", methods=["GET"])
def list_samples():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    zone_id = request.args.get("zone_id")
    return list_response("samples", lambda s: zone_id is None or s["zone_id"] == zone_id)


# --------------------------------------------------------------------------
# Advisory
# --------------------------------------------------------------------------
@app.route("/beach-ops/advisories/<advisory_id>", methods=["GET"])
def get_advisory(advisory_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    obj = get_or_404("advisories", advisory_id)
    return ok_object(serialize(obj), 200)


@app.route("/beach-ops/advisories", methods=["GET"])
def list_advisories():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    zone_id = request.args.get("zone_id")
    return list_response("advisories", lambda a: zone_id is None or a["zone_id"] == zone_id)


@app.route("/beach-ops/advisories/<advisory_id>/lift", methods=["POST"])
def lift_advisory(advisory_id):
    _, role = authenticate()
    authorize(role, {ROLE_INSPECTOR})
    adv = get_or_404("advisories", advisory_id)
    body = body_json()
    _ = opt_str(body, "reason", None)
    if adv["status"] != "ACTIVE":
        err("ERR_ADVISORY_NOT_ACTIVE", 409, "Advisory is not ACTIVE")
    adv["status"] = "LIFTED"
    touch(adv)
    if adv["level"] == "CLOSURE":
        zone = STATE["zones"].get(adv["zone_id"])
        if zone is not None:
            zone["water_status"] = "OPEN"
            if zone["flag_status"] == "BLACK":
                zone["flag_status"] = "RED"
            touch(zone)
    return ok_object(serialize(adv), 200)


# --------------------------------------------------------------------------
# Parking lots
# --------------------------------------------------------------------------
@app.route("/beach-ops/parking-lots", methods=["POST"])
def create_lot():
    _, role = authenticate()
    authorize(role, {ROLE_CLERK, ROLE_CAPTAIN})
    body = body_json()
    if body.get("beach_id") is not None:
        check_fk("beaches", body["beach_id"])
    beach_id = require_str(body, "beach_id")
    name = require_str(body, "name")
    total_spaces = require_int(body, "total_spaces")
    if total_spaces < 1:
        err("ERR_INVALID_REQUEST", 400, "total_spaces must be >= 1")
    daily_rate = require_int(body, "daily_rate_cents")
    obj = base_common()
    obj.update({
        "beach_id": beach_id,
        "name": name,
        "total_spaces": total_spaces,
        "available_spaces": total_spaces,
        "daily_rate_cents": daily_rate,
    })
    STATE["lots"][obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@app.route("/beach-ops/parking-lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    obj = get_or_404("lots", lot_id)
    return ok_object(serialize(obj), 200)


@app.route("/beach-ops/parking-lots", methods=["GET"])
def list_lots():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    beach_id = request.args.get("beach_id")
    return list_response("lots", lambda l: beach_id is None or l["beach_id"] == beach_id)


# --------------------------------------------------------------------------
# Parking passes
# --------------------------------------------------------------------------
@app.route("/beach-ops/parking-passes", methods=["POST"])
def create_pass():
    _, role = authenticate()
    authorize(role, {ROLE_CLERK})
    body = body_json()
    if body.get("lot_id") is not None:
        check_fk("lots", body["lot_id"])
    lot_id = require_str(body, "lot_id")
    plate = require_str(body, "plate")
    vehicle_type = require_enum(body, "vehicle_type", {"CAR", "OVERSIZED"})
    pass_type = require_enum(body, "pass_type", {"DAILY", "SEASON"})
    is_resident = opt_bool(body, "is_resident", False)

    lot = STATE["lots"][lot_id]
    if lot["available_spaces"] < 1:
        err("ERR_LOT_FULL", 409, "Parking lot has no available spaces")

    fee = compute_parking_fee(lot, vehicle_type, pass_type, is_resident)
    obj = base_common()
    obj.update({
        "lot_id": lot_id,
        "plate": plate,
        "vehicle_type": vehicle_type,
        "pass_type": pass_type,
        "is_resident": is_resident,
        "fee_cents": fee,
        "status": "ACTIVE",
        "issued_at": format_dt(clock_now()),
    })
    STATE["passes"][obj["id"]] = obj
    recompute_available(lot)
    touch(lot)
    return ok_object(serialize(obj), 201)


@app.route("/beach-ops/parking-passes/<pass_id>", methods=["GET"])
def get_pass(pass_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    obj = get_or_404("passes", pass_id)
    return ok_object(serialize(obj), 200)


@app.route("/beach-ops/parking-passes", methods=["GET"])
def list_passes():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    lot_id = request.args.get("lot_id")
    return list_response("passes", lambda p: lot_id is None or p["lot_id"] == lot_id)


@app.route("/beach-ops/parking-passes/<pass_id>/revoke", methods=["POST"])
def revoke_pass(pass_id):
    _, role = authenticate()
    authorize(role, {ROLE_CLERK})
    p = get_or_404("passes", pass_id)
    body = body_json()
    _ = opt_str(body, "reason", None)
    if p["status"] != "ACTIVE":
        err("ERR_PASS_NOT_ACTIVE", 409, "Parking pass is not ACTIVE")
    p["status"] = "REVOKED"
    touch(p)
    lot = STATE["lots"].get(p["lot_id"])
    if lot is not None:
        recompute_available(lot)
        touch(lot)
    return ok_object(serialize(p), 200)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
