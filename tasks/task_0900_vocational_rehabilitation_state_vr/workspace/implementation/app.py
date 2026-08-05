import os
import uuid
import random
import string
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot; no seeding)
# ---------------------------------------------------------------------------
DB = {
    "counselors": {},
    "supervisors": {},
    "providers": {},
    "priority_categories": {},
    "cases": {},
    "ipes": {},
    "authorizations": {},
    "payments": {},
    "placements": {},
    "progress_reviews": {},
}
CLOCK = {"iso": "2026-05-01T00:00:00Z"}
_SEQ = {"n": 0}

VALID_ROLES = {"VRAdmin", "Counselor", "Supervisor", "FiscalOfficer", "Provider"}
SIG_RANK = {"MSD": 1, "SD": 2, "NSD": 3}
DISABILITY_TYPES = {"PHYSICAL", "COGNITIVE", "PSYCHIATRIC", "SENSORY"}
SERVICE_CATEGORIES = {"TRAINING", "ASSISTIVE_TECH", "ASSESSMENT", "SUPPORTED_EMPLOYMENT"}
EMPLOYMENT_TYPES = {"COMPETITIVE_INTEGRATED", "SUPPORTED", "SELF_EMPLOYMENT"}
FEDERAL_MATCH_RATE = Decimal("0.787")

