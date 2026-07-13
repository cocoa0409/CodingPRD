import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
ROLES = {"Customer", "Helper", "Dispatcher", "Admin"}
ALL_ROLES = ROLES

CREW_SURCHARGE_THRESHOLD = 3
SERVICE_FEE_PCT = Decimal("0.15")
ADDON_TAX_PCT = Decimal("0.085")
ON_TIME_BONUS_PCT = Decimal("0.05")
CANCEL_FEE_PCT = Decimal("0.20")
CANCELLATION_FREE_WINDOW_HOURS = 24
BOOKING_WINDOW_HOURS = 48
TRAVEL_BUFFER = timedelta(minutes=60)
RATING_SUSPEND_THRESHOLD = 2.0

ACTIVE_COUNT_STATES = {"ASSIGNED", "CHECKED_IN", "CHECKED_OUT"}

CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# =============================================================================
# In-memory storage (wiped on every process start)
# =============================================================================
customers = {}
helpers = {}
rate_cards = {}
insurance_policies = {}
trucks = {}
jobs = {}
add_ons = {}
quotes = {}
assignments = {}
claims = {}
ratings = {}
payouts = {}

CLOCK = CLOCK_DEFAULT
_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# =============================================================================
# Time helpers
# =============================================================================
def now_iso():
    c = CLOCK
    return c.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (c.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_INVALID_REQUEST", 422, "bad datetime")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 422, "bad datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_weekend(window_start):
    return parse_dt(window_start).weekday() in (5, 6)


# =============================================================================
# Money helpers
# =============================================================================
def D(x):
    return Decimal(str(x))


def rhu(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# =============================================================================
# Entity helpers
# =============================================================================
def serialize(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def new_entity(store, fields, versioned=True):
    eid = str(uuid.uuid4())
    now = now_iso()
    ent = dict(fields)
    ent["id"] = eid
    ent["created_at"] = now
    if versioned:
        ent["updated_at"] = now
        ent["version"] = 1
    ent["_seq"] = next_seq()
    store[eid] = ent
    return ent


def touch(ent):
    ent["updated_at"] = now_iso()
    ent["version"] = ent.get("version", 1) + 1


# =============================================================================
# Response envelope
# =============================================================================
def make_meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok_object(data, code=200):
    body = {"meta": make_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def ok_array(items, limit, offset, total):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    body = {"meta": make_meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


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
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# =============================================================================
# Request helpers
# =============================================================================
def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid credentials")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


def get_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: %s" % f)


def lookup(store, eid):
    ent = store.get(eid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return ent


def get_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(store, filter_keys):
    items = list(store.values())
    for key in filter_keys:
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if str(e.get(key)) == val]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = [serialize(e) for e in items[offset:offset + limit]]
    return ok_array(page, limit, offset, total)


# =============================================================================
# Derived-field recomputation
# =============================================================================
def recompute_helper(hid):
    h = helpers.get(hid)
    if h is None:
        return
    hasgs = [a for a in assignments.values() if a["helper_id"] == hid]
    h["active_assignment_count"] = sum(1 for a in hasgs if a["status"] in ACTIVE_COUNT_STATES)
    h["no_show_count"] = sum(1 for a in hasgs if a["status"] == "NO_SHOW")
    hrs = [r for r in ratings.values() if r["helper_id"] == hid]
    h["rating_count"] = len(hrs)
    if hrs:
        total_stars = sum(r["stars"] for r in hrs)
        h["rating_avg"] = rhu2(D(total_stars) / D(len(hrs)))
    else:
        h["rating_avg"] = 0
    hpays = [p for p in payouts.values() if p["helper_id"] == hid and p["status"] == "RELEASED"]
    h["lifetime_payout_cents"] = sum(p["total_payout_cents"] for p in hpays)
    touch(h)


def recompute_customer_wallet(cid):
    c = customers.get(cid)
    if c is None:
        return
    total = 0
    for cl in claims.values():
        if cl["status"] != "APPROVED":
            continue
        job = jobs.get(cl["job_id"])
        if job and job["customer_id"] == cid and cl.get("insurance_covered_cents"):
            total += cl["insurance_covered_cents"]
    c["wallet_credit_cents"] = total
    touch(c)


def suspend_helper(hid):
    h = helpers[hid]
    h["vetting_status"] = "SUSPENDED"
    for a in assignments.values():
        if a["helper_id"] == hid and a["status"] == "ASSIGNED":
            a["status"] = "RELEASED"
            touch(a)
    recompute_helper(hid)
    touch(h)


# =============================================================================
# Calculation: job_charge
# =============================================================================
def job_addons(job_id):
    return [a for a in add_ons.values() if a["job_id"] == job_id]


def compute_job_charge(job, rate_card, hours_source):
    billable = max(D(hours_source), D(rate_card["min_billable_hours"]))
    base_raw = rhu(D(rate_card["base_hourly_rate_cents"]) * D(job["crew_size"]) * billable)
    if job["crew_size"] >= CREW_SURCHARGE_THRESHOLD:
        base_labor = rhu(D(base_raw) * (Decimal("1") + D(rate_card["crew_surcharge_pct"])))
    else:
        base_labor = base_raw
    truck_fee = rate_card["truck_fee_cents"] if job["truck_required"] else 0
    addons_total = sum(a["line_total_cents"] for a in job_addons(job["id"]))
    subtotal = base_labor + truck_fee + addons_total
    if is_weekend(job["window_start"]):
        surge = D(rate_card["peak_surge_multiplier"])
        surge_out = float(rate_card["peak_surge_multiplier"])
    else:
        surge = Decimal("1")
        surge_out = 1.0
    surged = rhu(D(subtotal) * surge)
    service_fee = rhu(D(surged) * SERVICE_FEE_PCT)
    total = surged + service_fee
    return {
        "base_labor_cents": base_labor,
        "truck_fee_cents": truck_fee,
        "addons_total_cents": addons_total,
        "surge_multiplier": surge_out,
        "subtotal_cents": subtotal,
        "service_fee_cents": service_fee,
        "total_cents": total,
    }


# =============================================================================
# Health
# =============================================================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# =============================================================================
# Clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global CLOCK
    _, role = authenticate()
    require_role(role, {"Admin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    CLOCK = parse_dt(body["to_iso8601"])
    return ok_object({}, 200)


# =============================================================================
# Customers
# =============================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    _, role = authenticate()
    require_role(role, {"Admin"})
    body = get_body()
    require_fields(body, ["display_name", "email"])
    ent = new_entity(customers, {
        "display_name": body["display_name"],
        "email": body["email"],
        "wallet_credit_cents": 0,
    })
    return ok_object(serialize(ent), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return ok_object(serialize(lookup(customers, cid)), 200)


# =============================================================================
# Helpers
# =============================================================================
@app.route("/helpers", methods=["POST"])
def create_helper():
    _, role = authenticate()
    require_role(role, {"Admin"})
    body = get_body()
    require_fields(body, ["display_name", "email", "base_hourly_rate_cents"])
    skill_tier = body.get("skill_tier", "STANDARD")
    if skill_tier not in ("STANDARD", "PRO"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "bad skill_tier")
    ent = new_entity(helpers, {
        "display_name": body["display_name"],
        "email": body["email"],
        "base_hourly_rate_cents": body["base_hourly_rate_cents"],
        "skill_tier": skill_tier,
        "vetting_status": "PENDING_REVIEW",
        "rating_avg": 0,
        "rating_count": 0,
        "no_show_count": 0,
        "active_assignment_count": 0,
        "lifetime_payout_cents": 0,
    })
    return ok_object(serialize(ent), 201)


@app.route("/helpers/<hid>", methods=["GET"])
def get_helper(hid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return ok_object(serialize(lookup(helpers, hid)), 200)


@app.route("/helpers/<hid>/vet", methods=["POST"])
def vet_helper(hid):
    _, role = authenticate()
    require_role(role, {"Admin"})
    h = lookup(helpers, hid)
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("APPROVE", "REJECT", "SUSPEND", "REINSTATE"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "bad decision")
    st = h["vetting_status"]
    if decision == "APPROVE":
        if st != "PENDING_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "helper not pending review")
        h["vetting_status"] = "APPROVED"
        touch(h)
    elif decision == "REJECT":
        if st != "PENDING_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "helper not pending review")
        h["vetting_status"] = "REJECTED"
        touch(h)
    elif decision == "SUSPEND":
        if st != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", 409, "helper not approved")
        suspend_helper(hid)
    elif decision == "REINSTATE":
        if st != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", 409, "helper not suspended")
        h["vetting_status"] = "APPROVED"
        touch(h)
    return ok_object(serialize(h), 200)


# =============================================================================
# Config: rate cards / insurance / trucks
# =============================================================================
@app.route("/rate-cards", methods=["POST"])
def create_rate_card():
    _, role = authenticate()
    require_role(role, {"Admin"})
    body = get_body()
    require_fields(body, ["name", "job_type", "base_hourly_rate_cents", "min_billable_hours",
                          "crew_surcharge_pct", "peak_surge_multiplier", "truck_fee_cents"])
    if body["job_type"] not in ("LOAD", "UNLOAD", "MOVE"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "bad job_type")
    ent = new_entity(rate_cards, {
        "name": body["name"],
        "job_type": body["job_type"],
        "base_hourly_rate_cents": body["base_hourly_rate_cents"],
        "min_billable_hours": body["min_billable_hours"],
        "crew_surcharge_pct": body["crew_surcharge_pct"],
        "peak_surge_multiplier": body["peak_surge_multiplier"],
        "truck_fee_cents": body["truck_fee_cents"],
    }, versioned=False)
    return ok_object(serialize(ent), 201)


@app.route("/insurance-policies", methods=["POST"])
def create_insurance_policy():
    _, role = authenticate()
    require_role(role, {"Admin"})
    body = get_body()
    require_fields(body, ["name", "tier", "coverage_cap_cents", "deductible_cents", "coverage_pct"])
    if body["tier"] not in ("BASIC", "FULL"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "bad tier")
    ent = new_entity(insurance_policies, {
        "name": body["name"],
        "tier": body["tier"],
        "coverage_cap_cents": body["coverage_cap_cents"],
        "deductible_cents": body["deductible_cents"],
        "coverage_pct": body["coverage_pct"],
    }, versioned=False)
    return ok_object(serialize(ent), 201)


@app.route("/trucks", methods=["POST"])
def create_truck():
    _, role = authenticate()
    require_role(role, {"Admin"})
    body = get_body()
    require_fields(body, ["name", "capacity_cuft", "daily_rate_cents"])
    ent = new_entity(trucks, {
        "name": body["name"],
        "capacity_cuft": body["capacity_cuft"],
        "daily_rate_cents": body["daily_rate_cents"],
    })
    return ok_object(serialize(ent), 201)


@app.route("/trucks/<tid>", methods=["GET"])
def get_truck(tid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return ok_object(serialize(lookup(trucks, tid)), 200)


# =============================================================================
# Jobs
# =============================================================================
def validate_number(val, positive=False):
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, "expected number")
    if positive and val <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "expected positive number")
    return val


@app.route("/jobs", methods=["POST"])
def create_job():
    uid, role = authenticate()
    require_role(role, {"Customer"})
    body = get_body()
    require_fields(body, ["rate_card_id", "insurance_policy_id", "job_type", "crew_size",
                          "estimated_hours", "window_start", "window_end"])
    job_type = body["job_type"]
    if job_type not in ("LOAD", "UNLOAD", "MOVE"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "bad job_type")
    crew_size = body["crew_size"]
    if not isinstance(crew_size, int) or isinstance(crew_size, bool) or crew_size < 1:
        raise ApiError("ERR_INVALID_REQUEST", 422, "crew_size must be >= 1")
    estimated_hours = body["estimated_hours"]
    validate_number(estimated_hours, positive=True)
    ws = parse_dt(body["window_start"])
    we = parse_dt(body["window_end"])
    if not (we > ws):
        raise ApiError("ERR_INVALID_REQUEST", 422, "window_end must be after window_start")
    truck_required = body.get("truck_required", False)
    if not isinstance(truck_required, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, "truck_required must be bool")

    rate_card = lookup(rate_cards, body["rate_card_id"])
    lookup(insurance_policies, body["insurance_policy_id"])

    if job_type != rate_card["job_type"]:
        raise ApiError("ERR_INVALID_REQUEST", 422, "job_type must equal rate card job_type")

    ent = new_entity(jobs, {
        "customer_id": uid,
        "rate_card_id": body["rate_card_id"],
        "insurance_policy_id": body["insurance_policy_id"],
        "truck_id": None,
        "job_type": job_type,
        "crew_size": crew_size,
        "estimated_hours": estimated_hours,
        "actual_hours": None,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "truck_required": truck_required,
        "status": "DRAFT",
        "estimated_total_cents": None,
        "final_total_cents": None,
        "cancellation_fee_cents": 0,
    })
    return ok_object(serialize(ent), 201)


@app.route("/jobs/<jid>", methods=["GET"])
def get_job(jid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return ok_object(serialize(lookup(jobs, jid)), 200)


@app.route("/jobs", methods=["GET"])
def list_jobs():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return list_response(jobs, ["customer_id", "rate_card_id", "insurance_policy_id",
                                "truck_id", "status"])


def require_job_owner(job, uid):
    if job["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not the job owner")


@app.route("/jobs/<jid>/add-ons", methods=["POST"])
def create_addon(jid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    job = lookup(jobs, jid)
    require_job_owner(job, uid)
    if job["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "job not in DRAFT")
    body = get_body()
    require_fields(body, ["addon_type", "quantity", "unit_fee_cents"])
    if body["addon_type"] not in ("PACKING_MATERIALS", "HEAVY_ITEM", "STAIRS", "LONG_CARRY", "ASSEMBLY"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "bad addon_type")
    quantity = body["quantity"]
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise ApiError("ERR_INVALID_REQUEST", 422, "quantity must be >= 1")
    unit_fee = body["unit_fee_cents"]
    line_total = rhu(D(unit_fee) * D(quantity) * (Decimal("1") + ADDON_TAX_PCT))
    ent = new_entity(add_ons, {
        "job_id": jid,
        "addon_type": body["addon_type"],
        "quantity": quantity,
        "unit_fee_cents": unit_fee,
        "line_total_cents": line_total,
    })
    return ok_object(serialize(ent), 201)


def create_quote_for_job(job, rate_card):
    comps = compute_job_charge(job, rate_card, job["estimated_hours"])
    created = now_iso()
    expires = (CLOCK + timedelta(hours=BOOKING_WINDOW_HOURS))
    expires_iso = expires.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (expires.microsecond // 1000)
    ent = new_entity(quotes, {
        "job_id": job["id"],
        "base_labor_cents": comps["base_labor_cents"],
        "truck_fee_cents": comps["truck_fee_cents"],
        "addons_total_cents": comps["addons_total_cents"],
        "surge_multiplier": comps["surge_multiplier"],
        "subtotal_cents": comps["subtotal_cents"],
        "service_fee_cents": comps["service_fee_cents"],
        "total_cents": comps["total_cents"],
        "expires_at": expires_iso,
        "status": "ACTIVE",
    })
    return ent


@app.route("/jobs/<jid>/quote", methods=["POST"])
def quote_job(jid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    job = lookup(jobs, jid)
    require_job_owner(job, uid)
    if job["status"] not in ("DRAFT", "QUOTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "job cannot be quoted")
    rate_card = rate_cards[job["rate_card_id"]]
    if job["status"] == "QUOTED":
        for q in quotes.values():
            if q["job_id"] == jid and q["status"] == "ACTIVE":
                q["status"] = "SUPERSEDED"
                touch(q)
    ent = create_quote_for_job(job, rate_card)
    job["status"] = "QUOTED"
    touch(job)
    return ok_object(serialize(ent), 201)


@app.route("/jobs/<jid>/book", methods=["POST"])
def book_job(jid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    job = lookup(jobs, jid)
    require_job_owner(job, uid)
    if job["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409, "job not QUOTED")
    body = get_body()
    require_fields(body, ["quote_id", "expected_job_version"])
    quote = quotes.get(body["quote_id"])
    if quote is None or quote["job_id"] != jid or quote["status"] != "ACTIVE":
        raise ApiError("ERR_QUOTE_NOT_ACTIVE", 409, "quote is not the job's active quote")
    if CLOCK >= parse_dt(quote["expires_at"]):
        raise ApiError("ERR_QUOTE_EXPIRED", 409, "booking window closed")
    try:
        expected = int(body["expected_job_version"])
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 422, "bad expected_job_version")
    if expected != job["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "job version mismatch")
    quote["status"] = "ACCEPTED"
    touch(quote)
    job["estimated_total_cents"] = quote["total_cents"]
    job["status"] = "BOOKED"
    touch(job)
    return ok_object(serialize(job), 200)


@app.route("/jobs/<jid>/reschedule", methods=["POST"])
def reschedule_job(jid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    job = lookup(jobs, jid)
    require_job_owner(job, uid)
    if job["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "job not BOOKED")
    body = get_body()
    require_fields(body, ["window_start", "window_end"])
    ws = parse_dt(body["window_start"])
    we = parse_dt(body["window_end"])
    if not (we > ws):
        raise ApiError("ERR_INVALID_REQUEST", 422, "window_end must be after window_start")
    if not (ws > CLOCK):
        raise ApiError("ERR_INVALID_REQUEST", 422, "window_start must be in the future")
    job["window_start"] = body["window_start"]
    job["window_end"] = body["window_end"]
    touch(job)
    return ok_object(serialize(job), 200)


@app.route("/jobs/<jid>/cancel", methods=["POST"])
def cancel_job(jid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    job = lookup(jobs, jid)
    require_job_owner(job, uid)
    status = job["status"]
    if status not in ("QUOTED", "BOOKED"):
        raise ApiError("ERR_INVALID_STATE", 409, "job cannot be cancelled")
    if status == "QUOTED":
        job["cancellation_fee_cents"] = 0
        job["final_total_cents"] = 0
        for q in quotes.values():
            if q["job_id"] == jid and q["status"] == "ACTIVE":
                q["status"] = "SUPERSEDED"
                touch(q)
    else:  # BOOKED
        hours_before = (parse_dt(job["window_start"]) - CLOCK).total_seconds() / 3600.0
        if hours_before >= CANCELLATION_FREE_WINDOW_HOURS:
            fee = 0
        else:
            fee = rhu(D(job["estimated_total_cents"]) * CANCEL_FEE_PCT)
        job["cancellation_fee_cents"] = fee
        job["final_total_cents"] = fee
        affected = set()
        for a in assignments.values():
            if a["job_id"] == jid and a["status"] in ("ASSIGNED", "CHECKED_IN"):
                a["status"] = "RELEASED"
                touch(a)
                affected.add(a["helper_id"])
        for hid in affected:
            recompute_helper(hid)
        job["truck_id"] = None
    job["status"] = "CANCELLED"
    touch(job)
    return ok_object(serialize(job), 200)


@app.route("/jobs/<jid>/assign-truck", methods=["POST"])
def assign_truck(jid):
    _, role = authenticate()
    require_role(role, {"Dispatcher"})
    job = lookup(jobs, jid)
    body = get_body()
    require_fields(body, ["truck_id"])
    truck = lookup(trucks, body["truck_id"])
    s2 = parse_dt(job["window_start"])
    e2 = parse_dt(job["window_end"])
    for other in jobs.values():
        if other["id"] == jid:
            continue
        if other.get("truck_id") != truck["id"]:
            continue
        if other["status"] not in ("BOOKED", "IN_PROGRESS"):
            continue
        s1 = parse_dt(other["window_start"])
        e1 = parse_dt(other["window_end"])
        if s1 <= e2 and s2 <= e1:
            raise ApiError("ERR_TRUCK_UNAVAILABLE", 409, "truck is occupied")
    job["truck_id"] = truck["id"]
    touch(job)
    return ok_object(serialize(job), 200)


@app.route("/jobs/<jid>/start", methods=["POST"])
def start_job(jid):
    _, role = authenticate()
    require_role(role, {"Dispatcher"})
    job = lookup(jobs, jid)
    if job["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "job not BOOKED")
    checked_in = any(a["job_id"] == jid and a["status"] == "CHECKED_IN" for a in assignments.values())
    if not checked_in:
        raise ApiError("ERR_NO_CREW_CHECKED_IN", 409, "no crew checked in")
    job["status"] = "IN_PROGRESS"
    touch(job)
    return ok_object(serialize(job), 200)


@app.route("/jobs/<jid>/complete", methods=["POST"])
def complete_job(jid):
    _, role = authenticate()
    require_role(role, {"Dispatcher"})
    job = lookup(jobs, jid)
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "job not IN_PROGRESS")
    body = get_body()
    require_fields(body, ["actual_hours"])
    actual_hours = body["actual_hours"]
    validate_number(actual_hours, positive=True)
    rate_card = rate_cards[job["rate_card_id"]]
    job["actual_hours"] = actual_hours
    comps = compute_job_charge(job, rate_card, actual_hours)
    job["final_total_cents"] = comps["total_cents"]
    job["status"] = "COMPLETED"
    touch(job)
    return ok_object(serialize(job), 200)


@app.route("/jobs/<jid>/settle", methods=["POST"])
def settle_job(jid):
    _, role = authenticate()
    require_role(role, {"Admin"})
    job = lookup(jobs, jid)
    if job["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "job not COMPLETED")
    for a in [x for x in assignments.values() if x["job_id"] == jid and x["status"] == "CHECKED_OUT"]:
        helper = helpers[a["helper_id"]]
        base_pay = rhu(D(helper["base_hourly_rate_cents"]) * D(job["actual_hours"]))
        tip = sum(r["tip_cents"] for r in ratings.values()
                  if r["job_id"] == jid and r["helper_id"] == helper["id"])
        if D(job["actual_hours"]) <= D(job["estimated_hours"]):
            bonus = rhu(D(base_pay) * ON_TIME_BONUS_PCT)
        else:
            bonus = 0
        total_payout = base_pay + tip + bonus
        new_entity(payouts, {
            "job_id": jid,
            "helper_id": helper["id"],
            "base_pay_cents": base_pay,
            "tip_cents": tip,
            "bonus_cents": bonus,
            "total_payout_cents": total_payout,
            "status": "RELEASED",
        })
        recompute_helper(helper["id"])
    job["status"] = "SETTLED"
    touch(job)
    return ok_object(serialize(job), 200)


# =============================================================================
# Add-ons / quotes read
# =============================================================================
@app.route("/add-ons/<aid>", methods=["GET"])
def get_addon(aid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return ok_object(serialize(lookup(add_ons, aid)), 200)


@app.route("/add-ons", methods=["GET"])
def list_addons():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return list_response(add_ons, ["job_id"])


@app.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return ok_object(serialize(lookup(quotes, qid)), 200)


@app.route("/quotes", methods=["GET"])
def list_quotes():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return list_response(quotes, ["job_id", "status"])


# =============================================================================
# Assignments
# =============================================================================
@app.route("/assignments", methods=["POST"])
def create_assignment():
    _, role = authenticate()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["job_id", "helper_id"])
    job = lookup(jobs, body["job_id"])
    helper = lookup(helpers, body["helper_id"])
    role_val = body.get("role", "CREW")
    if role_val not in ("LEAD", "CREW"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "bad role")

    # business_safety (priority 5)
    if helper["vetting_status"] != "APPROVED":
        raise ApiError("ERR_HELPER_NOT_APPROVED", 409, "helper not approved")

    # crew slots (priority 6)
    current = sum(1 for a in assignments.values()
                  if a["job_id"] == job["id"] and a["status"] in ACTIVE_COUNT_STATES)
    if current >= job["crew_size"]:
        raise ApiError("ERR_CREW_FULL", 409, "crew is full")

    # helper availability (priority 7)
    s2 = parse_dt(job["window_start"])
    e2 = parse_dt(job["window_end"])
    for a in assignments.values():
        if a["helper_id"] != helper["id"]:
            continue
        if a["status"] not in ACTIVE_COUNT_STATES:
            continue
        other_job = jobs.get(a["job_id"])
        if other_job is None:
            continue
        s1 = parse_dt(other_job["window_start"])
        e1 = parse_dt(other_job["window_end"])
        if s1 < e2 + TRAVEL_BUFFER and s2 < e1 + TRAVEL_BUFFER:
            raise ApiError("ERR_HELPER_UNAVAILABLE", 409, "helper unavailable")

    ent = new_entity(assignments, {
        "job_id": job["id"],
        "helper_id": helper["id"],
        "role": role_val,
        "status": "ASSIGNED",
    })
    recompute_helper(helper["id"])
    return ok_object(serialize(ent), 201)


@app.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return ok_object(serialize(lookup(assignments, aid)), 200)


@app.route("/assignments", methods=["GET"])
def list_assignments():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return list_response(assignments, ["job_id", "helper_id", "status"])


@app.route("/assignments/<aid>/check-in", methods=["POST"])
def check_in(aid):
    uid, role = authenticate()
    require_role(role, {"Helper"})
    a = lookup(assignments, aid)
    if a["helper_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not the assignment owner")
    if a["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "assignment not ASSIGNED")
    a["status"] = "CHECKED_IN"
    touch(a)
    recompute_helper(a["helper_id"])
    return ok_object(serialize(a), 200)


@app.route("/assignments/<aid>/check-out", methods=["POST"])
def check_out(aid):
    uid, role = authenticate()
    require_role(role, {"Helper"})
    a = lookup(assignments, aid)
    if a["helper_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not the assignment owner")
    if a["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "assignment not CHECKED_IN")
    a["status"] = "CHECKED_OUT"
    touch(a)
    recompute_helper(a["helper_id"])
    return ok_object(serialize(a), 200)


@app.route("/assignments/<aid>/no-show", methods=["POST"])
def no_show(aid):
    _, role = authenticate()
    require_role(role, {"Dispatcher"})
    a = lookup(assignments, aid)
    if a["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "assignment not ASSIGNED")
    a["status"] = "NO_SHOW"
    touch(a)
    recompute_helper(a["helper_id"])
    return ok_object(serialize(a), 200)


# =============================================================================
# Claims
# =============================================================================
@app.route("/claims", methods=["POST"])
def create_claim():
    uid, role = authenticate()
    require_role(role, {"Customer"})
    body = get_body()
    require_fields(body, ["job_id", "damage_description", "claimed_amount_cents"])
    job = lookup(jobs, body["job_id"])
    responsible = body.get("responsible_helper_id")
    if responsible is not None:
        lookup(helpers, responsible)
    require_job_owner(job, uid)
    ent = new_entity(claims, {
        "job_id": body["job_id"],
        "responsible_helper_id": responsible if responsible is not None else None,
        "damage_description": body["damage_description"],
        "claimed_amount_cents": body["claimed_amount_cents"],
        "status": "FILED",
        "approved_amount_cents": None,
        "insurance_covered_cents": None,
    })
    return ok_object(serialize(ent), 201)


@app.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return ok_object(serialize(lookup(claims, cid)), 200)


@app.route("/claims", methods=["GET"])
def list_claims():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return list_response(claims, ["job_id", "responsible_helper_id", "status"])


@app.route("/claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    _, role = authenticate()
    require_role(role, {"Admin"})
    cl = lookup(claims, cid)
    if cl["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "claim not FILED")
    cl["status"] = "UNDER_REVIEW"
    touch(cl)
    return ok_object(serialize(cl), 200)


@app.route("/claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    _, role = authenticate()
    require_role(role, {"Admin"})
    cl = lookup(claims, cid)
    if cl["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "claim not UNDER_REVIEW")
    job = jobs[cl["job_id"]]
    policy = insurance_policies[job["insurance_policy_id"]]
    if cl["claimed_amount_cents"] > policy["coverage_cap_cents"]:
        raise ApiError("ERR_CLAIM_EXCEEDS_COVERAGE", 409, "claim exceeds coverage cap")
    approved = min(cl["claimed_amount_cents"], policy["coverage_cap_cents"])
    if policy["tier"] == "BASIC":
        covered = max(0, approved - policy["deductible_cents"])
    else:  # FULL
        covered = rhu(D(approved) * D(policy["coverage_pct"]))
    cl["approved_amount_cents"] = approved
    cl["insurance_covered_cents"] = covered
    cl["status"] = "APPROVED"
    touch(cl)
    recompute_customer_wallet(job["customer_id"])
    resp = cl.get("responsible_helper_id")
    if resp:
        for p in payouts.values():
            if p["job_id"] == cl["job_id"] and p["helper_id"] == resp and p["status"] == "RELEASED":
                p["status"] = "REVERSED"
                touch(p)
                recompute_helper(resp)
    return ok_object(serialize(cl), 200)


@app.route("/claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    _, role = authenticate()
    require_role(role, {"Admin"})
    cl = lookup(claims, cid)
    if cl["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "claim not UNDER_REVIEW")
    cl["status"] = "DENIED"
    touch(cl)
    return ok_object(serialize(cl), 200)


# =============================================================================
# Ratings
# =============================================================================
@app.route("/ratings", methods=["POST"])
def create_rating():
    uid, role = authenticate()
    require_role(role, {"Customer"})
    body = get_body()
    require_fields(body, ["job_id", "helper_id", "stars"])
    job = lookup(jobs, body["job_id"])
    helper = lookup(helpers, body["helper_id"])
    require_job_owner(job, uid)
    stars = body["stars"]
    if not isinstance(stars, int) or isinstance(stars, bool) or stars < 1 or stars > 5:
        raise ApiError("ERR_INVALID_REQUEST", 422, "stars must be 1..5")
    tip = body.get("tip_cents", 0)
    if tip is None:
        tip = 0
    ent = new_entity(ratings, {
        "job_id": body["job_id"],
        "helper_id": body["helper_id"],
        "stars": stars,
        "tip_cents": tip,
        "comment": body.get("comment"),
    })
    recompute_helper(helper["id"])
    if helper["vetting_status"] == "APPROVED" and helper["rating_avg"] < RATING_SUSPEND_THRESHOLD:
        suspend_helper(helper["id"])
    return ok_object(serialize(ent), 201)


@app.route("/ratings/<rid>", methods=["GET"])
def get_rating(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return ok_object(serialize(lookup(ratings, rid)), 200)


@app.route("/ratings", methods=["GET"])
def list_ratings():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return list_response(ratings, ["job_id", "helper_id"])


# =============================================================================
# Payouts
# =============================================================================
@app.route("/payouts/<pid>", methods=["GET"])
def get_payout(pid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return ok_object(serialize(lookup(payouts, pid)), 200)


@app.route("/payouts", methods=["GET"])
def list_payouts():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return list_response(payouts, ["job_id", "helper_id", "status"])


@app.route("/payouts/<pid>/reverse", methods=["POST"])
def reverse_payout(pid):
    _, role = authenticate()
    require_role(role, {"Admin"})
    p = lookup(payouts, pid)
    if p["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", 409, "payout not RELEASED")
    p["status"] = "REVERSED"
    touch(p)
    recompute_helper(p["helper_id"])
    return ok_object(serialize(p), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
