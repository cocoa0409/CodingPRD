"""
Bath Remodel API — single-file Flask implementation.

All state is in-memory and reconstructed on every process boot (the test harness
restarts the server via start.sh before every test). Nothing is seeded at startup.
"""

import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext

from flask import Flask, request, jsonify
from werkzeug.exceptions import HTTPException

# ---------------------------------------------------------------------------
# Constants (from PRD §3 / SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

ROLES = {"Customer", "Designer", "FinanceOfficer", "InstallCoordinator", "PlatformAdmin"}

CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

BASE_RATE_CENTS = {"SMOOTH_ACRYLIC": 3750, "TILE_LOOK_ACRYLIC": 5900, "STONE_LOOK_ACRYLIC": 8250}
WALL_SYSTEMS = set(BASE_RATE_CENTS.keys())
COLORS = {"WHITE", "BONE", "GREY", "SANDSTONE"}
ADDONS = {"NONE", "GRAB_BARS", "BARRIER_FREE_SHOWER", "WALK_IN_TUB"}
ADDON_PRICE_CENTS = {"NONE": 0, "GRAB_BARS": 29900, "BARRIER_FREE_SHOWER": 249900, "WALK_IN_TUB": 449900}
PERMIT_ADDONS = {"WALK_IN_TUB", "BARRIER_FREE_SHOWER"}
PROMO_PCT = {"SPRING750": Decimal("0.075")}

TIER1_SQFT = Decimal("40")
TIER2_SQFT = Decimal("40")
TIER2_FACTOR = Decimal("0.90")
TIER3_FACTOR = Decimal("0.80")

SURCHARGE_TIER_THRESHOLD = 500000
PERMIT_FEE_LOW = 15000
PERMIT_FEE_HIGH = 30000

DEPOSIT_PCT = Decimal("0.10")
DTI_MAX_RATIO = Decimal("0.50")
DTI_TIERS = [(Decimal("0.20"), 0), (Decimal("0.35"), 250), (Decimal("0.50"), 600)]
PLANS = {
    "PLAN_12_0": {"apr_bps": 0, "term_months": 12, "min": 100000, "max": 1500000},
    "PLAN_60_999": {"apr_bps": 999, "term_months": 60, "min": 300000, "max": 5000000},
    "PLAN_120_1299": {"apr_bps": 1299, "term_months": 120, "min": 500000, "max": 8000000},
}

REFERRAL_FLAT_CENTS = 50000
REFERRAL_PCT = Decimal("0.03")

BUFFER_MINUTES = 60
MIN_LEAD_DAYS = 3

BATHROOM_TYPES = {"FULL_BATH", "SHOWER_ONLY", "TUB_ONLY"}
DEFECT_TYPES = {"CRACK", "LEAK", "DISCOLORATION", "HARDWARE_FAILURE"}