SLOT_HOLDING = {"PLAN_DEVELOPMENT", "SERVICES_ACTIVE", "EMPLOYED"}
CASE_TERMINAL = {"INELIGIBLE", "CLOSED_REHABILITATED", "CLOSED_OTHER"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_iso(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def clock_date():
    return parse_iso(CLOCK["iso"]).date()


def clock_iso():
    dt = parse_iso(CLOCK["iso"])
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def rhu(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def touch(rec):
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_ts()


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta_base():
    return {"api_request_id": request_id(), "api_request_timestamp": now_ts()}


def success(data, response_type="object", status=200, pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def get_actor():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in VALID_ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role")
    return {"id": uid, "role": role}


def require_role(actor, allowed):
    if actor["role"] not in allowed:
        err("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body parsing / validation
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        err("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return b


def v_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            err("ERR_VALIDATION", 422, f"Missing required field: {field}")
        return default
    v = body[field]
    if not isinstance(v, str):
        err("ERR_VALIDATION", 422, f"Field {field} must be a string")
    return v


def v_int(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            err("ERR_VALIDATION", 422, f"Missing required field: {field}")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", 422, f"Field {field} must be an integer")
    return v


def v_bool(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            err("ERR_VALIDATION", 422, f"Missing required field: {field}")
        return default
    v = body[field]
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 422, f"Field {field} must be a boolean")
    return v


def v_enum(body, field, allowed, required=True, default=None):
    v = v_str(body, field, required, default)
    if v is None:
        return default
    if v not in allowed:
        err("ERR_VALIDATION", 422, f"Field {field} must be one of {sorted(allowed)}")
    return v


def v_date(body, field, required=True, default=None):
    v = v_str(body, field, required, default)
    if v is None:
        return default
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 422, f"Field {field} must be a YYYY-MM-DD date")
    return v


def get_or_404(coll, rid):
    if rid is None or rid not in DB[coll]:
        err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return DB[coll][rid]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


# ---------------------------------------------------------------------------
# Computed field helpers
# ---------------------------------------------------------------------------
def auth_amount_paid(auth):
    return sum(
        p["amount_cents"]
        for p in DB["payments"].values()
        if p["authorization_id"] == auth["id"] and p["status"] == "ISSUED"
    )


def case_authorizations(case_id):
    return [a for a in DB["authorizations"].values() if a["case_id"] == case_id]


def case_funds(case):
    committed = 0
    paid = 0
    for a in case_authorizations(case["id"]):
        if a["status"] == "APPROVED":
            committed += a["agency_share_cents"] - auth_amount_paid(a)
    for a in case_authorizations(case["id"]):
        for p in DB["payments"].values():
            if p["authorization_id"] == a["id"] and p["status"] == "ISSUED":
                paid += p["amount_cents"]
    available = case["budget_allocated_cents"] - committed - paid
    return committed, paid, available


def provider_ledger(provider):
    pending = sum(
        p["amount_cents"]
        for p in DB["payments"].values()
        if p["provider_id"] == provider["id"] and p["status"] == "PENDING"
    )
    paid = sum(
        p["amount_cents"]
        for p in DB["payments"].values()
        if p["provider_id"] == provider["id"] and p["status"] == "ISSUED"
    )
    return pending, paid


def category_slots(cat):
    used = sum(
        1
        for c in DB["cases"].values()
        if c["priority_category_id"] == cat["id"] and c["status"] in SLOT_HOLDING
    )
    available = cat["slot_capacity"] - used
    if available < 0:
        available = 0
    return used, available


def most_recent_ipe(case_id):
    ipes = [i for i in DB["ipes"].values() if i["case_id"] == case_id]
    if not ipes:
        return None
    ipes.sort(key=lambda i: (i["created_at"], i["_seq"]))
    return ipes[-1]


def case_placement(case_id):
    pls = [p for p in DB["placements"].values() if p["case_id"] == case_id]
    if not pls:
        return None
    pls.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return pls[-1]


def placement_days_stable(pl):
    if pl["status"] == "STABILIZING" and pl["stabilization_start_date"]:
        start = date.fromisoformat(pl["stabilization_start_date"])
        return (clock_date() - start).days
    return 0


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_counselor(c):
    return {"id": c["id"], "created_at": c["created_at"], "name": c["name"],
            "email": c["email"], "unit": c["unit"]}


def ser_supervisor(s):
    return {"id": s["id"], "created_at": s["created_at"], "name": s["name"],
            "email": s["email"]}


def ser_provider(p):
    pending, paid = provider_ledger(p)
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "name": p["name"],
        "service_categories": p["service_categories"],
        "max_concurrent_authorizations": p["max_concurrent_authorizations"],
        "status": p["status"],
        "pending_disbursement_cents": pending, "ledger_paid_cents": paid,
    }


def ser_category(cat):
    used, available = category_slots(cat)
    return {
        "id": cat["id"], "created_at": cat["created_at"], "updated_at": cat["updated_at"],
        "version": cat["version"], "rank": cat["rank"], "label": cat["label"],
        "status": cat["status"], "slot_capacity": cat["slot_capacity"],
        "slots_used": used, "available_slots": available,
    }


def ser_case(c):
    committed, paid, available = case_funds(c)
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"], "counselor_id": c["counselor_id"],
        "priority_category_id": c["priority_category_id"],
        "consumer_full_name": c["consumer_full_name"], "consumer_dob": c["consumer_dob"],
        "disability_type": c["disability_type"],
        "disability_significance": c["disability_significance"],
        "referral_source": c["referral_source"],
        "monthly_income_cents": c["monthly_income_cents"],
        "budget_allocated_cents": c["budget_allocated_cents"],
        "funds_committed_cents": committed, "funds_paid_cents": paid,
        "funds_available_cents": available, "status": c["status"],
        "waitlisted_at": c["waitlisted_at"], "closure_type": c["closure_type"],
        "closure_reason": c["closure_reason"],
    }


def ser_ipe(i):
    return {
        "id": i["id"], "created_at": i["created_at"], "updated_at": i["updated_at"],
        "version": i["version"], "case_id": i["case_id"],
        "employment_goal": i["employment_goal"],
        "goal_wage_target_cents": i["goal_wage_target_cents"], "status": i["status"],
        "approved_by_supervisor_id": i["approved_by_supervisor_id"],
        "approved_plan_version": i["approved_plan_version"],
    }


def ser_auth(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"], "case_id": a["case_id"], "ipe_id": a["ipe_id"],
        "provider_id": a["provider_id"], "service_category": a["service_category"],
        "authorized_amount_cents": a["authorized_amount_cents"],
        "comparable_benefit_cents": a["comparable_benefit_cents"],
        "consumer_share_cents": a["consumer_share_cents"],
        "agency_share_cents": a["agency_share_cents"],
        "service_period_start": a["service_period_start"],
        "service_period_end": a["service_period_end"], "status": a["status"],
        "requested_by_counselor_id": a["requested_by_counselor_id"],
        "approved_by_supervisor_id": a["approved_by_supervisor_id"],
        "amount_paid_cents": auth_amount_paid(a),
    }


def ser_payment(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "authorization_id": p["authorization_id"],
        "provider_id": p["provider_id"], "amount_cents": p["amount_cents"],
        "status": p["status"], "federal_share_cents": p["federal_share_cents"],
        "state_share_cents": p["state_share_cents"], "issued_by": p["issued_by"],
    }


def ser_placement(pl):
    return {
        "id": pl["id"], "created_at": pl["created_at"], "updated_at": pl["updated_at"],
        "version": pl["version"], "case_id": pl["case_id"], "ipe_id": pl["ipe_id"],
        "employer_name": pl["employer_name"], "placement_date": pl["placement_date"],
        "weekly_wage_cents": pl["weekly_wage_cents"],
        "hours_per_week": pl["hours_per_week"],
        "employment_type": pl["employment_type"], "status": pl["status"],
        "stabilization_start_date": pl["stabilization_start_date"],
        "verified_avg_weekly_wage_cents": pl["verified_avg_weekly_wage_cents"],
        "days_stable": placement_days_stable(pl),
    }


def ser_progress(pr):
    return {
        "id": pr["id"], "created_at": pr["created_at"],
        "placement_id": pr["placement_id"], "review_date": pr["review_date"],
        "reported_weekly_wage_cents": pr["reported_weekly_wage_cents"],
        "status_ok": pr["status_ok"],
    }


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------
def ensure_case_owner(case, actor):
    if case["counselor_id"] != actor["id"]:
        err("ERR_FORBIDDEN", 403, "Counselor does not own this case")


# ---------------------------------------------------------------------------
# Cost share / splits
# ---------------------------------------------------------------------------
def compute_cost_share(authorized, comparable, monthly_income):
    net = max(0, authorized - comparable)
    if monthly_income <= 200000:
        rate = Decimal("0.00")
    elif monthly_income <= 400000:
        rate = Decimal("0.10")
    else:
        rate = Decimal("0.20")
    consumer = min(net, rhu(Decimal(net) * rate))
    agency = net - consumer
    return consumer, agency


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def void_pending_payments_of_auth(auth):
    for p in DB["payments"].values():
        if p["authorization_id"] == auth["id"] and p["status"] == "PENDING":
            p["status"] = "VOIDED"
            touch(p)
            provider = DB["providers"].get(p["provider_id"])
            if provider:
                touch(provider)  # CASCADE L4: pending_disbursement decrement


def cascade_cancel_auth(auth):
    # Fired as cascade from case close/rehab. Case.version handled by caller.
    void_pending_payments_of_auth(auth)
    auth["status"] = "CANCELLED"
    touch(auth)


def close_case_rehab(case):
    cat = DB["priority_categories"].get(case["priority_category_id"])
    for a in case_authorizations(case["id"]):
        if a["status"] in ("REQUESTED", "APPROVED"):
            cascade_cancel_auth(a)
    for i in DB["ipes"].values():
        if i["case_id"] == case["id"] and i["status"] in ("APPROVED", "AMENDING"):
            i["status"] = "CLOSED"
            touch(i)
    case["status"] = "CLOSED_REHABILITATED"
    case["closure_type"] = "REHABILITATED"
    touch(case)
    if cat:
        touch(cat)  # slot release


def close_case_other(case, reason):
    prior = case["status"]
    cat = DB["priority_categories"].get(case["priority_category_id"])
    if prior in ("SERVICES_ACTIVE", "EMPLOYED"):
        for a in case_authorizations(case["id"]):
            if a["status"] in ("REQUESTED", "APPROVED"):
                cascade_cancel_auth(a)
    if prior == "SERVICES_ACTIVE":
        for i in DB["ipes"].values():
            if i["case_id"] == case["id"] and i["status"] in (
                "DRAFT", "SUBMITTED", "APPROVED", "AMENDING"):
                i["status"] = "CLOSED"
                touch(i)
    if prior == "EMPLOYED":
        for i in DB["ipes"].values():
            if i["case_id"] == case["id"] and i["status"] != "CLOSED":
                i["status"] = "CLOSED"
                touch(i)
        for pl in DB["placements"].values():
            if pl["case_id"] == case["id"] and pl["status"] != "CLOSED":
                pl["status"] = "CLOSED"
                touch(pl)
    case["status"] = "CLOSED_OTHER"
    case["closure_type"] = "OTHER"
    case["closure_reason"] = reason
    touch(case)
    if prior in SLOT_HOLDING and cat:
        touch(cat)  # slot release


# ===========================================================================
# Routes: Actors / config (VRAdmin)
# ===========================================================================
@app.route("/vr/counselors", methods=["POST"])
def create_counselor():
    actor = get_actor()
    require_role(actor, {"VRAdmin"})
    body = get_body()
    name = v_str(body, "name")
    email = v_str(body, "email")
    unit = v_str(body, "unit")
    rec = {"id": new_id(), "created_at": now_ts(), "_seq": next_seq(),
           "name": name, "email": email, "unit": unit}
    DB["counselors"][rec["id"]] = rec
    return success(ser_counselor(rec), status=201)


@app.route("/vr/supervisors", methods=["POST"])
def create_supervisor():
    actor = get_actor()
    require_role(actor, {"VRAdmin"})
    body = get_body()
    name = v_str(body, "name")
    email = v_str(body, "email")
    rec = {"id": new_id(), "created_at": now_ts(), "_seq": next_seq(),
           "name": name, "email": email}
    DB["supervisors"][rec["id"]] = rec
    return success(ser_supervisor(rec), status=201)


@app.route("/vr/providers", methods=["POST"])
def create_provider():
    actor = get_actor()
    require_role(actor, {"VRAdmin"})
    body = get_body()
    name = v_str(body, "name")
    cats = body.get("service_categories")
    if cats is None or not isinstance(cats, list) or not all(
            isinstance(x, str) for x in cats):
        err("ERR_VALIDATION", 422, "service_categories must be an array of strings")
    for c in cats:
        if c not in SERVICE_CATEGORIES:
            err("ERR_VALIDATION", 422, f"Invalid service category: {c}")
    max_conc = v_int(body, "max_concurrent_authorizations")
    status = v_enum(body, "status", {"ACTIVE", "SUSPENDED"}, required=False,
                    default="ACTIVE")
    ts = now_ts()
    rec = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
           "_seq": next_seq(), "name": name, "service_categories": cats,
           "max_concurrent_authorizations": max_conc, "status": status}
    DB["providers"][rec["id"]] = rec
    return success(ser_provider(rec), status=201)


@app.route("/vr/providers/<provider_id>", methods=["GET"])
def get_provider(provider_id):
    get_actor()
    p = get_or_404("providers", provider_id)
    return success(ser_provider(p))


@app.route("/vr/priority-categories", methods=["POST"])
def create_category():
    actor = get_actor()
    require_role(actor, {"VRAdmin"})
    body = get_body()
    rank = v_int(body, "rank")
    label = v_str(body, "label")
    slot_capacity = v_int(body, "slot_capacity")
    status = v_enum(body, "status", {"OPEN", "CLOSED"}, required=False, default="OPEN")
    ts = now_ts()
    rec = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
           "_seq": next_seq(), "rank": rank, "label": label,
           "slot_capacity": slot_capacity, "status": status}
    DB["priority_categories"][rec["id"]] = rec
    return success(ser_category(rec), status=201)


@app.route("/vr/priority-categories/<category_id>", methods=["GET"])
def get_category(category_id):
    get_actor()
    cat = get_or_404("priority_categories", category_id)
    return success(ser_category(cat))


@app.route("/vr/priority-categories", methods=["GET"])
def list_categories():
    get_actor()
    items = list(DB["priority_categories"].values())
    rank = request.args.get("rank")
    status = request.args.get("status")
    if rank is not None and rank != "":
        try:
            rank_i = int(rank)
        except ValueError:
            err("ERR_VALIDATION", 422, "rank must be an integer")
        items = [c for c in items if c["rank"] == rank_i]
    if status:
        items = [c for c in items if c["status"] == status]
    page, pg = paginate(items)
    return success([ser_category(c) for c in page], response_type="array",
                   pagination=pg)


@app.route("/vr/priority-categories/<category_id>", methods=["PATCH"])
def patch_category(category_id):
    actor = get_actor()
    require_role(actor, {"VRAdmin"})
    cat = get_or_404("priority_categories", category_id)
    body = get_body()
    status = v_enum(body, "status", {"OPEN", "CLOSED"}, required=False, default=None)
    slot_capacity = v_int(body, "slot_capacity", required=False, default=None)
    if status is not None:
        cat["status"] = status
    if slot_capacity is not None:
        cat["slot_capacity"] = slot_capacity
    touch(cat)
    return success(ser_category(cat))


@app.route("/vr/priority-categories/<category_id>/promote-next", methods=["POST"])
def promote_next(category_id):
    actor = get_actor()
    require_role(actor, {"VRAdmin"})
    cat = get_or_404("priority_categories", category_id)
    _, available = category_slots(cat)
    if available <= 0:
        err("ERR_NO_SLOT_AVAILABLE", 409, "Category has no available slot")
    candidates = [
        c for c in DB["cases"].values()
        if c["priority_category_id"] == cat["id"] and c["status"] == "WAITLISTED"
    ]
    if not candidates:
        err("ERR_NO_WAITLISTED_CASE", 409, "No waitlisted case in this category")
    candidates.sort(key=lambda c: (c["waitlisted_at"], c["created_at"], c["_seq"]))
    chosen = candidates[0]
    chosen["status"] = "PLAN_DEVELOPMENT"
    chosen["waitlisted_at"] = None
    touch(chosen)
    touch(cat)  # reserve slot
    return success(ser_case(chosen))


@app.route("/vr/_clock/set_current_utc", methods=["POST"])
def set_clock():
    get_actor()
    body = get_body()
    to_iso = v_str(body, "to_iso8601")
    try:
        parse_iso(to_iso)
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 422, "to_iso8601 must be a valid ISO 8601 instant")
    CLOCK["iso"] = to_iso
    return success({})


# ===========================================================================
# Routes: Case
# ===========================================================================
@app.route("/vr/cases", methods=["POST"])
def create_case():
    actor = get_actor()
    require_role(actor, {"Counselor"})
    body = get_body()
    consumer_full_name = v_str(body, "consumer_full_name")
    consumer_dob = v_date(body, "consumer_dob")
    disability_type = v_enum(body, "disability_type", DISABILITY_TYPES)
    referral_source = v_str(body, "referral_source")
    monthly_income = v_int(body, "monthly_income_cents")
    budget = v_int(body, "budget_allocated_cents", required=False, default=0)
    ts = now_ts()
    rec = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "_seq": next_seq(), "counselor_id": actor["id"], "priority_category_id": None,
        "consumer_full_name": consumer_full_name, "consumer_dob": consumer_dob,
        "disability_type": disability_type, "disability_significance": None,
        "referral_source": referral_source, "monthly_income_cents": monthly_income,
        "budget_allocated_cents": budget, "status": "REFERRED",
        "waitlisted_at": None, "closure_type": None, "closure_reason": None,
    }
    DB["cases"][rec["id"]] = rec
    return success(ser_case(rec), status=201)


