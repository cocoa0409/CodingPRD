"""Community Paramedicine / Mobile Integrated Health (MIH) API.

Single-file Flask implementation. All state is in-memory (wiped on every boot).
No seeding: every entity is created by clients through the declared endpoints.
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
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "payers": {},
    "programs": {},
    "providers": {},
    "patients": {},
    "referrals": {},
    "enrollments": {},
    "care_plans": {},
    "home_visits": {},
    "telehealth_sessions": {},
    "med_reconciliations": {},
    "social_referrals": {},
    "ed_events": {},
    "billing_claims": {},
}
SEQ = 0

# Logical clock: default before any call is 2026-03-01T00:00:00Z (never wall clock)
CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

KNOWN_ROLES = {
    "ProgramAdmin",
    "CareCoordinator",
    "Paramedic",
    "Clinician",
    "BillingSpecialist",
    "PayerReviewer",
}

# Risk scoring constants
W_ED = 2
W_CHRONIC = 3
W_ADMIT = 5
MOD_MIN = 10
HIGH_MIN = 20
READMISSION_WINDOW_DAYS = 30
TELEHEALTH_BUFFER_MINUTES = 15


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time / id helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_iso():
    return fmt_iso(CLOCK)


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_iso(value, field="datetime"):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be an ISO 8601 string")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(dec):
    """Round-half-up to a whole integer."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record(kind, data, versioned=True):
    global SEQ
    rid = str(uuid.uuid4())
    now = now_iso()
    rec = dict(data)
    rec["id"] = rid
    rec["created_at"] = now
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    SEQ += 1
    rec["_seq"] = SEQ
    DB[kind][rid] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_or_404(kind, rid):
    rec = DB[kind].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{kind[:-1]} {rid} not found")
    return rec


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def build_meta(pag=None):
    m = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if pag:
        m.update(pag)
    return m