ERROR_HTTP = {
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_VALIDATION": 422,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_DESIGNER_NOT_FOUND": 404,
    "ERR_CREW_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_PROJECT_INVALID_STATE": 409,
    "ERR_PROJECT_NOT_INSTALL_READY": 409,
    "ERR_QUOTE_INVALID_STATE": 409,
    "ERR_APPOINTMENT_INVALID_STATE": 409,
    "ERR_BOOKING_INVALID_STATE": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
    "ERR_REFERRAL_INVALID_STATE": 409,
    "ERR_FINANCING_NOT_REQUESTED": 409,
    "ERR_FINANCING_NOT_APPROVED": 409,
    "ERR_CREW_NOT_CERTIFIED": 409,
    "ERR_WARRANTY_NOT_ACTIVE": 409,
    "ERR_PERMIT_NOT_REQUIRED": 409,
    "ERR_DESIGNER_INACTIVE": 409,
    "ERR_CREW_INACTIVE": 409,
    "ERR_DESIGNER_SLOT_CONFLICT": 409,
    "ERR_CREW_AT_CAPACITY": 409,
    "ERR_INSTALL_LEAD_TIME": 409,
    "ERR_FINANCING_AMOUNT_MISMATCH": 422,
    "ERR_FINANCING_AMOUNT_EXCEEDS_MAX": 422,
    "ERR_FINANCING_AMOUNT_BELOW_MIN": 422,
    "ERR_DTI_EXCEEDED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store (reset on every boot)
# ---------------------------------------------------------------------------

class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.customers = {}
        self.designers = {}
        self.crews = {}
        self.projects = {}
        self.appointments = {}
        self.quotes = {}
        self.bookings = {}
        self.claims = {}
        self.referrals = {}
        self.clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


# ---------------------------------------------------------------------------
# Time / id helpers (all timestamps use the logical clock)
# ---------------------------------------------------------------------------

def now_iso():
    dt = db.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def gen_referral_code():
    while True:
        code = "REF-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not any(r["referral_code"] == code for r in db.referrals.values()):
            return code


def base_record(**fields):
    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def parse_iso(value):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", "Invalid datetime")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def round_half_up(d):
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_system_price(wall_system, area):
    rate = Decimal(BASE_RATE_CENTS[wall_system])
    a = Decimal(str(area))
    t1 = min(a, TIER1_SQFT)
    t2 = min(max(a - TIER1_SQFT, Decimal(0)), TIER2_SQFT)
    t3 = max(a - (TIER1_SQFT + TIER2_SQFT), Decimal(0))
    total = t1 * rate + t2 * rate * TIER2_FACTOR + t3 * rate * TIER3_FACTOR
    return round_half_up(total)


def compute_discount(system_price, addon_price, promo_code):
    if promo_code == "SPRING750":
        pct = PROMO_PCT["SPRING750"]
        d_system = round_half_up(Decimal(system_price) * pct)
        d_addon = round_half_up(Decimal(addon_price) * pct)
        return d_system + d_addon
    return 0


def compute_permit_surcharge(addon, net_price):
    if addon in PERMIT_ADDONS:
        return PERMIT_FEE_LOW if net_price <= SURCHARGE_TIER_THRESHOLD else PERMIT_FEE_HIGH
    return 0


def compute_apr_and_payment(plan_code, financed, income):
    """Returns (approved_apr_bps, monthly_payment_cents). Raises ERR_DTI_EXCEEDED."""
    plan = PLANS[plan_code]
    with localcontext() as ctx:
        ctx.prec = 50
        ratio = Decimal(financed) / Decimal(income)
        if ratio > DTI_MAX_RATIO:
            raise ApiError("ERR_DTI_EXCEEDED", "Debt-to-income ratio exceeds tolerance")
        surcharge_bps = None
        for max_ratio, bps in DTI_TIERS:
            if ratio <= max_ratio:
                surcharge_bps = bps
                break
        apr_bps = plan["apr_bps"] + surcharge_bps
        n = plan["term_months"]
        if apr_bps == 0:
            payment = round_half_up(Decimal(financed) / Decimal(n))
        else:
            r = Decimal(apr_bps) / Decimal(10000) / Decimal(12)
            p = (Decimal(1) + r) ** n
            payment = round_half_up(Decimal(financed) * r * p / (p - Decimal(1)))
    return apr_bps, payment


def compute_referral_reward(program_tier, accepted_total):
    if program_tier == "PREMIUM":
        return round_half_up(Decimal(accepted_total) * REFERRAL_PCT)
    return REFERRAL_FLAT_CENTS  # STANDARD


# ---------------------------------------------------------------------------
# Flask app + envelope
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.url_map.strict_slashes = False


def meta_base():
    return {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}


def respond(data, response_type="object", status=200, pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    if isinstance(e, HTTPException):
        return e
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth / body helpers
# ---------------------------------------------------------------------------

def get_actor():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_USER_CONTEXT", "Missing or invalid user context headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", "Role %s not permitted" % role)


def get_body():
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        return {}
    return b


def req_present(b, field):
    if field not in b or b[field] is None:
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)


def v_string(b, field, required=True):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
        return None
    if not isinstance(b[field], str):
        raise ApiError("ERR_VALIDATION", "Field %s must be a string" % field)
    return b[field]


def v_enum(b, field, allowed, required=True, default=None):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
        return default
    if b[field] not in allowed:
        raise ApiError("ERR_VALIDATION", "Field %s must be one of %s" % (field, sorted(allowed)))
    return b[field]


def v_int(b, field, required=True, min_value=None):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
        return None
    v = b[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer" % field)
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", "Field %s must be >= %s" % (field, min_value))
    return v


def v_pos_number(b, field, required=True):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
        return None
    v = b[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", "Field %s must be a number" % field)
    if v <= 0:
        raise ApiError("ERR_VALIDATION", "Field %s must be positive" % field)
    return v


def v_bool(b, field, default):
    if field not in b or b[field] is None:
        return default
    if not isinstance(b[field], bool):
        raise ApiError("ERR_VALIDATION", "Field %s must be a boolean" % field)
    return b[field]


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------

def find(store, rid, err):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(err)
    return rec


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------

def check_customer_owner(project, uid):
    if project.get("customer_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer is not the owner")


def check_designer_owner(project, uid):
    if project.get("designer_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Designer is not assigned to this project")


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------

def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit out of range")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset out of range")
    return limit, offset


def list_response(store, filters):
    limit, offset = get_pagination()
    items = [r for r in store.values() if all(r.get(k) == v for k, v in filters.items())]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return respond([serialize(r) for r in page], "array", 200, pagination)


def collect_query_filters(mapping):
    """mapping: {query_param: record_field}. Returns filters for params present."""
    filters = {}
    for param, field in mapping.items():
        val = request.args.get(param)
        if val is not None:
            filters[field] = val
    return filters


# ---------------------------------------------------------------------------
# Shared side-effect helpers
# ---------------------------------------------------------------------------

def supersede_quote(q):
    q["status"] = "SUPERSEDED"
    if q["financing_status"] == "REQUESTED":
        q["financing_status"] = "DECLINED"
    touch(q)


def void_referral(referral):
    was_rewarded = referral["status"] == "REWARDED"
    referral["status"] = "VOID"
    touch(referral)
    if was_rewarded:
        cust = db.customers.get(referral["referrer_customer_id"])
        if cust is not None:
            cust["referral_credit_cents"] = max(0, cust["referral_credit_cents"] - referral["reward_cents"])
            touch(cust)


# ===========================================================================
# Customer
# ===========================================================================

@app.route("/customers", methods=["POST"])
def create_customer():
    uid, role = get_actor()
    require_role(role, {"PlatformAdmin", "InstallCoordinator"})
    b = get_body()
    full_name = v_string(b, "full_name")
    email = v_string(b, "email")
    phone = v_string(b, "phone")
    street_address = v_string(b, "street_address")
    city = v_string(b, "city")
    state_code = v_string(b, "state_code")
    postal_code = v_string(b, "postal_code")
    referral_code_used = v_string(b, "referral_code_used", required=False)

    cust = base_record(
        full_name=full_name,
        email=email,
        phone=phone,
        street_address=street_address,
        city=city,
        state_code=state_code,
        postal_code=postal_code,
        referral_code_used=referral_code_used,
        referral_credit_cents=0,
    )
    db.customers[cust["id"]] = cust

    if referral_code_used:
        for r in db.referrals.values():
            if r["referral_code"] == referral_code_used and r["status"] == "ISSUED":
                r["referred_customer_id"] = cust["id"]
                r["status"] = "REGISTERED"
                touch(r)
                break

    return respond(serialize(cust), "object", 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    get_actor()
    rec = find(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    return respond(serialize(rec), "object", 200)


# ===========================================================================
# Designer
# ===========================================================================

@app.route("/designers", methods=["POST"])
def create_designer():
    uid, role = get_actor()
    require_role(role, {"PlatformAdmin"})
    b = get_body()
    full_name = v_string(b, "full_name")
    email = v_string(b, "email")
    region_state_code = v_string(b, "region_state_code")
    active = v_bool(b, "active", True)

    rec = base_record(
        full_name=full_name,
        email=email,
        region_state_code=region_state_code,
        active=active,
    )
    db.designers[rec["id"]] = rec
    return respond(serialize(rec), "object", 201)


@app.route("/designers/<did>", methods=["GET"])
def get_designer(did):
    get_actor()
    rec = find(db.designers, did, "ERR_DESIGNER_NOT_FOUND")
    return respond(serialize(rec), "object", 200)


# ===========================================================================
# Crew
# ===========================================================================

@app.route("/crews", methods=["POST"])
def create_crew():
    uid, role = get_actor()
    require_role(role, {"PlatformAdmin"})
    b = get_body()
    crew_name = v_string(b, "crew_name")
    home_state_code = v_string(b, "home_state_code")
    max_installs_per_day = v_int(b, "max_installs_per_day", min_value=1)
    accessibility_certified = v_bool(b, "accessibility_certified", False)
    active = v_bool(b, "active", True)

    rec = base_record(
        crew_name=crew_name,
        home_state_code=home_state_code,
        max_installs_per_day=max_installs_per_day,
        accessibility_certified=accessibility_certified,
        active=active,
    )
    db.crews[rec["id"]] = rec
    return respond(serialize(rec), "object", 201)


@app.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    get_actor()
    rec = find(db.crews, cid, "ERR_CREW_NOT_FOUND")
    return respond(serialize(rec), "object", 200)


# ===========================================================================
# Project
# ===========================================================================

@app.route("/projects", methods=["POST"])
def create_project():
    uid, role = get_actor()
    require_role(role, {"InstallCoordinator", "PlatformAdmin", "Designer"})
    b = get_body()
    customer_id = v_string(b, "customer_id")
    state_code = v_string(b, "state_code")
    bathroom_type = v_enum(b, "bathroom_type", BATHROOM_TYPES)

    find(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")

    rec = base_record(
        customer_id=customer_id,
        designer_id=None,
        state_code=state_code,
        bathroom_type=bathroom_type,
        status="LEAD",
        measured_wall_area_sqft=None,
        permit_required=None,
        requires_accessible_crew=None,
        permit_status="NOT_APPLICABLE",
        accepted_quote_total_cents=None,
        warranty_status="NONE",
        warranty_issued_date=None,
        cancel_reason=None,
    )
    db.projects[rec["id"]] = rec
    return respond(serialize(rec), "object", 201)


@app.route("/projects", methods=["GET"])
def list_projects():
    get_actor()
    filters = collect_query_filters({"customer_id": "customer_id", "designer_id": "designer_id", "status": "status"})
    return list_response(db.projects, filters)


@app.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    get_actor()
    rec = find(db.projects, pid, "ERR_PROJECT_NOT_FOUND")
    return respond(serialize(rec), "object", 200)


@app.route("/projects/<pid>/resolve-permit", methods=["POST"])
def resolve_permit(pid):
    uid, role = get_actor()
    require_role(role, {"InstallCoordinator"})
    b = get_body()
    outcome = v_enum(b, "outcome", {"APPROVED", "REJECTED"})

    project = find(db.projects, pid, "ERR_PROJECT_NOT_FOUND")

    # permit_required gate is on the project's own flag (checked before the
    # PERMIT_PENDING state check so ERR_PERMIT_NOT_REQUIRED is reachable).
    if project.get("permit_required") is not True:
        raise ApiError("ERR_PERMIT_NOT_REQUIRED", "Project does not require a permit")
    if project["status"] != "PERMIT_PENDING":
        raise ApiError("ERR_PROJECT_INVALID_STATE", "Project is not PERMIT_PENDING")

    if outcome == "APPROVED":
        project["permit_status"] = "APPROVED"
        project["status"] = "INSTALL_READY"
    else:  # REJECTED
        project["permit_status"] = "REJECTED"
        # stays PERMIT_PENDING
    touch(project)
    return respond(serialize(project), "object", 200)


@app.route("/projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    uid, role = get_actor()
    require_role(role, {"Customer", "InstallCoordinator", "PlatformAdmin"})
    b = get_body()

    project = find(db.projects, pid, "ERR_PROJECT_NOT_FOUND")

    if role == "Customer":
        check_customer_owner(project, uid)

    if project["status"] in ("INSTALLED", "CANCELLED"):
        raise ApiError("ERR_PROJECT_INVALID_STATE", "Project cannot be cancelled")

    cancel_reason = b.get("cancel_reason")
    project["cancel_reason"] = cancel_reason
    project["status"] = "CANCELLED"
    touch(project)

    # Cascade: appointments
    for appt in db.appointments.values():
        if appt["project_id"] == pid and appt["status"] == "SCHEDULED":
            appt["status"] = "CANCELLED"
            touch(appt)
    # Cascade: bookings
    for bk in db.bookings.values():
        if bk["project_id"] == pid and bk["status"] == "BOOKED":
            bk["status"] = "CANCELLED"
            touch(bk)
    # Cascade: quotes
    for q in db.quotes.values():
        if q["project_id"] == pid and q["status"] in ("DRAFT", "PRESENTED", "REVISION_REQUESTED"):
            supersede_quote(q)
    # Cascade: rewarded referrals for this project
    for r in db.referrals.values():
        if r.get("referred_project_id") == pid and r["status"] == "REWARDED":
            void_referral(r)

    return respond(serialize(project), "object", 200)


# ===========================================================================
# DesignAppointment
# ===========================================================================

@app.route("/design-appointments", methods=["POST"])
def create_appointment():
    uid, role = get_actor()
    require_role(role, {"Customer", "InstallCoordinator"})
    b = get_body()
    project_id = v_string(b, "project_id")
    designer_id = v_string(b, "designer_id")
    scheduled_start = v_string(b, "scheduled_start")
    scheduled_end = v_string(b, "scheduled_end")
    start_dt = parse_iso(scheduled_start)
    end_dt = parse_iso(scheduled_end)
    if end_dt <= start_dt:
        raise ApiError("ERR_VALIDATION", "scheduled_end must be after scheduled_start")

    project = find(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    designer = find(db.designers, designer_id, "ERR_DESIGNER_NOT_FOUND")

    if role == "Customer":
        check_customer_owner(project, uid)

    if project["status"] != "LEAD":
        raise ApiError("ERR_PROJECT_INVALID_STATE", "Project must be LEAD to book a design visit")

    if not designer["active"]:
        raise ApiError("ERR_DESIGNER_INACTIVE", "Designer is not active")

    # Temporal: overlap + 60-minute buffer against this designer's SCHEDULED visits
    buf = timedelta(minutes=BUFFER_MINUTES)
    for appt in db.appointments.values():
        if appt["designer_id"] == designer_id and appt["status"] == "SCHEDULED":
            es = parse_iso(appt["scheduled_start"])
            ee = parse_iso(appt["scheduled_end"])
            if start_dt < (ee + buf) and es < (end_dt + buf):
                raise ApiError("ERR_DESIGNER_SLOT_CONFLICT", "Designer slot conflict")

    rec = base_record(
        project_id=project_id,
        designer_id=designer_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        measured_wall_area_sqft=None,
        status="SCHEDULED",
    )
    db.appointments[rec["id"]] = rec

    project["designer_id"] = designer_id
    project["status"] = "DESIGN_SCHEDULED"
    touch(project)

    return respond(serialize(rec), "object", 201)


@app.route("/design-appointments", methods=["GET"])
def list_appointments():
    get_actor()
    filters = collect_query_filters({"project_id": "project_id", "designer_id": "designer_id", "status": "status"})
    return list_response(db.appointments, filters)


@app.route("/design-appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    get_actor()
    rec = find(db.appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    return respond(serialize(rec), "object", 200)


@app.route("/design-appointments/<aid>/complete", methods=["POST"])
def complete_appointment(aid):
    uid, role = get_actor()
    require_role(role, {"Designer"})
    b = get_body()
    measured = v_pos_number(b, "measured_wall_area_sqft")

    appt = find(db.appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    project = db.projects.get(appt["project_id"])

    if project is None or project.get("designer_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Designer is not assigned to this project")

    if appt["status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_INVALID_STATE", "Appointment is not SCHEDULED")

    appt["status"] = "COMPLETED"
    appt["measured_wall_area_sqft"] = measured
    touch(appt)

    project["measured_wall_area_sqft"] = measured
    project["status"] = "DESIGN_COMPLETE"
    touch(project)

    return respond(serialize(appt), "object", 200)


@app.route("/design-appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    uid, role = get_actor()
    require_role(role, {"Customer", "InstallCoordinator"})

    appt = find(db.appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    project = db.projects.get(appt["project_id"])

    if role == "Customer":
        if project is None or project.get("customer_id") != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer is not the owner")

    if appt["status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_INVALID_STATE", "Appointment is not SCHEDULED")

    appt["status"] = "CANCELLED"
    touch(appt)
    return respond(serialize(appt), "object", 200)


# ===========================================================================
# Quote
# ===========================================================================

@app.route("/quotes", methods=["POST"])
def create_quote():
    uid, role = get_actor()
    require_role(role, {"Designer"})
    b = get_body()

    project_id = v_string(b, "project_id")
    wall_system = v_enum(b, "wall_system", WALL_SYSTEMS)
    color = v_enum(b, "color", COLORS)
    accessibility_addon = v_enum(b, "accessibility_addon", ADDONS, required=False, default="NONE")
    promo_code = v_string(b, "promo_code", required=False)
    expected_project_version = v_int(b, "expected_project_version")

    financing_plan_code = None
    requested_amount_cents = None
    stated_annual_income_cents = None
    if b.get("financing_plan_code") is not None:
        financing_plan_code = v_enum(b, "financing_plan_code", set(PLANS.keys()))
        requested_amount_cents = v_int(b, "requested_amount_cents", min_value=1)
        stated_annual_income_cents = v_int(b, "stated_annual_income_cents", min_value=1)

    # Existence
    project = find(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")

    # Ownership (Designer must be the project's assigned designer)
    check_designer_owner(project, uid)

    # OCC
    if expected_project_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION", "Project version is stale")

    # State
    if project["status"] != "DESIGN_COMPLETE":
        raise ApiError("ERR_PROJECT_INVALID_STATE", "Project must be DESIGN_COMPLETE to quote")

    # Pricing
    area = project["measured_wall_area_sqft"]
    system_price_cents = compute_system_price(wall_system, area)
    addon_price_cents = ADDON_PRICE_CENTS[accessibility_addon]
    discount_cents = compute_discount(system_price_cents, addon_price_cents, promo_code)
    net_price_cents = system_price_cents + addon_price_cents - discount_cents

    deposit_cents = None
    financed_amount_cents = None
    financing_status = "NONE"
    if financing_plan_code is not None:
        financing_status = "REQUESTED"
        deposit_cents = round_half_up(Decimal(net_price_cents) * DEPOSIT_PCT)
        financed_amount_cents = net_price_cents - deposit_cents
        # Financing amount coherence (priority 10)
        if requested_amount_cents != financed_amount_cents:
            raise ApiError("ERR_FINANCING_AMOUNT_MISMATCH", "requested_amount_cents must equal financed amount")
        # Financing bounds (priority 11)
        plan = PLANS[financing_plan_code]
        if requested_amount_cents < plan["min"]:
            raise ApiError("ERR_FINANCING_AMOUNT_BELOW_MIN", "Requested amount below plan minimum")
        if requested_amount_cents > plan["max"]:
            raise ApiError("ERR_FINANCING_AMOUNT_EXCEEDS_MAX", "Requested amount above plan maximum")

    quote = base_record(
        project_id=project_id,
        wall_system=wall_system,
        color=color,
        accessibility_addon=accessibility_addon,
        wall_area_sqft=area,
        promo_code=promo_code,
        system_price_cents=system_price_cents,
        addon_price_cents=addon_price_cents,
        discount_cents=discount_cents,
        net_price_cents=net_price_cents,
        permit_surcharge_cents=None,
        final_total_cents=None,
        status="DRAFT",
        financing_plan_code=financing_plan_code,
        financing_status=financing_status,
        requested_amount_cents=requested_amount_cents,
        stated_annual_income_cents=stated_annual_income_cents,
        deposit_cents=deposit_cents,
        financed_amount_cents=financed_amount_cents,
        approved_apr_bps=None,
        monthly_payment_cents=None,
        revision_round=0,
    )
    db.quotes[quote["id"]] = quote

    # Supersede sibling active quotes on this project
    for q in db.quotes.values():
        if q["id"] != quote["id"] and q["project_id"] == project_id and q["status"] in ("DRAFT", "PRESENTED", "REVISION_REQUESTED"):
            supersede_quote(q)

    # Creating the quote advances the project's version by one
    touch(project)

    return respond(serialize(quote), "object", 201)


@app.route("/quotes", methods=["GET"])
def list_quotes():
    get_actor()
    filters = collect_query_filters({"project_id": "project_id", "status": "status"})
    return list_response(db.quotes, filters)


@app.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    get_actor()
    rec = find(db.quotes, qid, "ERR_QUOTE_NOT_FOUND")
    return respond(serialize(rec), "object", 200)


@app.route("/quotes/<qid>/present", methods=["POST"])
def present_quote(qid):
    uid, role = get_actor()
    require_role(role, {"Designer"})

    quote = find(db.quotes, qid, "ERR_QUOTE_NOT_FOUND")
    project = db.projects.get(quote["project_id"])

    if project is None or project.get("designer_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Designer is not assigned to this project")

    if quote["status"] != "DRAFT":
        raise ApiError("ERR_QUOTE_INVALID_STATE", "Quote is not DRAFT")

    # Recompute the priced fields at presentation time
    area = quote["wall_area_sqft"]
    quote["system_price_cents"] = compute_system_price(quote["wall_system"], area)
    quote["addon_price_cents"] = ADDON_PRICE_CENTS[quote["accessibility_addon"]]
    quote["discount_cents"] = compute_discount(quote["system_price_cents"], quote["addon_price_cents"], quote["promo_code"])
    quote["net_price_cents"] = quote["system_price_cents"] + quote["addon_price_cents"] - quote["discount_cents"]
    quote["status"] = "PRESENTED"
    touch(quote)

    project["status"] = "QUOTED"
    touch(project)

    return respond(serialize(quote), "object", 200)


@app.route("/quotes/<qid>/request-revision", methods=["POST"])
def request_revision(qid):
    uid, role = get_actor()
    require_role(role, {"Customer"})

    quote = find(db.quotes, qid, "ERR_QUOTE_NOT_FOUND")
    project = db.projects.get(quote["project_id"])

    if project is None or project.get("customer_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer is not the owner")

    if quote["status"] != "PRESENTED":
        raise ApiError("ERR_QUOTE_INVALID_STATE", "Quote is not PRESENTED")

    quote["status"] = "REVISION_REQUESTED"
    quote["revision_round"] += 1
    touch(quote)

    project["status"] = "DESIGN_COMPLETE"
    touch(project)

    return respond(serialize(quote), "object", 200)


@app.route("/quotes/<qid>/finance-decide", methods=["POST"])
def finance_decide(qid):
    uid, role = get_actor()
    require_role(role, {"FinanceOfficer"})
    b = get_body()
    decision = v_enum(b, "decision", {"APPROVE", "DECLINE"})

    quote = find(db.quotes, qid, "ERR_QUOTE_NOT_FOUND")

    if quote["financing_status"] != "REQUESTED":
        raise ApiError("ERR_FINANCING_NOT_REQUESTED", "Financing is not REQUESTED")

    if decision == "DECLINE":
        quote["financing_status"] = "DECLINED"
        touch(quote)
        return respond(serialize(quote), "object", 200)

    # APPROVE
    apr_bps, payment = compute_apr_and_payment(
        quote["financing_plan_code"],
        quote["financed_amount_cents"],
        quote["stated_annual_income_cents"],
    )
    quote["approved_apr_bps"] = apr_bps
    quote["monthly_payment_cents"] = payment
    quote["financing_status"] = "APPROVED"
    touch(quote)
    return respond(serialize(quote), "object", 200)


@app.route("/quotes/<qid>/accept", methods=["POST"])
def accept_quote(qid):
    uid, role = get_actor()
    require_role(role, {"Customer"})

    quote = find(db.quotes, qid, "ERR_QUOTE_NOT_FOUND")
    project = db.projects.get(quote["project_id"])

    if project is None or project.get("customer_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer is not the owner")

    if quote["status"] != "PRESENTED":
        raise ApiError("ERR_QUOTE_INVALID_STATE", "Quote is not PRESENTED")

    if quote["financing_status"] not in ("NONE", "APPROVED"):
        raise ApiError("ERR_FINANCING_NOT_APPROVED", "Financing is not approved")

    # Final total (permit surcharge tiered on net price, evaluated first)
    permit_required = quote["accessibility_addon"] in PERMIT_ADDONS
    surcharge = compute_permit_surcharge(quote["accessibility_addon"], quote["net_price_cents"])
    quote["permit_surcharge_cents"] = surcharge
    quote["final_total_cents"] = quote["net_price_cents"] + surcharge
    quote["status"] = "ACCEPTED"
    touch(quote)

    # Project transitions
    project["permit_required"] = permit_required
    project["requires_accessible_crew"] = permit_required
    project["accepted_quote_total_cents"] = quote["final_total_cents"]
    if permit_required:
        project["status"] = "PERMIT_PENDING"
        project["permit_status"] = "PENDING"
    else:
        project["status"] = "INSTALL_READY"
        # permit_status stays NOT_APPLICABLE
    touch(project)

    # Supersede sibling quotes
    for q in db.quotes.values():
        if q["id"] != quote["id"] and q["project_id"] == project["id"] and q["status"] in ("DRAFT", "PRESENTED", "REVISION_REQUESTED"):
            supersede_quote(q)

    # Referral reward (REGISTERED referral for this customer/project)
    for r in db.referrals.values():
        if r["status"] == "REGISTERED" and r.get("referred_customer_id") == project["customer_id"]:
            r["referred_project_id"] = project["id"]
            r["reward_cents"] = compute_referral_reward(r["program_tier"], project["accepted_quote_total_cents"])
            r["status"] = "REWARDED"
            touch(r)
            referrer = db.customers.get(r["referrer_customer_id"])
            if referrer is not None:
                referrer["referral_credit_cents"] += r["reward_cents"]
                touch(referrer)

    return respond(serialize(quote), "object", 200)


# ===========================================================================
# InstallBooking
# ===========================================================================

@app.route("/install-bookings", methods=["POST"])
def create_booking():
    uid, role = get_actor()
    require_role(role, {"InstallCoordinator"})
    b = get_body()
    project_id = v_string(b, "project_id")
    crew_id = v_string(b, "crew_id")
    install_date_raw = v_string(b, "install_date")
    install_dt = parse_iso(install_date_raw)
    install_date = install_dt.date()

    project = find(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    crew = find(db.crews, crew_id, "ERR_CREW_NOT_FOUND")

    if project["status"] != "INSTALL_READY":
        raise ApiError("ERR_PROJECT_NOT_INSTALL_READY", "Project is not INSTALL_READY")

    if not crew["active"]:
        raise ApiError("ERR_CREW_INACTIVE", "Crew is not active")

    if project.get("requires_accessible_crew") and not crew["accessibility_certified"]:
        raise ApiError("ERR_CREW_NOT_CERTIFIED", "Crew is not accessibility certified")

    # Temporal: minimum lead time
    min_date = db.clock.date() + timedelta(days=MIN_LEAD_DAYS)
    if install_date < min_date:
        raise ApiError("ERR_INSTALL_LEAD_TIME", "Install date does not meet minimum lead time")

    # Temporal: crew per-date capacity
    bucket = install_date.isoformat()
    booked = sum(
        1 for bk in db.bookings.values()
        if bk["crew_id"] == crew_id and bk["_bucket"] == bucket and bk["status"] == "BOOKED"
    )
    if booked >= crew["max_installs_per_day"]:
        raise ApiError("ERR_CREW_AT_CAPACITY", "Crew is at capacity for that date")

    rec = base_record(
        project_id=project_id,
        crew_id=crew_id,
        install_date=install_date_raw,
        status="BOOKED",
        completed_at=None,
    )
    rec["_bucket"] = bucket
    db.bookings[rec["id"]] = rec

    project["status"] = "INSTALL_SCHEDULED"
    touch(project)

    return respond(serialize(rec), "object", 201)


@app.route("/install-bookings", methods=["GET"])
def list_bookings():
    get_actor()
    filters = collect_query_filters({"project_id": "project_id", "crew_id": "crew_id", "status": "status"})
    return list_response(db.bookings, filters)


@app.route("/install-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    get_actor()
    rec = find(db.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    return respond(serialize(rec), "object", 200)


@app.route("/install-bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    uid, role = get_actor()
    require_role(role, {"InstallCoordinator"})

    bk = find(db.bookings, bid, "ERR_BOOKING_NOT_FOUND")

    if bk["status"] != "BOOKED":
        raise ApiError("ERR_BOOKING_INVALID_STATE", "Booking is not BOOKED")

    bk["status"] = "COMPLETED"
    bk["completed_at"] = now_iso()
    touch(bk)

    project = db.projects.get(bk["project_id"])
    if project is not None:
        project["status"] = "INSTALLED"
        project["warranty_status"] = "ACTIVE"
        project["warranty_issued_date"] = now_iso()
        touch(project)

    return respond(serialize(bk), "object", 200)


@app.route("/install-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = get_actor()
    require_role(role, {"InstallCoordinator", "Customer"})

    bk = find(db.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    project = db.projects.get(bk["project_id"])

    if role == "Customer":
        if project is None or project.get("customer_id") != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer is not the owner")

    if bk["status"] != "BOOKED":
        raise ApiError("ERR_BOOKING_INVALID_STATE", "Booking is not BOOKED")

    bk["status"] = "CANCELLED"
    touch(bk)

    if project is not None and project["status"] == "INSTALL_SCHEDULED":
        project["status"] = "INSTALL_READY"
        touch(project)

    return respond(serialize(bk), "object", 200)


# ===========================================================================
# WarrantyClaim
# ===========================================================================

@app.route("/warranty-claims", methods=["POST"])
def create_claim():
    uid, role = get_actor()
    require_role(role, {"Customer"})
    b = get_body()
    project_id = v_string(b, "project_id")
    defect_type = v_enum(b, "defect_type", DEFECT_TYPES)
    description = v_string(b, "description")

    project = find(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")

    check_customer_owner(project, uid)

    if project["warranty_status"] != "ACTIVE":
        raise ApiError("ERR_WARRANTY_NOT_ACTIVE", "Project warranty is not active")

    rec = base_record(
        project_id=project_id,
        defect_type=defect_type,
        description=description,
        status="SUBMITTED",
        resolution=None,
        review_notes=None,
    )
    db.claims[rec["id"]] = rec
    return respond(serialize(rec), "object", 201)


@app.route("/warranty-claims", methods=["GET"])
def list_claims():
    get_actor()
    filters = collect_query_filters({"project_id": "project_id", "status": "status"})
    return list_response(db.claims, filters)


@app.route("/warranty-claims/<cid>", methods=["GET"])
def get_claim(cid):
    get_actor()
    rec = find(db.claims, cid, "ERR_CLAIM_NOT_FOUND")
    return respond(serialize(rec), "object", 200)


@app.route("/warranty-claims/<cid>/decide", methods=["POST"])
def decide_claim(cid):
    uid, role = get_actor()
    require_role(role, {"InstallCoordinator"})
    b = get_body()
    decision = v_enum(b, "decision", {"APPROVE", "REJECT"})
    review_notes = v_string(b, "review_notes", required=False)
    resolution = None
    if decision == "APPROVE":
        resolution = v_enum(b, "resolution", {"REPAIR", "REPLACE"})

    claim = find(db.claims, cid, "ERR_CLAIM_NOT_FOUND")

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE", "Claim is not SUBMITTED")

    if decision == "APPROVE":
        claim["status"] = "APPROVED"
        claim["resolution"] = resolution
        claim["review_notes"] = review_notes
    else:  # REJECT
        claim["status"] = "REJECTED"
        claim["resolution"] = "DENIED"
        claim["review_notes"] = review_notes
    touch(claim)
    return respond(serialize(claim), "object", 200)


# ===========================================================================
# Referral
# ===========================================================================

@app.route("/referrals", methods=["POST"])
def create_referral():
    uid, role = get_actor()
    require_role(role, {"Customer", "PlatformAdmin"})
    b = get_body()
    referrer_customer_id = v_string(b, "referrer_customer_id")
    program_tier = v_enum(b, "program_tier", {"STANDARD", "PREMIUM"}, required=False, default="STANDARD")

    find(db.customers, referrer_customer_id, "ERR_CUSTOMER_NOT_FOUND")

    if role == "Customer" and referrer_customer_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer may only issue referrals for themselves")

    rec = base_record(
        referrer_customer_id=referrer_customer_id,
        referred_customer_id=None,
        referred_project_id=None,
        referral_code=gen_referral_code(),
        program_tier=program_tier,
        status="ISSUED",
        reward_cents=0,
    )
    db.referrals[rec["id"]] = rec
    return respond(serialize(rec), "object", 201)


@app.route("/referrals", methods=["GET"])
def list_referrals():
    get_actor()
    filters = collect_query_filters({
        "referrer_customer_id": "referrer_customer_id",
        "referred_customer_id": "referred_customer_id",
        "referred_project_id": "referred_project_id",
        "status": "status",
    })
    return list_response(db.referrals, filters)


@app.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    get_actor()
    rec = find(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    return respond(serialize(rec), "object", 200)


@app.route("/referrals/<rid>/void", methods=["POST"])
def void_referral_endpoint(rid):
    uid, role = get_actor()
    require_role(role, {"PlatformAdmin", "InstallCoordinator"})

    referral = find(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")

    if referral["status"] == "VOID":
        raise ApiError("ERR_REFERRAL_INVALID_STATE", "Referral is already VOID")

    void_referral(referral)
    return respond(serialize(referral), "object", 200)


# ===========================================================================
# Logical clock
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = get_actor()
    require_role(role, {"PlatformAdmin"})
    b = get_body()
    to_iso8601 = v_string(b, "to_iso8601")
    db.clock = parse_iso(to_iso8601)
    return respond({}, "object", 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
