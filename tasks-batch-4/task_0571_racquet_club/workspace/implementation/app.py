import os
import re
import uuid
import random
import string
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Constants (from SCAFFOLD §1.3 / global constants)
# =============================================================================
CREDIT_MINUTES = 60
PEAK_START_HOUR = 17
PEAK_END_HOUR = 21
PEAK_SURCHARGE_PCT = Decimal("0.25")
NO_SHOW_GRACE_MINUTES = 15
NO_SHOW_SUSPEND_THRESHOLD = 3
CHECKIN_EARLY_MINUTES = 30
PRO_BUFFER_MINUTES = 15
MAX_ADVANCE_DAYS = 14
DAYS_PER_PERIOD = 30
MAX_OUTSTANDING_BALANCE_CENTS = 20000
POINTS_WIN = 3
POINTS_LOSS = 0
DEFAULT_CLOCK_UTC = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = {"Member", "Pro", "FrontDesk"}

SURFACES = {"HARD", "CLAY", "GRASS"}
LOCATION_TYPES = {"INDOOR", "OUTDOOR"}
TIERS = {"BASIC", "PREMIER", "ELITE"}
LESSON_KINDS = {"PRIVATE", "CLINIC"}
COMP_FORMATS = {"ROUND_ROBIN", "LADDER", "TOURNAMENT"}

RESERVATION_TERMINAL = {"COMPLETED", "CANCELLED", "NO_SHOW"}
LESSON_ACTIVE_STATES = {"SCHEDULED", "CONFIRMED", "COMPLETED"}  # non-cancelled

# =============================================================================
# In-memory store (starts EMPTY on every boot; no seeding)
# =============================================================================
class Store:
    def __init__(self):
        self.courts = {}
        self.plans = {}
        self.members = {}
        self.subscriptions = {}
        self.reservations = {}
        self.pros = {}
        self.lessons = {}
        self.enrollments = {}
        self.competitions = {}
        self.participants = {}
        self.stringing_jobs = {}
        self.clock = DEFAULT_CLOCK_UTC
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


# =============================================================================
# Datetime helpers
# =============================================================================
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.
    Returns None if the value is not a valid datetime string."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            frac = (frac + "000000")[:6]
            micro = int(frac)
        if tz is None or tz == "Z":
            tzinfo = timezone.utc
        else:
            tzs = tz.replace(":", "")
            sign = 1 if tzs[0] == "+" else -1
            oh = int(tzs[1:3])
            omm = int(tzs[3:5])
            tzinfo = timezone(sign * timedelta(hours=oh, minutes=omm))
        dt = datetime(int(year), int(month), int(day), int(hour),
                      int(minute), int(second), micro, tzinfo=tzinfo)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# =============================================================================
