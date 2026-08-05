"""WIOA Workforce & Job-Training (One-Stop) API — Python + Flask reference implementation.

In-memory store, empty on every boot. All amounts are integer cents. All
system timestamps are governed by a logical clock (default 2026-05-01T00:00:00Z).
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0)
STATE = {"clock": DEFAULT_CLOCK}


def parse_iso(s):
    """Parse an ISO-8601 instant into a naive UTC datetime."""
    if not isinstance(s, str) or not s.strip():
        raise ValueError("bad datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def fmt(dt):
    """Format a naive UTC datetime as ISO-8601 with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt(STATE["clock"])


# ---------------------------------------------------------------------------
# In-memory collections (empty on boot — NEVER seeded)
# ---------------------------------------------------------------------------
local_areas = {}
participants = {}
career_plans = {}
training_providers = {}
training_programs = {}
ita_vouchers = {}
ita_disbursements = {}
supportive_payments = {}
employers = {}
ojt_contracts = {}
job_referrals = {}

_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_id():
    return str(uuid.uuid4())


def common_fields():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Errors & response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta(extra=None):
    m = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok_object(data, code=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), code


def ok_array(items, page_meta, code=200):
    return jsonify({"meta": meta(page_meta), "response_type": "array", "data": items}), code


def err_response(error_id, message, http_status):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message or error_id}}
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return err_response("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def _handle_405(e):
    return err_response("ERR_NOT_FOUND", "resource not found", 404)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
VALID_ROLES = {"StateAdmin", "CaseManager", "FiscalOfficer", "BusinessServicesRep"}


def authorize(allowed):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "missing or invalid user context headers")
    if "Any" not in allowed and role not in allowed:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "role not permitted for this operation")
    return role


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def body():
    return request.get_json(silent=True, force=True) or {}


def _bad(name, why="invalid"):
    raise ApiError("ERR_INVALID_REQUEST", 400, f"{name} {why}")


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or v == "":
        _bad(name, "is required")
    return v


def opt_str(data, name, default=None):
    v = data.get(name, default)
    if v is None:
        return default
    if not isinstance(v, str):
        _bad(name, "must be a string")
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(data, name, positive=False, nonneg=False):
    v = data.get(name)
    if not is_int(v):
        _bad(name, "must be an integer")
    if positive and v <= 0:
        _bad(name, "must be positive")
    if nonneg and v < 0:
        _bad(name, "must be non-negative")
    return v


def opt_int(data, name, positive=False, default=None):
    if name not in data or data.get(name) is None:
        return default
    return req_int(data, name, positive=positive)


def req_number(data, name, positive=False):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name, "must be a number")
    if positive and v <= 0:
        _bad(name, "must be positive")
    return v


def req_bool(data, name, default=False):
    if name not in data or data.get(name) is None:
        return default
    v = data.get(name)
    if not isinstance(v, bool):
        _bad(name, "must be a boolean")
    return v


def req_enum(data, name, choices):
    v = data.get(name)
    if v not in choices:
        _bad(name, "is not a valid value")
    return v


def req_date(data, name):
    v = data.get(name)
    if not isinstance(v, str):
        _bad(name, "must be a datetime string")
    try:
        dt = parse_iso(v)
    except Exception:
        _bad(name, "is not a valid datetime")
    return v, dt


def get_or_404(coll, ident):
    if not isinstance(ident, str):
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    rec = coll.get(ident)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    return rec


# ---------------------------------------------------------------------------
# Pagination & listing
# ---------------------------------------------------------------------------
def paginate(items):
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    limit = 10
    raw = request.args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    offset = 0
    raw = request.args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    page_meta = {"limit": limit, "offset": offset, "total_count": total,
                 "has_more": offset + limit < total}
    return page, page_meta


# ---------------------------------------------------------------------------
# Serializers (explicit field lists — no internal leakage)
# ---------------------------------------------------------------------------
def s_common(rec, keys):
    out = {"id": rec["id"]}
    for k in keys:
        out[k] = rec[k]
    out["created_at"] = rec["created_at"]
    out["updated_at"] = rec["updated_at"]
    out["version"] = rec["version"]
    return out


def s_local_area(r):
    return s_common(r, ["name", "program_year", "ita_budget_total_cents",
                        "ita_individual_cap_cents", "supportive_annual_cap_cents",
                        "ita_budget_available_cents", "ita_budget_obligated_cents",
                        "ita_budget_expended_cents"])


def s_participant(r):
    return s_common(r, ["local_area_id", "full_name", "funding_stream", "veteran",
                        "low_income", "basic_skills_deficient", "priority_of_service",
                        "eligibility_status", "enrollment_status", "exit_date",
                        "exit_exclusion", "supportive_available_cents",
                        "supportive_obligated_cents", "supportive_expended_cents",
                        "credential_attained", "msg_attained"])


def s_career_plan(r):
    return s_common(r, ["participant_id", "goal_occupation", "service_track",
                        "supportive_need_documented", "revision_count", "status"])


def s_provider(r):
    return s_common(r, ["local_area_id", "name", "etpl_status"])


def s_program(r):
    return s_common(r, ["provider_id", "name", "cip_code", "total_cost_cents",
                        "credential_type", "in_demand", "status"])


def s_voucher(r):
    return s_common(r, ["participant_id", "program_id", "career_plan_id",
                        "authorized_cost_cents", "planned_start_date", "planned_end_date",
                        "amount_obligated_cents", "amount_expended_cents",
                        "credential_earned", "status"])