def ok(data, status=200, response_type="object", pag=None):
    return jsonify({"meta": build_meta(pag), "response_type": response_type, "data": data}), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authn_authz(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return user_id, role


# ---------------------------------------------------------------------------
# Body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "request body must be a JSON object")
    return b


def require(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"missing required field: {field}")
    return body[field]


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def require_int(body, field):
    v = require(body, field)
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be an integer")
    return v


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be a string")
    return v


def require_enum(body, field, allowed):
    v = require(body, field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be one of {sorted(allowed)}")
    return v


def resolve_fk(body, field, kind, required=True):
    """Existence check (priority 3) for a body FK that is present."""
    if field in body and body[field] is not None:
        return get_or_404(kind, body[field])
    if required and (field not in body or body[field] is None):
        # Absence handled later by body validation (priority 4).
        return None
    return None


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(items):
    items = sorted(items, key=lambda r: r["_seq"])
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok([serialize(r) for r in page], 200, "array", pag)


def filter_eq(items, field, value):
    if value is None:
        return items
    return [r for r in items if r.get(field) == value]


# ---------------------------------------------------------------------------
# Domain computations
# ---------------------------------------------------------------------------
def compute_risk(patient):
    cutoff = CLOCK - timedelta(days=365)
    recent = 0
    for ev in DB["ed_events"].values():
        if ev["patient_id"] == patient["id"] and ev["event_type"] == "INPATIENT_ADMISSION":
            if parse_iso(ev["event_date"]) >= cutoff:
                recent += 1
    score = patient["baseline_ed_visits_12mo"] * W_ED \
        + patient["chronic_conditions_count"] * W_CHRONIC \
        + recent * W_ADMIT
    if score >= HIGH_MIN:
        tier = "HIGH"
    elif score >= MOD_MIN:
        tier = "MODERATE"
    else:
        tier = "LOW"
    return score, tier


def compute_readmission(patient_id, event_type, event_date_str):
    if event_type != "INPATIENT_ADMISSION":
        return False
    ed = parse_iso(event_date_str)
    for ev in DB["ed_events"].values():
        if ev["patient_id"] != patient_id:
            continue
        if ev["event_type"] != "INPATIENT_ADMISSION":
            continue
        if not ev.get("discharge_date"):
            continue
        dd = parse_iso(ev["discharge_date"])
        if dd <= ed and (ed - dd).days <= READMISSION_WINDOW_DAYS:
            return True
    return False


def compute_claim(enr, program, ps, pe, status_set):
    """Returns (amount_cents, visit_count, telehealth_count) for the given
    encounter status set (variant)."""
    visits = 0
    for hv in DB["home_visits"].values():
        if hv["enrollment_id"] == enr["id"] and hv["status"] in status_set:
            if ps <= parse_iso(hv["scheduled_start"]) < pe:
                visits += 1
    teleh = 0
    for ts in DB["telehealth_sessions"].values():
        if ts["enrollment_id"] == enr["id"] and ts["status"] in status_set:
            if ps <= parse_iso(ts["scheduled_start"]) < pe:
                teleh += 1
    base = visits * program["per_visit_rate_cents"] + teleh * program["per_telehealth_rate_cents"]

    actual_ed = 0
    readmitted = False
    for ev in DB["ed_events"].values():
        if ev["patient_id"] != enr["patient_id"]:
            continue
        ed_dt = parse_iso(ev["event_date"])
        if not (ps <= ed_dt < pe):
            continue
        if ev["event_type"] == "ED_VISIT":
            actual_ed += 1
        elif ev["event_type"] == "INPATIENT_ADMISSION" and ev.get("is_readmission"):
            readmitted = True

    diversion_achieved = actual_ed <= program["diversion_target_max_ed_visits"]
    diversion_bonus = program["diversion_bonus_cents"] if diversion_achieved else 0
    readmission_penalty = program["readmission_penalty_cents"] if readmitted else 0

    amount = base + diversion_bonus - readmission_penalty
    if amount < 0:
        amount = 0
    return amount, visits, teleh


def recompute_program_slots(program):
    program["remaining_slots"] = program["enrollment_cap"] - program["active_enrollment_count"]


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def close_care_plan(cp):
    """Transition a care plan to CLOSED and cascade-cancel its SCHEDULED home
    visits."""
    cp["status"] = "CLOSED"
    touch(cp)
    for hv in DB["home_visits"].values():
        if hv["care_plan_id"] == cp["id"] and hv["status"] == "SCHEDULED":
            hv["status"] = "CANCELLED"
            touch(hv)


def revise_care_plan(cp):
    """ACTIVE -> UNDER_REVISION with enrollment side effects."""
    cp["status"] = "UNDER_REVISION"
    touch(cp)
    enr = DB["enrollments"].get(cp["enrollment_id"])
    if enr is not None:
        enr["revision_count"] += 1
        enr["needs_review"] = True
        touch(enr)


# ===========================================================================
# Payer
# ===========================================================================
@app.route("/mih/payers", methods=["POST"])
def create_payer():
    authn_authz({"ProgramAdmin"})
    body = get_body()
    name = require_str(body, "name")
    payer_type = require_enum(body, "payer_type", {"MEDICARE", "MEDICAID", "COMMERCIAL"})
    rec = new_record("payers", {"name": name, "payer_type": payer_type})
    return ok(serialize(rec), 201)


@app.route("/mih/payers/<rid>", methods=["GET"])
def get_payer(rid):
    authn_authz({"ProgramAdmin", "CareCoordinator", "BillingSpecialist", "PayerReviewer"})
    rec = get_or_404("payers", rid)
    return ok(serialize(rec), 200)


# ===========================================================================
# PilotProgram
# ===========================================================================
@app.route("/mih/programs", methods=["POST"])
def create_program():
    authn_authz({"ProgramAdmin"})
    body = get_body()
    resolve_fk(body, "payer_id", "payers")
    name = require_str(body, "name")
    payer_id = require_str(body, "payer_id")
    budget_cap_cents = require_int(body, "budget_cap_cents")
    enrollment_cap = require_int(body, "enrollment_cap")
    per_visit_rate_cents = require_int(body, "per_visit_rate_cents")
    per_telehealth_rate_cents = require_int(body, "per_telehealth_rate_cents")
    diversion_bonus_cents = require_int(body, "diversion_bonus_cents")
    readmission_penalty_cents = require_int(body, "readmission_penalty_cents")
    diversion_target_max_ed_visits = require_int(body, "diversion_target_max_ed_visits")
    avg_ed_cost_cents = require_int(body, "avg_ed_cost_cents")
    diversion_credit_pct = require(body, "diversion_credit_pct")
    if not is_number(diversion_credit_pct):
        raise ApiError("ERR_VALIDATION", 400, "diversion_credit_pct must be a number")
    start_date = require(body, "start_date")
    end_date = require(body, "end_date")
    rec = new_record("programs", {
        "name": name,
        "payer_id": payer_id,
        "status": "ACTIVE",
        "budget_cap_cents": budget_cap_cents,
        "available_budget_cents": budget_cap_cents,
        "committed_spend_cents": 0,
        "enrollment_cap": enrollment_cap,
        "active_enrollment_count": 0,
        "remaining_slots": enrollment_cap,
        "per_visit_rate_cents": per_visit_rate_cents,
        "per_telehealth_rate_cents": per_telehealth_rate_cents,
        "diversion_bonus_cents": diversion_bonus_cents,
        "readmission_penalty_cents": readmission_penalty_cents,
        "diversion_target_max_ed_visits": diversion_target_max_ed_visits,
        "avg_ed_cost_cents": avg_ed_cost_cents,
        "diversion_credit_pct": diversion_credit_pct,
        "start_date": start_date,
        "end_date": end_date,
    })
    return ok(serialize(rec), 201)


@app.route("/mih/programs/<rid>", methods=["GET"])
def get_program(rid):
    authn_authz({"ProgramAdmin", "CareCoordinator", "BillingSpecialist", "PayerReviewer", "Clinician"})
    rec = get_or_404("programs", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/programs", methods=["GET"])
def list_programs():
    authn_authz({"ProgramAdmin", "CareCoordinator", "BillingSpecialist", "PayerReviewer"})
    items = list(DB["programs"].values())
    items = filter_eq(items, "payer_id", request.args.get("payer_id"))
    return list_response(items)


@app.route("/mih/programs/<rid>/close", methods=["POST"])
def close_program(rid):
    authn_authz({"ProgramAdmin"})
    rec = get_or_404("programs", rid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "program is not ACTIVE")
    rec["status"] = "CLOSED"
    touch(rec)
    return ok(serialize(rec), 200)


# ===========================================================================
# Provider
# ===========================================================================
@app.route("/mih/providers", methods=["POST"])
def create_provider():
    authn_authz({"ProgramAdmin"})
    body = get_body()
    full_name = require_str(body, "full_name")
    provider_type = require_enum(body, "provider_type", {"PARAMEDIC", "CLINICIAN", "COORDINATOR", "BILLER"})
    npi = require_str(body, "npi")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise ApiError("ERR_VALIDATION", 400, "active must be a boolean")
    rec = new_record("providers", {
        "full_name": full_name,
        "provider_type": provider_type,
        "npi": npi,
        "active": active,
    })
    return ok(serialize(rec), 201)


@app.route("/mih/providers/<rid>", methods=["GET"])
def get_provider(rid):
    authn_authz({"ProgramAdmin", "CareCoordinator", "Clinician", "Paramedic", "BillingSpecialist"})
    rec = get_or_404("providers", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/providers", methods=["GET"])
def list_providers():
    authn_authz({"ProgramAdmin", "CareCoordinator", "Clinician", "Paramedic", "BillingSpecialist"})
    items = list(DB["providers"].values())
    items = filter_eq(items, "provider_type", request.args.get("provider_type"))
    return list_response(items)


# ===========================================================================
# Patient
# ===========================================================================
@app.route("/mih/patients", methods=["POST"])
def create_patient():
    authn_authz({"CareCoordinator", "ProgramAdmin"})
    body = get_body()
    full_name = require_str(body, "full_name")
    date_of_birth = require_str(body, "date_of_birth")
    baseline = require_int(body, "baseline_ed_visits_12mo")
    chronic = require_int(body, "chronic_conditions_count")
    consent = body.get("consent_on_file", False)
    if not isinstance(consent, bool):
        raise ApiError("ERR_VALIDATION", 400, "consent_on_file must be a boolean")
    rec = new_record("patients", {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "baseline_ed_visits_12mo": baseline,
        "chronic_conditions_count": chronic,
        "consent_on_file": consent,
        "risk_score": 0,
        "risk_tier": "LOW",
    })
    score, tier = compute_risk(rec)
    rec["risk_score"] = score
    rec["risk_tier"] = tier
    return ok(serialize(rec), 201)


@app.route("/mih/patients/<rid>", methods=["GET"])
def get_patient(rid):
    authn_authz({"CareCoordinator", "Clinician", "Paramedic", "ProgramAdmin"})
    rec = get_or_404("patients", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/patients", methods=["GET"])
def list_patients():
    authn_authz({"CareCoordinator", "Clinician", "Paramedic", "ProgramAdmin"})
    items = list(DB["patients"].values())
    items = filter_eq(items, "risk_tier", request.args.get("risk_tier"))
    return list_response(items)


# ===========================================================================
# Referral
# ===========================================================================
@app.route("/mih/referrals", methods=["POST"])
def create_referral():
    authn_authz({"CareCoordinator"})
    body = get_body()
    resolve_fk(body, "patient_id", "patients")
    resolve_fk(body, "program_id", "programs")
    patient_id = require_str(body, "patient_id")
    program_id = require_str(body, "program_id")
    referring_source = require_enum(body, "referring_source", {"ED", "HOSPITAL", "PCP", "SELF"})
    rec = new_record("referrals", {
        "patient_id": patient_id,
        "program_id": program_id,
        "referring_source": referring_source,
        "status": "SUBMITTED",
        "screened_risk_tier": None,
        "decline_reason": None,
    })
    return ok(serialize(rec), 201)


@app.route("/mih/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    authn_authz({"CareCoordinator", "Clinician", "ProgramAdmin"})
    rec = get_or_404("referrals", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/referrals", methods=["GET"])
def list_referrals():
    authn_authz({"CareCoordinator", "Clinician", "ProgramAdmin"})
    items = list(DB["referrals"].values())
    items = filter_eq(items, "patient_id", request.args.get("patient_id"))
    items = filter_eq(items, "program_id", request.args.get("program_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/mih/referrals/<rid>/screen", methods=["POST"])
def screen_referral(rid):
    authn_authz({"CareCoordinator"})
    ref = get_or_404("referrals", rid)
    if ref["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "referral is not SUBMITTED")
    patient = DB["patients"].get(ref["patient_id"])
    ref["screened_risk_tier"] = patient["risk_tier"] if patient else None
    ref["status"] = "SCREENED"
    touch(ref)
    return ok(serialize(ref), 200)


@app.route("/mih/referrals/<rid>/accept", methods=["POST"])
def accept_referral(rid):
    authn_authz({"CareCoordinator"})
    ref = get_or_404("referrals", rid)
    if ref["status"] != "SCREENED":
        raise ApiError("ERR_REFERRAL_NOT_SCREENED", 409, "referral is not SCREENED")
    program = get_or_404("programs", ref["program_id"])
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409, "program is not ACTIVE")
    if program["active_enrollment_count"] >= program["enrollment_cap"]:
        raise ApiError("ERR_ENROLLMENT_CAP_REACHED", 409, "program enrollment cap reached")
    enr = new_record("enrollments", {
        "patient_id": ref["patient_id"],
        "program_id": ref["program_id"],
        "referral_id": ref["id"],
        "status": "ACTIVE",
        "enrolled_at": clock_iso(),
        "discharged_at": None,
        "billed_amount_cents": 0,
        "revision_count": 0,
        "needs_review": False,
    })
    program["active_enrollment_count"] += 1
    recompute_program_slots(program)
    touch(program)
    ref["status"] = "ACCEPTED"
    touch(ref)
    return ok(serialize(enr), 201)


@app.route("/mih/referrals/<rid>/decline", methods=["POST"])
def decline_referral(rid):
    authn_authz({"CareCoordinator"})
    ref = get_or_404("referrals", rid)
    body = get_body()
    decline_reason = require_str(body, "decline_reason")
    if ref["status"] != "SCREENED":
        raise ApiError("ERR_REFERRAL_NOT_SCREENED", 409, "referral is not SCREENED")
    ref["decline_reason"] = decline_reason
    ref["status"] = "DECLINED"
    touch(ref)
    return ok(serialize(ref), 200)


# ===========================================================================
# Enrollment
# ===========================================================================
@app.route("/mih/enrollments/<rid>", methods=["GET"])
def get_enrollment(rid):
    authn_authz({"CareCoordinator", "Clinician", "Paramedic", "BillingSpecialist", "ProgramAdmin"})
    rec = get_or_404("enrollments", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/enrollments", methods=["GET"])
def list_enrollments():
    authn_authz({"CareCoordinator", "Clinician", "Paramedic", "BillingSpecialist", "ProgramAdmin"})
    items = list(DB["enrollments"].values())
    items = filter_eq(items, "patient_id", request.args.get("patient_id"))
    items = filter_eq(items, "program_id", request.args.get("program_id"))
    items = filter_eq(items, "referral_id", request.args.get("referral_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/mih/enrollments/<rid>/discharge", methods=["POST"])
def discharge_enrollment(rid):
    authn_authz({"CareCoordinator"})
    enr = get_or_404("enrollments", rid)
    if enr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "enrollment is not ACTIVE")
    for cp in list(DB["care_plans"].values()):
        if cp["enrollment_id"] == enr["id"] and cp["status"] in {"DRAFT", "ACTIVE", "UNDER_REVISION"}:
            close_care_plan(cp)
    program = DB["programs"].get(enr["program_id"])
    if program is not None:
        program["active_enrollment_count"] -= 1
        recompute_program_slots(program)
        touch(program)
    enr["discharged_at"] = clock_iso()
    enr["status"] = "DISCHARGED"
    touch(enr)
    return ok(serialize(enr), 200)


@app.route("/mih/enrollments/<rid>/withdraw", methods=["POST"])
def withdraw_enrollment(rid):
    authn_authz({"CareCoordinator"})
    enr = get_or_404("enrollments", rid)
    if enr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "enrollment is not ACTIVE")
    program = DB["programs"].get(enr["program_id"])
    if program is not None:
        program["active_enrollment_count"] -= 1
        recompute_program_slots(program)
        touch(program)
    enr["discharged_at"] = clock_iso()
    enr["status"] = "WITHDRAWN"
    touch(enr)
    return ok(serialize(enr), 200)


@app.route("/mih/enrollments/<rid>/cost-outcome", methods=["GET"])
def cost_outcome(rid):
    authn_authz({"CareCoordinator", "ProgramAdmin", "BillingSpecialist"})
    enr = get_or_404("enrollments", rid)
    patient = DB["patients"].get(enr["patient_id"])
    program = DB["programs"].get(enr["program_id"])
    enrolled_at = parse_iso(enr["enrolled_at"])
    enrollment_days = (CLOCK - enrolled_at).days
    if enrollment_days < 0:
        enrollment_days = 0
    baseline = patient["baseline_ed_visits_12mo"] if patient else 0
    expected_ed_visits = rhu(Decimal(baseline * enrollment_days) / Decimal(365))
    actual_ed_visits = 0
    for ev in DB["ed_events"].values():
        if ev["patient_id"] == enr["patient_id"] and ev["event_type"] == "ED_VISIT":
            ed_dt = parse_iso(ev["event_date"])
            if enrolled_at <= ed_dt < CLOCK:
                actual_ed_visits += 1
    averted_ed_visits = expected_ed_visits - actual_ed_visits
    if averted_ed_visits < 0:
        averted_ed_visits = 0
    per_averted_saving_cents = rhu(
        Decimal(program["avg_ed_cost_cents"]) * Decimal(str(program["diversion_credit_pct"]))
    ) if program else 0
    actual_savings_cents = averted_ed_visits * per_averted_saving_cents
    projected_savings_cents = expected_ed_visits * per_averted_saving_cents
    net_savings_cents = actual_savings_cents - enr["billed_amount_cents"]
    data = {
        "projected_savings_cents": projected_savings_cents,
        "actual_savings_cents": actual_savings_cents,
        "net_savings_cents": net_savings_cents,
        "averted_ed_visits": averted_ed_visits,
        "expected_ed_visits": expected_ed_visits,
        "actual_ed_visits": actual_ed_visits,
        "per_averted_saving_cents": per_averted_saving_cents,
    }
    return ok(data, 200)


# ===========================================================================
# CarePlan
# ===========================================================================
@app.route("/mih/enrollments/<rid>/care-plans", methods=["POST"])
def create_care_plan(rid):
    authn_authz({"Clinician"})
    enr = get_or_404("enrollments", rid)
    body = get_body()
    # Existence (priority 3): body FKs left-to-right.
    author = resolve_fk(body, "authoring_clinician_id", "providers")
    resolve_fk(body, "cosigner_clinician_id", "providers", required=False)
    # Body validation (priority 4).
    risk_level = require_enum(body, "risk_level", {"LOW", "MODERATE", "HIGH"})
    authoring_clinician_id = require_str(body, "authoring_clinician_id")
    cosigner_clinician_id = body.get("cosigner_clinician_id")
    require(body, "goals")
    goals = body["goals"]
    expected_version = require_int(body, "expected_enrollment_version")
    if author is None:
        author = DB["providers"].get(authoring_clinician_id)
    # OCC (priority 5).
    if expected_version != enr["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_enrollment_version does not match")
    # Operational status (priority 7).
    if enr["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409, "enrollment is not ACTIVE")
    # Referential (priority 9).
    if not author or author["provider_type"] != "CLINICIAN":
        raise ApiError("ERR_PROVIDER_TYPE_MISMATCH", 422, "authoring provider is not a CLINICIAN")
    # Supersede: close any existing non-CLOSED plan.
    for cp in list(DB["care_plans"].values()):
        if cp["enrollment_id"] == enr["id"] and cp["status"] != "CLOSED":
            close_care_plan(cp)
    rec = new_record("care_plans", {
        "enrollment_id": enr["id"],
        "authoring_clinician_id": authoring_clinician_id,
        "cosigner_clinician_id": cosigner_clinician_id,
        "risk_level": risk_level,
        "goals": goals,
        "status": "DRAFT",
    })
    touch(enr)  # increments enrollment version by one
    return ok(serialize(rec), 201)


@app.route("/mih/care-plans/<rid>", methods=["GET"])
def get_care_plan(rid):
    authn_authz({"Clinician", "CareCoordinator", "Paramedic", "ProgramAdmin"})
    rec = get_or_404("care_plans", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/care-plans", methods=["GET"])
def list_care_plans():
    authn_authz({"Clinician", "CareCoordinator", "Paramedic", "ProgramAdmin"})
    items = list(DB["care_plans"].values())
    items = filter_eq(items, "enrollment_id", request.args.get("enrollment_id"))
    items = filter_eq(items, "authoring_clinician_id", request.args.get("authoring_clinician_id"))
    items = filter_eq(items, "cosigner_clinician_id", request.args.get("cosigner_clinician_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/mih/care-plans/<rid>/activate", methods=["POST"])
def activate_care_plan(rid):
    authn_authz({"Clinician"})
    cp = get_or_404("care_plans", rid)
    if cp["status"] not in {"DRAFT", "UNDER_REVISION"}:
        raise ApiError("ERR_INVALID_STATE", 409, "care plan cannot be activated from its current state")
    enr = DB["enrollments"].get(cp["enrollment_id"])
    if enr is None or enr["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409, "enrollment is not ACTIVE")
    if cp["risk_level"] == "HIGH":
        if not cp.get("cosigner_clinician_id"):
            raise ApiError("ERR_COSIGN_REQUIRED", 422, "HIGH-risk care plan requires a cosigner")
        if cp["cosigner_clinician_id"] == cp["authoring_clinician_id"]:
            raise ApiError("ERR_COSIGN_SAME_CLINICIAN", 422, "cosigner must differ from author")
    was_revision = cp["status"] == "UNDER_REVISION"
    cp["status"] = "ACTIVE"
    touch(cp)
    if was_revision and enr is not None:
        enr["needs_review"] = False
        touch(enr)
    return ok(serialize(cp), 200)


@app.route("/mih/care-plans/<rid>/revise", methods=["POST"])
def revise_care_plan_endpoint(rid):
    authn_authz({"Clinician"})
    cp = get_or_404("care_plans", rid)
    if cp["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "care plan is not ACTIVE")
    revise_care_plan(cp)
    return ok(serialize(cp), 200)


@app.route("/mih/care-plans/<rid>/close", methods=["POST"])
def close_care_plan_endpoint(rid):
    authn_authz({"Clinician"})
    cp = get_or_404("care_plans", rid)
    if cp["status"] not in {"DRAFT", "ACTIVE", "UNDER_REVISION"}:
        raise ApiError("ERR_INVALID_STATE", 409, "care plan cannot be closed from its current state")
    close_care_plan(cp)
    return ok(serialize(cp), 200)


# ===========================================================================
# HomeVisit
# ===========================================================================
@app.route("/mih/home-visits", methods=["POST"])
def create_home_visit():
    authn_authz({"CareCoordinator"})
    body = get_body()
    # Existence (priority 3): enrollment_id, care_plan_id, provider_id left-to-right.
    enr = resolve_fk(body, "enrollment_id", "enrollments")
    cp = resolve_fk(body, "care_plan_id", "care_plans")
    provider = resolve_fk(body, "provider_id", "providers")
    # Body validation (priority 4).
    require_str(body, "enrollment_id")
    require_str(body, "care_plan_id")
    require_str(body, "provider_id")
    ss = require(body, "scheduled_start")
    se = require(body, "scheduled_end")
    ss_dt = parse_iso(ss, "scheduled_start")
    se_dt = parse_iso(se, "scheduled_end")
    if not (se_dt > ss_dt):
        raise ApiError("ERR_VALIDATION", 400, "scheduled_end must be strictly after scheduled_start")
    # Operational status (priority 7): care plan then enrollment.
    if cp["status"] != "ACTIVE":
        raise ApiError("ERR_CARE_PLAN_NOT_ACTIVE", 409, "care plan is not ACTIVE")
    if enr["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409, "enrollment is not ACTIVE")
    # Temporal (priority 8): provider double-booking, half-open overlap.
    for hv in DB["home_visits"].values():
        if hv["provider_id"] == body["provider_id"] and hv["status"] == "SCHEDULED":
            os = parse_iso(hv["scheduled_start"])
            oe = parse_iso(hv["scheduled_end"])
            if ss_dt < oe and os < se_dt:
                raise ApiError("ERR_SCHEDULE_CONFLICT", 409, "provider schedule conflict")
    # Referential (priority 9): provider type PARAMEDIC.
    if provider["provider_type"] != "PARAMEDIC":
        raise ApiError("ERR_PROVIDER_TYPE_MISMATCH", 422, "provider is not a PARAMEDIC")
    rec = new_record("home_visits", {
        "enrollment_id": body["enrollment_id"],
        "care_plan_id": body["care_plan_id"],
        "provider_id": body["provider_id"],
        "scheduled_start": ss,
        "scheduled_end": se,
        "status": "SCHEDULED",
        "systolic_bp": None,
        "diastolic_bp": None,
        "heart_rate": None,
        "billable": False,
    })
    return ok(serialize(rec), 201)


@app.route("/mih/home-visits/<rid>", methods=["GET"])
def get_home_visit(rid):
    authn_authz({"CareCoordinator", "Paramedic", "Clinician", "ProgramAdmin"})
    rec = get_or_404("home_visits", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/home-visits", methods=["GET"])
def list_home_visits():
    authn_authz({"CareCoordinator", "Paramedic", "Clinician", "ProgramAdmin"})
    items = list(DB["home_visits"].values())
    items = filter_eq(items, "enrollment_id", request.args.get("enrollment_id"))
    items = filter_eq(items, "care_plan_id", request.args.get("care_plan_id"))
    items = filter_eq(items, "provider_id", request.args.get("provider_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/mih/home-visits/<rid>/complete", methods=["POST"])
def complete_home_visit(rid):
    authn_authz({"Paramedic"})
    hv = get_or_404("home_visits", rid)
    body = get_body()
    systolic = require_int(body, "systolic_bp")
    diastolic = require_int(body, "diastolic_bp")
    hr = require_int(body, "heart_rate")
    if hv["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "home visit is not SCHEDULED")
    hv["systolic_bp"] = systolic
    hv["diastolic_bp"] = diastolic
    hv["heart_rate"] = hr
    hv["billable"] = True
    hv["status"] = "COMPLETED"
    touch(hv)
    return ok(serialize(hv), 200)


@app.route("/mih/home-visits/<rid>/cancel", methods=["POST"])
def cancel_home_visit(rid):
    authn_authz({"CareCoordinator", "Paramedic"})
    hv = get_or_404("home_visits", rid)
    if hv["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "home visit is not SCHEDULED")
    hv["status"] = "CANCELLED"
    touch(hv)
    return ok(serialize(hv), 200)


@app.route("/mih/home-visits/<rid>/no-show", methods=["POST"])
def no_show_home_visit(rid):
    authn_authz({"Paramedic"})
    hv = get_or_404("home_visits", rid)
    if hv["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "home visit is not SCHEDULED")
    hv["status"] = "NO_SHOW"
    touch(hv)
    return ok(serialize(hv), 200)


# ===========================================================================
# TelehealthSession
# ===========================================================================
@app.route("/mih/telehealth-sessions", methods=["POST"])
def create_telehealth():
    authn_authz({"CareCoordinator"})
    body = get_body()
    enr = resolve_fk(body, "enrollment_id", "enrollments")
    resolve_fk(body, "patient_id", "patients")
    provider = resolve_fk(body, "provider_id", "providers")
    require_str(body, "enrollment_id")
    require_str(body, "patient_id")
    require_str(body, "provider_id")
    ss = require(body, "scheduled_start")
    se = require(body, "scheduled_end")
    ss_dt = parse_iso(ss, "scheduled_start")
    se_dt = parse_iso(se, "scheduled_end")
    if not (se_dt > ss_dt):
        raise ApiError("ERR_VALIDATION", 400, "scheduled_end must be strictly after scheduled_start")
    if enr["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409, "enrollment is not ACTIVE")
    # Temporal (priority 8): patient buffer (15 min) against other SCHEDULED sessions.
    buf = timedelta(minutes=TELEHEALTH_BUFFER_MINUTES)
    for ts in DB["telehealth_sessions"].values():
        if ts["patient_id"] == body["patient_id"] and ts["status"] == "SCHEDULED":
            os = parse_iso(ts["scheduled_start"])
            oe = parse_iso(ts["scheduled_end"])
            if ss_dt < oe + buf and os < se_dt + buf:
                raise ApiError("ERR_TELEHEALTH_BUFFER_CONFLICT", 409, "telehealth buffer conflict")
    if provider["provider_type"] != "CLINICIAN":
        raise ApiError("ERR_PROVIDER_TYPE_MISMATCH", 422, "provider is not a CLINICIAN")
    rec = new_record("telehealth_sessions", {
        "enrollment_id": body["enrollment_id"],
        "patient_id": body["patient_id"],
        "provider_id": body["provider_id"],
        "scheduled_start": ss,
        "scheduled_end": se,
        "status": "SCHEDULED",
        "systolic_bp": None,
        "diastolic_bp": None,
        "heart_rate": None,
        "billable": False,
    })
    return ok(serialize(rec), 201)


@app.route("/mih/telehealth-sessions/<rid>", methods=["GET"])
def get_telehealth(rid):
    authn_authz({"CareCoordinator", "Paramedic", "Clinician", "ProgramAdmin"})
    rec = get_or_404("telehealth_sessions", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/telehealth-sessions", methods=["GET"])
def list_telehealth():
    authn_authz({"CareCoordinator", "Paramedic", "Clinician", "ProgramAdmin"})
    items = list(DB["telehealth_sessions"].values())
    items = filter_eq(items, "enrollment_id", request.args.get("enrollment_id"))
    items = filter_eq(items, "patient_id", request.args.get("patient_id"))
    items = filter_eq(items, "provider_id", request.args.get("provider_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/mih/telehealth-sessions/<rid>/complete", methods=["POST"])
def complete_telehealth(rid):
    authn_authz({"Clinician", "Paramedic"})
    ts = get_or_404("telehealth_sessions", rid)
    body = get_body()
    systolic = require_int(body, "systolic_bp")
    diastolic = require_int(body, "diastolic_bp")
    hr = require_int(body, "heart_rate")
    if ts["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "telehealth session is not SCHEDULED")
    ts["systolic_bp"] = systolic
    ts["diastolic_bp"] = diastolic
    ts["heart_rate"] = hr
    ts["billable"] = True
    ts["status"] = "COMPLETED"
    touch(ts)
    return ok(serialize(ts), 200)


@app.route("/mih/telehealth-sessions/<rid>/cancel", methods=["POST"])
def cancel_telehealth(rid):
    authn_authz({"CareCoordinator", "Clinician"})
    ts = get_or_404("telehealth_sessions", rid)
    if ts["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "telehealth session is not SCHEDULED")
    ts["status"] = "CANCELLED"
    touch(ts)
    return ok(serialize(ts), 200)


# ===========================================================================
# MedReconciliation
# ===========================================================================
@app.route("/mih/med-reconciliations", methods=["POST"])
def create_med_rec():
    authn_authz({"Paramedic"})
    body = get_body()
    resolve_fk(body, "enrollment_id", "enrollments")
    resolve_fk(body, "home_visit_id", "home_visits")
    enrollment_id = require_str(body, "enrollment_id")
    home_visit_id = require_str(body, "home_visit_id")
    medications = require(body, "medications")
    if not isinstance(medications, list):
        raise ApiError("ERR_VALIDATION", 400, "medications must be an array")
    discrepancy_count = body.get("discrepancy_count", 0)
    if discrepancy_count is None:
        discrepancy_count = 0
    if not is_int(discrepancy_count):
        raise ApiError("ERR_VALIDATION", 400, "discrepancy_count must be an integer")
    rec = new_record("med_reconciliations", {
        "enrollment_id": enrollment_id,
        "home_visit_id": home_visit_id,
        "medications": medications,
        "discrepancy_count": discrepancy_count,
        "status": "DRAFTED",
        "review_outcome": None,
    })
    return ok(serialize(rec), 201)


@app.route("/mih/med-reconciliations/<rid>", methods=["GET"])
def get_med_rec(rid):
    authn_authz({"Paramedic", "Clinician", "CareCoordinator", "ProgramAdmin"})
    rec = get_or_404("med_reconciliations", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/med-reconciliations", methods=["GET"])
def list_med_rec():
    authn_authz({"Paramedic", "Clinician", "CareCoordinator", "ProgramAdmin"})
    items = list(DB["med_reconciliations"].values())
    items = filter_eq(items, "enrollment_id", request.args.get("enrollment_id"))
    items = filter_eq(items, "home_visit_id", request.args.get("home_visit_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/mih/med-reconciliations/<rid>/submit", methods=["POST"])
def submit_med_rec(rid):
    authn_authz({"Paramedic"})
    mr = get_or_404("med_reconciliations", rid)
    if mr["status"] != "DRAFTED":
        raise ApiError("ERR_INVALID_STATE", 409, "med reconciliation is not DRAFTED")
    mr["status"] = "PENDING_REVIEW"
    touch(mr)
    return ok(serialize(mr), 200)


@app.route("/mih/med-reconciliations/<rid>/review", methods=["POST"])
def review_med_rec(rid):
    authn_authz({"Clinician"})
    mr = get_or_404("med_reconciliations", rid)
    body = get_body()
    review_outcome = require_enum(body, "review_outcome", {"RECONCILED", "FLAGGED"})
    if mr["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_MED_REC_NOT_PENDING", 409, "med reconciliation is not PENDING_REVIEW")
    mr["review_outcome"] = review_outcome
    mr["status"] = review_outcome
    touch(mr)
    if review_outcome == "FLAGGED":
        # Cascade: the enrollment's single ACTIVE care plan -> UNDER_REVISION.
        for cp in DB["care_plans"].values():
            if cp["enrollment_id"] == mr["enrollment_id"] and cp["status"] == "ACTIVE":
                revise_care_plan(cp)
                break
    return ok(serialize(mr), 200)


# ===========================================================================
# SocialNeedsReferral
# ===========================================================================
@app.route("/mih/social-referrals", methods=["POST"])
def create_social_referral():
    authn_authz({"CareCoordinator"})
    body = get_body()
    resolve_fk(body, "enrollment_id", "enrollments")
    enrollment_id = require_str(body, "enrollment_id")
    domain = require_enum(body, "domain", {"HOUSING", "FOOD", "TRANSPORT", "UTILITIES"})
    rec = new_record("social_referrals", {
        "enrollment_id": enrollment_id,
        "domain": domain,
        "status": "OPEN",
        "partner_org": None,
        "resolution_status": None,
        "resolution_note": None,
    })
    return ok(serialize(rec), 201)


@app.route("/mih/social-referrals/<rid>", methods=["GET"])
def get_social_referral(rid):
    authn_authz({"CareCoordinator", "Clinician", "ProgramAdmin"})
    rec = get_or_404("social_referrals", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/social-referrals", methods=["GET"])
def list_social_referrals():
    authn_authz({"CareCoordinator", "Clinician", "ProgramAdmin"})
    items = list(DB["social_referrals"].values())
    items = filter_eq(items, "enrollment_id", request.args.get("enrollment_id"))
    items = filter_eq(items, "domain", request.args.get("domain"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/mih/social-referrals/<rid>/refer", methods=["POST"])
def refer_social_referral(rid):
    authn_authz({"CareCoordinator"})
    sr = get_or_404("social_referrals", rid)
    body = get_body()
    partner_org = require_str(body, "partner_org")
    if sr["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "social referral is not OPEN")
    sr["partner_org"] = partner_org
    sr["status"] = "REFERRED"
    touch(sr)
    return ok(serialize(sr), 200)


@app.route("/mih/social-referrals/<rid>/resolve", methods=["POST"])
def resolve_social_referral(rid):
    authn_authz({"CareCoordinator"})
    sr = get_or_404("social_referrals", rid)
    body = get_body()
    resolution_status = require_enum(body, "resolution_status", {"RESOLVED", "UNMET"})
    resolution_note = body.get("resolution_note")
    if sr["status"] != "REFERRED":
        raise ApiError("ERR_INVALID_STATE", 409, "social referral is not REFERRED")
    sr["resolution_status"] = resolution_status
    sr["resolution_note"] = resolution_note
    sr["status"] = resolution_status
    touch(sr)
    return ok(serialize(sr), 200)


# ===========================================================================
# EDEvent
# ===========================================================================
@app.route("/mih/ed-events", methods=["POST"])
def create_ed_event():
    authn_authz({"CareCoordinator", "ProgramAdmin"})
    body = get_body()
    resolve_fk(body, "patient_id", "patients")
    patient_id = require_str(body, "patient_id")
    event_type = require_enum(body, "event_type", {"ED_VISIT", "INPATIENT_ADMISSION"})
    event_date = require(body, "event_date")
    parse_iso(event_date, "event_date")
    discharge_date = body.get("discharge_date")
    if discharge_date is not None:
        parse_iso(discharge_date, "discharge_date")
    is_readmission = compute_readmission(patient_id, event_type, event_date)
    rec = new_record("ed_events", {
        "patient_id": patient_id,
        "event_type": event_type,
        "event_date": event_date,
        "discharge_date": discharge_date,
        "is_readmission": is_readmission,
    }, versioned=False)
    # Recompute patient risk (mutation only if it changes).
    patient = DB["patients"].get(patient_id)
    if patient is not None:
        score, tier = compute_risk(patient)
        if score != patient["risk_score"] or tier != patient["risk_tier"]:
            patient["risk_score"] = score
            patient["risk_tier"] = tier
            touch(patient)
    return ok(serialize(rec), 201)


@app.route("/mih/ed-events/<rid>", methods=["GET"])
def get_ed_event(rid):
    authn_authz({"CareCoordinator", "Clinician", "ProgramAdmin"})
    rec = get_or_404("ed_events", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/ed-events", methods=["GET"])
def list_ed_events():
    authn_authz({"CareCoordinator", "Clinician", "ProgramAdmin"})
    items = list(DB["ed_events"].values())
    items = filter_eq(items, "patient_id", request.args.get("patient_id"))
    items = filter_eq(items, "event_type", request.args.get("event_type"))
    return list_response(items)


# ===========================================================================
# BillingClaim
# ===========================================================================
@app.route("/mih/billing-claims", methods=["POST"])
def create_billing_claim():
    authn_authz({"BillingSpecialist"})
    body = get_body()
    enr = resolve_fk(body, "enrollment_id", "enrollments")
    resolve_fk(body, "program_id", "programs")
    resolve_fk(body, "payer_id", "payers")
    enrollment_id = require_str(body, "enrollment_id")
    program_id = require_str(body, "program_id")
    payer_id = require_str(body, "payer_id")
    period_start = require(body, "period_start")
    period_end = require(body, "period_end")
    ps = parse_iso(period_start, "period_start")
    pe = parse_iso(period_end, "period_end")
    # Referential (priority 9): program/payer consistent with the enrollment.
    program_of_enr = DB["programs"].get(enr["program_id"])
    if program_id != enr["program_id"] or (program_of_enr and payer_id != program_of_enr["payer_id"]):
        raise ApiError("ERR_CLAIM_EVENTS_CROSS_ENROLLMENT", 422,
                       "claim program/payer inconsistent with enrollment")
    program = DB["programs"].get(program_id)
    prov_amount, _pv, _pt = compute_claim(enr, program, ps, pe, {"SCHEDULED", "COMPLETED"})
    _fa, fv, ft = compute_claim(enr, program, ps, pe, {"COMPLETED"})
    rec = new_record("billing_claims", {
        "enrollment_id": enrollment_id,
        "program_id": program_id,
        "payer_id": payer_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "provisional_amount_cents": prov_amount,
        "final_amount_cents": None,
        "amount_cents": None,
        "billable_visit_count": fv,
        "billable_telehealth_count": ft,
        "denial_reason": None,
    })
    return ok(serialize(rec), 201)


@app.route("/mih/billing-claims/<rid>", methods=["GET"])
def get_billing_claim(rid):
    authn_authz({"BillingSpecialist", "ProgramAdmin", "PayerReviewer"})
    rec = get_or_404("billing_claims", rid)
    return ok(serialize(rec), 200)


@app.route("/mih/billing-claims", methods=["GET"])
def list_billing_claims():
    authn_authz({"BillingSpecialist", "ProgramAdmin", "PayerReviewer"})
    items = list(DB["billing_claims"].values())
    items = filter_eq(items, "enrollment_id", request.args.get("enrollment_id"))
    items = filter_eq(items, "program_id", request.args.get("program_id"))
    items = filter_eq(items, "payer_id", request.args.get("payer_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/mih/billing-claims/<rid>/submit", methods=["POST"])
def submit_billing_claim(rid):
    authn_authz({"BillingSpecialist"})
    claim = get_or_404("billing_claims", rid)
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "claim is not DRAFT")
    program = get_or_404("programs", claim["program_id"])
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409, "program is not ACTIVE")
    enr = get_or_404("enrollments", claim["enrollment_id"])
    ps = parse_iso(claim["period_start"])
    pe = parse_iso(claim["period_end"])
    final_amount, fv, ft = compute_claim(enr, program, ps, pe, {"COMPLETED"})
    if fv + ft <= 0:
        raise ApiError("ERR_CLAIM_NO_BILLABLE_EVENTS", 422, "no realized billable events in period")
    if final_amount > program["available_budget_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 409, "claim exceeds available budget")
    claim["final_amount_cents"] = final_amount
    claim["amount_cents"] = final_amount
    claim["billable_visit_count"] = fv
    claim["billable_telehealth_count"] = ft
    claim["status"] = "SUBMITTED"
    touch(claim)
    program["available_budget_cents"] -= final_amount
    program["committed_spend_cents"] += final_amount
    touch(program)
    return ok(serialize(claim), 200)


@app.route("/mih/billing-claims/<rid>/adjudicate", methods=["POST"])
def adjudicate_billing_claim(rid):
    authn_authz({"PayerReviewer"})
    claim = get_or_404("billing_claims", rid)
    body = get_body()
    outcome = require_enum(body, "outcome", {"PAID", "DENIED"})
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "claim is not SUBMITTED")
    if outcome == "PAID":
        enr = DB["enrollments"].get(claim["enrollment_id"])
        if enr is not None:
            enr["billed_amount_cents"] += claim["amount_cents"]
            touch(enr)
        claim["status"] = "PAID"
        touch(claim)
    else:  # DENIED
        program = DB["programs"].get(claim["program_id"])
        if program is not None:
            program["available_budget_cents"] += claim["amount_cents"]
            program["committed_spend_cents"] -= claim["amount_cents"]
            touch(program)
        claim["denial_reason"] = body.get("denial_reason")
        claim["status"] = "DENIED"
        touch(claim)
    return ok(serialize(claim), 200)


@app.route("/mih/billing-claims/<rid>/resubmit", methods=["POST"])
def resubmit_billing_claim(rid):
    authn_authz({"BillingSpecialist"})
    claim = get_or_404("billing_claims", rid)
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", 409, "claim is not DENIED")
    program = get_or_404("programs", claim["program_id"])
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409, "program is not ACTIVE")
    enr = get_or_404("enrollments", claim["enrollment_id"])
    ps = parse_iso(claim["period_start"])
    pe = parse_iso(claim["period_end"])
    final_amount, fv, ft = compute_claim(enr, program, ps, pe, {"COMPLETED"})
    if final_amount > program["available_budget_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 409, "claim exceeds available budget")
    claim["final_amount_cents"] = final_amount
    claim["amount_cents"] = final_amount
    claim["billable_visit_count"] = fv
    claim["billable_telehealth_count"] = ft
    claim["status"] = "SUBMITTED"
    touch(claim)
    program["available_budget_cents"] -= final_amount
    program["committed_spend_cents"] += final_amount
    touch(program)
    return ok(serialize(claim), 200)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/mih/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authn_authz({"ProgramAdmin"})
    global CLOCK
    body = get_body()
    to_iso = require(body, "to_iso8601")
    CLOCK = parse_iso(to_iso, "to_iso8601")
    return ok({"current_utc": clock_iso()}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