# Errors + response envelope
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def meta(pagination=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": fmt_dt(now()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def success(data, response_type="object", code=200, pagination=None):
    body = {
        "meta": meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), code


def error_response(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_VALIDATION", 400, str(e)))


# =============================================================================
# Auth / RBAC
# =============================================================================
def identity():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown auth headers")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


# =============================================================================
# Field validation helpers
# =============================================================================
def verr(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


def req_str(body, key):
    if key not in body:
        verr("Missing required field: %s" % key)
    v = body[key]
    if not isinstance(v, str) or v == "":
        verr("Field %s must be a non-empty string" % key)
    return v


def req_int(body, key, minimum=None):
    if key not in body:
        verr("Missing required field: %s" % key)
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        verr("Field %s must be an integer" % key)
    if minimum is not None and v < minimum:
        verr("Field %s must be >= %s" % (key, minimum))
    return v


def opt_int(body, key, default, minimum=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        verr("Field %s must be an integer" % key)
    if minimum is not None and v < minimum:
        verr("Field %s must be >= %s" % (key, minimum))
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        verr("Field %s must be one of %s" % (key, sorted(allowed)))
    return v


def opt_bool(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        verr("Field %s must be a boolean" % key)
    return v


def req_bool(body, key):
    if key not in body:
        verr("Missing required field: %s" % key)
    v = body[key]
    if not isinstance(v, bool):
        verr("Field %s must be a boolean" % key)
    return v


def req_dt(body, key):
    if key not in body:
        verr("Missing required field: %s" % key)
    dt = parse_dt(body[key])
    if dt is None:
        verr("Field %s must be an ISO 8601 datetime" % key)
    return dt


def is_power_of_two(n):
    return isinstance(n, int) and not isinstance(n, bool) and n >= 1 and (n & (n - 1)) == 0


# =============================================================================
# Common fields / touch
# =============================================================================
def base_record():
    t = now()
    return {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


# =============================================================================
# Serialization
# =============================================================================
def clean(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def view_lesson(rec):
    out = clean(rec)
    out["enrolled_count"] = enrolled_count(rec["id"])
    return out


VIEWS = {}


def default_view(rec):
    return clean(rec)


# =============================================================================
# Lookup helpers
# =============================================================================
def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return rec


def fk_exists_or_404(coll, rid):
    if rid is not None and rid in coll:
        return coll[rid]
    raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource not found")


def member_subscription(member_id):
    """Return the member's single non-CANCELLED subscription, or None."""
    for s in db.subscriptions.values():
        if s["member_id"] == member_id and s["status"] != "CANCELLED":
            return s
    return None


def get_plan(plan_id):
    return db.plans.get(plan_id)


def enrolled_count(lesson_id):
    return sum(1 for e in db.enrollments.values()
               if e["lesson_id"] == lesson_id and e["status"] == "ENROLLED")


# =============================================================================
# Pagination / listing
# =============================================================================
def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            limit = 10
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(records, view=default_view, extra_filter=None):
    items = list(records)
    if extra_filter:
        items = [r for r in items if extra_filter(r)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    data = [view(r) for r in page]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success(data, "array", 200, pagination)


def filt(records, key, value):
    if value is None:
        return records
    return [r for r in records if str(r.get(key)) == str(value)]


# =============================================================================
# Charge computation
# =============================================================================
def duration_hours(start, end):
    secs = (end - start).total_seconds()
    return int(math.ceil(secs / 3600.0))


def is_peak_start(start):
    return PEAK_START_HOUR <= start.astimezone(timezone.utc).hour < PEAK_END_HOUR


def base_court_charge(court, start, end):
    dur = duration_hours(start, end)
    peak = is_peak_start(start)
    base = court["hourly_rate_cents"] * dur
    if peak:
        surcharge = int((Decimal(base) * PEAK_SURCHARGE_PCT).to_integral_value(
            rounding="ROUND_CEILING"))
        base = base + surcharge
    return dur, peak, base


def compute_provisional(court, sub, plan, start, end, guest_count, uses_ball):
    dur, peak, base = base_court_charge(court, start, end)
    credit_eligible = (
        sub is not None
        and sub["status"] == "ACTIVE"
        and sub["court_credits_remaining"] >= dur
        and ((not peak) or (plan is not None and plan["peak_access"]))
    )
    if credit_eligible:
        credits_used = dur
        court_charge = 0
    else:
        credits_used = 0
        court_charge = base
    guest_fee = plan["guest_fee_cents"] if plan is not None else 0
    guest_charge = guest_count * guest_fee
    ball = court["ball_machine_fee_cents"] if (uses_ball and court["has_ball_machine"]) else 0
    fee = court_charge + guest_charge + ball
    return dur, peak, credits_used, fee


def compute_final(court, plan, start, end, actual_guests, uses_ball, credits_used):
    dur, peak, base = base_court_charge(court, start, end)
    court_charge = 0 if credits_used > 0 else base
    guest_fee = plan["guest_fee_cents"] if plan is not None else 0
    guest_charge = actual_guests * guest_fee
    ball = court["ball_machine_fee_cents"] if (uses_ball and court["has_ball_machine"]) else 0
    return court_charge + guest_charge + ball


def interval_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


# =============================================================================
# CLOCK
# =============================================================================
@app.route("/racquet/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    body = body_json()
    dt = req_dt(body, "to_iso8601")
    db.clock = dt
    return success({}, "object", 200)


# =============================================================================
# COURTS
# =============================================================================
@app.route("/racquet/courts", methods=["POST"])
def create_court():
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    body = body_json()
    name = req_str(body, "name")
    surface = req_enum(body, "surface", SURFACES)
    location_type = req_enum(body, "location_type", LOCATION_TYPES)
    hourly_rate = req_int(body, "hourly_rate_cents", 0)
    has_ball = opt_bool(body, "has_ball_machine", False)
    ball_fee = opt_int(body, "ball_machine_fee_cents", 0, 0)
    rec = base_record()
    rec.update({
        "name": name, "surface": surface, "location_type": location_type,
        "hourly_rate_cents": hourly_rate, "has_ball_machine": has_ball,
        "ball_machine_fee_cents": ball_fee, "status": "AVAILABLE",
    })
    db.courts[rec["id"]] = rec
    return success(clean(rec), "object", 201)


@app.route("/racquet/courts/<court_id>", methods=["GET"])
def get_court(court_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.courts, court_id)
    return success(clean(rec), "object", 200)


@app.route("/racquet/courts", methods=["GET"])
def list_courts():
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    recs = list(db.courts.values())
    recs = filt(recs, "status", request.args.get("status"))
    recs = filt(recs, "location_type", request.args.get("location_type"))
    return list_response(recs)


@app.route("/racquet/courts/<court_id>/maintenance", methods=["POST"])
def court_maintenance(court_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    court = get_or_404(db.courts, court_id)
    if court["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Court is not AVAILABLE")
    court["status"] = "MAINTENANCE"
    touch(court)
    # cascade: future BOOKED reservations -> CANCELLED with compensation
    clock = now()
    for r in db.reservations.values():
        if r["court_id"] == court_id and r["status"] == "BOOKED" and r["start_time"] >= clock:
            _cancel_reservation_effects(r)
            r["status"] = "CANCELLED"
            touch(r)
    return success(clean(court), "object", 200)


@app.route("/racquet/courts/<court_id>/reopen", methods=["POST"])
def court_reopen(court_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    court = get_or_404(db.courts, court_id)
    if court["status"] != "MAINTENANCE":
        raise ApiError("ERR_INVALID_STATE", 409, "Court is not in MAINTENANCE")
    court["status"] = "AVAILABLE"
    touch(court)
    return success(clean(court), "object", 200)


@app.route("/racquet/courts/<court_id>/retire", methods=["POST"])
def court_retire(court_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    court = get_or_404(db.courts, court_id)
    clock = now()
    for r in db.reservations.values():
        if (r["court_id"] == court_id and r["status"] in ("BOOKED", "CHECKED_IN")
                and r["start_time"] >= clock):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Court has active future reservations")
    court["status"] = "RETIRED"
    touch(court)
    return success(clean(court), "object", 200)


# =============================================================================
# MEMBERSHIP PLANS
# =============================================================================
@app.route("/racquet/membership-plans", methods=["POST"])
def create_plan():
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    body = body_json()
    rec = base_record()
    rec.update({
        "name": req_str(body, "name"),
        "tier": req_enum(body, "tier", TIERS),
        "monthly_fee_cents": req_int(body, "monthly_fee_cents", 0),
        "monthly_court_credits": req_int(body, "monthly_court_credits", 0),
        "peak_access": req_bool(body, "peak_access"),
        "guest_fee_cents": req_int(body, "guest_fee_cents", 0),
        "freeze_limit": req_int(body, "freeze_limit", 0),
    })
    db.plans[rec["id"]] = rec
    return success(clean(rec), "object", 201)


@app.route("/racquet/membership-plans/<plan_id>", methods=["GET"])
def get_plan_ep(plan_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.plans, plan_id)
    return success(clean(rec), "object", 200)


@app.route("/racquet/membership-plans", methods=["GET"])
def list_plans():
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    recs = filt(list(db.plans.values()), "tier", request.args.get("tier"))
    return list_response(recs)


# =============================================================================
# MEMBERS
# =============================================================================
@app.route("/racquet/members", methods=["POST"])
def create_member():
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    body = body_json()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    rec = base_record()
    rec.update({
        "full_name": full_name, "email": email, "status": "ACTIVE",
        "no_show_strikes": 0, "account_balance_cents": 0,
    })
    db.members[rec["id"]] = rec
    return success(clean(rec), "object", 201)


@app.route("/racquet/members/<member_id>", methods=["GET"])
def get_member(member_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.members, member_id)
    return success(clean(rec), "object", 200)


@app.route("/racquet/members", methods=["GET"])
def list_members():
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    recs = list(db.members.values())
    recs = filt(recs, "status", request.args.get("status"))
    recs = filt(recs, "email", request.args.get("email"))
    return list_response(recs)


def _suspend_member(member):
    """Perform ACTIVE->SUSPENDED and cascade freeze of the ACTIVE subscription."""
    member["status"] = "SUSPENDED"
    touch(member)
    sub = member_subscription(member["id"])
    if sub is not None and sub["status"] == "ACTIVE":
        sub["status"] = "FROZEN"
        sub["frozen_at"] = now()
        touch(sub)


@app.route("/racquet/members/<member_id>/suspend", methods=["POST"])
def suspend_member(member_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    member = get_or_404(db.members, member_id)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Member is not ACTIVE")
    _suspend_member(member)
    return success(clean(member), "object", 200)


@app.route("/racquet/members/<member_id>/reinstate", methods=["POST"])
def reinstate_member(member_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    member = get_or_404(db.members, member_id)
    if member["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Member is not SUSPENDED")
    member["status"] = "ACTIVE"
    member["no_show_strikes"] = 0
    touch(member)
    return success(clean(member), "object", 200)


# =============================================================================
# SUBSCRIPTIONS
# =============================================================================
@app.route("/racquet/subscriptions", methods=["POST"])
def create_subscription():
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    body = body_json()
    # existence (layer 3)
    member_id = body.get("member_id")
    plan_id = body.get("plan_id")
    if member_id is not None:
        fk_exists_or_404(db.members, member_id)
    if plan_id is not None:
        fk_exists_or_404(db.plans, plan_id)
    # body well-formedness (layer 4)
    member_id = req_str(body, "member_id")
    plan_id = req_str(body, "plan_id")
    member = get_or_404(db.members, member_id)
    plan = get_or_404(db.plans, plan_id)
    # uniqueness (layer 9): one non-CANCELLED subscription
    if member_subscription(member_id) is not None:
        raise ApiError("ERR_SUBSCRIPTION_EXISTS", 409,
                       "Member already has a non-CANCELLED subscription")
    t = now()
    rec = base_record()
    rec.update({
        "member_id": member_id, "plan_id": plan_id, "status": "ACTIVE",
        "court_credits_remaining": plan["monthly_court_credits"],
        "estimated_period_fee_cents": plan["monthly_fee_cents"],
        "freeze_count": 0,
        "current_period_start": t,
        "current_period_end": t + timedelta(days=DAYS_PER_PERIOD),
        "frozen_at": None,
    })
    db.subscriptions[rec["id"]] = rec
    return success(clean(rec), "object", 201)


@app.route("/racquet/subscriptions/<subscription_id>", methods=["GET"])
def get_subscription(subscription_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.subscriptions, subscription_id)
    return success(clean(rec), "object", 200)


@app.route("/racquet/subscriptions", methods=["GET"])
def list_subscriptions():
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    recs = list(db.subscriptions.values())
    recs = filt(recs, "member_id", request.args.get("member_id"))
    recs = filt(recs, "plan_id", request.args.get("plan_id"))
    recs = filt(recs, "status", request.args.get("status"))
    return list_response(recs)


def _sub_owner_check(sub, uid, role):
    if role == "Member" and sub["member_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Not your subscription")


@app.route("/racquet/subscriptions/<subscription_id>/freeze", methods=["POST"])
def freeze_subscription(subscription_id):
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    sub = get_or_404(db.subscriptions, subscription_id)
    _sub_owner_check(sub, uid, role)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is not ACTIVE")
    plan = get_plan(sub["plan_id"])
    if sub["freeze_count"] >= plan["freeze_limit"]:
        raise ApiError("ERR_FREEZE_LIMIT_REACHED", 409, "Freeze limit reached")
    sub["status"] = "FROZEN"
    sub["freeze_count"] += 1
    sub["frozen_at"] = now()
    touch(sub)
    return success(clean(sub), "object", 200)


@app.route("/racquet/subscriptions/<subscription_id>/unfreeze", methods=["POST"])
def unfreeze_subscription(subscription_id):
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    sub = get_or_404(db.subscriptions, subscription_id)
    _sub_owner_check(sub, uid, role)
    if sub["status"] != "FROZEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is not FROZEN")
    sub["status"] = "ACTIVE"
    sub["frozen_at"] = None
    touch(sub)
    return success(clean(sub), "object", 200)


@app.route("/racquet/subscriptions/<subscription_id>/change-plan", methods=["POST"])
def change_plan(subscription_id):
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    sub = get_or_404(db.subscriptions, subscription_id)
    _sub_owner_check(sub, uid, role)
    body = body_json()
    # existence of FK plan (layer 3)
    plan_id = body.get("plan_id")
    if plan_id is not None:
        fk_exists_or_404(db.plans, plan_id)
    # body well-formedness (layer 4)
    plan_id = req_str(body, "plan_id")
    if "expected_subscription_version" not in body:
        verr("Missing required field: expected_subscription_version")
    exp = req_int(body, "expected_subscription_version")
    plan = get_or_404(db.plans, plan_id)
    # OCC (layer 5)
    if exp != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale subscription version")
    # state (layer 6)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is not ACTIVE")
    sub["plan_id"] = plan_id
    sub["estimated_period_fee_cents"] = plan["monthly_fee_cents"]
    touch(sub)
    return success(clean(sub), "object", 200)


def _active_days(sub):
    period_start = sub["current_period_start"]
    frozen_at = sub["frozen_at"]
    if sub["status"] == "FROZEN" and frozen_at is not None:
        base = period_start.replace(hour=0, minute=0, second=0, microsecond=0)
        count = 0
        for i in range(DAYS_PER_PERIOD):
            dm = base + timedelta(days=i)
            if dm < frozen_at:
                count += 1
        return count
    return DAYS_PER_PERIOD


def _chronological_cost(sub):
    plan = get_plan(sub["plan_id"])
    daily = Decimal(plan["monthly_fee_cents"]) / Decimal(DAYS_PER_PERIOD)
    per_day = int(daily.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return per_day * _active_days(sub)


@app.route("/racquet/subscriptions/<subscription_id>/renew", methods=["POST"])
def renew_subscription(subscription_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    sub = get_or_404(db.subscriptions, subscription_id)
    if sub["status"] not in ("ACTIVE", "FROZEN"):
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is CANCELLED")
    if now() < sub["current_period_end"]:
        raise ApiError("ERR_RENEW_NOT_DUE", 409, "Renewal not due")
    plan = get_plan(sub["plan_id"])
    cost = _chronological_cost(sub)
    member = db.members.get(sub["member_id"])
    if member is not None:
        member["account_balance_cents"] += cost
    old_end = sub["current_period_end"]
    sub["current_period_start"] = old_end
    sub["current_period_end"] = old_end + timedelta(days=DAYS_PER_PERIOD)
    sub["court_credits_remaining"] = plan["monthly_court_credits"]
    sub["estimated_period_fee_cents"] = plan["monthly_fee_cents"]
    sub["frozen_at"] = None
    sub["status"] = "ACTIVE"
    touch(sub)
    return success(clean(sub), "object", 200)


@app.route("/racquet/subscriptions/<subscription_id>/cancel", methods=["POST"])
def cancel_subscription(subscription_id):
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    sub = get_or_404(db.subscriptions, subscription_id)
    _sub_owner_check(sub, uid, role)
    if sub["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription already CANCELLED")
    sub["status"] = "CANCELLED"
    sub["court_credits_remaining"] = 0
    touch(sub)
    return success(clean(sub), "object", 200)


# =============================================================================
# RESERVATIONS
# =============================================================================
def _cancel_reservation_effects(r):
    """Compensating reversal for a BOOKED reservation being cancelled."""
    member = db.members.get(r["member_id"])
    if member is not None:
        member["account_balance_cents"] -= r["provisional_fee_cents"]
    if r["credits_used"] > 0:
        sub = member_subscription(r["member_id"])
        if sub is not None:
            sub["court_credits_remaining"] += r["credits_used"]


@app.route("/racquet/reservations", methods=["POST"])
def create_reservation():
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    body = body_json()
    # ownership on body member_id (authz, string compare)
    if role == "Member" and body.get("member_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only book for themselves")
    # existence (layer 3)
    court_id = body.get("court_id")
    member_id = body.get("member_id")
    if court_id is not None:
        fk_exists_or_404(db.courts, court_id)
    if member_id is not None:
        fk_exists_or_404(db.members, member_id)
    # body well-formedness (layer 4)
    court_id = req_str(body, "court_id")
    member_id = req_str(body, "member_id")
    start = req_dt(body, "start_time")
    end = req_dt(body, "end_time")
    if end <= start:
        verr("end_time must be strictly greater than start_time")
    guest_count = opt_int(body, "guest_count", 0, 0)
    uses_ball = opt_bool(body, "uses_ball_machine", False)
    court = get_or_404(db.courts, court_id)
    member = get_or_404(db.members, member_id)
    # cross-entity referential (layer 7)
    if court["status"] != "AVAILABLE":
        raise ApiError("ERR_COURT_NOT_AVAILABLE", 409, "Court is not AVAILABLE")
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409, "Member is suspended")
    # temporal (layer 8)
    clock = now()
    if start <= clock:
        raise ApiError("ERR_BOOKING_IN_PAST", 409, "start_time is not in the future")
    if start > clock + timedelta(days=MAX_ADVANCE_DAYS):
        raise ApiError("ERR_BOOKING_WINDOW_EXCEEDED", 409, "Booking too far ahead")
    for other in db.reservations.values():
        if (other["court_id"] == court_id and other["status"] not in RESERVATION_TERMINAL
                and interval_overlap(start, end, other["start_time"], other["end_time"])):
            raise ApiError("ERR_COURT_TIME_CONFLICT", 409, "Court time conflict")
    # uniqueness (layer 9)
    for other in db.reservations.values():
        if (other["member_id"] == member_id and other["court_id"] == court_id
                and other["status"] not in RESERVATION_TERMINAL
                and other["start_time"] == start):
            raise ApiError("ERR_DUPLICATE_RESERVATION", 409, "Duplicate reservation")
    # fiscal (layer 10)
    if member["account_balance_cents"] > MAX_OUTSTANDING_BALANCE_CENTS:
        raise ApiError("ERR_BALANCE_LIMIT_EXCEEDED", 402, "Outstanding balance too high")

    sub = member_subscription(member_id)
    plan = get_plan(sub["plan_id"]) if sub is not None else None
    dur, peak, credits_used, fee = compute_provisional(
        court, sub, plan, start, end, guest_count, uses_ball)

    rec = base_record()
    rec.update({
        "court_id": court_id, "member_id": member_id,
        "start_time": start, "end_time": end,
        "guest_count": guest_count, "actual_guest_count": None,
        "uses_ball_machine": uses_ball, "is_peak": peak,
        "credits_used": credits_used, "provisional_fee_cents": fee,
        "final_fee_cents": None, "status": "BOOKED",
    })
    db.reservations[rec["id"]] = rec
    member["account_balance_cents"] += fee
    if credits_used > 0 and sub is not None:
        sub["court_credits_remaining"] -= credits_used
        if sub["court_credits_remaining"] < 0:
            sub["court_credits_remaining"] = 0
    return success(clean(rec), "object", 201)


@app.route("/racquet/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.reservations, reservation_id)
    return success(clean(rec), "object", 200)


@app.route("/racquet/reservations", methods=["GET"])
def list_reservations():
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    recs = list(db.reservations.values())
    recs = filt(recs, "court_id", request.args.get("court_id"))
    recs = filt(recs, "member_id", request.args.get("member_id"))
    recs = filt(recs, "status", request.args.get("status"))
    return list_response(recs)


def _res_owner_check(r, uid, role):
    if role == "Member" and r["member_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Not your reservation")


@app.route("/racquet/reservations/<reservation_id>/check-in", methods=["POST"])
def checkin_reservation(reservation_id):
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    r = get_or_404(db.reservations, reservation_id)
    _res_owner_check(r, uid, role)
    body = body_json()
    if r["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation is not BOOKED")
    clock = now()
    window_start = r["start_time"] - timedelta(minutes=CHECKIN_EARLY_MINUTES)
    if not (window_start <= clock < r["end_time"]):
        raise ApiError("ERR_CHECKIN_WINDOW", 409, "Outside check-in window")
    agc = opt_int(body, "actual_guest_count", r["guest_count"], 0)
    r["actual_guest_count"] = agc
    r["status"] = "CHECKED_IN"
    touch(r)
    return success(clean(r), "object", 200)


@app.route("/racquet/reservations/<reservation_id>/complete", methods=["POST"])
def complete_reservation(reservation_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    r = get_or_404(db.reservations, reservation_id)
    if r["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation is not CHECKED_IN")
    court = db.courts.get(r["court_id"])
    sub = member_subscription(r["member_id"])
    plan = get_plan(sub["plan_id"]) if sub is not None else None
    actual = r["actual_guest_count"]
    if actual is None:
        actual = r["guest_count"]
    final = compute_final(court, plan, r["start_time"], r["end_time"],
                          actual, r["uses_ball_machine"], r["credits_used"])
    delta = final - r["provisional_fee_cents"]
    r["final_fee_cents"] = final
    r["status"] = "COMPLETED"
    member = db.members.get(r["member_id"])
    if member is not None:
        member["account_balance_cents"] += delta
    touch(r)
    return success(clean(r), "object", 200)


@app.route("/racquet/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    r = get_or_404(db.reservations, reservation_id)
    _res_owner_check(r, uid, role)
    if r["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation is not BOOKED")
    _cancel_reservation_effects(r)
    r["status"] = "CANCELLED"
    touch(r)
    return success(clean(r), "object", 200)


@app.route("/racquet/reservations/<reservation_id>/reschedule", methods=["POST"])
def reschedule_reservation(reservation_id):
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    r = get_or_404(db.reservations, reservation_id)
    _res_owner_check(r, uid, role)
    body = body_json()
    start = req_dt(body, "start_time")
    end = req_dt(body, "end_time")
    if end <= start:
        verr("end_time must be strictly greater than start_time")
    if "expected_reservation_version" not in body:
        verr("Missing required field: expected_reservation_version")
    exp = req_int(body, "expected_reservation_version")
    # OCC (layer 5)
    if exp != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale reservation version")
    # state (layer 6)
    if r["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation is not BOOKED")
    # temporal (layer 8)
    clock = now()
    if start <= clock:
        raise ApiError("ERR_BOOKING_IN_PAST", 409, "start_time is not in the future")
    if start > clock + timedelta(days=MAX_ADVANCE_DAYS):
        raise ApiError("ERR_BOOKING_WINDOW_EXCEEDED", 409, "Booking too far ahead")
    for other in db.reservations.values():
        if (other["id"] != r["id"] and other["court_id"] == r["court_id"]
                and other["status"] not in RESERVATION_TERMINAL
                and interval_overlap(start, end, other["start_time"], other["end_time"])):
            raise ApiError("ERR_COURT_TIME_CONFLICT", 409, "Court time conflict")
    # re-settle: reverse old, recompute, apply new
    _cancel_reservation_effects(r)
    court = db.courts.get(r["court_id"])
    sub = member_subscription(r["member_id"])
    plan = get_plan(sub["plan_id"]) if sub is not None else None
    dur, peak, credits_used, fee = compute_provisional(
        court, sub, plan, start, end, r["guest_count"], r["uses_ball_machine"])
    r["start_time"] = start
    r["end_time"] = end
    r["is_peak"] = peak
    r["credits_used"] = credits_used
    r["provisional_fee_cents"] = fee
    member = db.members.get(r["member_id"])
    if member is not None:
        member["account_balance_cents"] += fee
    if credits_used > 0 and sub is not None:
        sub["court_credits_remaining"] -= credits_used
        if sub["court_credits_remaining"] < 0:
            sub["court_credits_remaining"] = 0
    touch(r)
    return success(clean(r), "object", 200)


@app.route("/racquet/reservations/<reservation_id>/mark-no-show", methods=["POST"])
def mark_no_show(reservation_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    r = get_or_404(db.reservations, reservation_id)
    if r["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation is not BOOKED")
    clock = now()
    if clock < r["start_time"] + timedelta(minutes=NO_SHOW_GRACE_MINUTES):
        raise ApiError("ERR_NO_SHOW_TOO_EARLY", 409, "Grace period not elapsed")
    r["status"] = "NO_SHOW"
    touch(r)
    member = db.members.get(r["member_id"])
    if member is not None:
        member["no_show_strikes"] += 1
        if member["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD and member["status"] == "ACTIVE":
            _suspend_member(member)
    return success(clean(r), "object", 200)


# =============================================================================
# PROS
# =============================================================================
@app.route("/racquet/pros", methods=["POST"])
def create_pro():
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    body = body_json()
    rec = base_record()
    rec.update({
        "full_name": req_str(body, "full_name"),
        "hourly_rate_cents": req_int(body, "hourly_rate_cents", 0),
        "status": "ACTIVE",
    })
    db.pros[rec["id"]] = rec
    return success(clean(rec), "object", 201)


@app.route("/racquet/pros/<pro_id>", methods=["GET"])
def get_pro(pro_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.pros, pro_id)
    return success(clean(rec), "object", 200)


@app.route("/racquet/pros", methods=["GET"])
def list_pros():
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    recs = filt(list(db.pros.values()), "status", request.args.get("status"))
    return list_response(recs)


# =============================================================================
# LESSONS
# =============================================================================
@app.route("/racquet/lessons", methods=["POST"])
def create_lesson():
    uid, role = identity()
    require_roles(role, {"Pro", "FrontDesk"})
    body = body_json()
    # ownership on body pro_id (authz, string compare)
    if role == "Pro" and body.get("pro_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Pros may only schedule their own lessons")
    # existence (layer 3)
    pro_id = body.get("pro_id")
    court_id = body.get("court_id")
    if pro_id is not None:
        fk_exists_or_404(db.pros, pro_id)
    if court_id is not None:
        fk_exists_or_404(db.courts, court_id)
    # body well-formedness (layer 4)
    pro_id = req_str(body, "pro_id")
    court_id = req_str(body, "court_id")
    kind = req_enum(body, "kind", LESSON_KINDS)
    start = req_dt(body, "start_time")
    end = req_dt(body, "end_time")
    if end <= start:
        verr("end_time must be strictly greater than start_time")
    price = req_int(body, "price_cents", 0)
    capacity = opt_int(body, "capacity", 1, 1)
    if kind == "PRIVATE":
        capacity = 1
    get_or_404(db.pros, pro_id)
    get_or_404(db.courts, court_id)
    # temporal (layer 8): court conflict, then pro buffer
    for other in db.reservations.values():
        if (other["court_id"] == court_id and other["status"] not in RESERVATION_TERMINAL
                and interval_overlap(start, end, other["start_time"], other["end_time"])):
            raise ApiError("ERR_LESSON_COURT_CONFLICT", 409, "Lesson court conflict")
    for other in db.lessons.values():
        if (other["court_id"] == court_id and other["status"] != "CANCELLED"
                and interval_overlap(start, end, other["start_time"], other["end_time"])):
            raise ApiError("ERR_LESSON_COURT_CONFLICT", 409, "Lesson court conflict")
    buf = timedelta(minutes=PRO_BUFFER_MINUTES)
    for other in db.lessons.values():
        if other["pro_id"] == pro_id and other["status"] != "CANCELLED":
            if start < other["end_time"] + buf and other["start_time"] < end + buf:
                raise ApiError("ERR_PRO_TIME_CONFLICT", 409, "Pro time conflict")
    rec = base_record()
    rec.update({
        "pro_id": pro_id, "court_id": court_id, "kind": kind,
        "start_time": start, "end_time": end, "capacity": capacity,
        "price_cents": price, "status": "SCHEDULED",
    })
    db.lessons[rec["id"]] = rec
    return success(view_lesson(rec), "object", 201)


@app.route("/racquet/lessons/<lesson_id>", methods=["GET"])
def get_lesson(lesson_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.lessons, lesson_id)
    return success(view_lesson(rec), "object", 200)


@app.route("/racquet/lessons", methods=["GET"])
def list_lessons():
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    recs = list(db.lessons.values())
    recs = filt(recs, "pro_id", request.args.get("pro_id"))
    recs = filt(recs, "court_id", request.args.get("court_id"))
    recs = filt(recs, "status", request.args.get("status"))
    return list_response(recs, view=view_lesson)


def _lesson_owner_check(lesson, uid, role):
    if role == "Pro" and lesson["pro_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Not your lesson")


@app.route("/racquet/lessons/<lesson_id>/confirm", methods=["POST"])
def confirm_lesson(lesson_id):
    uid, role = identity()
    require_roles(role, {"Pro", "FrontDesk"})
    lesson = get_or_404(db.lessons, lesson_id)
    _lesson_owner_check(lesson, uid, role)
    if lesson["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Lesson is not SCHEDULED")
    if enrolled_count(lesson_id) < 1:
        raise ApiError("ERR_INVALID_STATE", 409, "Lesson has no enrolled members")
    lesson["status"] = "CONFIRMED"
    touch(lesson)
    return success(view_lesson(lesson), "object", 200)


@app.route("/racquet/lessons/<lesson_id>/complete", methods=["POST"])
def complete_lesson(lesson_id):
    uid, role = identity()
    require_roles(role, {"Pro", "FrontDesk"})
    lesson = get_or_404(db.lessons, lesson_id)
    _lesson_owner_check(lesson, uid, role)
    if lesson["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Lesson is not CONFIRMED")
    lesson["status"] = "COMPLETED"
    for e in db.enrollments.values():
        if e["lesson_id"] == lesson_id and e["status"] == "ENROLLED":
            member = db.members.get(e["member_id"])
            if member is not None:
                member["account_balance_cents"] += lesson["price_cents"]
    touch(lesson)
    return success(view_lesson(lesson), "object", 200)


@app.route("/racquet/lessons/<lesson_id>/cancel", methods=["POST"])
def cancel_lesson(lesson_id):
    uid, role = identity()
    require_roles(role, {"Pro", "FrontDesk"})
    lesson = get_or_404(db.lessons, lesson_id)
    _lesson_owner_check(lesson, uid, role)
    if lesson["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Lesson cannot be cancelled")
    lesson["status"] = "CANCELLED"
    for e in db.enrollments.values():
        if e["lesson_id"] == lesson_id and e["status"] in ("ENROLLED", "WAITLISTED"):
            e["status"] = "CANCELLED"
            touch(e)
    touch(lesson)
    return success(view_lesson(lesson), "object", 200)


# =============================================================================
# ENROLLMENTS
# =============================================================================
def _promote_waitlist(lesson_id):
    lesson = db.lessons.get(lesson_id)
    if lesson is None:
        return
    if enrolled_count(lesson_id) >= lesson["capacity"]:
        return
    waitlisted = [e for e in db.enrollments.values()
                  if e["lesson_id"] == lesson_id and e["status"] == "WAITLISTED"]
    if not waitlisted:
        return
    waitlisted.sort(key=lambda e: (e["created_at"], e["_seq"]))
    promoted = waitlisted[0]
    promoted["status"] = "ENROLLED"
    touch(promoted)


@app.route("/racquet/enrollments", methods=["POST"])
def create_enrollment():
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    body = body_json()
    if role == "Member" and body.get("member_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only enroll themselves")
    lesson_id = body.get("lesson_id")
    member_id = body.get("member_id")
    if lesson_id is not None:
        fk_exists_or_404(db.lessons, lesson_id)
    if member_id is not None:
        fk_exists_or_404(db.members, member_id)
    lesson_id = req_str(body, "lesson_id")
    member_id = req_str(body, "member_id")
    lesson = get_or_404(db.lessons, lesson_id)
    member = get_or_404(db.members, member_id)
    # cross-entity referential (layer 7)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409, "Member is suspended")
    sub = member_subscription(member_id)
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_REQUIRED", 409, "Member has no subscription")
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription is not ACTIVE")
    # uniqueness (layer 9)
    for e in db.enrollments.values():
        if (e["lesson_id"] == lesson_id and e["member_id"] == member_id
                and e["status"] != "CANCELLED"):
            raise ApiError("ERR_DUPLICATE_ENROLLMENT", 409, "Duplicate enrollment")
    status = "ENROLLED" if enrolled_count(lesson_id) < lesson["capacity"] else "WAITLISTED"
    rec = base_record()
    rec.update({
        "lesson_id": lesson_id, "member_id": member_id, "status": status,
    })
    db.enrollments[rec["id"]] = rec
    return success(clean(rec), "object", 201)


@app.route("/racquet/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.enrollments, enrollment_id)
    return success(clean(rec), "object", 200)


@app.route("/racquet/enrollments", methods=["GET"])
def list_enrollments():
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    recs = list(db.enrollments.values())
    recs = filt(recs, "lesson_id", request.args.get("lesson_id"))
    recs = filt(recs, "member_id", request.args.get("member_id"))
    recs = filt(recs, "status", request.args.get("status"))
    return list_response(recs)


@app.route("/racquet/enrollments/<enrollment_id>/cancel", methods=["POST"])
def cancel_enrollment(enrollment_id):
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    e = get_or_404(db.enrollments, enrollment_id)
    if role == "Member" and e["member_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Not your enrollment")
    if e["status"] not in ("ENROLLED", "WAITLISTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Enrollment cannot be cancelled")
    was_enrolled = e["status"] == "ENROLLED"
    e["status"] = "CANCELLED"
    touch(e)
    if was_enrolled:
        _promote_waitlist(e["lesson_id"])
    return success(clean(e), "object", 200)


# =============================================================================
# COMPETITIONS
# =============================================================================
@app.route("/racquet/competitions", methods=["POST"])
def create_competition():
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    body = body_json()
    name = req_str(body, "name")
    fmt = req_enum(body, "format", COMP_FORMATS)
    draw_size = None
    if fmt == "TOURNAMENT":
        if "draw_size" not in body or body["draw_size"] is None:
            verr("draw_size is required for TOURNAMENT")
        draw_size = req_int(body, "draw_size", 1)
        if not is_power_of_two(draw_size):
            verr("draw_size must be a power of two")
    else:
        if body.get("draw_size") is not None:
            ds = body["draw_size"]
            if not is_power_of_two(ds):
                verr("draw_size must be a power of two")
        draw_size = None
    entry_fee = opt_int(body, "entry_fee_cents", 0, 0)
    rec = base_record()
    rec.update({
        "name": name, "format": fmt, "draw_size": draw_size,
        "entry_fee_cents": entry_fee, "status": "REGISTRATION",
    })
    db.competitions[rec["id"]] = rec
    return success(clean(rec), "object", 201)


@app.route("/racquet/competitions/<competition_id>", methods=["GET"])
def get_competition(competition_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.competitions, competition_id)
    return success(clean(rec), "object", 200)


@app.route("/racquet/competitions", methods=["GET"])
def list_competitions():
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    recs = list(db.competitions.values())
    recs = filt(recs, "status", request.args.get("status"))
    recs = filt(recs, "format", request.args.get("format"))
    return list_response(recs)


def _active_participants(competition_id):
    ps = [p for p in db.participants.values()
          if p["competition_id"] == competition_id and p["status"] == "ACTIVE"]
    ps.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return ps


@app.route("/racquet/competitions/<competition_id>/start", methods=["POST"])
def start_competition(competition_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    comp = get_or_404(db.competitions, competition_id)
    if comp["status"] != "REGISTRATION":
        raise ApiError("ERR_INVALID_STATE", 409, "Competition is not in REGISTRATION")
    active = _active_participants(competition_id)
    if comp["format"] == "TOURNAMENT":
        ds = comp["draw_size"]
        if not is_power_of_two(ds) or ds != len(active):
            raise ApiError("ERR_INVALID_DRAW_SIZE", 409,
                           "draw_size must be a power of two equal to participant count")
        ordered = sorted(
            active,
            key=lambda p: (
                p["seed"] if p["seed"] is not None else float("inf"),
                p["created_at"], p["_seq"]))
        for i, p in enumerate(ordered, start=1):
            p["bracket_slot"] = i
    elif comp["format"] == "LADDER":
        for i, p in enumerate(active, start=1):
            p["ladder_rank"] = i
    comp["status"] = "IN_PROGRESS"
    touch(comp)
    return success(clean(comp), "object", 200)


@app.route("/racquet/competitions/<competition_id>/report", methods=["POST"])
def report_competition(competition_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    comp = get_or_404(db.competitions, competition_id)
    body = body_json()
    p1_id = body.get("player1_participant_id")
    p2_id = body.get("player2_participant_id")
    w_id = body.get("winner_participant_id")
    for pid in (p1_id, p2_id, w_id):
        if pid is not None and pid not in db.participants:
            raise ApiError("ERR_NOT_FOUND", 404, "Participant not found")
    p1 = req_str(body, "player1_participant_id")
    p2 = req_str(body, "player2_participant_id")
    w = req_str(body, "winner_participant_id")
    part1 = get_or_404(db.participants, p1)
    part2 = get_or_404(db.participants, p2)
    winner = get_or_404(db.participants, w)
    for p in (part1, part2, winner):
        if p["competition_id"] != competition_id:
            raise ApiError("ERR_NOT_FOUND", 404, "Participant not in competition")
    if comp["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Competition is not IN_PROGRESS")
    if w not in (p1, p2):
        verr("winner must be one of the two players")
    loser = part2 if w == p1 else part1
    winner["wins"] += 1
    loser["losses"] += 1
    if comp["format"] == "ROUND_ROBIN":
        winner["points"] += POINTS_WIN
    elif comp["format"] == "TOURNAMENT":
        loser["status"] = "ELIMINATED"
        touch(loser)
    elif comp["format"] == "LADDER":
        wr = winner["ladder_rank"]
        lr = loser["ladder_rank"]
        if wr is not None and lr is not None and wr > lr:
            for p in db.participants.values():
                if (p["competition_id"] == competition_id and p["ladder_rank"] is not None
                        and lr <= p["ladder_rank"] < wr):
                    p["ladder_rank"] += 1
            winner["ladder_rank"] = lr
    return success(clean(comp), "object", 200)


@app.route("/racquet/competitions/<competition_id>/close", methods=["POST"])
def close_competition(competition_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    comp = get_or_404(db.competitions, competition_id)
    if comp["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Competition is not IN_PROGRESS")
    comp["status"] = "COMPLETED"
    touch(comp)
    return success(clean(comp), "object", 200)


# =============================================================================
# PARTICIPANTS
# =============================================================================
@app.route("/racquet/participants", methods=["POST"])
def create_participant():
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    body = body_json()
    if role == "Member" and body.get("member_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only register themselves")
    comp_id = body.get("competition_id")
    member_id = body.get("member_id")
    if comp_id is not None:
        fk_exists_or_404(db.competitions, comp_id)
    if member_id is not None:
        fk_exists_or_404(db.members, member_id)
    comp_id = req_str(body, "competition_id")
    member_id = req_str(body, "member_id")
    seed = None
    if "seed" in body and body["seed"] is not None:
        seed = req_int(body, "seed")
    comp = get_or_404(db.competitions, comp_id)
    member = get_or_404(db.members, member_id)
    if comp["status"] != "REGISTRATION":
        raise ApiError("ERR_COMPETITION_NOT_OPEN", 409, "Competition is not open")
    for p in db.participants.values():
        if p["competition_id"] == comp_id and p["member_id"] == member_id:
            raise ApiError("ERR_DUPLICATE_PARTICIPANT", 409, "Duplicate participant")
    rec = base_record()
    rec.update({
        "competition_id": comp_id, "member_id": member_id, "seed": seed,
        "bracket_slot": None, "ladder_rank": None, "wins": 0, "losses": 0,
        "points": 0, "status": "ACTIVE",
    })
    db.participants[rec["id"]] = rec
    member["account_balance_cents"] += comp["entry_fee_cents"]
    return success(clean(rec), "object", 201)


@app.route("/racquet/participants/<participant_id>", methods=["GET"])
def get_participant(participant_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.participants, participant_id)
    return success(clean(rec), "object", 200)


@app.route("/racquet/participants", methods=["GET"])
def list_participants():
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    recs = list(db.participants.values())
    recs = filt(recs, "competition_id", request.args.get("competition_id"))
    recs = filt(recs, "member_id", request.args.get("member_id"))
    recs = filt(recs, "status", request.args.get("status"))
    return list_response(recs)


# =============================================================================
# STRINGING JOBS
# =============================================================================
@app.route("/racquet/stringing-jobs", methods=["POST"])
def create_stringing_job():
    uid, role = identity()
    require_roles(role, {"Member", "FrontDesk"})
    body = body_json()
    if role == "Member" and body.get("member_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only request for themselves")
    member_id = body.get("member_id")
    if member_id is not None:
        fk_exists_or_404(db.members, member_id)
    member_id = req_str(body, "member_id")
    racquet_label = req_str(body, "racquet_label")
    string_type = req_str(body, "string_type")
    tension = req_int(body, "tension", 1)
    price = req_int(body, "price_cents", 0)
    member = get_or_404(db.members, member_id)
    rec = base_record()
    rec.update({
        "member_id": member_id, "racquet_label": racquet_label,
        "string_type": string_type, "tension": tension, "price_cents": price,
        "status": "RECEIVED",
    })
    db.stringing_jobs[rec["id"]] = rec
    member["account_balance_cents"] += price
    return success(clean(rec), "object", 201)


@app.route("/racquet/stringing-jobs/<job_id>", methods=["GET"])
def get_stringing_job(job_id):
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    rec = get_or_404(db.stringing_jobs, job_id)
    return success(clean(rec), "object", 200)


@app.route("/racquet/stringing-jobs", methods=["GET"])
def list_stringing_jobs():
    _uid, role = identity()
    require_roles(role, {"Member", "Pro", "FrontDesk"})
    recs = list(db.stringing_jobs.values())
    recs = filt(recs, "member_id", request.args.get("member_id"))
    recs = filt(recs, "status", request.args.get("status"))
    return list_response(recs)


STRINGING_NEXT = {"RECEIVED": "IN_PROGRESS", "IN_PROGRESS": "READY", "READY": "PICKED_UP"}


@app.route("/racquet/stringing-jobs/<job_id>/advance", methods=["POST"])
def advance_stringing_job(job_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    job = get_or_404(db.stringing_jobs, job_id)
    if job["status"] not in STRINGING_NEXT:
        raise ApiError("ERR_INVALID_STATE", 409, "Job cannot be advanced")
    job["status"] = STRINGING_NEXT[job["status"]]
    touch(job)
    return success(clean(job), "object", 200)


@app.route("/racquet/stringing-jobs/<job_id>/cancel", methods=["POST"])
def cancel_stringing_job(job_id):
    _uid, role = identity()
    require_roles(role, {"FrontDesk"})
    job = get_or_404(db.stringing_jobs, job_id)
    if job["status"] not in ("RECEIVED", "IN_PROGRESS", "READY"):
        raise ApiError("ERR_INVALID_STATE", 409, "Job cannot be cancelled")
    job["status"] = "CANCELLED"
    member = db.members.get(job["member_id"])
    if member is not None:
        member["account_balance_cents"] -= job["price_cents"]
    touch(job)
    return success(clean(job), "object", 200)


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