def s_disbursement(r):
    return {"id": r["id"], "voucher_id": r["voucher_id"], "amount_cents": r["amount_cents"],
            "note": r["note"], "created_at": r["created_at"]}


def s_supportive(r):
    return s_common(r, ["participant_id", "service_type", "amount_cents", "trips",
                        "computed_amount_cents", "status"])


def s_employer(r):
    return s_common(r, ["local_area_id", "name", "size", "max_concurrent_ojt_slots"])


def s_ojt(r):
    return s_common(r, ["employer_id", "participant_id", "reimbursement_rate",
                        "wage_cents_per_hour", "planned_hours", "obligated_amount_cents",
                        "amount_expended_cents", "start_date", "end_date", "status"])


def s_referral(r):
    return s_common(r, ["participant_id", "employer_id", "job_title",
                        "offered_wage_cents_per_hour", "placement_wage_cents_per_hour",
                        "placement_date", "status"])


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
MILEAGE_RATE = Decimal("65.5")
SMALL_CEILING = Decimal("0.75")
LARGE_CEILING = Decimal("0.50")


def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate4(num, den):
    if den == 0:
        return 0.0
    return float((Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"),
                                                         rounding=ROUND_HALF_UP))


def overlaps(a_start, a_end, b_start, b_end):
    # half-open: a.start < b.end AND b.start < a.end
    return a_start < b_end and b_start < a_end


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/wioa/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(["StateAdmin"])
    data = body()
    raw = data.get("to_iso8601")
    if not isinstance(raw, str):
        _bad("to_iso8601", "is required")
    try:
        STATE["clock"] = parse_iso(raw)
    except Exception:
        _bad("to_iso8601", "is not a valid datetime")
    return ok_object({}, 200)


# ===========================================================================
# LocalArea
# ===========================================================================
@app.route("/wioa/local-areas", methods=["POST"])
def create_local_area():
    authorize(["StateAdmin"])
    data = body()
    name = req_str(data, "name")
    program_year = req_int(data, "program_year")
    total = req_int(data, "ita_budget_total_cents", nonneg=True)
    ind_cap = req_int(data, "ita_individual_cap_cents", nonneg=True)
    sup_cap = req_int(data, "supportive_annual_cap_cents", nonneg=True)
    rec = common_fields()
    rec.update({
        "name": name, "program_year": program_year,
        "ita_budget_total_cents": total, "ita_individual_cap_cents": ind_cap,
        "supportive_annual_cap_cents": sup_cap,
        "ita_budget_available_cents": total, "ita_budget_obligated_cents": 0,
        "ita_budget_expended_cents": 0,
    })
    local_areas[rec["id"]] = rec
    return ok_object(s_local_area(rec), 201)


@app.route("/wioa/local-areas/<area_id>", methods=["GET"])
def get_local_area(area_id):
    authorize(["Any"])
    return ok_object(s_local_area(get_or_404(local_areas, area_id)), 200)


@app.route("/wioa/local-areas/<area_id>/participants", methods=["GET"])
def list_area_participants(area_id):
    authorize(["Any"])
    get_or_404(local_areas, area_id)
    items = [p for p in participants.values() if p["local_area_id"] == area_id]
    fs = request.args.get("funding_stream")
    if fs is not None:
        items = [p for p in items if p["funding_stream"] == fs]
    es = request.args.get("eligibility_status")
    if es is not None:
        items = [p for p in items if p["eligibility_status"] == es]
    ens = request.args.get("enrollment_status")
    if ens is not None:
        items = [p for p in items if p["enrollment_status"] == ens]
    page, pm = paginate(items)
    return ok_array([s_participant(p) for p in page], pm, 200)


@app.route("/wioa/local-areas/<area_id>/performance-summary", methods=["GET"])
def performance_summary(area_id):
    authorize(["Any"])
    get_or_404(local_areas, area_id)
    exiters = [p for p in participants.values()
               if p["local_area_id"] == area_id and p["enrollment_status"] == "EXITED"]
    exiter_count = len(exiters)
    excluded = [p for p in exiters if p["exit_exclusion"]]
    included = [p for p in exiters if not p["exit_exclusion"]]
    excluded_count = len(excluded)
    included_count = len(included)
    credential_count = sum(1 for p in included if p["credential_attained"])
    placement_count = 0
    for p in included:
        if any(r["participant_id"] == p["id"] and r["status"] == "PLACED"
               for r in job_referrals.values()):
            placement_count += 1
    data = {
        "raw_credential_rate": rate4(credential_count, exiter_count),
        "adjusted_credential_rate": rate4(credential_count, included_count),
        "placement_rate": rate4(placement_count, included_count),
        "exiter_count": exiter_count,
        "excluded_count": excluded_count,
        "included_count": included_count,
        "credential_count": credential_count,
        "placement_count": placement_count,
    }
    return ok_object(data, 200)


# ===========================================================================
# Participant
# ===========================================================================
def compute_priority(funding_stream, veteran, low_income, basic_skills_deficient):
    if funding_stream == "ADULT" and (veteran or low_income or basic_skills_deficient):
        return "PRIORITY"
    if veteran:
        return "PRIORITY"
    return "NON_PRIORITY"


