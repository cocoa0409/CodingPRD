"""Volunteer Fire & EMS Department Management API (Python + Flask, in-memory)."""
import os
import math
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Chief", "Officer", "Member"}

ROLE_CLASSES = {"OFFICER", "PARAMEDIC", "EMT", "FIREFIGHTER", "PROBATIONARY"}
CERT_TYPES = {"FIREFIGHTER_1", "EMT_BASIC", "PARAMEDIC", "HAZMAT", "DRIVER_OPERATOR", "CPR"}
CATEGORIES = {"FIRE", "EMS", "HAZMAT", "DRIVER", "CPR"}
APPARATUS_TYPES = {"ENGINE", "LADDER", "AMBULANCE", "RESCUE", "TANKER"}
INCIDENT_TYPES = {"STRUCTURE_FIRE", "MVA", "EMS", "ALARM", "OTHER"}

CERT_VALIDITY_DAYS = 365
EXPIRING_WINDOW_DAYS = 30
CARRYOVER_CAP = 8
CERT_REQUIRED_HOURS = {
    "FIREFIGHTER_1": 24, "EMT_BASIC": 20, "PARAMEDIC": 40,
    "HAZMAT": 16, "DRIVER_OPERATOR": 12, "CPR": 4,
}

INCIDENT_TYPE_BASE = {"STRUCTURE_FIRE": 5, "MVA": 4, "EMS": 3, "ALARM": 2, "OTHER": 1}
ROLE_MULT = {"OFFICER": "1.5", "PARAMEDIC": "1.4", "EMT": "1.2", "FIREFIGHTER": "1.0", "PROBATIONARY": "0.5"}
SCENE_CAP = 6
SCENE_POINTS_PER_HOUR = 1
OFFICER_IC_BONUS = 2

DUTY_POINTS_PER_HOUR = "0.5"
DUTY_MIN_POINTS = 2

SILVER_MIN = 10
GOLD_MIN = 20
RATE_CENTS_PER_POINT = {"BRONZE": 0, "SILVER": 150, "GOLD": 250}

REST_BUFFER = timedelta(hours=8)
CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (fresh on every boot; nothing seeded)
# ---------------------------------------------------------------------------
members = {}
certifications = {}
training_records = {}
point_adjustments = {}
stations = {}
apparatus = {}
equipment = {}
maintenance_windows = {}
duty_shifts = {}
duty_assignments = {}
incidents = {}
turnouts = {}
campaigns = {}
donations = {}

_clock = CLOCK_DEFAULT
_seq = 0


def now_clock():
    return _clock


def next_seq():
    global _seq
    _seq += 1
    return _seq


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


NOT_FOUND = {
    "member": "ERR_MEMBER_NOT_FOUND",
    "certification": "ERR_CERTIFICATION_NOT_FOUND",
    "station": "ERR_STATION_NOT_FOUND",
    "apparatus": "ERR_APPARATUS_NOT_FOUND",
    "equipment": "ERR_EQUIPMENT_NOT_FOUND",
    "maintenance_window": "ERR_MAINTENANCE_WINDOW_NOT_FOUND",
    "duty_shift": "ERR_DUTY_SHIFT_NOT_FOUND",
    "duty_assignment": "ERR_DUTY_ASSIGNMENT_NOT_FOUND",
    "incident": "ERR_INCIDENT_NOT_FOUND",
    "turnout": "ERR_TURNOUT_NOT_FOUND",
    "campaign": "ERR_CAMPAIGN_NOT_FOUND",
    "donation": "ERR_DONATION_NOT_FOUND",
}