@app.route("/vr/cases/<case_id>", methods=["GET"])
def get_case(case_id):
    get_actor()
    c = get_or_404("cases", case_id)
    return success(ser_case(c))


@app.route("/vr/cases", methods=["GET"])
def list_cases():
    get_actor()
    items = list(DB["cases"].values())
    status = request.args.get("status")
    counselor_id = request.args.get("counselor_id")
    priority_category_id = request.args.get("priority_category_id")
    if status:
        items = [c for c in items if c["status"] == status]
    if counselor_id:
        items = [c for c in items if c["counselor_id"] == counselor_id]
    if priority_category_id:
        items = [c for c in items if c["priority_category_id"] == priority_category_id]
    page, pg = paginate(items)
    return success([ser_case(c) for c in page], response_type="array", pagination=pg)


@app.route("/vr/cases/<case_id>/application", methods=["POST"])
def case_application(case_id):
    actor = get_actor()
    require_role(actor, {"Counselor"})
    case = get_or_404("cases", case_id)
    ensure_case_owner(case, actor)
    if case["status"] != "REFERRED":
        err("ERR_INVALID_STATE", 409, "Case is not in REFERRED")
    case["status"] = "APPLICATION"
    touch(case)
    return success(ser_case(case))


@app.route("/vr/cases/<case_id>/eligibility", methods=["POST"])
def case_eligibility(case_id):
    actor = get_actor()
    require_role(actor, {"Counselor"})
    case = get_or_404("cases", case_id)
    ensure_case_owner(case, actor)
    body = get_body()
    decision = v_enum(body, "decision", {"ELIGIBLE", "INELIGIBLE"})
    significance = v_enum(body, "disability_significance", {"MSD", "SD", "NSD"})
    if case["status"] != "APPLICATION":
        err("ERR_INVALID_STATE", 409, "Case is not in APPLICATION")
    if decision == "INELIGIBLE":
        case["disability_significance"] = significance
        case["status"] = "INELIGIBLE"
        touch(case)
        return success(ser_case(case))
    # ELIGIBLE
    rank = SIG_RANK[significance]
    cat = None
    for c in DB["priority_categories"].values():
        if c["rank"] == rank:
            cat = c
            break
    if cat is None:
        err("ERR_CATEGORY_NOT_FOUND", 422,
            "No priority category exists for this disability significance rank")
    case["disability_significance"] = significance
    case["priority_category_id"] = cat["id"]
    _, available = category_slots(cat)
    if cat["status"] == "OPEN" and available > 0:
        case["status"] = "PLAN_DEVELOPMENT"
        touch(case)
        touch(cat)  # reserve slot
    else:
        case["status"] = "WAITLISTED"
        case["waitlisted_at"] = clock_iso()
        touch(case)
    return success(ser_case(case))


