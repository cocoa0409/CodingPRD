"""
SORNA — Sex-Offender & Registrant Compliance API
Python + Flask, in-memory store, logical clock. See workspace/PRD.md.
"""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (wiped on every boot; no seeding)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0)

STATE = {"clock": DEFAULT_CLOCK, "seq": 0}

jurisdictions = {}
exclusion_zones = {}
registrants = {}
offenses = {}
addresses = {}
verifications = {}
flags = {}
travel_notices = {}
notifications = {}
petitions = {}

ROLES = {"RegistryAdmin", "RegistrationOfficer", "ComplianceReviewer", "Registrant"}

FLAG_META = {
    "LATE_VERIFICATION": ("MAJOR", 15),
    "UNREPORTED_MOVE": ("MAJOR", 15),
    "TRAVEL_VIOLATION": ("MINOR", 5),
    "EXCLUSION_VIOLATION": ("CRITICAL", 40),
    "ABSCONDED": ("CRITICAL", 40),
}

DELINQUENT_THRESHOLD = 15
DECAY_PER_DAY = Decimal("0.01")
DECAY_FLOOR = Decimal("0.5")
TRAVEL_OVERDUE_GRACE_DAYS = 2

CLASS_BASE = {"CLASS_A": 30, "CLASS_B": 20, "CLASS_C": 10}
AGG_BONUS = 10
PRIOR_BONUS_PER = 5
T2_MIN = 30
T3_MIN = 60

INTERVAL_BY_TIER = {"TIER_1": 365, "TIER_2": 180, "TIER_3": 90}
NOTIF_RADIUS = {"TIER_1": 0, "TIER_2": 500, "TIER_3": 1500}
NOTIF_MULT = {"TIER_1": 0, "TIER_2": 3, "TIER_3": 10}
MIN_YEARS = {"TIER_1": 10, "TIER_2": 25, "TIER_3": 999}
ADJ_MAX = 30