def bad(msg="Invalid request"):
    raise ApiError("ERR_VALIDATION", 400, msg)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    if not isinstance(value, str):
        bad("Invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        bad("Invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def response_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def rhu(dec):
    """Round half up to integer."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def make_meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": response_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {"meta": make_meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


def paginate(items, response_type="array"):
    limit, offset = read_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return ok(page, 200, "array", meta_extra)


def read_pagination():
    limit = 10
    offset = 0
    raw_l = request.args.get("limit")
    raw_o = request.args.get("offset")
    if raw_l is not None:
        try:
            limit = int(raw_l)
        except (TypeError, ValueError):
            limit = 10
    if raw_o is not None:
        try:
            offset = int(raw_o)
        except (TypeError, ValueError):
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return role, uid


def authorize(*allowed):
    role, uid = require_auth()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")
    return role, uid


def body_json():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        return {}
    return b


def require_field(body, name):
    if name not in body or body[name] is None:
        bad("Missing required field: %s" % name)
    return body[name]


def as_int(body, name, required=True, positive=False, non_negative=False):
    if name not in body or body[name] is None:
        if required:
            bad("Missing required field: %s" % name)
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field %s must be an integer" % name)
    if positive and v <= 0:
        bad("Field %s must be positive" % name)
    if non_negative and v < 0:
        bad("Field %s must be non-negative" % name)
    return v


def as_number(body, name, required=True, positive=False):
    if name not in body or body[name] is None:
        if required:
            bad("Missing required field: %s" % name)
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad("Field %s must be a number" % name)
    if positive and v <= 0:
        bad("Field %s must be positive" % name)
    return v


def as_enum(body, name, allowed, required=True):
    if name not in body or body[name] is None:
        if required:
            bad("Missing required field: %s" % name)
        return None
    v = body[name]
    if v not in allowed:
        bad("Field %s has invalid value" % name)
    return v


def as_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        bad("Field %s must be boolean" % name)
    return v


def as_str(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            bad("Missing required field: %s" % name)
        return None
    v = body[name]
    if not isinstance(v, str):
        bad("Field %s must be a string" % name)
    return v


def get_or_404(store, rid, kind):
    ent = store.get(rid)
    if ent is None:
        raise ApiError(NOT_FOUND[kind], 404, "%s not found" % kind)
    return ent


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def base_entity(versioned=True):
    clock = now_clock()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": clock,
        "_seq": next_seq(),
    }
    if versioned:
        ent["updated_at"] = clock
        ent["version"] = 1
    return ent


def touch(ent):
    ent["updated_at"] = now_clock()
    ent["version"] = ent.get("version", 1) + 1


def common_out(ent, versioned=True):
    out = {
        "id": ent["id"],
        "created_at": iso(ent["created_at"]),
    }
    if versioned:
        out["updated_at"] = iso(ent["updated_at"])
        out["version"] = ent["version"]
    return out


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


# ---------------------------------------------------------------------------
# Computations
# ---------------------------------------------------------------------------
def cert_completed_hours(cert):
    member_id = cert["member_id"]
    category = cert["category"]
    cycle_start = cert["cycle_start_at"]
    clock = now_clock()
    in_cycle = 0.0
    pre_cycle = 0.0
    pre_start = cycle_start - timedelta(days=90)
    for tr in training_records.values():
        if tr["member_id"] != member_id or tr["category"] != category:
            continue
        td = tr["training_date"]
        if cycle_start <= td <= clock:
            in_cycle += tr["hours"]
        elif pre_start <= td < cycle_start:
            pre_cycle += tr["hours"]
    strict = round(in_cycle, 1)
    carry = round(in_cycle + min(pre_cycle, CARRYOVER_CAP), 1)
    return strict, carry


def turnout_points_value(t):
    """Live points for a RELEASED turnout; 0 otherwise."""
    if t["status"] != "RELEASED":
        return 0
    inc = incidents.get(t["incident_id"])
    member = members.get(t["member_id"])
    if inc is None or member is None:
        return 0
    base = INCIDENT_TYPE_BASE[inc["incident_type"]]
    role_mult = ROLE_MULT[member["role_class"]]
    onscene = inc.get("onscene_at")
    cleared = inc.get("cleared_at")
    scene_component = 0
    if onscene is not None and cleared is not None:
        seconds = int((cleared - onscene).total_seconds())
        if seconds < 0:
            seconds = 0
        scene_hours = (seconds + 3599) // 3600
        scene_component = min(scene_hours, SCENE_CAP) * SCENE_POINTS_PER_HOUR
    officer_bonus = OFFICER_IC_BONUS if member["role_class"] == "OFFICER" else 0
    base_component = rhu(Decimal(base) * Decimal(role_mult))
    return base_component + scene_component + officer_bonus


def duty_points_value(shift):
    seconds = (shift["end_at"] - shift["start_at"]).total_seconds()
    shift_hours = Decimal(str(seconds / 3600.0))
    computed = rhu(shift_hours * Decimal(DUTY_POINTS_PER_HOUR))
    return max(computed, DUTY_MIN_POINTS)


def member_points(member_id, basis="FINAL"):
    pts = 0
    for t in turnouts.values():
        if t["member_id"] == member_id and t["status"] == "RELEASED":
            pts += turnout_points_value(t)
    for a in duty_assignments.values():
        if a["member_id"] != member_id:
            continue
        if a["status"] == "VERIFIED":
            shift = duty_shifts.get(a["duty_shift_id"])
            if shift is not None:
                pts += duty_points_value(shift)
        elif basis == "PROVISIONAL" and a["status"] in ("ASSIGNED", "CHECKED_IN"):
            shift = duty_shifts.get(a["duty_shift_id"])
            if shift is not None:
                pts += duty_points_value(shift)
    for adj in point_adjustments.values():
        if adj["member_id"] == member_id and not adj["reversed"]:
            pts += adj["points"]
    return pts


def points_tier(points):
    if points >= GOLD_MIN:
        return "GOLD"
    if points >= SILVER_MIN:
        return "SILVER"
    return "BRONZE"


def member_stipend(points, dues_balance):
    tier = points_tier(points)
    gross = points * RATE_CENTS_PER_POINT[tier]
    if tier == "GOLD":
        waiver = dues_balance
    elif tier == "SILVER":
        waiver = dues_balance // 2
    else:
        waiver = 0
    net = gross - (dues_balance - waiver)
    return max(0, net)


def training_hours_ytd(member_id):
    year = now_clock().year
    total = 0.0
    for tr in training_records.values():
        if tr["member_id"] == member_id and tr["training_date"].year == year:
            total += tr["hours"]
    return round(total, 1)


def member_required_lapsed(member_id):
    for c in certifications.values():
        if c["member_id"] == member_id and c["is_required"] and c["status"] in ("EXPIRED", "SUSPENDED", "REVOKED"):
            return True
    return False


def response_eligible(member):
    if member["membership_status"] != "ACTIVE":
        return False
    return not member_required_lapsed(member["id"])


def has_required_current(member_id):
    for c in certifications.values():
        if c["member_id"] == member_id and c["is_required"] and c["status"] == "CURRENT":
            return True
    return False


def apparatus_posture(apparatus_id):
    for w in maintenance_windows.values():
        if w["apparatus_id"] == apparatus_id and w["status"] == "IN_PROGRESS":
            return "OUT_OF_SERVICE"
    for e in equipment.values():
        if e["apparatus_id"] == apparatus_id and e["is_critical"] and e["status"] == "OUT_OF_SERVICE":
            return "OUT_OF_SERVICE"
    for e in equipment.values():
        if e["apparatus_id"] == apparatus_id and not e["is_critical"] and e["status"] == "OUT_OF_SERVICE":
            return "RESERVE"
    return "IN_SERVICE"


def shift_assigned_count(shift_id):
    n = 0
    for a in duty_assignments.values():
        if a["duty_shift_id"] == shift_id and a["status"] in ("ASSIGNED", "CHECKED_IN", "VERIFIED"):
            n += 1
    return n


def shift_staffing(shift):
    count = shift_assigned_count(shift["id"])
    if count == 0 or count < shift["min_crew"]:
        return "UNDERSTAFFED"
    if count >= shift["max_crew"]:
        return "FULL"
    return "STAFFED"


def campaign_raised(campaign_id):
    total = 0
    for d in donations.values():
        if d["campaign_id"] == campaign_id and d["status"] == "POSTED":
            total += d["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_member(m, basis="FINAL"):
    pts = member_points(m["id"], basis)
    out = common_out(m)
    out.update({
        "full_name": m["full_name"],
        "email": m["email"],
        "role_class": m["role_class"],
        "membership_status": m["membership_status"],
        "join_date": iso(m["join_date"]),
        "dues_balance_cents": m["dues_balance_cents"],
        "dues_paid_through": iso(m.get("dues_paid_through")),
        "response_eligible": response_eligible(m),
        "training_hours_ytd": training_hours_ytd(m["id"]),
        "points_ytd": pts,
        "stipend_cents": member_stipend(pts, m["dues_balance_cents"]),
        "points_tier": points_tier(pts),
    })
    return out


def ser_cert(c):
    strict, carry = cert_completed_hours(c)
    out = common_out(c)
    out.update({
        "member_id": c["member_id"],
        "cert_type": c["cert_type"],
        "is_required": c["is_required"],
        "category": c["category"],
        "status": c["status"],
        "cycle_start_at": iso(c["cycle_start_at"]),
        "issued_at": iso(c.get("issued_at")),
        "expires_at": iso(c.get("expires_at")),
        "completed_hours_strict": strict,
        "completed_hours_carryover": carry,
    })
    return out


def ser_training(t):
    out = common_out(t, versioned=False)
    out.update({
        "member_id": t["member_id"],
        "certification_id": t.get("certification_id"),
        "category": t["category"],
        "hours": t["hours"],
        "training_date": iso(t["training_date"]),
        "description": t.get("description"),
    })
    return out


def ser_adjustment(a):
    out = common_out(a, versioned=False)
    out.update({
        "member_id": a["member_id"],
        "points": a["points"],
        "reason": a["reason"],
        "reversed": a["reversed"],
    })
    return out


def ser_station(s):
    out = common_out(s)
    out.update({"name": s["name"], "address": s.get("address")})
    return out


def ser_apparatus(a):
    out = common_out(a)
    out.update({
        "station_id": a["station_id"],
        "unit_designation": a["unit_designation"],
        "apparatus_type": a["apparatus_type"],
        "min_crew": a["min_crew"],
        "posture": apparatus_posture(a["id"]),
    })
    return out


def ser_equipment(e):
    out = common_out(e)
    out.update({
        "apparatus_id": e["apparatus_id"],
        "name": e["name"],
        "is_critical": e["is_critical"],
        "status": e["status"],
    })
    return out


def ser_window(w):
    out = common_out(w)
    out.update({
        "apparatus_id": w["apparatus_id"],
        "start_at": iso(w["start_at"]),
        "end_at": iso(w["end_at"]),
        "reason": w.get("reason"),
        "status": w["status"],
    })
    return out


def ser_shift(s):
    out = common_out(s)
    out.update({
        "station_id": s["station_id"],
        "apparatus_id": s["apparatus_id"],
        "start_at": iso(s["start_at"]),
        "end_at": iso(s["end_at"]),
        "min_crew": s["min_crew"],
        "max_crew": s["max_crew"],
        "assigned_count": shift_assigned_count(s["id"]),
        "staffing_status": shift_staffing(s),
        "status": s["status"],
    })
    return out


def ser_assignment(a):
    dp = 0
    if a["status"] == "VERIFIED":
        shift = duty_shifts.get(a["duty_shift_id"])
        if shift is not None:
            dp = duty_points_value(shift)
    out = common_out(a)
    out.update({
        "duty_shift_id": a["duty_shift_id"],
        "member_id": a["member_id"],
        "status": a["status"],
        "checked_in_at": iso(a.get("checked_in_at")),
        "duty_points": dp,
    })
    return out


def ser_incident(i):
    out = common_out(i)
    out.update({
        "station_id": i["station_id"],
        "apparatus_id": i["apparatus_id"],
        "incident_type": i["incident_type"],
        "alarm_at": iso(i["alarm_at"]),
        "enroute_at": iso(i.get("enroute_at")),
        "onscene_at": iso(i.get("onscene_at")),
        "cleared_at": iso(i.get("cleared_at")),
        "response_status": i["response_status"],
        "report_status": i["report_status"],
        "nfirs_property_use": i.get("nfirs_property_use"),
        "nfirs_actions_taken": i.get("nfirs_actions_taken"),
        "report_revision": i["report_revision"],
    })
    return out


def ser_turnout(t):
    out = common_out(t)
    out.update({
        "incident_id": t["incident_id"],
        "member_id": t["member_id"],
        "responded_at": iso(t["responded_at"]),
        "status": t["status"],
        "turnout_points": turnout_points_value(t),
    })
    return out


def ser_campaign(c):
    out = common_out(c)
    out.update({
        "name": c["name"],
        "goal_cents": c["goal_cents"],
        "raised_cents": campaign_raised(c["id"]),
        "status": c["status"],
    })
    return out


def ser_donation(d):
    out = common_out(d)
    out.update({
        "campaign_id": d["campaign_id"],
        "donor_name": d["donor_name"],
        "amount_cents": d["amount_cents"],
        "status": d["status"],
    })
    return out


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def cancel_future_assignments(member_id):
    clock = now_clock()
    for a in duty_assignments.values():
        if a["member_id"] != member_id or a["status"] not in ("ASSIGNED", "CHECKED_IN"):
            continue
        shift = duty_shifts.get(a["duty_shift_id"])
        if shift is not None and shift["start_at"] > clock:
            a["status"] = "CANCELLED"
            touch(a)


def suspend_future_shifts(apparatus_id):
    clock = now_clock()
    for s in duty_shifts.values():
        if s["apparatus_id"] == apparatus_id and s["status"] == "PUBLISHED" and s["start_at"] > clock:
            s["status"] = "SUSPENDED"
            touch(s)


def restore_suspended_shifts(apparatus_id):
    for s in duty_shifts.values():
        if s["apparatus_id"] == apparatus_id and s["status"] == "SUSPENDED":
            s["status"] = "PUBLISHED"
            touch(s)


# ===========================================================================
# Routes: logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize("Chief", "Officer")
    body = body_json()
    val = require_field(body, "to_iso8601")
    global _clock
    _clock = parse_dt(val)
    return ok(None, 200, "object")


# ===========================================================================
# Routes: Members
# ===========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    authorize("Chief")
    body = body_json()
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    role_class = as_enum(body, "role_class", ROLE_CLASSES)
    join_date = parse_dt(require_field(body, "join_date"))
    dues = as_int(body, "dues_balance_cents", required=False, non_negative=True)
    if dues is None:
        dues = 0
    m = base_entity()
    m.update({
        "full_name": full_name,
        "email": email,
        "role_class": role_class,
        "membership_status": "PROBATIONARY",
        "join_date": join_date,
        "dues_balance_cents": dues,
        "dues_paid_through": None,
    })
    members[m["id"]] = m
    return ok(ser_member(m), 201)


@app.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    authorize("Chief", "Officer", "Member")
    m = get_or_404(members, member_id, "member")
    return ok(ser_member(m))


@app.route("/members", methods=["GET"])
def list_members():
    authorize("Chief", "Officer", "Member")
    items = list(members.values())
    status = request.args.get("membership_status")
    if status is not None:
        items = [m for m in items if m["membership_status"] == status]
    items = sort_created(items)
    return paginate([ser_member(m) for m in items])


@app.route("/members/<member_id>/summary", methods=["GET"])
def member_summary(member_id):
    authorize("Chief", "Officer", "Member")
    m = get_or_404(members, member_id, "member")
    basis = request.args.get("basis", "FINAL")
    if basis != "PROVISIONAL":
        basis = "FINAL"
    return ok(ser_member(m, basis))


def _member_transition(member_id, allowed_from, to, precheck=None, on_success=None):
    m = get_or_404(members, member_id, "member")
    if m["membership_status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409, "Member not in a valid state for this transition")
    if precheck:
        precheck(m)
    m["membership_status"] = to
    touch(m)
    if on_success:
        on_success(m)
    return ok(ser_member(m))


@app.route("/members/<member_id>/activate", methods=["POST"])
def activate_member(member_id):
    authorize("Chief")

    def precheck(m):
        if not has_required_current(m["id"]):
            raise ApiError("ERR_INVALID_STATE", 409, "No required certification in CURRENT status")

    return _member_transition(member_id, {"PROBATIONARY"}, "ACTIVE", precheck)


@app.route("/members/<member_id>/leave", methods=["POST"])
def leave_member(member_id):
    authorize("Chief")
    return _member_transition(member_id, {"ACTIVE"}, "LOA",
                              on_success=lambda m: cancel_future_assignments(m["id"]))


@app.route("/members/<member_id>/return", methods=["POST"])
def return_member(member_id):
    authorize("Chief")
    return _member_transition(member_id, {"LOA"}, "ACTIVE")


@app.route("/members/<member_id>/retire", methods=["POST"])
def retire_member(member_id):
    authorize("Chief")
    return _member_transition(member_id, {"ACTIVE", "LOA"}, "RETIRED",
                              on_success=lambda m: cancel_future_assignments(m["id"]))


@app.route("/members/<member_id>/expel", methods=["POST"])
def expel_member(member_id):
    authorize("Chief")
    return _member_transition(member_id, {"ACTIVE"}, "EXPELLED",
                              on_success=lambda m: cancel_future_assignments(m["id"]))


@app.route("/members/<member_id>/dues-payments", methods=["POST"])
def dues_payment(member_id):
    authorize("Chief", "Officer")
    body = body_json()
    amount = as_int(body, "amount_cents", positive=True)
    paid_through = body.get("paid_through")
    m = get_or_404(members, member_id, "member")
    m["dues_balance_cents"] = max(0, m["dues_balance_cents"] - amount)
    if paid_through is not None:
        m["dues_paid_through"] = parse_dt(paid_through)
    touch(m)
    return ok(ser_member(m))


# ===========================================================================
# Routes: Certifications
# ===========================================================================
@app.route("/members/<member_id>/certifications", methods=["POST"])
def create_cert(member_id):
    authorize("Chief", "Officer")
    body = body_json()
    cert_type = as_enum(body, "cert_type", CERT_TYPES)
    category = as_enum(body, "category", CATEGORIES)
    is_required = as_bool(body, "is_required", True)
    get_or_404(members, member_id, "member")
    c = base_entity()
    c.update({
        "member_id": member_id,
        "cert_type": cert_type,
        "category": category,
        "is_required": is_required,
        "status": "PENDING",
        "cycle_start_at": now_clock(),
        "issued_at": None,
        "expires_at": None,
    })
    certifications[c["id"]] = c
    return ok(ser_cert(c), 201)


@app.route("/certifications/<cert_id>", methods=["GET"])
def get_cert(cert_id):
    authorize("Chief", "Officer", "Member")
    c = get_or_404(certifications, cert_id, "certification")
    return ok(ser_cert(c))


@app.route("/certifications", methods=["GET"])
def list_certs():
    authorize("Chief", "Officer", "Member")
    items = list(certifications.values())
    mid = request.args.get("member_id")
    status = request.args.get("status")
    if mid is not None:
        items = [c for c in items if c["member_id"] == mid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_created(items)
    return paginate([ser_cert(c) for c in items])


@app.route("/certifications/<cert_id>/issue", methods=["POST"])
def issue_cert(cert_id):
    authorize("Officer")
    c = get_or_404(certifications, cert_id, "certification")
    if c["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Certification not PENDING")
    strict, _ = cert_completed_hours(c)
    if strict < CERT_REQUIRED_HOURS[c["cert_type"]]:
        raise ApiError("ERR_INSUFFICIENT_TRAINING_HOURS", 422, "Insufficient training hours")
    clock = now_clock()
    c["issued_at"] = clock
    c["expires_at"] = clock + timedelta(days=CERT_VALIDITY_DAYS)
    c["status"] = "CURRENT"
    touch(c)
    return ok(ser_cert(c))


@app.route("/certifications/<cert_id>/renew", methods=["POST"])
def renew_cert(cert_id):
    authorize("Officer")
    c = get_or_404(certifications, cert_id, "certification")
    if c["status"] not in ("EXPIRED", "EXPIRING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Certification not renewable")
    _, carry = cert_completed_hours(c)
    if carry < CERT_REQUIRED_HOURS[c["cert_type"]]:
        raise ApiError("ERR_INSUFFICIENT_TRAINING_HOURS", 422, "Insufficient training hours")
    clock = now_clock()
    c["cycle_start_at"] = clock
    c["issued_at"] = clock
    c["expires_at"] = clock + timedelta(days=CERT_VALIDITY_DAYS)
    c["status"] = "CURRENT"
    touch(c)
    return ok(ser_cert(c))


@app.route("/certifications/<cert_id>/suspend", methods=["POST"])
def suspend_cert(cert_id):
    authorize("Officer")
    c = get_or_404(certifications, cert_id, "certification")
    if c["status"] not in ("CURRENT", "EXPIRING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Certification not suspendable")
    c["status"] = "SUSPENDED"
    touch(c)
    return ok(ser_cert(c))


@app.route("/certifications/<cert_id>/reinstate", methods=["POST"])
def reinstate_cert(cert_id):
    authorize("Officer")
    c = get_or_404(certifications, cert_id, "certification")
    if c["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Certification not SUSPENDED")
    if c.get("expires_at") is None or now_clock() >= c["expires_at"]:
        raise ApiError("ERR_INVALID_STATE", 409, "Certification already past expiry")
    c["status"] = "CURRENT"
    touch(c)
    return ok(ser_cert(c))


@app.route("/certifications/<cert_id>/revoke", methods=["POST"])
def revoke_cert(cert_id):
    authorize("Chief")
    c = get_or_404(certifications, cert_id, "certification")
    if c["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Certification not SUSPENDED")
    c["status"] = "REVOKED"
    touch(c)
    return ok(ser_cert(c))


@app.route("/certifications/sweep", methods=["POST"])
def sweep_certs():
    authorize("Chief", "Officer")
    clock = now_clock()
    transitioned = []
    for c in list(certifications.values()):
        exp = c.get("expires_at")
        if exp is None:
            continue
        changed = False
        if c["status"] == "CURRENT":
            if clock >= exp:
                c["status"] = "EXPIRED"
                changed = True
            elif clock >= exp - timedelta(days=EXPIRING_WINDOW_DAYS):
                c["status"] = "EXPIRING"
                changed = True
        elif c["status"] == "EXPIRING":
            if clock >= exp:
                c["status"] = "EXPIRED"
                changed = True
        if changed:
            touch(c)
            if c["status"] == "EXPIRED" and c["is_required"]:
                cancel_future_assignments(c["member_id"])
            transitioned.append(c)
    transitioned = sort_created(transitioned)
    return ok([ser_cert(c) for c in transitioned], 200, "array")


# ===========================================================================
# Routes: TrainingRecord
# ===========================================================================
@app.route("/members/<member_id>/training-records", methods=["POST"])
def create_training(member_id):
    authorize("Chief", "Officer")
    body = body_json()
    category = as_enum(body, "category", CATEGORIES)
    hours = as_number(body, "hours", positive=True)
    training_date = parse_dt(require_field(body, "training_date"))
    description = as_str(body, "description", required=False)
    cert_id = body.get("certification_id")
    get_or_404(members, member_id, "member")
    if cert_id is not None:
        get_or_404(certifications, cert_id, "certification")
    t = base_entity(versioned=False)
    t.update({
        "member_id": member_id,
        "certification_id": cert_id,
        "category": category,
        "hours": hours,
        "training_date": training_date,
        "description": description,
    })
    training_records[t["id"]] = t
    return ok(ser_training(t), 201)


@app.route("/training-records/<record_id>", methods=["GET"])
def get_training(record_id):
    authorize("Chief", "Officer", "Member")
    t = training_records.get(record_id)
    if t is None:
        raise ApiError("ERR_VALIDATION", 404, "Training record not found")
    return ok(ser_training(t))


@app.route("/training-records", methods=["GET"])
def list_training():
    authorize("Chief", "Officer", "Member")
    items = list(training_records.values())
    mid = request.args.get("member_id")
    cid = request.args.get("certification_id")
    if mid is not None:
        items = [t for t in items if t["member_id"] == mid]
    if cid is not None:
        items = [t for t in items if t.get("certification_id") == cid]
    items = sort_created(items)
    return paginate([ser_training(t) for t in items])


# ===========================================================================
# Routes: PointAdjustment
# ===========================================================================
@app.route("/members/<member_id>/point-adjustments", methods=["POST"])
def create_adjustment(member_id):
    authorize("Officer")
    body = body_json()
    points = as_int(body, "points")
    reason = as_str(body, "reason")
    get_or_404(members, member_id, "member")
    a = base_entity(versioned=False)
    a.update({
        "member_id": member_id,
        "points": points,
        "reason": reason,
        "reversed": False,
    })
    point_adjustments[a["id"]] = a
    return ok(ser_adjustment(a), 201)


@app.route("/point-adjustments/<adjustment_id>", methods=["GET"])
def get_adjustment(adjustment_id):
    authorize("Chief", "Officer", "Member")
    a = point_adjustments.get(adjustment_id)
    if a is None:
        raise ApiError("ERR_VALIDATION", 404, "Point adjustment not found")
    return ok(ser_adjustment(a))


@app.route("/point-adjustments", methods=["GET"])
def list_adjustments():
    authorize("Chief", "Officer", "Member")
    items = list(point_adjustments.values())
    mid = request.args.get("member_id")
    if mid is not None:
        items = [a for a in items if a["member_id"] == mid]
    items = sort_created(items)
    return paginate([ser_adjustment(a) for a in items])


# ===========================================================================
# Routes: Stations / Apparatus / Equipment
# ===========================================================================
@app.route("/stations", methods=["POST"])
def create_station():
    authorize("Chief")
    body = body_json()
    name = as_str(body, "name")
    address = as_str(body, "address", required=False)
    s = base_entity()
    s.update({"name": name, "address": address})
    stations[s["id"]] = s
    return ok(ser_station(s), 201)


@app.route("/stations/<station_id>", methods=["GET"])
def get_station(station_id):
    authorize("Chief", "Officer", "Member")
    s = get_or_404(stations, station_id, "station")
    return ok(ser_station(s))


@app.route("/stations/<station_id>/apparatus", methods=["POST"])
def create_apparatus(station_id):
    authorize("Chief")
    body = body_json()
    unit = as_str(body, "unit_designation")
    atype = as_enum(body, "apparatus_type", APPARATUS_TYPES)
    min_crew = as_int(body, "min_crew", positive=True)
    get_or_404(stations, station_id, "station")
    a = base_entity()
    a.update({
        "station_id": station_id,
        "unit_designation": unit,
        "apparatus_type": atype,
        "min_crew": min_crew,
    })
    apparatus[a["id"]] = a
    return ok(ser_apparatus(a), 201)


@app.route("/apparatus/<apparatus_id>", methods=["GET"])
def get_apparatus(apparatus_id):
    authorize("Chief", "Officer", "Member")
    a = get_or_404(apparatus, apparatus_id, "apparatus")
    return ok(ser_apparatus(a))


@app.route("/apparatus", methods=["GET"])
def list_apparatus():
    authorize("Chief", "Officer", "Member")
    items = list(apparatus.values())
    sid = request.args.get("station_id")
    if sid is not None:
        items = [a for a in items if a["station_id"] == sid]
    items = sort_created(items)
    return paginate([ser_apparatus(a) for a in items])


@app.route("/apparatus/<apparatus_id>/equipment", methods=["POST"])
def create_equipment(apparatus_id):
    authorize("Chief")
    body = body_json()
    name = as_str(body, "name")
    is_critical = as_bool(body, "is_critical", False)
    get_or_404(apparatus, apparatus_id, "apparatus")
    e = base_entity()
    e.update({
        "apparatus_id": apparatus_id,
        "name": name,
        "is_critical": is_critical,
        "status": "OPERATIONAL",
    })
    equipment[e["id"]] = e
    return ok(ser_equipment(e), 201)


@app.route("/equipment/<equipment_id>", methods=["GET"])
def get_equipment(equipment_id):
    authorize("Chief", "Officer", "Member")
    e = get_or_404(equipment, equipment_id, "equipment")
    return ok(ser_equipment(e))


@app.route("/equipment", methods=["GET"])
def list_equipment():
    authorize("Chief", "Officer", "Member")
    items = list(equipment.values())
    aid = request.args.get("apparatus_id")
    if aid is not None:
        items = [e for e in items if e["apparatus_id"] == aid]
    items = sort_created(items)
    return paginate([ser_equipment(e) for e in items])


@app.route("/equipment/<equipment_id>/out-of-service", methods=["POST"])
def equipment_oos(equipment_id):
    authorize("Chief")
    e = get_or_404(equipment, equipment_id, "equipment")
    if e["status"] != "OPERATIONAL":
        raise ApiError("ERR_INVALID_STATE", 409, "Equipment not OPERATIONAL")
    e["status"] = "OUT_OF_SERVICE"
    touch(e)
    if apparatus_posture(e["apparatus_id"]) == "OUT_OF_SERVICE":
        suspend_future_shifts(e["apparatus_id"])
    return ok(ser_equipment(e))


@app.route("/equipment/<equipment_id>/return-to-service", methods=["POST"])
def equipment_rts(equipment_id):
    authorize("Chief")
    e = get_or_404(equipment, equipment_id, "equipment")
    if e["status"] != "OUT_OF_SERVICE":
        raise ApiError("ERR_INVALID_STATE", 409, "Equipment not OUT_OF_SERVICE")
    e["status"] = "OPERATIONAL"
    touch(e)
    if apparatus_posture(e["apparatus_id"]) != "OUT_OF_SERVICE":
        restore_suspended_shifts(e["apparatus_id"])
    return ok(ser_equipment(e))


# ===========================================================================
# Routes: MaintenanceWindow
# ===========================================================================
@app.route("/apparatus/<apparatus_id>/maintenance-windows", methods=["POST"])
def create_window(apparatus_id):
    authorize("Chief")
    body = body_json()
    start_at = parse_dt(require_field(body, "start_at"))
    end_at = parse_dt(require_field(body, "end_at"))
    if end_at <= start_at:
        bad("end_at must be after start_at")
    reason = as_str(body, "reason", required=False)
    get_or_404(apparatus, apparatus_id, "apparatus")
    # overlap check (half-open; adjacency allowed)
    for w in maintenance_windows.values():
        if w["apparatus_id"] == apparatus_id and w["status"] in ("SCHEDULED", "IN_PROGRESS"):
            if max(start_at, w["start_at"]) < min(end_at, w["end_at"]):
                raise ApiError("ERR_MAINTENANCE_OVERLAP", 409, "Overlapping maintenance window")
    w = base_entity()
    w.update({
        "apparatus_id": apparatus_id,
        "start_at": start_at,
        "end_at": end_at,
        "reason": reason,
        "status": "SCHEDULED",
    })
    maintenance_windows[w["id"]] = w
    return ok(ser_window(w), 201)


@app.route("/maintenance-windows/<window_id>", methods=["GET"])
def get_window(window_id):
    authorize("Chief", "Officer", "Member")
    w = get_or_404(maintenance_windows, window_id, "maintenance_window")
    return ok(ser_window(w))


@app.route("/maintenance-windows", methods=["GET"])
def list_windows():
    authorize("Chief", "Officer", "Member")
    items = list(maintenance_windows.values())
    aid = request.args.get("apparatus_id")
    status = request.args.get("status")
    if aid is not None:
        items = [w for w in items if w["apparatus_id"] == aid]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = sort_created(items)
    return paginate([ser_window(w) for w in items])


@app.route("/maintenance-windows/<window_id>/start", methods=["POST"])
def start_window(window_id):
    authorize("Chief")
    w = get_or_404(maintenance_windows, window_id, "maintenance_window")
    if w["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Window not SCHEDULED")
    w["status"] = "IN_PROGRESS"
    touch(w)
    # posture becomes OUT_OF_SERVICE -> suspend future published shifts
    suspend_future_shifts(w["apparatus_id"])
    return ok(ser_window(w))


@app.route("/maintenance-windows/<window_id>/complete", methods=["POST"])
def complete_window(window_id):
    authorize("Chief")
    w = get_or_404(maintenance_windows, window_id, "maintenance_window")
    if w["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Window not IN_PROGRESS")
    w["status"] = "COMPLETED"
    touch(w)
    if apparatus_posture(w["apparatus_id"]) != "OUT_OF_SERVICE":
        restore_suspended_shifts(w["apparatus_id"])
    return ok(ser_window(w))


@app.route("/maintenance-windows/<window_id>/cancel", methods=["POST"])
def cancel_window(window_id):
    authorize("Chief")
    w = get_or_404(maintenance_windows, window_id, "maintenance_window")
    if w["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Window not SCHEDULED")
    w["status"] = "CANCELLED"
    touch(w)
    return ok(ser_window(w))


# ===========================================================================
# Routes: DutyShift
# ===========================================================================
@app.route("/duty-shifts", methods=["POST"])
def create_shift():
    authorize("Officer")
    body = body_json()
    station_id = as_str(body, "station_id")
    apparatus_id = as_str(body, "apparatus_id")
    start_at = parse_dt(require_field(body, "start_at"))
    end_at = parse_dt(require_field(body, "end_at"))
    if end_at <= start_at:
        bad("end_at must be after start_at")
    max_crew = as_int(body, "max_crew", positive=True)
    min_crew = as_int(body, "min_crew", required=False, positive=True)
    # existence left-to-right
    st = get_or_404(stations, station_id, "station")
    ap = get_or_404(apparatus, apparatus_id, "apparatus")
    if ap["station_id"] != station_id:
        raise ApiError("ERR_APPARATUS_NOT_AT_STATION", 409, "Apparatus not at station")
    if min_crew is None:
        min_crew = ap["min_crew"]
    if max_crew < min_crew:
        bad("max_crew must be >= min_crew")
    s = base_entity()
    s.update({
        "station_id": station_id,
        "apparatus_id": apparatus_id,
        "start_at": start_at,
        "end_at": end_at,
        "min_crew": min_crew,
        "max_crew": max_crew,
        "status": "DRAFT",
    })
    duty_shifts[s["id"]] = s
    return ok(ser_shift(s), 201)


@app.route("/duty-shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    authorize("Chief", "Officer", "Member")
    s = get_or_404(duty_shifts, shift_id, "duty_shift")
    return ok(ser_shift(s))


@app.route("/duty-shifts", methods=["GET"])
def list_shifts():
    authorize("Chief", "Officer", "Member")
    items = list(duty_shifts.values())
    sid = request.args.get("station_id")
    aid = request.args.get("apparatus_id")
    status = request.args.get("status")
    if sid is not None:
        items = [s for s in items if s["station_id"] == sid]
    if aid is not None:
        items = [s for s in items if s["apparatus_id"] == aid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_created(items)
    return paginate([ser_shift(s) for s in items])


@app.route("/duty-shifts/<shift_id>/publish", methods=["POST"])
def publish_shift(shift_id):
    authorize("Officer")
    s = get_or_404(duty_shifts, shift_id, "duty_shift")
    if s["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Shift not DRAFT")
    if apparatus_posture(s["apparatus_id"]) == "OUT_OF_SERVICE":
        raise ApiError("ERR_APPARATUS_OUT_OF_SERVICE", 409, "Apparatus out of service")
    s["status"] = "PUBLISHED"
    touch(s)
    return ok(ser_shift(s))


@app.route("/duty-shifts/<shift_id>/cancel", methods=["POST"])
def cancel_shift(shift_id):
    authorize("Officer")
    s = get_or_404(duty_shifts, shift_id, "duty_shift")
    if s["status"] not in ("DRAFT", "PUBLISHED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Shift not cancellable")
    prev = s["status"]
    s["status"] = "CANCELLED"
    touch(s)
    if prev in ("PUBLISHED", "SUSPENDED"):
        for a in duty_assignments.values():
            if a["duty_shift_id"] == shift_id and a["status"] in ("ASSIGNED", "CHECKED_IN"):
                a["status"] = "CANCELLED"
                touch(a)
    return ok(ser_shift(s))


@app.route("/duty-shifts/sweep", methods=["POST"])
def sweep_shifts():
    authorize("Chief", "Officer")
    clock = now_clock()
    transitioned = []
    # PUBLISHED -> IN_PROGRESS (start has arrived; if end has also passed the
    # completion loop below settles it in the same sweep so the lifecycle is
    # advanced against the clock even when the sweep is first run after end_at)
    for s in list(duty_shifts.values()):
        if s["status"] == "PUBLISHED" and s["start_at"] <= clock:
            s["status"] = "IN_PROGRESS"
            touch(s)
            transitioned.append(s)
    # IN_PROGRESS -> COMPLETED
    for s in list(duty_shifts.values()):
        if s["status"] == "IN_PROGRESS" and clock >= s["end_at"]:
            s["status"] = "COMPLETED"
            touch(s)
            for a in duty_assignments.values():
                if a["duty_shift_id"] != s["id"]:
                    continue
                if a["status"] == "CHECKED_IN":
                    a["status"] = "VERIFIED"
                    touch(a)
                elif a["status"] == "ASSIGNED":
                    a["status"] = "NO_SHOW"
                    touch(a)
            if s not in transitioned:
                transitioned.append(s)
    transitioned = sort_created(transitioned)
    return ok([ser_shift(s) for s in transitioned], 200, "array")


# ===========================================================================
# Routes: DutyAssignment
# ===========================================================================
@app.route("/duty-shifts/<shift_id>/assignments", methods=["POST"])
def create_assignment(shift_id):
    authorize("Officer")
    body = body_json()
    # field validity (band 3)
    member_id = as_str(body, "member_id")
    expected_version = as_int(body, "expected_duty_shift_version")
    # existence (band 4): path shift then body member
    s = get_or_404(duty_shifts, shift_id, "duty_shift")
    m = get_or_404(members, member_id, "member")
    # state (band 5)
    if s["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Shift does not accept assignments")
    # response-eligibility (band 6)
    if not response_eligible(m):
        raise ApiError("ERR_MEMBER_NOT_RESPONSE_ELIGIBLE", 409, "Member not response eligible")
    # temporal rest-buffer (band 8)
    s1, e1 = s["start_at"], s["end_at"]
    for a in duty_assignments.values():
        if a["member_id"] != member_id or a["status"] not in ("ASSIGNED", "CHECKED_IN"):
            continue
        other = duty_shifts.get(a["duty_shift_id"])
        if other is None:
            continue
        s2, e2 = other["start_at"], other["end_at"]
        if not (e1 + REST_BUFFER <= s2 or e2 + REST_BUFFER <= s1):
            raise ApiError("ERR_SHIFT_OVERLAP", 409, "Rest-buffer conflict")
    # capacity (band 9)
    if shift_assigned_count(shift_id) >= s["max_crew"]:
        raise ApiError("ERR_SHIFT_FULL", 409, "Shift is full")
    # fiscal (band 10)
    if m["dues_balance_cents"] > 0:
        raise ApiError("ERR_DUES_OVERDUE", 402, "Member owes back dues")
    # OCC (band 11)
    if expected_version != s["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale shift version")
    a = base_entity()
    a.update({
        "duty_shift_id": shift_id,
        "member_id": member_id,
        "status": "ASSIGNED",
        "checked_in_at": None,
    })
    duty_assignments[a["id"]] = a
    touch(s)  # assignment create increments DutyShift.version by 1
    return ok(ser_assignment(a), 201)


@app.route("/duty-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    authorize("Chief", "Officer", "Member")
    a = get_or_404(duty_assignments, assignment_id, "duty_assignment")
    return ok(ser_assignment(a))


@app.route("/duty-assignments", methods=["GET"])
def list_assignments():
    authorize("Chief", "Officer", "Member")
    items = list(duty_assignments.values())
    sid = request.args.get("duty_shift_id")
    mid = request.args.get("member_id")
    status = request.args.get("status")
    if sid is not None:
        items = [a for a in items if a["duty_shift_id"] == sid]
    if mid is not None:
        items = [a for a in items if a["member_id"] == mid]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_created(items)
    return paginate([ser_assignment(a) for a in items])


@app.route("/duty-assignments/<assignment_id>/check-in", methods=["POST"])
def checkin_assignment(assignment_id):
    role, uid = authorize("Member", "Officer")
    a = get_or_404(duty_assignments, assignment_id, "duty_assignment")
    if role == "Member" and uid != a["member_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your assignment")
    if a["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment not ASSIGNED")
    shift = duty_shifts.get(a["duty_shift_id"])
    if shift is None or shift["status"] not in ("PUBLISHED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", 409, "Shift not open for check-in")
    a["status"] = "CHECKED_IN"
    a["checked_in_at"] = now_clock()
    touch(a)
    return ok(ser_assignment(a))


@app.route("/duty-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    authorize("Officer")
    a = get_or_404(duty_assignments, assignment_id, "duty_assignment")
    if a["status"] not in ("ASSIGNED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment not cancellable")
    a["status"] = "CANCELLED"
    touch(a)
    return ok(ser_assignment(a))


# ===========================================================================
# Routes: Incident + NFIRS
# ===========================================================================
@app.route("/incidents", methods=["POST"])
def create_incident():
    authorize("Officer")
    body = body_json()
    station_id = as_str(body, "station_id")
    apparatus_id = as_str(body, "apparatus_id")
    incident_type = as_enum(body, "incident_type", INCIDENT_TYPES)
    alarm_at = parse_dt(require_field(body, "alarm_at"))
    get_or_404(stations, station_id, "station")
    ap = get_or_404(apparatus, apparatus_id, "apparatus")
    if ap["station_id"] != station_id:
        raise ApiError("ERR_APPARATUS_NOT_AT_STATION", 409, "Apparatus not at station")
    i = base_entity()
    i.update({
        "station_id": station_id,
        "apparatus_id": apparatus_id,
        "incident_type": incident_type,
        "alarm_at": alarm_at,
        "enroute_at": None,
        "onscene_at": None,
        "cleared_at": None,
        "response_status": "DISPATCHED",
        "report_status": "NONE",
        "nfirs_property_use": None,
        "nfirs_actions_taken": None,
        "report_revision": 0,
    })
    incidents[i["id"]] = i
    return ok(ser_incident(i), 201)


@app.route("/incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    authorize("Chief", "Officer", "Member")
    i = get_or_404(incidents, incident_id, "incident")
    return ok(ser_incident(i))


@app.route("/incidents", methods=["GET"])
def list_incidents():
    authorize("Chief", "Officer", "Member")
    items = list(incidents.values())
    sid = request.args.get("station_id")
    aid = request.args.get("apparatus_id")
    if sid is not None:
        items = [i for i in items if i["station_id"] == sid]
    if aid is not None:
        items = [i for i in items if i["apparatus_id"] == aid]
    items = sort_created(items)
    return paginate([ser_incident(i) for i in items])


@app.route("/incidents/<incident_id>/enroute", methods=["POST"])
def incident_enroute(incident_id):
    authorize("Officer")
    i = get_or_404(incidents, incident_id, "incident")
    if i["response_status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Incident not DISPATCHED")
    i["response_status"] = "ENROUTE"
    i["enroute_at"] = now_clock()
    touch(i)
    return ok(ser_incident(i))


@app.route("/incidents/<incident_id>/arrive", methods=["POST"])
def incident_arrive(incident_id):
    authorize("Officer")
    i = get_or_404(incidents, incident_id, "incident")
    if i["response_status"] != "ENROUTE":
        raise ApiError("ERR_INVALID_STATE", 409, "Incident not ENROUTE")
    i["response_status"] = "ONSCENE"
    i["onscene_at"] = now_clock()
    touch(i)
    return ok(ser_incident(i))


@app.route("/incidents/<incident_id>/clear", methods=["POST"])
def incident_clear(incident_id):
    authorize("Officer")
    i = get_or_404(incidents, incident_id, "incident")
    if i["response_status"] != "ONSCENE":
        raise ApiError("ERR_INVALID_STATE", 409, "Incident not ONSCENE")
    i["response_status"] = "CLEARED"
    i["cleared_at"] = now_clock()
    touch(i)
    # release turnouts
    for t in turnouts.values():
        if t["incident_id"] == incident_id and t["status"] == "RESPONDED":
            t["status"] = "RELEASED"
            touch(t)
    return ok(ser_incident(i))


@app.route("/incidents/<incident_id>/report", methods=["POST"])
def incident_report(incident_id):
    authorize("Officer")
    body = body_json()
    i = get_or_404(incidents, incident_id, "incident")
    if i["report_status"] != "NONE":
        raise ApiError("ERR_INVALID_STATE", 409, "Report already started")
    if i["response_status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE", 409, "Incident not cleared")
    pu = as_str(body, "nfirs_property_use", required=False)
    at = as_str(body, "nfirs_actions_taken", required=False)
    if pu is not None:
        i["nfirs_property_use"] = pu
    if at is not None:
        i["nfirs_actions_taken"] = at
    i["report_status"] = "DRAFT"
    touch(i)
    return ok(ser_incident(i))


@app.route("/incidents/<incident_id>/report/lock", methods=["POST"])
def incident_report_lock(incident_id):
    authorize("Officer")
    i = get_or_404(incidents, incident_id, "incident")
    if i["report_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Report not DRAFT")
    if not i.get("nfirs_property_use") or not i.get("nfirs_actions_taken"):
        raise ApiError("ERR_NFIRS_INCOMPLETE", 422, "NFIRS fields incomplete")
    i["report_status"] = "LOCKED"
    i["report_revision"] += 1
    touch(i)
    return ok(ser_incident(i))


@app.route("/incidents/<incident_id>/report/amend", methods=["POST"])
def incident_report_amend(incident_id):
    authorize("Officer")
    body = body_json()
    expected_version = as_int(body, "expected_incident_version")
    i = get_or_404(incidents, incident_id, "incident")
    if i["report_status"] not in ("LOCKED", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Report not amendable")
    pu = as_str(body, "nfirs_property_use", required=False)
    at = as_str(body, "nfirs_actions_taken", required=False)
    eff_pu = pu if pu is not None else i.get("nfirs_property_use")
    eff_at = at if at is not None else i.get("nfirs_actions_taken")
    # compliance (band 9) before OCC (band 11)
    if not eff_pu or not eff_at:
        raise ApiError("ERR_NFIRS_INCOMPLETE", 422, "NFIRS fields incomplete")
    if expected_version != i["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale incident version")
    if pu is not None:
        i["nfirs_property_use"] = pu
    if at is not None:
        i["nfirs_actions_taken"] = at
    i["report_status"] = "AMENDED"
    i["report_revision"] += 1
    touch(i)
    return ok(ser_incident(i))


# ===========================================================================
# Routes: TurnoutResponse
# ===========================================================================
@app.route("/incidents/<incident_id>/turnouts", methods=["POST"])
def create_turnout(incident_id):
    authorize("Officer")
    body = body_json()
    member_id = as_str(body, "member_id")
    get_or_404(incidents, incident_id, "incident")
    get_or_404(members, member_id, "member")
    t = base_entity()
    t.update({
        "incident_id": incident_id,
        "member_id": member_id,
        "responded_at": now_clock(),
        "status": "RESPONDED",
    })
    turnouts[t["id"]] = t
    return ok(ser_turnout(t), 201)


@app.route("/turnouts/<turnout_id>", methods=["GET"])
def get_turnout(turnout_id):
    authorize("Chief", "Officer", "Member")
    t = get_or_404(turnouts, turnout_id, "turnout")
    return ok(ser_turnout(t))


@app.route("/turnouts", methods=["GET"])
def list_turnouts():
    authorize("Chief", "Officer", "Member")
    items = list(turnouts.values())
    iid = request.args.get("incident_id")
    mid = request.args.get("member_id")
    status = request.args.get("status")
    if iid is not None:
        items = [t for t in items if t["incident_id"] == iid]
    if mid is not None:
        items = [t for t in items if t["member_id"] == mid]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sort_created(items)
    return paginate([ser_turnout(t) for t in items])


@app.route("/turnouts/<turnout_id>/void", methods=["POST"])
def void_turnout(turnout_id):
    authorize("Officer")
    t = get_or_404(turnouts, turnout_id, "turnout")
    if t["status"] not in ("RESPONDED", "RELEASED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Turnout not voidable")
    t["status"] = "VOIDED"
    touch(t)
    return ok(ser_turnout(t))


# ===========================================================================
# Routes: Fundraising
# ===========================================================================
@app.route("/campaigns", methods=["POST"])
def create_campaign():
    authorize("Chief")
    body = body_json()
    name = as_str(body, "name")
    goal_cents = as_int(body, "goal_cents", positive=True)
    c = base_entity()
    c.update({"name": name, "goal_cents": goal_cents, "status": "DRAFT"})
    campaigns[c["id"]] = c
    return ok(ser_campaign(c), 201)


@app.route("/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    authorize("Chief", "Officer", "Member")
    c = get_or_404(campaigns, campaign_id, "campaign")
    return ok(ser_campaign(c))


@app.route("/campaigns", methods=["GET"])
def list_campaigns():
    authorize("Chief", "Officer", "Member")
    items = list(campaigns.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_created(items)
    return paginate([ser_campaign(c) for c in items])


@app.route("/campaigns/<campaign_id>/open", methods=["POST"])
def open_campaign(campaign_id):
    authorize("Chief")
    c = get_or_404(campaigns, campaign_id, "campaign")
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Campaign not DRAFT")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(ser_campaign(c))


@app.route("/campaigns/<campaign_id>/close", methods=["POST"])
def close_campaign(campaign_id):
    authorize("Chief")
    c = get_or_404(campaigns, campaign_id, "campaign")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Campaign not ACTIVE")
    c["status"] = "CLOSED"
    touch(c)
    return ok(ser_campaign(c))


@app.route("/campaigns/<campaign_id>/donations", methods=["POST"])
def create_donation(campaign_id):
    authorize("Chief", "Officer")
    body = body_json()
    donor_name = as_str(body, "donor_name")
    amount_cents = as_int(body, "amount_cents", positive=True)
    c = get_or_404(campaigns, campaign_id, "campaign")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Campaign not ACTIVE")
    d = base_entity()
    d.update({
        "campaign_id": campaign_id,
        "donor_name": donor_name,
        "amount_cents": amount_cents,
        "status": "POSTED",
    })
    donations[d["id"]] = d
    return ok(ser_donation(d), 201)


@app.route("/donations/<donation_id>", methods=["GET"])
def get_donation(donation_id):
    authorize("Chief", "Officer", "Member")
    d = get_or_404(donations, donation_id, "donation")
    return ok(ser_donation(d))


@app.route("/donations", methods=["GET"])
def list_donations():
    authorize("Chief", "Officer", "Member")
    items = list(donations.values())
    cid = request.args.get("campaign_id")
    status = request.args.get("status")
    if cid is not None:
        items = [d for d in items if d["campaign_id"] == cid]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sort_created(items)
    return paginate([ser_donation(d) for d in items])


@app.route("/donations/<donation_id>/refund", methods=["POST"])
def refund_donation(donation_id):
    authorize("Chief")
    d = get_or_404(donations, donation_id, "donation")
    if d["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Donation not POSTED")
    c = campaigns.get(d["campaign_id"])
    if c is not None and c["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Campaign is closed")
    d["status"] = "REFUNDED"
    touch(d)
    return ok(ser_donation(d))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