@app.route("/vr/cases/<case_id>/close", methods=["POST"])
def case_close(case_id):
    actor = get_actor()
    require_role(actor, {"Counselor"})
    case = get_or_404("cases", case_id)
    ensure_case_owner(case, actor)
    body = get_body()
    reason = v_str(body, "closure_reason")
    if case["status"] in CASE_TERMINAL:
        err("ERR_INVALID_STATE", 409, "Case is already in a terminal state")
    close_case_other(case, reason)
    return success(ser_case(case))


@app.route("/vr/cases/<case_id>/rsa911", methods=["GET"])
def case_rsa911(case_id):
    actor = get_actor()
    require_role(actor, {"VRAdmin", "Counselor", "Supervisor"})
    case = get_or_404("cases", case_id)
    pl = case_placement(case["id"])
    total_fed = 0
    total_state = 0
    for a in case_authorizations(case["id"]):
        for p in DB["payments"].values():
            if p["authorization_id"] == a["id"] and p["status"] == "ISSUED":
                total_fed += p["federal_share_cents"] or 0
                total_state += p["state_share_cents"] or 0
    employment_outcome = "rehabilitated" if case["status"] == "CLOSED_REHABILITATED" else "other"
    competitive = bool(pl and pl["employment_type"] == "COMPETITIVE_INTEGRATED")
    verified_wage = pl["verified_avg_weekly_wage_cents"] if pl else None
    record = {
        "case_id": case["id"],
        "disability_type": case["disability_type"],
        "disability_significance": case["disability_significance"],
        "employment_outcome": employment_outcome,
        "competitive_integrated": competitive,
        "verified_weekly_wage_cents": verified_wage,
        "total_federal_expenditure_cents": total_fed,
        "total_state_expenditure_cents": total_state,
        "closure_type": case["closure_type"],
        "closure_reason": case["closure_reason"],
    }
    return success(record)