TRAVEL_NON_TERMINAL = {"SUBMITTED", "APPROVED", "ACTIVE", "OVERDUE"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_wall():
    return datetime.now(timezone.utc)


def fmt_ms(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_z(dt):
    """Serialize a logical-clock datetime, matching input format (no fractional
    when whole-second)."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def clock():
    return STATE["clock"]


def stamp_clock():
    return iso_z(STATE["clock"])


def add_years(dt, years):
    y = dt.year + years
    try:
        return dt.replace(year=y)
    except ValueError:
        return dt.replace(year=y, day=28)


def rhu(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def new_common():
    ts = fmt_ms(now_wall())
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_light():
    return {
        "id": str(uuid.uuid4()),
        "created_at": fmt_ms(now_wall()),
        "_seq": next_seq(),
    }


def touch(rec):
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = fmt_ms(now_wall())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def make_meta(pagination=None):
    meta = {
        "api_request_id": gen_req_id(),
        "api_request_timestamp": fmt_ms(now_wall()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, response_type="object", status=200, pagination=None):
    return (
        jsonify({"meta": make_meta(pagination), "response_type": response_type, "data": data}),
        status,
    )


@app.errorhandler(ApiError)
def handle_api_error(err):
    return (
        jsonify(
            {
                "meta": make_meta(),
                "response_type": "error",
                "data": {"error_id": err.error_id, "message": err.message},
            }
        ),
        err.http_status,
    )


# ---------------------------------------------------------------------------
# Request parsing / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return body


def req_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
        return None
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a string")
    return v


def req_int(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an integer")
    return v


def req_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a boolean")
    return v


def check_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, f"Field {field} has invalid value: {value}")


def parse_dt_field(value, field):
    try:
        return parse_iso(value)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} is not a valid ISO 8601 datetime")


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth_ctx():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized authentication headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def registrant_scope_guard(role, user_id, registrant_id):
    if role == "Registrant" and user_id != registrant_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Registrant may act only on its own record")


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_jurisdiction(jid, err="ERR_JURISDICTION_NOT_FOUND"):
    j = jurisdictions.get(jid)
    if j is None:
        raise ApiError(err, 404, "Jurisdiction not found")
    return j


def get_registrant(rid):
    r = registrants.get(rid)
    if r is None:
        raise ApiError("ERR_REGISTRANT_NOT_FOUND", 404, "Registrant not found")
    return r


def get_zone(zid):
    z = exclusion_zones.get(zid)
    if z is None:
        raise ApiError("ERR_EXCLUSION_ZONE_NOT_FOUND", 404, "Exclusion zone not found")
    return z


def get_flag(fid):
    f = flags.get(fid)
    if f is None:
        raise ApiError("ERR_FLAG_NOT_FOUND", 404, "Compliance flag not found")
    return f


def get_travel(tid):
    t = travel_notices.get(tid)
    if t is None:
        raise ApiError("ERR_TRAVEL_NOTICE_NOT_FOUND", 404, "Travel notice not found")
    return t


def get_petition(pid):
    p = petitions.get(pid)
    if p is None:
        raise ApiError("ERR_PETITION_NOT_FOUND", 404, "Petition not found")
    return p


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 422, "limit out of range")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 422, "offset must be >= 0")
    return limit, offset


def paginate(items):
    items = sorted(items, key=lambda r: r["_seq"])
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset : offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pag


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def active_registrant_count(jid):
    return sum(
        1
        for r in registrants.values()
        if r["jurisdiction_id"] == jid and r["status"] in ("ACTIVE", "DELINQUENT")
    )


def active_travel_hold_count(jid):
    return sum(
        1
        for t in travel_notices.values()
        if t["destination_jurisdiction_id"] == jid and t["status"] in ("APPROVED", "ACTIVE")
    )


def ser_jurisdiction(j):
    return {
        "id": j["id"],
        "name": j["name"],
        "state_code": j["state_code"],
        "verification_grace_days": j["verification_grace_days"],
        "est_households_per_notification": j["est_households_per_notification"],
        "status": j["status"],
        "active_registrant_count": active_registrant_count(j["id"]),
        "active_travel_hold_count": active_travel_hold_count(j["id"]),
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def ser_zone(z):
    return {
        "id": z["id"],
        "jurisdiction_id": z["jurisdiction_id"],
        "name": z["name"],
        "zone_type": z["zone_type"],
        "center_x": z["center_x"],
        "center_y": z["center_y"],
        "radius_meters": z["radius_meters"],
        "buffer_meters": z["buffer_meters"],
        "status": z["status"],
        "created_at": z["created_at"],
        "updated_at": z["updated_at"],
        "version": z["version"],
    }


def ser_registrant(r):
    return {
        "id": r["id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "full_name": r["full_name"],
        "date_of_birth": r["date_of_birth"],
        "initial_registration_date": r["initial_registration_date"],
        "tier": r["tier"],
        "tier_score": r["tier_score"],
        "verification_interval_days": r["verification_interval_days"],
        "last_verified_date": r["last_verified_date"],
        "next_verification_due": r["next_verification_due"],
        "risk_score": r["risk_score"],
        "current_residence_address_id": r["current_residence_address_id"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_offense(o):
    return {
        "id": o["id"],
        "registrant_id": o["registrant_id"],
        "statute_code": o["statute_code"],
        "offense_class": o["offense_class"],
        "is_aggravated": o["is_aggravated"],
        "victim_minor": o["victim_minor"],
        "conviction_date": o["conviction_date"],
        "offense_points": o["offense_points"],
        "created_at": o["created_at"],
    }


def ser_address(a):
    return {
        "id": a["id"],
        "registrant_id": a["registrant_id"],
        "address_type": a["address_type"],
        "line1": a["line1"],
        "city": a["city"],
        "state_code": a["state_code"],
        "postal_code": a["postal_code"],
        "grid_x": a["grid_x"],
        "grid_y": a["grid_y"],
        "effective_from": a["effective_from"],
        "effective_to": a["effective_to"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_verification(v):
    return {
        "id": v["id"],
        "registrant_id": v["registrant_id"],
        "verification_type": v["verification_type"],
        "method": v["method"],
        "officer_ref": v["officer_ref"],
        "completed_date": v["completed_date"],
        "result": v["result"],
        "created_at": v["created_at"],
    }


def ser_flag(f):
    return {
        "id": f["id"],
        "registrant_id": f["registrant_id"],
        "flag_type": f["flag_type"],
        "severity": f["severity"],
        "base_points": f["base_points"],
        "opened_date": f["opened_date"],
        "resolved_date": f["resolved_date"],
        "status": f["status"],
        "note": f["note"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_travel(t):
    return {
        "id": t["id"],
        "registrant_id": t["registrant_id"],
        "destination_jurisdiction_id": t["destination_jurisdiction_id"],
        "travel_type": t["travel_type"],
        "departure_date": t["departure_date"],
        "return_date": t["return_date"],
        "decision_note": t["decision_note"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_notification(n):
    return {
        "id": n["id"],
        "registrant_id": n["registrant_id"],
        "audience_scope": n["audience_scope"],
        "radius_meters": n["radius_meters"],
        "estimated_recipients": n["estimated_recipients"],
        "actual_recipients": n["actual_recipients"],
        "dispatched_date": n["dispatched_date"],
        "created_at": n["created_at"],
    }


def ser_petition(p):
    return {
        "id": p["id"],
        "registrant_id": p["registrant_id"],
        "petition_type": p["petition_type"],
        "filed_date": p["filed_date"],
        "adjudicated_risk_score": p["adjudicated_risk_score"],
        "eligibility_met": p["eligibility_met"],
        "reviewer_ref": p["reviewer_ref"],
        "decided_date": p["decided_date"],
        "decision": p["decision"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


# ---------------------------------------------------------------------------
# Domain sub-collections
# ---------------------------------------------------------------------------
def reg_offenses(rid):
    return [o for o in offenses.values() if o["registrant_id"] == rid]


def reg_addresses(rid):
    return [a for a in addresses.values() if a["registrant_id"] == rid]


def reg_flags(rid):
    return [f for f in flags.values() if f["registrant_id"] == rid]


def reg_open_flags(rid):
    return [f for f in flags.values() if f["registrant_id"] == rid and f["status"] == "OPEN"]


def reg_travels(rid):
    return [t for t in travel_notices.values() if t["registrant_id"] == rid]


def reg_petitions(rid):
    return [p for p in petitions.values() if p["registrant_id"] == rid]


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_offense_points(offense_class, is_aggravated, victim_minor):
    base = CLASS_BASE[offense_class]
    raw = base + (AGG_BONUS if is_aggravated else 0)
    mult = Decimal("1.5") if victim_minor else Decimal("1")
    return rhu(Decimal(raw) * mult)


def recompute_tier(reg):
    offs = reg_offenses(reg["id"])
    total = sum(o["offense_points"] for o in offs)
    n = len(offs)
    prior = max(0, n - 1) * PRIOR_BONUS_PER
    score = total + prior
    if score >= T3_MIN:
        tier = "TIER_3"
    elif score >= T2_MIN:
        tier = "TIER_2"
    else:
        tier = "TIER_1"
    reg["tier_score"] = score
    reg["tier"] = tier
    reg["verification_interval_days"] = INTERVAL_BY_TIER[tier]


def compute_risk_open(reg):
    total = 0
    now = clock()
    for f in reg_open_flags(reg["id"]):
        days = (now - parse_iso(f["opened_date"])).days
        if days < 0:
            days = 0
        decay = Decimal(1) - DECAY_PER_DAY * days
        if decay < DECAY_FLOOR:
            decay = DECAY_FLOOR
        total += rhu(Decimal(f["base_points"]) * decay)
    return int(total)


def compute_adjudicated(reg):
    return int(sum(f["base_points"] for f in reg_flags(reg["id"])))


def compute_eligibility(reg, petition_type, adjudicated):
    tier = reg["tier"]
    min_years = MIN_YEARS[tier]
    initial = parse_iso(reg["initial_registration_date"])
    duration_met = clock() >= add_years(initial, min_years)
    open_count = len(reg_open_flags(reg["id"]))
    ever_critical = any(f["severity"] == "CRITICAL" for f in reg_flags(reg["id"]))
    clean = (open_count == 0) and (not ever_critical) and (adjudicated < ADJ_MAX)
    return (
        petition_type == "DEREGISTER"
        and tier != "TIER_3"
        and duration_met
        and clean
    )


# ---------------------------------------------------------------------------
# State transition helpers
# ---------------------------------------------------------------------------
def cascade_pending_petitions_denied(reg):
    for p in reg_petitions(reg["id"]):
        if p["decision"] == "PENDING":
            p["decision"] = "DENIED"
            p["decided_date"] = stamp_clock()
            touch(p)


def open_flag(reg, flag_type, note=None):
    severity, base_points = FLAG_META[flag_type]
    f = new_common()
    f.update(
        {
            "registrant_id": reg["id"],
            "flag_type": flag_type,
            "severity": severity,
            "base_points": base_points,
            "opened_date": stamp_clock(),
            "resolved_date": None,
            "status": "OPEN",
            "note": note,
        }
    )
    flags[f["id"]] = f

    if flag_type == "ABSCONDED":
        if reg["status"] in ("ACTIVE", "DELINQUENT"):
            reg["status"] = "ABSCONDER"
            for t in reg_travels(reg["id"]):
                if t["status"] in ("SUBMITTED", "APPROVED", "ACTIVE"):
                    t["status"] = "CANCELLED"
                    touch(t)
        reg["risk_score"] = compute_risk_open(reg)
    else:
        reg["risk_score"] = compute_risk_open(reg)
        if reg["status"] == "ACTIVE" and reg["risk_score"] >= DELINQUENT_THRESHOLD:
            reg["status"] = "DELINQUENT"
            cascade_pending_petitions_denied(reg)
    touch(reg)
    return f


# ---------------------------------------------------------------------------
# Routes: Jurisdiction / configuration
# ---------------------------------------------------------------------------
@app.route("/sorna/jurisdictions", methods=["POST"])
def create_jurisdiction():
    _, role = auth_ctx()
    require_role(role, {"RegistryAdmin"})
    body = get_body()
    name = req_str(body, "name")
    state_code = req_str(body, "state_code")
    grace = req_int(body, "verification_grace_days", required=False)
    if grace is None:
        grace = 3
    est = req_int(body, "est_households_per_notification", required=False)
    if est is None:
        est = 100
    status = req_str(body, "status", required=False)
    if status is None:
        status = "ACTIVE"
    check_enum(status, {"ACTIVE", "INACTIVE"}, "status")

    j = new_common()
    j.update(
        {
            "name": name,
            "state_code": state_code,
            "verification_grace_days": grace,
            "est_households_per_notification": est,
            "status": status,
        }
    )
    jurisdictions[j["id"]] = j
    return ok(ser_jurisdiction(j), "object", 201)


@app.route("/sorna/jurisdictions/<jid>", methods=["GET"])
def read_jurisdiction(jid):
    _, role = auth_ctx()
    require_role(role, {"RegistryAdmin", "RegistrationOfficer", "ComplianceReviewer"})
    j = get_jurisdiction(jid)
    return ok(ser_jurisdiction(j), "object", 200)


@app.route("/sorna/jurisdictions/<jid>/exclusion-zones", methods=["POST"])
def create_zone(jid):
    _, role = auth_ctx()
    require_role(role, {"RegistryAdmin"})
    j = get_jurisdiction(jid)
    body = get_body()
    name = req_str(body, "name")
    zone_type = req_str(body, "zone_type")
    check_enum(zone_type, {"SCHOOL", "PARK", "DAYCARE"}, "zone_type")
    center_x = req_int(body, "center_x")
    center_y = req_int(body, "center_y")
    radius = req_int(body, "radius_meters")
    buffer_m = req_int(body, "buffer_meters", required=False)
    if buffer_m is None:
        buffer_m = 100

    z = new_common()
    z.update(
        {
            "jurisdiction_id": j["id"],
            "name": name,
            "zone_type": zone_type,
            "center_x": center_x,
            "center_y": center_y,
            "radius_meters": radius,
            "buffer_meters": buffer_m,
            "status": "ACTIVE",
        }
    )
    exclusion_zones[z["id"]] = z
    return ok(ser_zone(z), "object", 201)


@app.route("/sorna/jurisdictions/<jid>/exclusion-zones", methods=["GET"])
def list_zones(jid):
    _, role = auth_ctx()
    require_role(role, {"RegistryAdmin", "RegistrationOfficer"})
    get_jurisdiction(jid)
    items = [z for z in exclusion_zones.values() if z["jurisdiction_id"] == jid]
    page, pag = paginate(items)
    return ok([ser_zone(z) for z in page], "array", 200, pag)


@app.route("/sorna/exclusion-zones/<zid>", methods=["GET"])
def read_zone(zid):
    _, role = auth_ctx()
    require_role(role, {"RegistryAdmin", "RegistrationOfficer"})
    z = get_zone(zid)
    return ok(ser_zone(z), "object", 200)


@app.route("/sorna/jurisdictions/<jid>/registrants", methods=["GET"])
def list_jurisdiction_registrants(jid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "ComplianceReviewer"})
    get_jurisdiction(jid)
    items = [r for r in registrants.values() if r["jurisdiction_id"] == jid]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    page, pag = paginate(items)
    return ok([ser_registrant(r) for r in page], "array", 200, pag)


@app.route("/sorna/jurisdictions/<jid>/inbound-travel-notices", methods=["GET"])
def list_inbound_travel(jid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "ComplianceReviewer"})
    get_jurisdiction(jid)
    items = [t for t in travel_notices.values() if t["destination_jurisdiction_id"] == jid]
    page, pag = paginate(items)
    return ok([ser_travel(t) for t in page], "array", 200, pag)


@app.route("/sorna/jurisdictions/<jid>/compliance-report", methods=["GET"])
def compliance_report(jid):
    _, role = auth_ctx()
    require_role(role, {"ComplianceReviewer", "RegistrationOfficer"})
    get_jurisdiction(jid)
    regs = [r for r in registrants.values() if r["jurisdiction_id"] == jid]
    report = {
        "total_registrants": len(regs),
        "active_count": sum(1 for r in regs if r["status"] == "ACTIVE"),
        "delinquent_count": sum(1 for r in regs if r["status"] == "DELINQUENT"),
        "absconder_count": sum(1 for r in regs if r["status"] == "ABSCONDER"),
        "deregistered_count": sum(1 for r in regs if r["status"] == "DEREGISTERED"),
    }
    return ok(report, "object", 200)


# ---------------------------------------------------------------------------
# Routes: Registrant lifecycle
# ---------------------------------------------------------------------------
@app.route("/sorna/registrants", methods=["POST"])
def create_registrant():
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    body = get_body()
    jurisdiction_id = req_str(body, "jurisdiction_id")
    full_name = req_str(body, "full_name")
    dob = req_str(body, "date_of_birth")
    get_jurisdiction(jurisdiction_id)

    r = new_common()
    r.update(
        {
            "jurisdiction_id": jurisdiction_id,
            "full_name": full_name,
            "date_of_birth": dob,
            "initial_registration_date": None,
            "tier": None,
            "tier_score": None,
            "verification_interval_days": None,
            "last_verified_date": None,
            "next_verification_due": None,
            "risk_score": None,
            "current_residence_address_id": None,
            "status": "PENDING",
        }
    )
    registrants[r["id"]] = r
    return ok(ser_registrant(r), "object", 201)


@app.route("/sorna/registrants/<rid>", methods=["GET"])
def read_registrant(rid):
    user_id, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "ComplianceReviewer", "Registrant"})
    registrant_scope_guard(role, user_id, rid)
    r = get_registrant(rid)
    return ok(ser_registrant(r), "object", 200)


@app.route("/sorna/registrants/<rid>/offenses", methods=["POST"])
def create_offense(rid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    r = get_registrant(rid)
    body = get_body()
    statute_code = req_str(body, "statute_code")
    offense_class = req_str(body, "offense_class")
    check_enum(offense_class, {"CLASS_A", "CLASS_B", "CLASS_C"}, "offense_class")
    is_aggravated = req_bool(body, "is_aggravated", False)
    victim_minor = req_bool(body, "victim_minor", False)
    conviction_date = req_str(body, "conviction_date")

    o = new_light()
    o.update(
        {
            "registrant_id": r["id"],
            "statute_code": statute_code,
            "offense_class": offense_class,
            "is_aggravated": is_aggravated,
            "victim_minor": victim_minor,
            "conviction_date": conviction_date,
            "offense_points": compute_offense_points(offense_class, is_aggravated, victim_minor),
        }
    )
    offenses[o["id"]] = o
    recompute_tier(r)
    touch(r)
    return ok(ser_offense(o), "object", 201)


@app.route("/sorna/registrants/<rid>/offenses", methods=["GET"])
def list_offenses(rid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    get_registrant(rid)
    page, pag = paginate(reg_offenses(rid))
    return ok([ser_offense(o) for o in page], "array", 200, pag)


@app.route("/sorna/registrants/<rid>/activate", methods=["POST"])
def activate_registrant(rid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    r = get_registrant(rid)
    if r["status"] != "PENDING":
        raise ApiError("ERR_REGISTRANT_NOT_PENDING", 409, "Registrant is not PENDING")
    if len(reg_offenses(rid)) == 0:
        raise ApiError("ERR_NO_OFFENSES", 409, "Registrant has no offenses")

    recompute_tier(r)
    initial = clock()
    r["initial_registration_date"] = iso_z(initial)
    r["last_verified_date"] = None
    r["next_verification_due"] = iso_z(initial + timedelta(days=r["verification_interval_days"]))
    r["risk_score"] = 0
    r["status"] = "ACTIVE"
    touch(r)
    return ok(ser_registrant(r), "object", 200)


@app.route("/sorna/registrants/<rid>/addresses", methods=["POST"])
def create_address(rid):
    user_id, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "Registrant"})
    registrant_scope_guard(role, user_id, rid)
    r = get_registrant(rid)
    body = get_body()

    address_type = req_str(body, "address_type")
    check_enum(address_type, {"RESIDENCE", "EMPLOYMENT", "SCHOOL", "TEMPORARY"}, "address_type")
    line1 = req_str(body, "line1")
    city = req_str(body, "city")
    state_code = req_str(body, "state_code")
    postal_code = req_str(body, "postal_code")
    grid_x = req_int(body, "grid_x")
    grid_y = req_int(body, "grid_y")
    expected_version = req_int(body, "expected_registrant_version")
    eff_from_raw = req_str(body, "effective_from", required=False)
    eff_to_raw = req_str(body, "effective_to", required=False)

    # Temporal (priority 6)
    if address_type == "TEMPORARY":
        if eff_to_raw is None:
            raise ApiError("ERR_MISSING_TRAVEL_RETURN", 422, "TEMPORARY address requires effective_to")
        if eff_from_raw is None:
            raise ApiError("ERR_VALIDATION", 422, "TEMPORARY address requires effective_from")
        eff_from = parse_dt_field(eff_from_raw, "effective_from")
        eff_to = parse_dt_field(eff_to_raw, "effective_to")
        if not (eff_to > eff_from):
            raise ApiError("ERR_INVALID_TRAVEL_DATES", 422, "effective_to must be after effective_from")
        eff_from_val = eff_from_raw
        eff_to_val = eff_to_raw
    else:
        if eff_from_raw is not None:
            parse_dt_field(eff_from_raw, "effective_from")
            eff_from_val = eff_from_raw
        else:
            eff_from_val = stamp_clock()
        eff_to_val = None

    # Safety (priority 7): RESIDENCE exclusion-zone screen
    if address_type == "RESIDENCE":
        for z in exclusion_zones.values():
            if z["jurisdiction_id"] != r["jurisdiction_id"] or z["status"] != "ACTIVE":
                continue
            dx = grid_x - z["center_x"]
            dy = grid_y - z["center_y"]
            thr = z["radius_meters"] + z["buffer_meters"]
            if dx * dx + dy * dy <= thr * thr:
                raise ApiError(
                    "ERR_EXCLUSION_ZONE_VIOLATION", 409, "Address falls within an active exclusion zone"
                )

    # Constraint (priority 8): TEMPORARY window overlap (closed, touching conflicts)
    if address_type == "TEMPORARY":
        new_from = parse_iso(eff_from_val)
        new_to = parse_iso(eff_to_val)
        for a in reg_addresses(rid):
            if a["address_type"] != "TEMPORARY":
                continue
            if a["effective_from"] is None or a["effective_to"] is None:
                continue
            ex_from = parse_iso(a["effective_from"])
            ex_to = parse_iso(a["effective_to"])
            if new_from <= ex_to and ex_from <= new_to:
                raise ApiError(
                    "ERR_ADDRESS_PERIOD_CONFLICT", 409, "TEMPORARY address window overlaps an existing window"
                )

    # OCC (priority 9)
    if expected_version != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_registrant_version does not match")

    a = new_common()
    a.update(
        {
            "registrant_id": r["id"],
            "address_type": address_type,
            "line1": line1,
            "city": city,
            "state_code": state_code,
            "postal_code": postal_code,
            "grid_x": grid_x,
            "grid_y": grid_y,
            "effective_from": eff_from_val,
            "effective_to": eff_to_val,
            "status": "VERIFIED",
        }
    )
    addresses[a["id"]] = a

    if address_type == "RESIDENCE":
        for other in reg_addresses(rid):
            if (
                other["id"] != a["id"]
                and other["address_type"] == "RESIDENCE"
                and other["status"] == "VERIFIED"
            ):
                other["status"] = "HISTORICAL"
                touch(other)
        r["current_residence_address_id"] = a["id"]
        # Only recording a RESIDENCE is "a genuine mutation of the registrant
        # record" per PRD 3.3 (repoints current_residence_address_id); other
        # address types do not increment the registrant version.
        touch(r)

    return ok(ser_address(a), "object", 201)


@app.route("/sorna/registrants/<rid>/addresses", methods=["GET"])
def list_addresses(rid):
    user_id, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "Registrant"})
    registrant_scope_guard(role, user_id, rid)
    get_registrant(rid)
    items = reg_addresses(rid)
    at = request.args.get("address_type")
    if at:
        items = [a for a in items if a["address_type"] == at]
    page, pag = paginate(items)
    return ok([ser_address(a) for a in page], "array", 200, pag)


# ---------------------------------------------------------------------------
# Routes: Verification
# ---------------------------------------------------------------------------
@app.route("/sorna/registrants/<rid>/verifications", methods=["POST"])
def create_verification(rid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    r = get_registrant(rid)
    body = get_body()
    verification_type = req_str(body, "verification_type")
    check_enum(verification_type, {"INITIAL", "PERIODIC", "ADDRESS_CHANGE"}, "verification_type")
    method = req_str(body, "method", required=False)
    if method is None:
        method = "IN_PERSON"
    check_enum(method, {"IN_PERSON", "MAIL"}, "method")
    officer_ref = req_str(body, "officer_ref")

    completed = stamp_clock()
    v = new_light()
    v.update(
        {
            "registrant_id": r["id"],
            "verification_type": verification_type,
            "method": method,
            "officer_ref": officer_ref,
            "completed_date": completed,
            "result": "VERIFIED",
        }
    )
    verifications[v["id"]] = v

    r["last_verified_date"] = completed
    if r["verification_interval_days"] is not None:
        r["next_verification_due"] = iso_z(
            parse_iso(completed) + timedelta(days=r["verification_interval_days"])
        )
    touch(r)
    return ok(ser_verification(v), "object", 201)


@app.route("/sorna/registrants/<rid>/verifications", methods=["GET"])
def list_verifications(rid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    get_registrant(rid)
    page, pag = paginate([v for v in verifications.values() if v["registrant_id"] == rid])
    return ok([ser_verification(v) for v in page], "array", 200, pag)


@app.route("/sorna/registrants/<rid>/verification-check", methods=["POST"])
def verification_check(rid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    r = get_registrant(rid)
    now = clock()

    # Overdue schedule check -> LATE_VERIFICATION flag
    if r["status"] in ("ACTIVE", "DELINQUENT") and r["next_verification_due"]:
        j = jurisdictions.get(r["jurisdiction_id"])
        grace = j["verification_grace_days"] if j else 0
        due = parse_iso(r["next_verification_due"])
        if now >= due + timedelta(days=grace):
            open_flag(r, "LATE_VERIFICATION")

    # Advance travel notices against their windows
    for t in reg_travels(rid):
        if t["status"] == "APPROVED":
            dep = parse_iso(t["departure_date"])
            if now >= dep:
                t["status"] = "ACTIVE"
                touch(t)
        if t["status"] == "ACTIVE" and t["travel_type"] == "TEMPORARY" and t["return_date"]:
            ret = parse_iso(t["return_date"])
            if now > ret + timedelta(days=TRAVEL_OVERDUE_GRACE_DAYS):
                t["status"] = "OVERDUE"
                touch(t)
                open_flag(r, "TRAVEL_VIOLATION")
            elif now >= ret:
                t["status"] = "COMPLETED"
                touch(t)

    return ok(ser_registrant(r), "object", 200)


# ---------------------------------------------------------------------------
# Routes: Compliance flags
# ---------------------------------------------------------------------------
@app.route("/sorna/registrants/<rid>/flags", methods=["POST"])
def create_flag(rid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    r = get_registrant(rid)
    body = get_body()
    flag_type = req_str(body, "flag_type")
    check_enum(flag_type, set(FLAG_META.keys()), "flag_type")
    note = req_str(body, "note", required=False)

    f = open_flag(r, flag_type, note)
    return ok(ser_flag(f), "object", 201)


@app.route("/sorna/registrants/<rid>/flags", methods=["GET"])
def list_flags(rid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "ComplianceReviewer"})
    get_registrant(rid)
    items = reg_flags(rid)
    status = request.args.get("status")
    if status:
        items = [f for f in items if f["status"] == status]
    page, pag = paginate(items)
    return ok([ser_flag(f) for f in page], "array", 200, pag)


@app.route("/sorna/compliance-flags/<fid>/resolve", methods=["POST"])
def resolve_flag(fid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    f = get_flag(fid)
    if f["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Flag is not OPEN")

    f["status"] = "RESOLVED"
    f["resolved_date"] = stamp_clock()
    touch(f)

    r = registrants.get(f["registrant_id"])
    if r is not None:
        r["risk_score"] = compute_risk_open(r)
        open_remaining = len(reg_open_flags(r["id"]))
        if r["status"] == "ABSCONDER":
            if f["flag_type"] == "ABSCONDED" and open_remaining == 0:
                r["status"] = "ACTIVE"
        elif r["status"] == "DELINQUENT":
            if open_remaining == 0 and r["risk_score"] < DELINQUENT_THRESHOLD:
                r["status"] = "ACTIVE"
        touch(r)
    return ok(ser_flag(f), "object", 200)


# ---------------------------------------------------------------------------
# Routes: Travel / inter-jurisdiction
# ---------------------------------------------------------------------------
@app.route("/sorna/registrants/<rid>/travel-notices", methods=["POST"])
def create_travel(rid):
    user_id, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "Registrant"})
    registrant_scope_guard(role, user_id, rid)
    r = get_registrant(rid)
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRANT_NOT_ACTIVE", 409, "Registrant is not ACTIVE")

    body = get_body()
    destination_id = req_str(body, "destination_jurisdiction_id")
    travel_type = req_str(body, "travel_type")
    check_enum(travel_type, {"TEMPORARY", "RELOCATION"}, "travel_type")
    departure_raw = req_str(body, "departure_date")
    return_raw = req_str(body, "return_date", required=False)

    # Referential (priority 5)
    get_jurisdiction(destination_id)

    # Temporal (priority 6)
    dep = parse_dt_field(departure_raw, "departure_date")
    if travel_type == "TEMPORARY":
        if return_raw is None:
            raise ApiError("ERR_MISSING_TRAVEL_RETURN", 422, "TEMPORARY travel requires return_date")
        ret = parse_dt_field(return_raw, "return_date")
        if not (ret > dep):
            raise ApiError("ERR_INVALID_TRAVEL_DATES", 422, "return_date must be after departure_date")
        if not (dep >= clock()):
            raise ApiError("ERR_INVALID_TRAVEL_DATES", 422, "departure_date must not be in the past")
        return_val = return_raw
    else:
        return_val = None
        ret = None

    # Constraint (priority 8): overlapping travel window (half-open)
    new_end = ret if ret is not None else datetime.max
    for t in reg_travels(rid):
        if t["status"] not in TRAVEL_NON_TERMINAL:
            continue
        t_dep = parse_iso(t["departure_date"])
        t_end = parse_iso(t["return_date"]) if t["return_date"] else datetime.max
        if dep < t_end and t_dep < new_end:
            raise ApiError("ERR_TRAVEL_WINDOW_CONFLICT", 409, "Travel window overlaps an existing notice")

    t = new_common()
    t.update(
        {
            "registrant_id": r["id"],
            "destination_jurisdiction_id": destination_id,
            "travel_type": travel_type,
            "departure_date": departure_raw,
            "return_date": return_val,
            "decision_note": None,
            "status": "SUBMITTED",
        }
    )
    travel_notices[t["id"]] = t
    return ok(ser_travel(t), "object", 201)


@app.route("/sorna/registrants/<rid>/travel-notices", methods=["GET"])
def list_travel(rid):
    user_id, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "Registrant"})
    registrant_scope_guard(role, user_id, rid)
    get_registrant(rid)
    items = reg_travels(rid)
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    page, pag = paginate(items)
    return ok([ser_travel(t) for t in page], "array", 200, pag)


@app.route("/sorna/travel-notices/<tid>/decision", methods=["POST"])
def decide_travel(tid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    t = get_travel(tid)
    if t["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Travel notice is not SUBMITTED")
    body = get_body()
    decision = req_str(body, "decision")
    check_enum(decision, {"APPROVE", "DENY"}, "decision")
    decision_note = req_str(body, "decision_note", required=False)
    if decision_note is not None:
        t["decision_note"] = decision_note

    if decision == "DENY":
        t["status"] = "DENIED"
        touch(t)
        return ok(ser_travel(t), "object", 200)

    # APPROVE
    r = registrants.get(t["registrant_id"])
    if r is None or r["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRANT_NOT_ACTIVE", 409, "Registrant is not ACTIVE")
    dest = get_jurisdiction(t["destination_jurisdiction_id"])
    if dest["status"] != "ACTIVE":
        raise ApiError("ERR_JURISDICTION_INACTIVE", 409, "Destination jurisdiction is INACTIVE")
    t["status"] = "APPROVED"
    touch(t)
    return ok(ser_travel(t), "object", 200)


@app.route("/sorna/travel-notices/<tid>/cancel", methods=["POST"])
def cancel_travel(tid):
    user_id, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "Registrant"})
    t = get_travel(tid)
    if role == "Registrant" and t["registrant_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Registrant may act only on its own record")
    if t["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Travel notice is not APPROVED or ACTIVE")
    t["status"] = "CANCELLED"
    touch(t)
    return ok(ser_travel(t), "object", 200)


# ---------------------------------------------------------------------------
# Routes: Community notification
# ---------------------------------------------------------------------------
@app.route("/sorna/registrants/<rid>/notifications", methods=["POST"])
def create_notification(rid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer"})
    r = get_registrant(rid)
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRANT_NOT_ACTIVE", 409, "Registrant is not ACTIVE")
    body = get_body()
    audience_scope = req_str(body, "audience_scope")
    check_enum(audience_scope, {"LAW_ENFORCEMENT", "SCHOOLS_ONLY", "PUBLIC"}, "audience_scope")

    tier = r["tier"]
    radius = NOTIF_RADIUS[tier]
    mult = NOTIF_MULT[tier]
    j = jurisdictions.get(r["jurisdiction_id"])
    estimated = (j["est_households_per_notification"] if j else 0) * mult

    actual = 0
    subj_addr = addresses.get(r["current_residence_address_id"]) if r["current_residence_address_id"] else None
    if subj_addr is not None:
        for a in addresses.values():
            if (
                a["status"] == "VERIFIED"
                and a["address_type"] == "RESIDENCE"
                and a["registrant_id"] != r["id"]
            ):
                dx = a["grid_x"] - subj_addr["grid_x"]
                dy = a["grid_y"] - subj_addr["grid_y"]
                if dx * dx + dy * dy <= radius * radius:
                    actual += 1

    n = new_light()
    n.update(
        {
            "registrant_id": r["id"],
            "audience_scope": audience_scope,
            "radius_meters": radius,
            "estimated_recipients": estimated,
            "actual_recipients": actual,
            "dispatched_date": stamp_clock(),
        }
    )
    notifications[n["id"]] = n
    return ok(ser_notification(n), "object", 201)


@app.route("/sorna/registrants/<rid>/notifications", methods=["GET"])
def list_notifications(rid):
    _, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "ComplianceReviewer"})
    get_registrant(rid)
    page, pag = paginate([n for n in notifications.values() if n["registrant_id"] == rid])
    return ok([ser_notification(n) for n in page], "array", 200, pag)


# ---------------------------------------------------------------------------
# Routes: Petitions
# ---------------------------------------------------------------------------
@app.route("/sorna/registrants/<rid>/petitions", methods=["POST"])
def create_petition(rid):
    user_id, role = auth_ctx()
    require_role(role, {"Registrant", "RegistrationOfficer"})
    registrant_scope_guard(role, user_id, rid)
    r = get_registrant(rid)
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRANT_NOT_ACTIVE", 409, "Registrant is not ACTIVE")
    body = get_body()
    petition_type = req_str(body, "petition_type")
    check_enum(petition_type, {"DEREGISTER", "TIER_REDUCTION"}, "petition_type")

    for p in reg_petitions(rid):
        if p["decision"] == "PENDING":
            raise ApiError("ERR_DUPLICATE_ACTIVE_PETITION", 409, "A PENDING petition already exists")

    adjudicated = compute_adjudicated(r)
    eligibility = compute_eligibility(r, petition_type, adjudicated)

    p = new_common()
    p.update(
        {
            "registrant_id": r["id"],
            "petition_type": petition_type,
            "filed_date": stamp_clock(),
            "adjudicated_risk_score": adjudicated,
            "eligibility_met": eligibility,
            "reviewer_ref": None,
            "decided_date": None,
            "decision": "PENDING",
        }
    )
    petitions[p["id"]] = p
    return ok(ser_petition(p), "object", 201)


@app.route("/sorna/registrants/<rid>/petitions", methods=["GET"])
def list_petitions(rid):
    user_id, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "ComplianceReviewer", "Registrant"})
    registrant_scope_guard(role, user_id, rid)
    get_registrant(rid)
    page, pag = paginate(reg_petitions(rid))
    return ok([ser_petition(p) for p in page], "array", 200, pag)


@app.route("/sorna/petitions/<pid>", methods=["GET"])
def read_petition(pid):
    user_id, role = auth_ctx()
    require_role(role, {"RegistrationOfficer", "ComplianceReviewer", "Registrant"})
    p = get_petition(pid)
    if role == "Registrant" and p["registrant_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Registrant may act only on its own record")
    return ok(ser_petition(p), "object", 200)


@app.route("/sorna/petitions/<pid>/decision", methods=["POST"])
def decide_petition(pid):
    _, role = auth_ctx()
    require_role(role, {"ComplianceReviewer"})
    p = get_petition(pid)
    if p["decision"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Petition is not PENDING")
    body = get_body()
    decision = req_str(body, "decision")
    check_enum(decision, {"GRANT", "DENY", "WITHDRAW"}, "decision")
    reviewer_ref = req_str(body, "reviewer_ref", required=False)
    if reviewer_ref is not None:
        p["reviewer_ref"] = reviewer_ref

    if decision == "WITHDRAW":
        p["decision"] = "WITHDRAWN"
        touch(p)
        return ok(ser_petition(p), "object", 200)

    if decision == "DENY":
        p["decision"] = "DENIED"
        p["decided_date"] = stamp_clock()
        touch(p)
        return ok(ser_petition(p), "object", 200)

    # GRANT
    r = registrants.get(p["registrant_id"])
    adjudicated = compute_adjudicated(r) if r else 0
    eligible = (
        r is not None
        and p["petition_type"] == "DEREGISTER"
        and r["status"] == "ACTIVE"
        and len(reg_open_flags(r["id"])) == 0
        and compute_eligibility(r, "DEREGISTER", adjudicated)
    )
    if not eligible:
        raise ApiError("ERR_PETITION_NOT_ELIGIBLE", 409, "Deregistration eligibility does not hold")

    p["decision"] = "GRANTED"
    p["decided_date"] = stamp_clock()
    touch(p)

    r["status"] = "DEREGISTERED"
    for a in reg_addresses(r["id"]):
        if a["status"] == "VERIFIED":
            a["status"] = "HISTORICAL"
            touch(a)
    r["current_residence_address_id"] = None
    touch(r)
    return ok(ser_petition(p), "object", 200)


# ---------------------------------------------------------------------------
# Routes: Test-driving clock
# ---------------------------------------------------------------------------
@app.route("/sorna/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth_ctx()
    require_role(role, {"RegistryAdmin"})
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    STATE["clock"] = parse_dt_field(to_iso, "to_iso8601")
    return ok({"current_utc": iso_z(STATE["clock"])}, "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