@app.route("/wioa/local-areas/<area_id>/participants", methods=["POST"])
def intake_participant(area_id):
    authorize(["CaseManager"])
    area = get_or_404(local_areas, area_id)
    data = body()
    full_name = req_str(data, "full_name")
    funding_stream = req_enum(data, "funding_stream", {"ADULT", "DISLOCATED_WORKER", "YOUTH"})
    veteran = req_bool(data, "veteran", False)
    low_income = req_bool(data, "low_income", False)
    bsd = req_bool(data, "basic_skills_deficient", False)
    rec = common_fields()
    rec.update({
        "local_area_id": area_id, "full_name": full_name, "funding_stream": funding_stream,
        "veteran": veteran, "low_income": low_income, "basic_skills_deficient": bsd,
        "priority_of_service": compute_priority(funding_stream, veteran, low_income, bsd),
        "eligibility_status": "PENDING", "enrollment_status": "NOT_ENROLLED",
        "exit_date": None, "exit_exclusion": False,
        "supportive_available_cents": area["supportive_annual_cap_cents"],
        "supportive_obligated_cents": 0, "supportive_expended_cents": 0,
        "credential_attained": False, "msg_attained": False,
    })
    participants[rec["id"]] = rec
    return ok_object(s_participant(rec), 201)


@app.route("/wioa/participants/<pid>", methods=["GET"])
def get_participant(pid):
    authorize(["Any"])
    return ok_object(s_participant(get_or_404(participants, pid)), 200)