# ===========================================================================
# Routes: IPE
# ===========================================================================
@app.route("/vr/ipes", methods=["POST"])
def create_ipe():
    actor = get_actor()
    require_role(actor, {"Counselor"})
    body = get_body()
    case_id = v_str(body, "case_id")
    employment_goal = v_str(body, "employment_goal")
    goal_wage = v_int(body, "goal_wage_target_cents")
    case = get_or_404("cases", case_id)
    ensure_case_owner(case, actor)
    for i in DB["ipes"].values():
        if i["case_id"] == case_id and i["status"] in (
                "DRAFT", "SUBMITTED", "APPROVED", "AMENDING"):
            err("ERR_ACTIVE_IPE_EXISTS", 409, "Case already has an active IPE")
    ts = now_ts()
    rec = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "_seq": next_seq(), "case_id": case_id, "employment_goal": employment_goal,
        "goal_wage_target_cents": goal_wage, "status": "DRAFT",
        "approved_by_supervisor_id": None, "approved_plan_version": None,
    }
    DB["ipes"][rec["id"]] = rec
    return success(ser_ipe(rec), status=201)


@app.route("/vr/ipes/<ipe_id>", methods=["GET"])
def get_ipe(ipe_id):
    get_actor()
    i = get_or_404("ipes", ipe_id)
    return success(ser_ipe(i))


@app.route("/vr/ipes", methods=["GET"])
def list_ipes():
    get_actor()
    items = list(DB["ipes"].values())
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    if case_id:
        items = [i for i in items if i["case_id"] == case_id]
    if status:
        items = [i for i in items if i["status"] == status]
    page, pg = paginate(items)
    return success([ser_ipe(i) for i in page], response_type="array", pagination=pg)