@app.route("/wioa/participants/<pid>/determine-eligibility", methods=["POST"])
def determine_eligibility(pid):
    authorize(["CaseManager"])
    p = get_or_404(participants, pid)
    data = body()
    decision = req_enum(data, "decision", {"ELIGIBLE", "INELIGIBLE"})
    if p["eligibility_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "eligibility not PENDING")
    p["eligibility_status"] = decision
    touch(p)
    return ok_object(s_participant(p), 200)


@app.route("/wioa/participants/<pid>/enroll", methods=["POST"])
def enroll_participant(pid):
    authorize(["CaseManager"])
    p = get_or_404(participants, pid)
    if p["eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_PARTICIPANT_NOT_ELIGIBLE", 409, "participant not eligible")
    if p["enrollment_status"] != "NOT_ENROLLED":
        raise ApiError("ERR_INVALID_STATE", 409, "enrollment not NOT_ENROLLED")
    p["enrollment_status"] = "ENROLLED"
    touch(p)
    return ok_object(s_participant(p), 200)


@app.route("/wioa/participants/<pid>/exit", methods=["POST"])
def exit_participant(pid):
    authorize(["CaseManager"])
    p = get_or_404(participants, pid)
    data = body()
    exclusion = req_bool(data, "exit_exclusion", False)
    if p["enrollment_status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", 409, "enrollment not ENROLLED")
    p["enrollment_status"] = "EXITED"
    p["exit_date"] = now_iso()
    p["exit_exclusion"] = exclusion
    touch(p)
    area = local_areas.get(p["local_area_id"])
    # CASCADE hop 1: close ACTIVE/UNDER_REVISION career plans
    plans = sorted([cp for cp in career_plans.values()
                    if cp["participant_id"] == pid and cp["status"] in ("ACTIVE", "UNDER_REVISION")],
                   key=lambda r: r["_seq"])
    for plan in plans:
        plan["status"] = "CLOSED"
        touch(plan)
        # hop 2: cancel OBLIGATED vouchers referencing this plan, release remainder
        vs = sorted([v for v in ita_vouchers.values()
                     if v["participant_id"] == pid and v["career_plan_id"] == plan["id"]
                     and v["status"] == "OBLIGATED"], key=lambda r: r["_seq"])
        for v in vs:
            remainder = v["amount_obligated_cents"] - v["amount_expended_cents"]
            if area is not None:
                area["ita_budget_obligated_cents"] -= remainder
                area["ita_budget_available_cents"] += remainder
                touch(area)
            v["status"] = "CANCELLED"
            touch(v)
    # fan-out: void REQUESTED/APPROVED supportive payments
    pays = sorted([sp for sp in supportive_payments.values()
                   if sp["participant_id"] == pid and sp["status"] in ("REQUESTED", "APPROVED")],
                  key=lambda r: r["_seq"])
    for sp in pays:
        if sp["status"] == "APPROVED":
            amt = sp["computed_amount_cents"]
            p["supportive_obligated_cents"] -= amt
            p["supportive_available_cents"] += amt
            touch(p)
        sp["status"] = "VOIDED"
        touch(sp)
    return ok_object(s_participant(p), 200)


# ===========================================================================
# CareerPlan
# ===========================================================================
@app.route("/wioa/participants/<pid>/career-plans", methods=["POST"])
def create_career_plan(pid):
    authorize(["CaseManager"])
    get_or_404(participants, pid)
    data = body()
    goal = req_str(data, "goal_occupation")
    track = req_enum(data, "service_track", {"TRAINING", "JOB_READY", "OJT"})
    need = req_bool(data, "supportive_need_documented", False)
    rec = common_fields()
    rec.update({"participant_id": pid, "goal_occupation": goal, "service_track": track,
                "supportive_need_documented": need, "revision_count": 0, "status": "DRAFT"})
    career_plans[rec["id"]] = rec
    return ok_object(s_career_plan(rec), 201)


@app.route("/wioa/participants/<pid>/career-plans", methods=["GET"])
def list_career_plans(pid):
    authorize(["Any"])
    get_or_404(participants, pid)
    items = [cp for cp in career_plans.values() if cp["participant_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [cp for cp in items if cp["status"] == st]
    page, pm = paginate(items)
    return ok_array([s_career_plan(cp) for cp in page], pm, 200)


@app.route("/wioa/career-plans/<cpid>", methods=["GET"])
def get_career_plan(cpid):
    authorize(["Any"])
    return ok_object(s_career_plan(get_or_404(career_plans, cpid)), 200)


@app.route("/wioa/career-plans/<cpid>/activate", methods=["POST"])
def activate_career_plan(cpid):
    authorize(["CaseManager"])
    cp = get_or_404(career_plans, cpid)
    if cp["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "plan not DRAFT")
    p = participants.get(cp["participant_id"])
    if p is None or p["eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_PARTICIPANT_NOT_ELIGIBLE", 409, "participant not eligible")
    cp["status"] = "ACTIVE"
    touch(cp)
    return ok_object(s_career_plan(cp), 200)


@app.route("/wioa/career-plans/<cpid>/request-revision", methods=["POST"])
def request_revision(cpid):
    authorize(["CaseManager"])
    cp = get_or_404(career_plans, cpid)
    if cp["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "plan not ACTIVE")
    cp["status"] = "UNDER_REVISION"
    touch(cp)
    return ok_object(s_career_plan(cp), 200)


@app.route("/wioa/career-plans/<cpid>/approve-revision", methods=["POST"])
def approve_revision(cpid):
    authorize(["CaseManager"])
    cp = get_or_404(career_plans, cpid)
    if cp["status"] != "UNDER_REVISION":
        raise ApiError("ERR_INVALID_STATE", 409, "plan not UNDER_REVISION")
    cp["status"] = "ACTIVE"
    cp["revision_count"] += 1
    touch(cp)
    return ok_object(s_career_plan(cp), 200)


# ===========================================================================
# TrainingProvider (ETPL)
# ===========================================================================
@app.route("/wioa/local-areas/<area_id>/training-providers", methods=["POST"])
def create_provider(area_id):
    authorize(["StateAdmin"])
    get_or_404(local_areas, area_id)
    data = body()
    name = req_str(data, "name")
    rec = common_fields()
    rec.update({"local_area_id": area_id, "name": name, "etpl_status": "APPLIED"})
    training_providers[rec["id"]] = rec
    return ok_object(s_provider(rec), 201)


@app.route("/wioa/training-providers/<prov_id>", methods=["GET"])
def get_provider(prov_id):
    authorize(["Any"])
    return ok_object(s_provider(get_or_404(training_providers, prov_id)), 200)


@app.route("/wioa/training-providers", methods=["GET"])
def list_providers():
    authorize(["Any"])
    items = list(training_providers.values())
    la = request.args.get("local_area_id")
    if la is not None:
        items = [p for p in items if p["local_area_id"] == la]
    st = request.args.get("etpl_status")
    if st is not None:
        items = [p for p in items if p["etpl_status"] == st]
    page, pm = paginate(items)
    return ok_array([s_provider(p) for p in page], pm, 200)


@app.route("/wioa/training-providers/<prov_id>/approve", methods=["POST"])
def approve_provider(prov_id):
    authorize(["StateAdmin"])
    prov = get_or_404(training_providers, prov_id)
    if prov["etpl_status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE", 409, "provider not APPLIED")
    prov["etpl_status"] = "ELIGIBLE"
    touch(prov)
    return ok_object(s_provider(prov), 200)


@app.route("/wioa/training-providers/<prov_id>/suspend", methods=["POST"])
def suspend_provider(prov_id):
    authorize(["StateAdmin"])
    prov = get_or_404(training_providers, prov_id)
    if prov["etpl_status"] != "ELIGIBLE":
        raise ApiError("ERR_INVALID_STATE", 409, "provider not ELIGIBLE")
    prov["etpl_status"] = "SUSPENDED"
    touch(prov)
    # CASCADE hop 1: ACTIVE programs -> SUSPENDED
    progs = sorted([pr for pr in training_programs.values()
                    if pr["provider_id"] == prov_id and pr["status"] == "ACTIVE"],
                   key=lambda r: r["_seq"])
    for pr in progs:
        pr["status"] = "SUSPENDED"
        touch(pr)
        # hop 2: DRAFT vouchers referencing this program -> CANCELLED (no funds move)
        vs = sorted([v for v in ita_vouchers.values()
                     if v["program_id"] == pr["id"] and v["status"] == "DRAFT"],
                    key=lambda r: r["_seq"])
        for v in vs:
            v["status"] = "CANCELLED"
            touch(v)
    return ok_object(s_provider(prov), 200)


# ===========================================================================
# TrainingProgram
# ===========================================================================
@app.route("/wioa/training-providers/<prov_id>/programs", methods=["POST"])
def create_program(prov_id):
    authorize(["StateAdmin"])
    get_or_404(training_providers, prov_id)
    data = body()
    name = req_str(data, "name")
    cip = req_str(data, "cip_code")
    total = req_int(data, "total_cost_cents", nonneg=True)
    ctype = req_enum(data, "credential_type", {"DEGREE", "CERTIFICATE", "LICENSE", "NONE"})
    in_demand = req_bool(data, "in_demand", True)
    rec = common_fields()
    rec.update({"provider_id": prov_id, "name": name, "cip_code": cip,
                "total_cost_cents": total, "credential_type": ctype,
                "in_demand": in_demand, "status": "ACTIVE"})
    training_programs[rec["id"]] = rec
    return ok_object(s_program(rec), 201)


@app.route("/wioa/training-programs/<prog_id>", methods=["GET"])
def get_program(prog_id):
    authorize(["Any"])
    return ok_object(s_program(get_or_404(training_programs, prog_id)), 200)


@app.route("/wioa/training-providers/<prov_id>/programs", methods=["GET"])
def list_programs(prov_id):
    authorize(["Any"])
    get_or_404(training_providers, prov_id)
    items = [pr for pr in training_programs.values() if pr["provider_id"] == prov_id]
    st = request.args.get("status")
    if st is not None:
        items = [pr for pr in items if pr["status"] == st]
    page, pm = paginate(items)
    return ok_array([s_program(pr) for pr in page], pm, 200)


# ===========================================================================
# ITAVoucher
# ===========================================================================
@app.route("/wioa/participants/<pid>/ita-vouchers", methods=["POST"])
def create_voucher(pid):
    authorize(["CaseManager"])
    get_or_404(participants, pid)
    data = body()
    program_id = data.get("program_id")
    career_plan_id = data.get("career_plan_id")
    if not isinstance(program_id, str) or program_id == "":
        _bad("program_id", "is required")
    if not isinstance(career_plan_id, str) or career_plan_id == "":
        _bad("career_plan_id", "is required")
    program = get_or_404(training_programs, program_id)
    get_or_404(career_plans, career_plan_id)
    authorized = req_int(data, "authorized_cost_cents", positive=True)
    start_raw, start_dt = req_date(data, "planned_start_date")
    end_raw, end_dt = req_date(data, "planned_end_date")
    if not end_dt > start_dt:
        _bad("planned_end_date", "must be after planned_start_date")
    if authorized > program["total_cost_cents"]:
        _bad("authorized_cost_cents", "exceeds program total_cost_cents")
    rec = common_fields()
    rec.update({"participant_id": pid, "program_id": program_id,
                "career_plan_id": career_plan_id, "authorized_cost_cents": authorized,
                "planned_start_date": start_raw, "planned_end_date": end_raw,
                "amount_obligated_cents": 0, "amount_expended_cents": 0,
                "credential_earned": False, "status": "DRAFT"})
    ita_vouchers[rec["id"]] = rec
    return ok_object(s_voucher(rec), 201)


@app.route("/wioa/ita-vouchers/<vid>", methods=["GET"])
def get_voucher(vid):
    authorize(["Any"])
    return ok_object(s_voucher(get_or_404(ita_vouchers, vid)), 200)


@app.route("/wioa/ita-vouchers", methods=["GET"])
def list_vouchers():
    authorize(["Any"])
    items = list(ita_vouchers.values())
    for key in ("participant_id", "program_id", "career_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v[key] == val]
    page, pm = paginate(items)
    return ok_array([s_voucher(v) for v in page], pm, 200)


@app.route("/wioa/ita-vouchers/<vid>/obligate", methods=["POST"])
def obligate_voucher(vid):
    authorize(["CaseManager"])
    v = get_or_404(ita_vouchers, vid)
    data = body()
    expected_version = req_int(data, "expected_local_area_version")
    p = participants.get(v["participant_id"])
    area = local_areas.get(p["local_area_id"]) if p else None
    plan = career_plans.get(v["career_plan_id"])
    program = training_programs.get(v["program_id"])
    # ordered preconditions
    if v["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "voucher not DRAFT")
    if p is None or p["enrollment_status"] != "ENROLLED":
        raise ApiError("ERR_PARTICIPANT_NOT_ENROLLED", 409, "participant not enrolled")
    if plan is None or plan["status"] != "ACTIVE":
        raise ApiError("ERR_NO_ACTIVE_CAREER_PLAN", 409, "referenced career plan not ACTIVE")
    if program is None or program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ELIGIBLE", 409, "referenced program not ACTIVE")
    a_start = parse_iso(v["planned_start_date"])
    a_end = parse_iso(v["planned_end_date"])
    for other in ita_vouchers.values():
        if other["id"] == vid or other["participant_id"] != v["participant_id"]:
            continue
        if other["status"] != "OBLIGATED":
            continue
        b_start = parse_iso(other["planned_start_date"])
        b_end = parse_iso(other["planned_end_date"])
        if overlaps(a_start, a_end, b_start, b_end):
            raise ApiError("ERR_TRAINING_PERIOD_OVERLAP", 409, "training period overlap")
    if v["authorized_cost_cents"] > area["ita_individual_cap_cents"]:
        raise ApiError("ERR_ITA_CAP_EXCEEDED", 409, "authorized cost exceeds individual cap")
    if v["authorized_cost_cents"] > area["ita_budget_available_cents"]:
        raise ApiError("ERR_ITA_BUDGET_EXCEEDED", 409, "authorized cost exceeds available budget")
    if expected_version != area["version"]:
        raise ApiError("ERR_STALE_LOCAL_AREA_VERSION", 412, "stale local area version")
    # side effects
    cost = v["authorized_cost_cents"]
    v["status"] = "OBLIGATED"
    v["amount_obligated_cents"] = cost
    touch(v)
    area["ita_budget_available_cents"] -= cost
    area["ita_budget_obligated_cents"] += cost
    touch(area)
    return ok_object(s_voucher(v), 200)


@app.route("/wioa/ita-vouchers/<vid>/disburse", methods=["POST"])
def disburse_voucher(vid):
    authorize(["FiscalOfficer"])
    v = get_or_404(ita_vouchers, vid)
    data = body()
    amount = req_int(data, "amount_cents", positive=True)
    note = opt_str(data, "note", None)
    if v["status"] != "OBLIGATED":
        raise ApiError("ERR_INVALID_STATE", 409, "voucher not OBLIGATED")
    remaining = v["amount_obligated_cents"] - v["amount_expended_cents"]
    if amount > remaining:
        raise ApiError("ERR_DISBURSEMENT_EXCEEDS_OBLIGATION", 409,
                       "disbursement exceeds unexpended obligation")
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": next_seq(),
           "voucher_id": vid, "amount_cents": amount, "note": note}
    ita_disbursements[rec["id"]] = rec
    v["amount_expended_cents"] += amount
    touch(v)
    area = local_areas.get(participants[v["participant_id"]]["local_area_id"])
    if area is not None:
        area["ita_budget_obligated_cents"] -= amount
        area["ita_budget_expended_cents"] += amount
        touch(area)
    return ok_object(s_disbursement(rec), 201)


@app.route("/wioa/ita-vouchers/<vid>/disbursements", methods=["GET"])
def list_disbursements(vid):
    authorize(["Any"])
    get_or_404(ita_vouchers, vid)
    items = [d for d in ita_disbursements.values() if d["voucher_id"] == vid]
    page, pm = paginate(items)
    return ok_array([s_disbursement(d) for d in page], pm, 200)


@app.route("/wioa/ita-vouchers/<vid>/complete", methods=["POST"])
def complete_voucher(vid):
    authorize(["CaseManager"])
    v = get_or_404(ita_vouchers, vid)
    data = body()
    credential = req_bool(data, "credential_earned", None) if "credential_earned" in data else None
    if credential is None:
        _bad("credential_earned", "is required")
    if v["status"] != "OBLIGATED":
        raise ApiError("ERR_INVALID_STATE", 409, "voucher not OBLIGATED")
    remainder = v["amount_obligated_cents"] - v["amount_expended_cents"]
    v["status"] = "COMPLETED"
    v["credential_earned"] = credential
    touch(v)
    area = local_areas.get(participants[v["participant_id"]]["local_area_id"])
    if area is not None:
        area["ita_budget_obligated_cents"] -= remainder
        area["ita_budget_available_cents"] += remainder
        touch(area)
    p = participants.get(v["participant_id"])
    if p is not None:
        p["credential_attained"] = credential
        p["msg_attained"] = True
        touch(p)
    return ok_object(s_voucher(v), 200)


@app.route("/wioa/ita-vouchers/<vid>/cancel", methods=["POST"])
def cancel_voucher(vid):
    authorize(["CaseManager"])
    v = get_or_404(ita_vouchers, vid)
    if v["status"] not in ("DRAFT", "OBLIGATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "voucher not DRAFT or OBLIGATED")
    if v["status"] == "OBLIGATED":
        remainder = v["amount_obligated_cents"] - v["amount_expended_cents"]
        area = local_areas.get(participants[v["participant_id"]]["local_area_id"])
        if area is not None:
            area["ita_budget_obligated_cents"] -= remainder
            area["ita_budget_available_cents"] += remainder
            touch(area)
    v["status"] = "CANCELLED"
    touch(v)
    return ok_object(s_voucher(v), 200)


# ===========================================================================
# SupportiveServicePayment
# ===========================================================================
@app.route("/wioa/participants/<pid>/supportive-services", methods=["POST"])
def create_supportive(pid):
    authorize(["CaseManager"])
    get_or_404(participants, pid)
    data = body()
    service_type = req_enum(data, "service_type", {"MILEAGE", "CHILDCARE", "TOOLS", "OTHER"})
    amount_cents = None
    trips = None
    if service_type == "MILEAGE":
        trips = data.get("trips")
        if not isinstance(trips, list) or len(trips) == 0:
            _bad("trips", "must be a non-empty array")
        total = 0
        for t in trips:
            if not is_int(t) or t <= 0:
                _bad("trips", "each trip must be a whole number of miles > 0")
            total += round_half_up(Decimal(t) * MILEAGE_RATE)
        computed = total
    else:
        amount_cents = req_int(data, "amount_cents", positive=True)
        computed = amount_cents
    rec = common_fields()
    rec.update({"participant_id": pid, "service_type": service_type,
                "amount_cents": amount_cents, "trips": trips,
                "computed_amount_cents": computed, "status": "REQUESTED"})
    supportive_payments[rec["id"]] = rec
    return ok_object(s_supportive(rec), 201)


@app.route("/wioa/supportive-services/<sid>", methods=["GET"])
def get_supportive(sid):
    authorize(["Any"])
    return ok_object(s_supportive(get_or_404(supportive_payments, sid)), 200)


@app.route("/wioa/participants/<pid>/supportive-services", methods=["GET"])
def list_supportive(pid):
    authorize(["Any"])
    get_or_404(participants, pid)
    items = [sp for sp in supportive_payments.values() if sp["participant_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [sp for sp in items if sp["status"] == st]
    stype = request.args.get("service_type")
    if stype is not None:
        items = [sp for sp in items if sp["service_type"] == stype]
    page, pm = paginate(items)
    return ok_array([s_supportive(sp) for sp in page], pm, 200)


@app.route("/wioa/supportive-services/<sid>/approve", methods=["POST"])
def approve_supportive(sid):
    authorize(["FiscalOfficer"])
    sp = get_or_404(supportive_payments, sid)
    if sp["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "payment not REQUESTED")
    p = participants.get(sp["participant_id"])
    has_plan = any(cp["participant_id"] == sp["participant_id"] and cp["status"] == "ACTIVE"
                   and cp["supportive_need_documented"] for cp in career_plans.values())
    if not has_plan:
        raise ApiError("ERR_NO_ACTIVE_CAREER_PLAN", 409,
                       "no ACTIVE career plan documenting supportive need")
    amt = sp["computed_amount_cents"]
    if amt > p["supportive_available_cents"]:
        raise ApiError("ERR_SUPPORTIVE_CAP_EXCEEDED", 409, "exceeds supportive available balance")
    p["supportive_available_cents"] -= amt
    p["supportive_obligated_cents"] += amt
    touch(p)
    sp["status"] = "APPROVED"
    touch(sp)
    return ok_object(s_supportive(sp), 200)


@app.route("/wioa/supportive-services/<sid>/pay", methods=["POST"])
def pay_supportive(sid):
    authorize(["FiscalOfficer"])
    sp = get_or_404(supportive_payments, sid)
    if sp["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "payment not APPROVED")
    p = participants.get(sp["participant_id"])
    amt = sp["computed_amount_cents"]
    p["supportive_obligated_cents"] -= amt
    p["supportive_expended_cents"] += amt
    touch(p)
    sp["status"] = "PAID"
    touch(sp)
    return ok_object(s_supportive(sp), 200)


@app.route("/wioa/supportive-services/<sid>/void", methods=["POST"])
def void_supportive(sid):
    authorize(["FiscalOfficer"])
    sp = get_or_404(supportive_payments, sid)
    if sp["status"] not in ("REQUESTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "payment not REQUESTED or APPROVED")
    if sp["status"] == "APPROVED":
        p = participants.get(sp["participant_id"])
        amt = sp["computed_amount_cents"]
        p["supportive_obligated_cents"] -= amt
        p["supportive_available_cents"] += amt
        touch(p)
    sp["status"] = "VOIDED"
    touch(sp)
    return ok_object(s_supportive(sp), 200)


# ===========================================================================
# Employer
# ===========================================================================
@app.route("/wioa/local-areas/<area_id>/employers", methods=["POST"])
def create_employer(area_id):
    authorize(["BusinessServicesRep"])
    get_or_404(local_areas, area_id)
    data = body()
    name = req_str(data, "name")
    size = req_enum(data, "size", {"SMALL", "LARGE"})
    max_slots = req_int(data, "max_concurrent_ojt_slots", nonneg=True)
    rec = common_fields()
    rec.update({"local_area_id": area_id, "name": name, "size": size,
                "max_concurrent_ojt_slots": max_slots})
    employers[rec["id"]] = rec
    return ok_object(s_employer(rec), 201)


@app.route("/wioa/employers/<eid>", methods=["GET"])
def get_employer(eid):
    authorize(["Any"])
    return ok_object(s_employer(get_or_404(employers, eid)), 200)


@app.route("/wioa/employers", methods=["GET"])
def list_employers():
    authorize(["Any"])
    items = list(employers.values())
    la = request.args.get("local_area_id")
    if la is not None:
        items = [e for e in items if e["local_area_id"] == la]
    sz = request.args.get("size")
    if sz is not None:
        items = [e for e in items if e["size"] == sz]
    page, pm = paginate(items)
    return ok_array([s_employer(e) for e in page], pm, 200)


# ===========================================================================
# OJTContract
# ===========================================================================
@app.route("/wioa/employers/<eid>/ojt-contracts", methods=["POST"])
def create_ojt(eid):
    authorize(["BusinessServicesRep"])
    employer = get_or_404(employers, eid)
    data = body()
    participant_id = data.get("participant_id")
    if not isinstance(participant_id, str) or participant_id == "":
        _bad("participant_id", "is required")
    get_or_404(participants, participant_id)
    rate = req_number(data, "reimbursement_rate", positive=True)
    wage = req_int(data, "wage_cents_per_hour", positive=True)
    hours = req_int(data, "planned_hours", positive=True)
    obligated = req_int(data, "obligated_amount_cents", positive=True)
    start_raw, start_dt = req_date(data, "start_date")
    end_raw, end_dt = req_date(data, "end_date")
    if not end_dt > start_dt:
        _bad("end_date", "must be after start_date")
    ceiling = SMALL_CEILING if employer["size"] == "SMALL" else LARGE_CEILING
    if Decimal(str(rate)) > ceiling:
        raise ApiError("ERR_OJT_RATE_EXCEEDED", 409, "reimbursement rate exceeds size ceiling")
    rec = common_fields()
    rec.update({"employer_id": eid, "participant_id": participant_id,
                "reimbursement_rate": rate, "wage_cents_per_hour": wage,
                "planned_hours": hours, "obligated_amount_cents": obligated,
                "amount_expended_cents": 0, "start_date": start_raw, "end_date": end_raw,
                "status": "DRAFT"})
    ojt_contracts[rec["id"]] = rec
    return ok_object(s_ojt(rec), 201)


@app.route("/wioa/ojt-contracts/<oid>", methods=["GET"])
def get_ojt(oid):
    authorize(["Any"])
    return ok_object(s_ojt(get_or_404(ojt_contracts, oid)), 200)


@app.route("/wioa/ojt-contracts", methods=["GET"])
def list_ojt():
    authorize(["Any"])
    items = list(ojt_contracts.values())
    for key in ("participant_id", "employer_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    page, pm = paginate(items)
    return ok_array([s_ojt(c) for c in page], pm, 200)


@app.route("/wioa/ojt-contracts/<oid>/activate", methods=["POST"])
def activate_ojt(oid):
    authorize(["BusinessServicesRep"])
    c = get_or_404(ojt_contracts, oid)
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "contract not DRAFT")
    p = participants.get(c["participant_id"])
    if p is None or p["eligibility_status"] != "ELIGIBLE" or p["enrollment_status"] != "ENROLLED":
        raise ApiError("ERR_PARTICIPANT_NOT_ELIGIBLE", 409, "participant not eligible/enrolled")
    employer = employers.get(c["employer_id"])
    a_start = parse_iso(c["start_date"])
    a_end = parse_iso(c["end_date"])
    overlap_count = 0
    for other in ojt_contracts.values():
        if other["id"] == oid or other["employer_id"] != c["employer_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        b_start = parse_iso(other["start_date"])
        b_end = parse_iso(other["end_date"])
        if overlaps(a_start, a_end, b_start, b_end):
            overlap_count += 1
    if overlap_count >= employer["max_concurrent_ojt_slots"]:
        raise ApiError("ERR_OJT_CAPACITY_EXCEEDED", 409, "employer OJT capacity exceeded")
    c["status"] = "ACTIVE"
    touch(c)
    return ok_object(s_ojt(c), 200)


@app.route("/wioa/ojt-contracts/<oid>/reimburse", methods=["POST"])
def reimburse_ojt(oid):
    authorize(["FiscalOfficer"])
    c = get_or_404(ojt_contracts, oid)
    data = body()
    hours = req_int(data, "hours_worked", positive=True)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "contract not ACTIVE")
    gross = round_half_up(Decimal(str(c["reimbursement_rate"])) *
                          Decimal(c["wage_cents_per_hour"]) * Decimal(hours))
    remaining = c["obligated_amount_cents"] - c["amount_expended_cents"]
    reimb = min(gross, remaining)
    c["amount_expended_cents"] += reimb
    touch(c)
    return ok_object(s_ojt(c), 200)


@app.route("/wioa/ojt-contracts/<oid>/complete", methods=["POST"])
def complete_ojt(oid):
    authorize(["BusinessServicesRep"])
    c = get_or_404(ojt_contracts, oid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "contract not ACTIVE")
    c["status"] = "COMPLETED"
    touch(c)
    return ok_object(s_ojt(c), 200)


@app.route("/wioa/ojt-contracts/<oid>/terminate", methods=["POST"])
def terminate_ojt(oid):
    authorize(["BusinessServicesRep"])
    c = get_or_404(ojt_contracts, oid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "contract not ACTIVE")
    c["status"] = "TERMINATED"
    touch(c)
    return ok_object(s_ojt(c), 200)


# ===========================================================================
# JobReferral
# ===========================================================================
@app.route("/wioa/participants/<pid>/job-referrals", methods=["POST"])
def create_referral(pid):
    authorize(["BusinessServicesRep", "CaseManager"])
    get_or_404(participants, pid)
    data = body()
    employer_id = data.get("employer_id")
    if not isinstance(employer_id, str) or employer_id == "":
        _bad("employer_id", "is required")
    get_or_404(employers, employer_id)
    job_title = req_str(data, "job_title")
    offered_wage = opt_int(data, "offered_wage_cents_per_hour", positive=True, default=None)
    rec = common_fields()
    rec.update({"participant_id": pid, "employer_id": employer_id, "job_title": job_title,
                "offered_wage_cents_per_hour": offered_wage,
                "placement_wage_cents_per_hour": None, "placement_date": None,
                "status": "REFERRED"})
    job_referrals[rec["id"]] = rec
    return ok_object(s_referral(rec), 201)


@app.route("/wioa/job-referrals/<rid>", methods=["GET"])
def get_referral(rid):
    authorize(["Any"])
    return ok_object(s_referral(get_or_404(job_referrals, rid)), 200)


@app.route("/wioa/job-referrals", methods=["GET"])
def list_referrals():
    authorize(["Any"])
    items = list(job_referrals.values())
    for key in ("participant_id", "employer_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    page, pm = paginate(items)
    return ok_array([s_referral(r) for r in page], pm, 200)


@app.route("/wioa/job-referrals/<rid>/place", methods=["POST"])
def place_referral(rid):
    authorize(["BusinessServicesRep"])
    r = get_or_404(job_referrals, rid)
    data = body()
    placement_wage = opt_int(data, "placement_wage_cents_per_hour", positive=True, default=None)
    if r["status"] != "REFERRED":
        raise ApiError("ERR_INVALID_STATE", 409, "referral not REFERRED")
    p = participants.get(r["participant_id"])
    if p is None or p["enrollment_status"] not in ("ENROLLED", "EXITED"):
        raise ApiError("ERR_PARTICIPANT_NOT_ENROLLED", 409, "participant not enrolled/exited")
    r["placement_wage_cents_per_hour"] = placement_wage
    r["placement_date"] = now_iso()
    r["status"] = "PLACED"
    touch(r)
    return ok_object(s_referral(r), 200)


@app.route("/wioa/job-referrals/<rid>/reject", methods=["POST"])
def reject_referral(rid):
    authorize(["BusinessServicesRep"])
    r = get_or_404(job_referrals, rid)
    if r["status"] != "REFERRED":
        raise ApiError("ERR_INVALID_STATE", 409, "referral not REFERRED")
    r["status"] = "REJECTED"
    touch(r)
    return ok_object(s_referral(r), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