@app.route("/vr/ipes/<ipe_id>/submit", methods=["POST"])
def ipe_submit(ipe_id):
    actor = get_actor()
    require_role(actor, {"Counselor"})
    ipe = get_or_404("ipes", ipe_id)
    case = DB["cases"].get(ipe["case_id"])
    if case is None:
        err("ERR_NOT_FOUND", 404, "Case not found")
    ensure_case_owner(case, actor)
    if ipe["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "IPE is not in DRAFT")
    if case["status"] != "PLAN_DEVELOPMENT":
        err("ERR_INVALID_STATE", 409, "Case is not in PLAN_DEVELOPMENT")
    ipe["status"] = "SUBMITTED"
    touch(ipe)
    return success(ser_ipe(ipe))


@app.route("/vr/ipes/<ipe_id>/approve", methods=["POST"])
def ipe_approve(ipe_id):
    actor = get_actor()
    require_role(actor, {"Supervisor"})
    ipe = get_or_404("ipes", ipe_id)
    if ipe["status"] not in ("SUBMITTED", "AMENDING"):
        err("ERR_INVALID_STATE", 409, "IPE is not in SUBMITTED or AMENDING")
    ipe["status"] = "APPROVED"
    touch(ipe)
    ipe["approved_by_supervisor_id"] = actor["id"]
    ipe["approved_plan_version"] = ipe["version"]
    case = DB["cases"].get(ipe["case_id"])
    if case is not None and case["status"] == "PLAN_DEVELOPMENT":
        case["status"] = "SERVICES_ACTIVE"
        touch(case)
    return success(ser_ipe(ipe))


@app.route("/vr/ipes/<ipe_id>/return", methods=["POST"])
def ipe_return(ipe_id):
    actor = get_actor()
    require_role(actor, {"Supervisor"})
    ipe = get_or_404("ipes", ipe_id)
    if ipe["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "IPE is not in SUBMITTED")
    ipe["status"] = "DRAFT"
    touch(ipe)
    return success(ser_ipe(ipe))


@app.route("/vr/ipes/<ipe_id>/amend", methods=["POST"])
def ipe_amend(ipe_id):
    actor = get_actor()
    require_role(actor, {"Counselor"})
    ipe = get_or_404("ipes", ipe_id)
    case = DB["cases"].get(ipe["case_id"])
    if case is None:
        err("ERR_NOT_FOUND", 404, "Case not found")
    ensure_case_owner(case, actor)
    if ipe["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "IPE is not in APPROVED")
    ipe["status"] = "AMENDING"
    touch(ipe)
    return success(ser_ipe(ipe))


# ===========================================================================
# Routes: ServiceAuthorization
# ===========================================================================
@app.route("/vr/authorizations", methods=["POST"])
def create_authorization():
    actor = get_actor()
    require_role(actor, {"Counselor"})
    body = get_body()
    case_id = v_str(body, "case_id")
    ipe_id = v_str(body, "ipe_id")
    provider_id = v_str(body, "provider_id")
    service_category = v_enum(body, "service_category", SERVICE_CATEGORIES)
    authorized = v_int(body, "authorized_amount_cents")
    start = v_date(body, "service_period_start")
    end = v_date(body, "service_period_end")
    comparable = v_int(body, "comparable_benefit_cents", required=False, default=0)
    case = get_or_404("cases", case_id)
    get_or_404("ipes", ipe_id)
    get_or_404("providers", provider_id)
    ensure_case_owner(case, actor)
    if date.fromisoformat(start) > date.fromisoformat(end):
        err("ERR_VALIDATION", 422, "service_period_start must be <= service_period_end")
    if authorized <= 0:
        err("ERR_AMOUNT_NOT_POSITIVE", 422, "authorized_amount_cents must be > 0")
    consumer, agency = compute_cost_share(authorized, comparable,
                                          case["monthly_income_cents"])
    ts = now_ts()
    rec = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "_seq": next_seq(), "case_id": case_id, "ipe_id": ipe_id,
        "provider_id": provider_id, "service_category": service_category,
        "authorized_amount_cents": authorized, "comparable_benefit_cents": comparable,
        "consumer_share_cents": consumer, "agency_share_cents": agency,
        "service_period_start": start, "service_period_end": end,
        "status": "REQUESTED", "requested_by_counselor_id": actor["id"],
        "approved_by_supervisor_id": None,
    }
    DB["authorizations"][rec["id"]] = rec
    return success(ser_auth(rec), status=201)


@app.route("/vr/authorizations/<authorization_id>", methods=["GET"])
def get_authorization(authorization_id):
    get_actor()
    a = get_or_404("authorizations", authorization_id)
    return success(ser_auth(a))


@app.route("/vr/authorizations", methods=["GET"])
def list_authorizations():
    get_actor()
    items = list(DB["authorizations"].values())
    for f in ("case_id", "ipe_id", "provider_id", "status"):
        val = request.args.get(f)
        if val:
            items = [a for a in items if a[f] == val]
    page, pg = paginate(items)
    return success([ser_auth(a) for a in page], response_type="array", pagination=pg)


def periods_overlap_closed(s1, e1, s2, e2):
    return s1 <= e2 and s2 <= e1


def periods_overlap_halfopen(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@app.route("/vr/authorizations/<authorization_id>/approve", methods=["POST"])
def approve_authorization(authorization_id):
    actor = get_actor()
    require_role(actor, {"Supervisor"})
    auth = get_or_404("authorizations", authorization_id)
    body = get_body()
    expected = v_int(body, "expected_case_version")
    case = DB["cases"].get(auth["case_id"])
    if case is None:
        err("ERR_NOT_FOUND", 404, "Case not found")
    # 1. OCC
    if expected != case["version"]:
        err("ERR_STALE_VERSION", 412, "expected_case_version does not match Case.version")
    # 2. state
    if auth["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "Authorization is not in REQUESTED")
    # 3. IPE approved
    ipe = most_recent_ipe(case["id"])
    if ipe is None or ipe["status"] != "APPROVED":
        err("ERR_IPE_NOT_APPROVED", 409, "The case's most recent IPE is not APPROVED")
    # 4. provider eligibility
    provider = DB["providers"].get(auth["provider_id"])
    if provider is None or provider["status"] != "ACTIVE" or \
            auth["service_category"] not in provider["service_categories"]:
        err("ERR_PROVIDER_INELIGIBLE", 422,
            "Provider is not ACTIVE or not approved for the service category")
    s_new = date.fromisoformat(auth["service_period_start"])
    e_new = date.fromisoformat(auth["service_period_end"])
    # 5. period overlap (same case + same service_category, closed interval)
    for other in DB["authorizations"].values():
        if other["id"] == auth["id"]:
            continue
        if other["status"] == "APPROVED" and other["case_id"] == case["id"] and \
                other["service_category"] == auth["service_category"]:
            os_ = date.fromisoformat(other["service_period_start"])
            oe_ = date.fromisoformat(other["service_period_end"])
            if periods_overlap_closed(s_new, e_new, os_, oe_):
                err("ERR_AUTHORIZATION_PERIOD_OVERLAP", 409,
                    "Overlapping APPROVED authorization on same case + service category")
    # 6. provider capacity (half-open interval)
    overlapping = 0
    for other in DB["authorizations"].values():
        if other["id"] == auth["id"]:
            continue
        if other["status"] == "APPROVED" and other["provider_id"] == auth["provider_id"]:
            os_ = date.fromisoformat(other["service_period_start"])
            oe_ = date.fromisoformat(other["service_period_end"])
            if periods_overlap_halfopen(s_new, e_new, os_, oe_):
                overlapping += 1
    if overlapping + 1 > provider["max_concurrent_authorizations"]:
        err("ERR_PROVIDER_CAPACITY_EXCEEDED", 409,
            "Provider concurrent authorization capacity exceeded")
    # 7. budget
    _, _, available = case_funds(case)
    if auth["agency_share_cents"] > available:
        err("ERR_BUDGET_EXCEEDED", 409, "agency_share_cents exceeds funds_available_cents")
    # success
    auth["status"] = "APPROVED"
    touch(auth)
    auth["approved_by_supervisor_id"] = actor["id"]
    touch(case)  # commit funds
    return success(ser_auth(auth))


@app.route("/vr/authorizations/<authorization_id>/complete", methods=["POST"])
def complete_authorization(authorization_id):
    actor = get_actor()
    require_role(actor, {"Provider"})
    auth = get_or_404("authorizations", authorization_id)
    if auth["provider_id"] != actor["id"]:
        err("ERR_FORBIDDEN", 403, "Provider does not own this authorization")
    if auth["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Authorization is not in APPROVED")
    auth["status"] = "COMPLETED"
    touch(auth)
    return success(ser_auth(auth))


@app.route("/vr/authorizations/<authorization_id>/cancel", methods=["POST"])
def cancel_authorization(authorization_id):
    actor = get_actor()
    require_role(actor, {"Counselor"})
    auth = get_or_404("authorizations", authorization_id)
    case = DB["cases"].get(auth["case_id"])
    if case is None:
        err("ERR_NOT_FOUND", 404, "Case not found")
    ensure_case_owner(case, actor)
    if auth["status"] not in ("REQUESTED", "APPROVED"):
        err("ERR_INVALID_STATE", 409, "Authorization is not in REQUESTED or APPROVED")
    was_approved = auth["status"] == "APPROVED"
    void_pending_payments_of_auth(auth)
    auth["status"] = "CANCELLED"
    touch(auth)
    if was_approved:
        touch(case)  # release committed funds
    return success(ser_auth(auth))


# ===========================================================================
# Routes: Payment
# ===========================================================================
@app.route("/vr/payments", methods=["POST"])
def create_payment():
    actor = get_actor()
    require_role(actor, {"FiscalOfficer"})
    body = get_body()
    authorization_id = v_str(body, "authorization_id")
    amount = v_int(body, "amount_cents")
    auth = get_or_404("authorizations", authorization_id)
    if amount <= 0:
        err("ERR_AMOUNT_NOT_POSITIVE", 422, "amount_cents must be > 0")
    remaining = auth["agency_share_cents"] - auth_amount_paid(auth)
    if amount > remaining:
        err("ERR_PAYMENT_EXCEEDS_AUTHORIZATION", 409,
            "Payment exceeds the authorization's remaining obligation")
    ts = now_ts()
    rec = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "_seq": next_seq(), "authorization_id": authorization_id,
        "provider_id": auth["provider_id"], "amount_cents": amount,
        "status": "PENDING", "federal_share_cents": None, "state_share_cents": None,
        "issued_by": None,
    }
    DB["payments"][rec["id"]] = rec
    return success(ser_payment(rec), status=201)


@app.route("/vr/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    get_actor()
    p = get_or_404("payments", payment_id)
    return success(ser_payment(p))


@app.route("/vr/payments", methods=["GET"])
def list_payments():
    get_actor()
    items = list(DB["payments"].values())
    for f in ("authorization_id", "provider_id", "status"):
        val = request.args.get(f)
        if val:
            items = [p for p in items if p[f] == val]
    page, pg = paginate(items)
    return success([ser_payment(p) for p in page], response_type="array", pagination=pg)


@app.route("/vr/payments/<payment_id>/issue", methods=["POST"])
def issue_payment(payment_id):
    actor = get_actor()
    require_role(actor, {"FiscalOfficer"})
    payment = get_or_404("payments", payment_id)
    if payment["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Payment is not in PENDING")
    auth = DB["authorizations"].get(payment["authorization_id"])
    if auth is None:
        err("ERR_NOT_FOUND", 404, "Authorization not found")
    if auth["status"] not in ("APPROVED", "COMPLETED"):
        err("ERR_INVALID_STATE", 409, "Authorization is not in APPROVED or COMPLETED")
    federal = rhu(Decimal(payment["amount_cents"]) * FEDERAL_MATCH_RATE)
    state = payment["amount_cents"] - federal
    payment["status"] = "ISSUED"
    payment["issued_by"] = actor["id"]
    payment["federal_share_cents"] = federal
    payment["state_share_cents"] = state
    touch(payment)
    case = DB["cases"].get(auth["case_id"])
    if case is not None:
        touch(case)  # move committed -> paid
    provider = DB["providers"].get(payment["provider_id"])
    if provider is not None:
        touch(provider)  # pending -> ledger_paid
    return success(ser_payment(payment))


@app.route("/vr/payments/<payment_id>/void", methods=["POST"])
def void_payment(payment_id):
    actor = get_actor()
    require_role(actor, {"FiscalOfficer"})
    payment = get_or_404("payments", payment_id)
    if payment["status"] not in ("PENDING", "ISSUED"):
        err("ERR_INVALID_STATE", 409, "Payment is not in PENDING or ISSUED")
    auth = DB["authorizations"].get(payment["authorization_id"])
    was_issued = payment["status"] == "ISSUED"
    payment["status"] = "VOIDED"
    touch(payment)
    provider = DB["providers"].get(payment["provider_id"])
    if was_issued:
        if auth is not None:
            case = DB["cases"].get(auth["case_id"])
            if case is not None:
                touch(case)  # paid -> committed
        if provider is not None:
            touch(provider)  # ledger_paid decrement
    else:
        if provider is not None:
            touch(provider)  # pending decrement
    return success(ser_payment(payment))


# ===========================================================================
# Routes: Placement
# ===========================================================================
@app.route("/vr/placements", methods=["POST"])
def create_placement():
    actor = get_actor()
    require_role(actor, {"Counselor"})
    body = get_body()
    case_id = v_str(body, "case_id")
    ipe_id = v_str(body, "ipe_id")
    employer_name = v_str(body, "employer_name")
    placement_date = v_date(body, "placement_date")
    weekly_wage = v_int(body, "weekly_wage_cents")
    hours = v_int(body, "hours_per_week")
    employment_type = v_enum(body, "employment_type", EMPLOYMENT_TYPES)
    case = get_or_404("cases", case_id)
    get_or_404("ipes", ipe_id)
    ensure_case_owner(case, actor)
    if case["status"] != "SERVICES_ACTIVE":
        err("ERR_INVALID_STATE", 409, "Case is not in SERVICES_ACTIVE")
    ipe = most_recent_ipe(case["id"])
    if ipe is None or ipe["status"] != "APPROVED":
        err("ERR_IPE_NOT_APPROVED", 409, "The case's most recent IPE is not APPROVED")
    ts = now_ts()
    rec = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "_seq": next_seq(), "case_id": case_id, "ipe_id": ipe_id,
        "employer_name": employer_name, "placement_date": placement_date,
        "weekly_wage_cents": weekly_wage, "hours_per_week": hours,
        "employment_type": employment_type, "status": "PLACED",
        "stabilization_start_date": None, "verified_avg_weekly_wage_cents": None,
    }
    DB["placements"][rec["id"]] = rec
    case["status"] = "EMPLOYED"
    touch(case)
    return success(ser_placement(rec), status=201)


@app.route("/vr/placements/<placement_id>", methods=["GET"])
def get_placement(placement_id):
    get_actor()
    pl = get_or_404("placements", placement_id)
    return success(ser_placement(pl))


@app.route("/vr/placements", methods=["GET"])
def list_placements():
    get_actor()
    items = list(DB["placements"].values())
    for f in ("case_id", "ipe_id", "status"):
        val = request.args.get(f)
        if val:
            items = [p for p in items if p[f] == val]
    page, pg = paginate(items)
    return success([ser_placement(p) for p in page], response_type="array",
                   pagination=pg)


def placement_owner_check(pl, actor):
    case = DB["cases"].get(pl["case_id"])
    if case is None:
        err("ERR_NOT_FOUND", 404, "Case not found")
    ensure_case_owner(case, actor)
    return case


@app.route("/vr/placements/<placement_id>/begin-stabilization", methods=["POST"])
def begin_stabilization(placement_id):
    actor = get_actor()
    require_role(actor, {"Counselor"})
    pl = get_or_404("placements", placement_id)
    placement_owner_check(pl, actor)
    if pl["status"] != "PLACED":
        err("ERR_INVALID_STATE", 409, "Placement is not in PLACED")
    if pl["employment_type"] not in ("COMPETITIVE_INTEGRATED", "SUPPORTED"):
        err("ERR_PLACEMENT_TYPE_INVALID", 409,
            "employment_type must be COMPETITIVE_INTEGRATED or SUPPORTED")
    pl["status"] = "STABILIZING"
    pl["stabilization_start_date"] = clock_date().isoformat()
    touch(pl)
    return success(ser_placement(pl))


@app.route("/vr/placements/<placement_id>/report-loss", methods=["POST"])
def report_loss(placement_id):
    actor = get_actor()
    require_role(actor, {"Counselor"})
    pl = get_or_404("placements", placement_id)
    placement_owner_check(pl, actor)
    if pl["status"] != "STABILIZING":
        err("ERR_INVALID_STATE", 409, "Placement is not in STABILIZING")
    pl["status"] = "DESTABILIZED"
    touch(pl)
    return success(ser_placement(pl))


@app.route("/vr/placements/<placement_id>/resume", methods=["POST"])
def resume_placement(placement_id):
    actor = get_actor()
    require_role(actor, {"Counselor"})
    pl = get_or_404("placements", placement_id)
    placement_owner_check(pl, actor)
    if pl["status"] != "DESTABILIZED":
        err("ERR_INVALID_STATE", 409, "Placement is not in DESTABILIZED")
    pl["status"] = "STABILIZING"
    pl["stabilization_start_date"] = clock_date().isoformat()
    touch(pl)
    return success(ser_placement(pl))


@app.route("/vr/placements/<placement_id>/verify-stability", methods=["POST"])
def verify_stability(placement_id):
    actor = get_actor()
    require_role(actor, {"Counselor"})
    pl = get_or_404("placements", placement_id)
    case = placement_owner_check(pl, actor)
    if pl["status"] != "STABILIZING":
        err("ERR_INVALID_STATE", 409, "Placement is not in STABILIZING")
    if placement_days_stable(pl) < 90:
        err("ERR_STABILIZATION_NOT_MET", 409, "days_stable is less than 90")
    # compute verified average weekly wage over the current window
    start = date.fromisoformat(pl["stabilization_start_date"])
    now_d = clock_date()
    wages = []
    for pr in DB["progress_reviews"].values():
        if pr["placement_id"] != pl["id"]:
            continue
        rd = date.fromisoformat(pr["review_date"])
        if start <= rd <= now_d:
            wages.append(pr["reported_weekly_wage_cents"])
    if not wages:
        pl["verified_avg_weekly_wage_cents"] = None
    else:
        pl["verified_avg_weekly_wage_cents"] = rhu(
            Decimal(sum(wages)) / Decimal(len(wages)))
    pl["status"] = "STABLE"
    touch(pl)
    if case is not None and case["status"] == "EMPLOYED":
        close_case_rehab(case)
    return success(ser_placement(pl))


# ===========================================================================
# Routes: ProgressReview
# ===========================================================================
@app.route("/vr/progress-reviews", methods=["POST"])
def create_progress_review():
    actor = get_actor()
    require_role(actor, {"Counselor"})
    body = get_body()
    placement_id = v_str(body, "placement_id")
    review_date = v_date(body, "review_date")
    reported_wage = v_int(body, "reported_weekly_wage_cents")
    status_ok = v_bool(body, "status_ok", required=False, default=True)
    pl = get_or_404("placements", placement_id)
    placement_owner_check(pl, actor)
    rec = {
        "id": new_id(), "created_at": now_ts(), "_seq": next_seq(),
        "placement_id": placement_id, "review_date": review_date,
        "reported_weekly_wage_cents": reported_wage, "status_ok": status_ok,
    }
    DB["progress_reviews"][rec["id"]] = rec
    return success(ser_progress(rec), status=201)


@app.route("/vr/placements/<placement_id>/progress-reviews", methods=["GET"])
def list_progress_reviews(placement_id):
    get_actor()
    get_or_404("placements", placement_id)
    items = [pr for pr in DB["progress_reviews"].values()
             if pr["placement_id"] == placement_id]
    page, pg = paginate(items)
    return success([ser_progress(pr) for pr in page], response_type="array",
                   pagination=pg)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
