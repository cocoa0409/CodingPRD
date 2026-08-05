"""Cardiac & Pulmonary Rehab Program API (Task 902).

Single-file Flask implementation. In-memory storage only; store starts empty
on every boot. No entity seeding at startup.
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"ReferringPhysician", "RehabCoordinator", "RehabClinician", "BillingSpecialist"}
ALL_ROLES = ["ReferringPhysician", "RehabCoordinator", "RehabClinician", "BillingSpecialist"]

SESSION_CAP_DEFAULT = 36
MAX_CONSECUTIVE_MISSED = 3
SPO2_MIN_THRESHOLD = 85
RPE_MAX_THRESHOLD = 18
CLINICIAN_TURNOVER_BUFFER_MINUTES = 15
MAINTENANCE_INTENSIVE_THRESHOLD_PCT = Decimal("10.0")

BASE_RATE_CENTS = {"MONITORED_EXERCISE": 15000, "EDUCATION": 8000, "ASSESSMENT": 10000}
RISK_MULTIPLIER = {"LOW": Decimal("1.00"), "MODERATE": Decimal("1.10"), "HIGH": Decimal("1.25")}
TELEMETRY_SURCHARGE_CENTS = 3000
MAX_BILLED_PER_SESSION_CENTS = 20000
MONTHLY_ALLOWANCE = {"STANDARD": 4, "INTENSIVE": 8}

CREDENTIALS = {"RN", "RRT", "EP"}
STATION_TYPES = {"TELEMETRY", "STANDARD"}
PROGRAM_TYPES = {"CARDIAC", "PULMONARY"}
RISK_TIERS = {"LOW", "MODERATE", "HIGH"}
PHASES = {"PHASE_I", "PHASE_II", "PHASE_III"}
SESSION_TYPES = {"MONITORED_EXERCISE", "EDUCATION", "ASSESSMENT"}
ITEM_TYPES = {"EDUCATION_MODULE", "GOAL"}
TIMINGS = {"BASELINE", "DISCHARGE"}
ASSESSMENT_TYPES = {"SIX_MINUTE_WALK"}
RESOLUTIONS = {"ACHIEVED", "NOT_ACHIEVED", "WAIVED"}
DECISIONS = {"ACCEPT", "DECLINE"}
ADJ_OUTCOMES = {"PAID", "DENIED"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "patients": {},
    "physicians": {},
    "clinicians": {},
    "stations": {},
    "referrals": {},
    "programs": {},
    "authorizations": {},
    "sessions": {},
    "care_plan_items": {},
    "outcomes": {},
    "claims": {},
    "maintenance": {},
}
_SEQ = 0
_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


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
# Time helpers
# ---------------------------------------------------------------------------
def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_iso(_CLOCK)


def parse_dt(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _rand_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(extra=None):
    m = {"api_request_id": _rand_req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def respond(data, code=200, is_array=False, meta_extra=None):
    body = {
        "meta": make_meta(meta_extra),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), code


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def _handle_generic(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "Role not permitted for this operation")
    g.uid = uid
    g.role = role


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body(optional=True):
    raw = request.get_data()
    if raw:
        parsed = request.get_json(silent=True)
        if parsed is None:
            raise ApiError("ERR_VALIDATION", 400, "Malformed JSON body")
        if not isinstance(parsed, dict):
            raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
        return parsed
    if optional:
        return {}
    raise ApiError("ERR_VALIDATION", 400, "Request body required")


def val_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be a string" % field)
    return v


def val_int(body, field, required=True, positive=False, min_val=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % field)
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be an integer" % field)
    if positive and v <= 0:
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be positive" % field)
    if min_val is not None and v < min_val:
        raise ApiError("ERR_VALIDATION", 400, "Field %s below minimum" % field)
    return v


def val_enum(body, field, allowed, required=True, err="ERR_INVALID_ENUM"):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(err, 400, "Invalid value for %s" % field)
    return v


# ---------------------------------------------------------------------------
# Entity creation / mutation helpers
# ---------------------------------------------------------------------------
def new_entity(extra):
    now = now_iso()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(extra)
    return e


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def sorted_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def _find(collection, _id, err_id):
    obj = DB[collection].get(_id)
    if obj is None:
        raise ApiError(err_id, 404, "Resource not found")
    return obj


# ---------------------------------------------------------------------------
# Program derived-field computations
# ---------------------------------------------------------------------------
def program_sessions(program_id):
    return [s for s in DB["sessions"].values() if s["program_id"] == program_id]


def program_claims(program_id):
    return [c for c in DB["claims"].values() if c["program_id"] == program_id]


def claim_reimbursement(c):
    if c["status"] == "PAID":
        return c.get("adjudicated_reimbursement_cents") or 0
    if c["status"] == "DENIED":
        return 0
    return c["estimated_reimbursement_cents"]


def auth_visits_billed(auth_id):
    return sum(
        1 for c in DB["claims"].values()
        if c["authorization_id"] == auth_id and c["status"] != "VOID"
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_patient(e):
    d = _common(e)
    d.update({"mrn": e["mrn"], "full_name": e["full_name"], "date_of_birth": e["date_of_birth"]})
    return d


def ser_physician(e):
    d = _common(e)
    d.update({"full_name": e["full_name"], "npi": e["npi"], "specialty": e.get("specialty")})
    return d


def ser_clinician(e):
    d = _common(e)
    d.update({"full_name": e["full_name"], "credential": e["credential"]})
    return d


def ser_station(e):
    d = _common(e)
    d.update({"name": e["name"], "station_type": e["station_type"]})
    return d


def ser_referral(e):
    d = _common(e)
    d.update({
        "patient_id": e["patient_id"],
        "physician_id": e["physician_id"],
        "program_type": e["program_type"],
        "indication": e["indication"],
        "risk_stratification": e["risk_stratification"],
        "status": e["status"],
    })
    return d


def ser_program(e):
    sessions = program_sessions(e["id"])
    used = sum(1 for s in sessions if s["status"] == "COMPLETED")
    scheduled = sum(1 for s in sessions if s["status"] == "SCHEDULED")
    claims = [c for c in program_claims(e["id"]) if c["status"] != "VOID"]
    total_billed = sum(c["billed_amount_cents"] for c in claims)
    total_reimb = sum(claim_reimbursement(c) for c in claims)
    total_pr = sum(c["patient_responsibility_cents"] for c in claims)
    outstanding = sum(
        c["patient_responsibility_cents"] for c in claims if c["status"] == "DENIED"
    )
    d = _common(e)
    d.update({
        "patient_id": e["patient_id"],
        "referral_id": e["referral_id"],
        "program_type": e["program_type"],
        "risk_stratification": e["risk_stratification"],
        "current_phase": e["current_phase"],
        "authorized_session_cap": e["authorized_session_cap"],
        "sessions_used": used,
        "sessions_scheduled": scheduled,
        "sessions_remaining_authorized": e["authorized_session_cap"] - used,
        "consecutive_missed_count": e["consecutive_missed_count"],
        "total_billed_cents": total_billed,
        "total_reimbursed_cents": total_reimb,
        "total_patient_responsibility_cents": total_pr,
        "outstanding_balance_cents": outstanding,
        "status": e["status"],
    })
    return d


def ser_authorization(e):
    vb = auth_visits_billed(e["id"])
    if e["status"] == "APPROVED" and vb >= e["authorized_visits"]:
        status = "EXHAUSTED"
    else:
        status = e["status"]
    d = _common(e)
    d.update({
        "program_id": e["program_id"],
        "payer_name": e["payer_name"],
        "authorized_visits": e["authorized_visits"],
        "allowed_amount_cents": e["allowed_amount_cents"],
        "copay_cents": e["copay_cents"],
        "visits_billed": vb,
        "status": status,
    })
    return d


def ser_session(e):
    d = _common(e)
    d.update({
        "program_id": e["program_id"],
        "clinician_id": e["clinician_id"],
        "station_id": e["station_id"],
        "session_type": e["session_type"],
        "phase": e["phase"],
        "scheduled_start": e["scheduled_start"],
        "scheduled_end": e["scheduled_end"],
        "pre_hr": e.get("pre_hr"),
        "post_hr": e.get("post_hr"),
        "post_spo2": e.get("post_spo2"),
        "rpe": e.get("rpe"),
        "exercise_minutes": e.get("exercise_minutes"),
        "adverse_event": e.get("adverse_event", False),
        "status": e["status"],
    })
    return d


def ser_care_item(e):
    d = _common(e)
    d.update({
        "program_id": e["program_id"],
        "item_type": e["item_type"],
        "title": e["title"],
        "target_description": e.get("target_description"),
        "status": e["status"],
    })
    return d


def latest_finalized_baseline(program_id):
    cands = [
        o for o in DB["outcomes"].values()
        if o["program_id"] == program_id
        and o["timing"] == "BASELINE"
        and o["status"] == "FINALIZED"
    ]
    if not cands:
        return None
    return max(cands, key=lambda x: x["_seq"])


def compute_improvement(o):
    """Return (improvement_meters, improvement_pct) or (None, None)."""
    if o["timing"] != "DISCHARGE":
        return None, None
    base = latest_finalized_baseline(o["program_id"])
    if base is None:
        return None, None
    b = base["distance_meters"]
    d = o["distance_meters"]
    imp_m = d - b
    if b == 0:
        return imp_m, None
    imp_p = float(round_half_up(Decimal(d - b) / Decimal(b) * Decimal(100), 1))
    return imp_m, imp_p


def ser_outcome(e):
    imp_m, imp_p = compute_improvement(e)
    d = _common(e)
    d.update({
        "program_id": e["program_id"],
        "assessment_type": e["assessment_type"],
        "timing": e["timing"],
        "distance_meters": e["distance_meters"],
        "improvement_meters": imp_m,
        "improvement_pct": imp_p,
        "status": e["status"],
    })
    return d


def ser_claim(e):
    d = _common(e)
    d.update({
        "program_id": e["program_id"],
        "session_id": e["session_id"],
        "authorization_id": e["authorization_id"],
        "billed_amount_cents": e["billed_amount_cents"],
        "estimated_reimbursement_cents": e["estimated_reimbursement_cents"],
        "estimated_patient_responsibility_cents": e["estimated_patient_responsibility_cents"],
        "adjudicated_reimbursement_cents": e.get("adjudicated_reimbursement_cents"),
        "patient_responsibility_cents": e["patient_responsibility_cents"],
        "denial_reason": e.get("denial_reason"),
        "status": e["status"],
    })
    return d


def ser_maintenance(e):
    d = _common(e)
    d.update({
        "program_id": e["program_id"],
        "patient_id": e["patient_id"],
        "tier": e["tier"],
        "monthly_visit_allowance": e["monthly_visit_allowance"],
        "status": e["status"],
    })
    return d


# ---------------------------------------------------------------------------
# Pagination + list helper
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit out of range")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset out of range")
    return limit, offset


def list_response(items, serializer):
    limit, offset = parse_pagination()
    items = sorted_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    data = [serializer(x) for x in page]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return respond(data, 200, is_array=True, meta_extra=meta_extra)


# ---------------------------------------------------------------------------
# Scheduling guard helpers
# ---------------------------------------------------------------------------
def check_telemetry(program, session_type, station):
    if (program["risk_stratification"] == "HIGH"
            and session_type == "MONITORED_EXERCISE"
            and station["station_type"] != "TELEMETRY"):
        raise ApiError("ERR_TELEMETRY_STATION_REQUIRED", 422,
                       "HIGH-risk monitored exercise requires a TELEMETRY station")


def check_station_overlap(station_id, start_dt, end_dt, exclude_session_id=None):
    for s in DB["sessions"].values():
        if s["status"] != "SCHEDULED":
            continue
        if s["station_id"] != station_id:
            continue
        if exclude_session_id and s["id"] == exclude_session_id:
            continue
        s_start = s["_start_dt"]
        s_end = s["_end_dt"]
        # half-open overlap
        if start_dt < s_end and s_start < end_dt:
            raise ApiError("ERR_STATION_OVERLAP", 409,
                           "Session overlaps another scheduled session on this station")


def check_clinician_availability(clinician_id, start_dt, end_dt, exclude_session_id=None):
    from datetime import timedelta
    buffer = timedelta(minutes=CLINICIAN_TURNOVER_BUFFER_MINUTES)
    for s in DB["sessions"].values():
        if s["status"] != "SCHEDULED":
            continue
        if s["clinician_id"] != clinician_id:
            continue
        if exclude_session_id and s["id"] == exclude_session_id:
            continue
        s_start = s["_start_dt"]
        s_end = s["_end_dt"]
        # separated by MORE than buffer: (start - s_end > buffer) or (s_start - end > buffer)
        if (start_dt - s_end > buffer) or (s_start - end_dt > buffer):
            continue
        raise ApiError("ERR_CLINICIAN_UNAVAILABLE", 409,
                       "Clinician unavailable within turnover buffer")


def check_capacity(program):
    sessions = program_sessions(program["id"])
    used = sum(1 for s in sessions if s["status"] == "COMPLETED")
    scheduled = sum(1 for s in sessions if s["status"] == "SCHEDULED")
    if used + scheduled >= program["authorized_session_cap"]:
        raise ApiError("ERR_SESSION_CAP_REACHED", 409, "36-session authorization cap reached")


def cascade_cancel_scheduled(program):
    for s in DB["sessions"].values():
        if s["program_id"] == program["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)


# ===========================================================================
# ROUTES
# ===========================================================================

# ---- Patients ----
@app.route("/rehab/patients", methods=["POST"])
def create_patient():
    require_auth(["RehabCoordinator"])
    b = get_body()
    e = new_entity({
        "mrn": val_str(b, "mrn"),
        "full_name": val_str(b, "full_name"),
        "date_of_birth": val_str(b, "date_of_birth"),
    })
    DB["patients"][e["id"]] = e
    return respond(ser_patient(e), 201)


@app.route("/rehab/patients/<pid>", methods=["GET"])
def get_patient(pid):
    require_auth(ALL_ROLES)
    return respond(ser_patient(_find("patients", pid, "ERR_PATIENT_NOT_FOUND")))


# ---- Physicians ----
@app.route("/rehab/physicians", methods=["POST"])
def create_physician():
    require_auth(["RehabCoordinator"])
    b = get_body()
    e = new_entity({
        "full_name": val_str(b, "full_name"),
        "npi": val_str(b, "npi"),
        "specialty": val_str(b, "specialty", required=False),
    })
    DB["physicians"][e["id"]] = e
    return respond(ser_physician(e), 201)


@app.route("/rehab/physicians/<pid>", methods=["GET"])
def get_physician(pid):
    require_auth(ALL_ROLES)
    return respond(ser_physician(_find("physicians", pid, "ERR_PHYSICIAN_NOT_FOUND")))


# ---- Clinicians ----
@app.route("/rehab/clinicians", methods=["POST"])
def create_clinician():
    require_auth(["RehabCoordinator"])
    b = get_body()
    e = new_entity({
        "full_name": val_str(b, "full_name"),
        "credential": val_enum(b, "credential", CREDENTIALS),
    })
    DB["clinicians"][e["id"]] = e
    return respond(ser_clinician(e), 201)


@app.route("/rehab/clinicians/<cid>", methods=["GET"])
def get_clinician(cid):
    require_auth(ALL_ROLES)
    return respond(ser_clinician(_find("clinicians", cid, "ERR_CLINICIAN_NOT_FOUND")))


# ---- Stations ----
@app.route("/rehab/stations", methods=["POST"])
def create_station():
    require_auth(["RehabCoordinator"])
    b = get_body()
    e = new_entity({
        "name": val_str(b, "name"),
        "station_type": val_enum(b, "station_type", STATION_TYPES),
    })
    DB["stations"][e["id"]] = e
    return respond(ser_station(e), 201)


@app.route("/rehab/stations/<sid>", methods=["GET"])
def get_station(sid):
    require_auth(ALL_ROLES)
    return respond(ser_station(_find("stations", sid, "ERR_STATION_NOT_FOUND")))


# ---- Referrals ----
@app.route("/rehab/referrals", methods=["POST"])
def create_referral():
    require_auth(["ReferringPhysician"])
    b = get_body()
    patient_id = val_str(b, "patient_id")
    physician_id = val_str(b, "physician_id")
    program_type = val_enum(b, "program_type", PROGRAM_TYPES)
    indication = val_str(b, "indication")
    risk = val_enum(b, "risk_stratification", RISK_TIERS)
    # ownership (priority 2, before existence)
    if physician_id != g.uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "physician_id must equal the acting physician's X-User-ID")
    # existence left-to-right: patient, physician
    _find("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    _find("physicians", physician_id, "ERR_PHYSICIAN_NOT_FOUND")
    e = new_entity({
        "patient_id": patient_id,
        "physician_id": physician_id,
        "program_type": program_type,
        "indication": indication,
        "risk_stratification": risk,
        "status": "PENDING",
    })
    DB["referrals"][e["id"]] = e
    return respond(ser_referral(e), 201)


@app.route("/rehab/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    require_auth(ALL_ROLES)
    return respond(ser_referral(_find("referrals", rid, "ERR_REFERRAL_NOT_FOUND")))


@app.route("/rehab/referrals", methods=["GET"])
def list_referrals():
    require_auth(ALL_ROLES)
    items = list(DB["referrals"].values())
    pid = request.args.get("patient_id")
    phid = request.args.get("physician_id")
    if pid is not None:
        items = [x for x in items if x["patient_id"] == pid]
    if phid is not None:
        items = [x for x in items if x["physician_id"] == phid]
    return list_response(items, ser_referral)


@app.route("/rehab/referrals/<rid>/decision", methods=["POST"])
def referral_decision(rid):
    require_auth(["RehabCoordinator"])
    ref = _find("referrals", rid, "ERR_REFERRAL_NOT_FOUND")
    b = get_body()
    decision = val_enum(b, "decision", DECISIONS, err="ERR_INVALID_DECISION")
    if ref["status"] != "PENDING":
        raise ApiError("ERR_REFERRAL_NOT_PENDING", 409, "Referral is not PENDING")
    ref["status"] = "ACCEPTED" if decision == "ACCEPT" else "DECLINED"
    touch(ref)
    return respond(ser_referral(ref))


# ---- Programs ----
@app.route("/rehab/programs", methods=["POST"])
def create_program():
    require_auth(["RehabCoordinator"])
    b = get_body()
    referral_id = val_str(b, "referral_id")
    current_phase = val_enum(b, "current_phase", PHASES, required=False)
    cap = val_int(b, "authorized_session_cap", required=False, positive=True)
    ref = _find("referrals", referral_id, "ERR_REFERRAL_NOT_FOUND")
    if ref["status"] != "ACCEPTED":
        raise ApiError("ERR_REFERRAL_NOT_ACCEPTED", 409, "Referral is not ACCEPTED")
    e = new_entity({
        "patient_id": ref["patient_id"],
        "referral_id": referral_id,
        "program_type": ref["program_type"],
        "risk_stratification": ref["risk_stratification"],
        "current_phase": current_phase or "PHASE_I",
        "authorized_session_cap": cap if cap is not None else SESSION_CAP_DEFAULT,
        "consecutive_missed_count": 0,
        "status": "DRAFT",
    })
    DB["programs"][e["id"]] = e
    return respond(ser_program(e), 201)


@app.route("/rehab/programs/<pid>", methods=["GET"])
def get_program(pid):
    require_auth(ALL_ROLES)
    return respond(ser_program(_find("programs", pid, "ERR_PROGRAM_NOT_FOUND")))


@app.route("/rehab/programs", methods=["GET"])
def list_programs():
    require_auth(ALL_ROLES)
    items = list(DB["programs"].values())
    pat = request.args.get("patient_id")
    ref = request.args.get("referral_id")
    if pat is not None:
        items = [x for x in items if x["patient_id"] == pat]
    if ref is not None:
        items = [x for x in items if x["referral_id"] == ref]
    return list_response(items, ser_program)


@app.route("/rehab/programs/<pid>/activate", methods=["POST"])
def activate_program(pid):
    require_auth(["RehabCoordinator"])
    p = _find("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    if p["status"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_NOT_DRAFT", 409, "Program is not DRAFT")
    has_appr = any(
        a["program_id"] == pid and a["status"] == "APPROVED"
        for a in DB["authorizations"].values()
    )
    if not has_appr:
        raise ApiError("ERR_NO_APPROVED_AUTHORIZATION", 409,
                       "No APPROVED authorization exists for the program")
    has_baseline = any(
        o["program_id"] == pid and o["timing"] == "BASELINE" and o["status"] == "FINALIZED"
        for o in DB["outcomes"].values()
    )
    if not has_baseline:
        raise ApiError("ERR_BASELINE_OUTCOME_REQUIRED", 409,
                       "A FINALIZED BASELINE outcome is required")
    p["status"] = "ACTIVE"
    touch(p)
    return respond(ser_program(p))


@app.route("/rehab/programs/<pid>/hold", methods=["POST"])
def hold_program(pid):
    require_auth(["RehabCoordinator", "RehabClinician"])
    p = _find("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    get_body()  # reason optional
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409, "Program is not ACTIVE")
    p["status"] = "ON_HOLD"
    cascade_cancel_scheduled(p)
    touch(p)
    return respond(ser_program(p))


@app.route("/rehab/programs/<pid>/resume", methods=["POST"])
def resume_program(pid):
    require_auth(["RehabCoordinator"])
    p = _find("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    if p["status"] != "ON_HOLD":
        raise ApiError("ERR_PROGRAM_NOT_ON_HOLD", 409, "Program is not ON_HOLD")
    p["status"] = "ACTIVE"
    p["consecutive_missed_count"] = 0
    touch(p)
    return respond(ser_program(p))


@app.route("/rehab/programs/<pid>/discharge", methods=["POST"])
def discharge_program(pid):
    require_auth(["RehabCoordinator"])
    p = _find("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409, "Program is not ACTIVE")
    if any(s["program_id"] == pid and s["status"] == "SCHEDULED"
           for s in DB["sessions"].values()):
        raise ApiError("ERR_ACTIVE_SESSIONS_EXIST", 409, "Scheduled sessions still exist")
    disc = [
        o for o in DB["outcomes"].values()
        if o["program_id"] == pid and o["timing"] == "DISCHARGE" and o["status"] == "FINALIZED"
    ]
    if not disc:
        raise ApiError("ERR_NO_FINALIZED_DISCHARGE_OUTCOME", 409,
                       "A FINALIZED DISCHARGE outcome is required")
    p["status"] = "DISCHARGED"
    # side effect: OPEN GOAL care items -> NOT_ACHIEVED
    for item in DB["care_plan_items"].values():
        if item["program_id"] == pid and item["item_type"] == "GOAL" and item["status"] == "OPEN":
            item["status"] = "NOT_ACHIEVED"
            touch(item)
    # side effect: create MaintenanceProgram
    disc_outcome = max(disc, key=lambda x: x["_seq"])
    _, imp_p = compute_improvement(disc_outcome)
    if imp_p is not None and Decimal(str(imp_p)) < MAINTENANCE_INTENSIVE_THRESHOLD_PCT:
        tier = "INTENSIVE"
    else:
        tier = "STANDARD"
    m = new_entity({
        "program_id": pid,
        "patient_id": p["patient_id"],
        "tier": tier,
        "monthly_visit_allowance": MONTHLY_ALLOWANCE[tier],
        "status": "ACTIVE",
    })
    DB["maintenance"][m["id"]] = m
    touch(p)
    return respond(ser_program(p))


@app.route("/rehab/programs/<pid>/withdraw", methods=["POST"])
def withdraw_program(pid):
    require_auth(["RehabCoordinator"])
    p = _find("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    get_body()  # reason optional
    if p["status"] not in ("DRAFT", "ACTIVE", "ON_HOLD"):
        raise ApiError("ERR_PROGRAM_ALREADY_TERMINAL", 409, "Program is already terminal")
    p["status"] = "WITHDRAWN"
    cascade_cancel_scheduled(p)
    touch(p)
    return respond(ser_program(p))


@app.route("/rehab/programs/<pid>/statement", methods=["GET"])
def program_statement(pid):
    require_auth(["RehabCoordinator", "BillingSpecialist"])
    p = _find("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    claims = [c for c in program_claims(pid) if c["status"] != "VOID"]
    claims = sorted_by_created(claims)
    total_dollars = 0
    total_pr = 0
    outstanding = 0
    for c in claims:
        pr = c["patient_responsibility_cents"]
        total_dollars += int(round_half_up(Decimal(pr) / Decimal(100), 0))
        total_pr += pr
        if c["status"] == "DENIED":
            outstanding += pr
    data = {
        "statement_total_dollars": total_dollars,
        "claim_count": len(claims),
        "total_patient_responsibility_cents": total_pr,
        "outstanding_balance_cents": outstanding,
    }
    return respond(data)


# ---- Insurance Authorizations ----
@app.route("/rehab/authorizations", methods=["POST"])
def create_authorization():
    require_auth(["RehabCoordinator"])
    b = get_body()
    program_id = val_str(b, "program_id")
    payer_name = val_str(b, "payer_name")
    authorized_visits = val_int(b, "authorized_visits", positive=True)
    allowed_amount_cents = val_int(b, "allowed_amount_cents", min_val=0)
    copay_cents = val_int(b, "copay_cents", min_val=0)
    _find("programs", program_id, "ERR_PROGRAM_NOT_FOUND")
    e = new_entity({
        "program_id": program_id,
        "payer_name": payer_name,
        "authorized_visits": authorized_visits,
        "allowed_amount_cents": allowed_amount_cents,
        "copay_cents": copay_cents,
        "status": "PENDING",
    })
    DB["authorizations"][e["id"]] = e
    return respond(ser_authorization(e), 201)


@app.route("/rehab/authorizations/<aid>", methods=["GET"])
def get_authorization(aid):
    require_auth(ALL_ROLES)
    return respond(ser_authorization(_find("authorizations", aid, "ERR_AUTHORIZATION_NOT_FOUND")))


@app.route("/rehab/authorizations", methods=["GET"])
def list_authorizations():
    require_auth(ALL_ROLES)
    items = list(DB["authorizations"].values())
    prog = request.args.get("program_id")
    if prog is not None:
        items = [x for x in items if x["program_id"] == prog]
    return list_response(items, ser_authorization)


@app.route("/rehab/authorizations/<aid>/approve", methods=["POST"])
def approve_authorization(aid):
    require_auth(["RehabCoordinator"])
    a = _find("authorizations", aid, "ERR_AUTHORIZATION_NOT_FOUND")
    if a["status"] != "PENDING":
        raise ApiError("ERR_AUTHORIZATION_NOT_PENDING", 409, "Authorization is not PENDING")
    a["status"] = "APPROVED"
    touch(a)
    return respond(ser_authorization(a))


# ---- Sessions ----
@app.route("/rehab/sessions", methods=["POST"])
def create_session():
    require_auth(["RehabCoordinator"])
    b = get_body()
    # structural validation
    program_id = val_str(b, "program_id")
    clinician_id = val_str(b, "clinician_id")
    station_id = val_str(b, "station_id")
    session_type = val_enum(b, "session_type", SESSION_TYPES)
    phase = val_enum(b, "phase", PHASES)
    start_raw = val_str(b, "scheduled_start")
    end_raw = val_str(b, "scheduled_end")
    expected_version = val_int(b, "expected_program_version")
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if start_dt is None or end_dt is None:
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime format")
    # existence (left-to-right): program, clinician, station
    program = _find("programs", program_id, "ERR_PROGRAM_NOT_FOUND")
    clinician = _find("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    station = _find("stations", station_id, "ERR_STATION_NOT_FOUND")
    # OCC
    if expected_version != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION", 412, "Program version is stale")
    # state
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409, "Program is not ACTIVE")
    # telemetry safety
    check_telemetry(program, session_type, station)
    # station overlap
    check_station_overlap(station_id, start_dt, end_dt)
    # clinician availability
    check_clinician_availability(clinician_id, start_dt, end_dt)
    # time range
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_TIME_RANGE", 400, "scheduled_end must be after scheduled_start")
    # capacity cap
    check_capacity(program)
    e = new_entity({
        "program_id": program_id,
        "clinician_id": clinician_id,
        "station_id": station_id,
        "session_type": session_type,
        "phase": phase,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "pre_hr": None,
        "post_hr": None,
        "post_spo2": None,
        "rpe": None,
        "exercise_minutes": None,
        "adverse_event": False,
        "status": "SCHEDULED",
    })
    DB["sessions"][e["id"]] = e
    touch(program)
    return respond(ser_session(e), 201)


@app.route("/rehab/sessions/<sid>", methods=["GET"])
def get_session(sid):
    require_auth(ALL_ROLES)
    return respond(ser_session(_find("sessions", sid, "ERR_SESSION_NOT_FOUND")))


@app.route("/rehab/sessions", methods=["GET"])
def list_sessions():
    require_auth(ALL_ROLES)
    items = list(DB["sessions"].values())
    for key in ("program_id", "clinician_id", "station_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_session)


@app.route("/rehab/sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    require_auth(["RehabClinician"])
    s = _find("sessions", sid, "ERR_SESSION_NOT_FOUND")
    # ownership: session.clinician_id must equal caller
    if s["clinician_id"] != g.uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "Not the supervising clinician")
    program = _find("programs", s["program_id"], "ERR_PROGRAM_NOT_FOUND")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED", 409, "Session is not SCHEDULED")
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409, "Program is not ACTIVE")
    b = get_body()
    pre_hr = val_int(b, "pre_hr", required=False)
    post_hr = val_int(b, "post_hr", required=False)
    post_spo2 = val_int(b, "post_spo2", required=False)
    rpe = val_int(b, "rpe", required=False)
    exercise_minutes = val_int(b, "exercise_minutes", required=False)
    if pre_hr is not None:
        s["pre_hr"] = pre_hr
    if post_hr is not None:
        s["post_hr"] = post_hr
    if post_spo2 is not None:
        s["post_spo2"] = post_spo2
    if rpe is not None:
        s["rpe"] = rpe
    if exercise_minutes is not None:
        s["exercise_minutes"] = exercise_minutes
    # adverse vitals check
    adverse = ((s["post_spo2"] is not None and s["post_spo2"] < SPO2_MIN_THRESHOLD)
               or (s["rpe"] is not None and s["rpe"] >= RPE_MAX_THRESHOLD))
    s["adverse_event"] = adverse
    s["status"] = "COMPLETED"
    touch(s)
    program["consecutive_missed_count"] = 0
    touch(program)
    if adverse and program["status"] == "ACTIVE":
        program["status"] = "ON_HOLD"
        cascade_cancel_scheduled(program)
    return respond(ser_session(s))


@app.route("/rehab/sessions/<sid>/mark-missed", methods=["POST"])
def mark_missed_session(sid):
    require_auth(["RehabClinician"])
    s = _find("sessions", sid, "ERR_SESSION_NOT_FOUND")
    if s["clinician_id"] != g.uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "Not the supervising clinician")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED", 409, "Session is not SCHEDULED")
    program = DB["programs"].get(s["program_id"])
    s["status"] = "MISSED"
    touch(s)
    if program is not None:
        program["consecutive_missed_count"] += 1
        touch(program)
        if (program["consecutive_missed_count"] >= MAX_CONSECUTIVE_MISSED
                and program["status"] == "ACTIVE"):
            program["status"] = "ON_HOLD"
            cascade_cancel_scheduled(program)
    return respond(ser_session(s))


@app.route("/rehab/sessions/<sid>/reschedule", methods=["POST"])
def reschedule_session(sid):
    require_auth(["RehabCoordinator"])
    s = _find("sessions", sid, "ERR_SESSION_NOT_FOUND")
    b = get_body()
    start_raw = val_str(b, "scheduled_start")
    end_raw = val_str(b, "scheduled_end")
    new_clinician = val_str(b, "clinician_id", required=False)
    new_station = val_str(b, "station_id", required=False)
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if start_dt is None or end_dt is None:
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime format")
    if new_clinician is not None:
        _find("clinicians", new_clinician, "ERR_CLINICIAN_NOT_FOUND")
    if new_station is not None:
        _find("stations", new_station, "ERR_STATION_NOT_FOUND")
    if s["status"] != "MISSED":
        raise ApiError("ERR_SESSION_NOT_MISSED", 409, "Session is not MISSED")
    program = _find("programs", s["program_id"], "ERR_PROGRAM_NOT_FOUND")
    clinician_id = new_clinician or s["clinician_id"]
    station_id = new_station or s["station_id"]
    station = _find("stations", station_id, "ERR_STATION_NOT_FOUND")
    # guards in precedence: telemetry, overlap, clinician, time-range, cap
    check_telemetry(program, s["session_type"], station)
    check_station_overlap(station_id, start_dt, end_dt, exclude_session_id=sid)
    check_clinician_availability(clinician_id, start_dt, end_dt, exclude_session_id=sid)
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_TIME_RANGE", 400, "scheduled_end must be after scheduled_start")
    check_capacity(program)
    s["scheduled_start"] = start_raw
    s["scheduled_end"] = end_raw
    s["_start_dt"] = start_dt
    s["_end_dt"] = end_dt
    s["clinician_id"] = clinician_id
    s["station_id"] = station_id
    s["status"] = "SCHEDULED"
    touch(s)
    return respond(ser_session(s))


@app.route("/rehab/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    require_auth(["RehabCoordinator"])
    s = _find("sessions", sid, "ERR_SESSION_NOT_FOUND")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED", 409, "Session is not SCHEDULED")
    s["status"] = "CANCELLED"
    touch(s)
    return respond(ser_session(s))


@app.route("/rehab/sessions/<sid>/void", methods=["POST"])
def void_session(sid):
    require_auth(["RehabCoordinator"])
    s = _find("sessions", sid, "ERR_SESSION_NOT_FOUND")
    if s["status"] != "COMPLETED":
        raise ApiError("ERR_SESSION_NOT_COMPLETED", 409, "Session is not COMPLETED")
    if any(c["session_id"] == sid and c["status"] != "VOID" for c in DB["claims"].values()):
        raise ApiError("ERR_SESSION_HAS_ACTIVE_CLAIM", 409, "Session has a non-VOID claim")
    s["status"] = "VOIDED"
    touch(s)
    program = DB["programs"].get(s["program_id"])
    if program is not None:
        touch(program)
    return respond(ser_session(s))


# ---- Care Plan Items ----
@app.route("/rehab/care-plan-items", methods=["POST"])
def create_care_item():
    require_auth(["RehabClinician"])
    b = get_body()
    program_id = val_str(b, "program_id")
    item_type = val_enum(b, "item_type", ITEM_TYPES)
    title = val_str(b, "title")
    target = val_str(b, "target_description", required=False)
    _find("programs", program_id, "ERR_PROGRAM_NOT_FOUND")
    e = new_entity({
        "program_id": program_id,
        "item_type": item_type,
        "title": title,
        "target_description": target,
        "status": "OPEN",
    })
    DB["care_plan_items"][e["id"]] = e
    return respond(ser_care_item(e), 201)


@app.route("/rehab/care-plan-items/<iid>", methods=["GET"])
def get_care_item(iid):
    require_auth(ALL_ROLES)
    return respond(ser_care_item(_find("care_plan_items", iid, "ERR_CARE_PLAN_ITEM_NOT_FOUND")))


@app.route("/rehab/care-plan-items", methods=["GET"])
def list_care_items():
    require_auth(ALL_ROLES)
    items = list(DB["care_plan_items"].values())
    for key in ("program_id", "item_type"):
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_care_item)


@app.route("/rehab/care-plan-items/<iid>/resolve", methods=["POST"])
def resolve_care_item(iid):
    require_auth(["RehabClinician"])
    item = _find("care_plan_items", iid, "ERR_CARE_PLAN_ITEM_NOT_FOUND")
    b = get_body()
    resolution = val_enum(b, "resolution", RESOLUTIONS)
    if item["status"] != "OPEN":
        raise ApiError("ERR_CARE_ITEM_NOT_OPEN", 409, "Care plan item is not OPEN")
    item["status"] = resolution
    touch(item)
    return respond(ser_care_item(item))


# ---- Outcome Assessments ----
@app.route("/rehab/outcomes", methods=["POST"])
def create_outcome():
    require_auth(["RehabClinician"])
    b = get_body()
    program_id = val_str(b, "program_id")
    timing = val_enum(b, "timing", TIMINGS)
    distance = val_int(b, "distance_meters", min_val=0)
    assessment_type = val_enum(b, "assessment_type", ASSESSMENT_TYPES, required=False)
    _find("programs", program_id, "ERR_PROGRAM_NOT_FOUND")
    e = new_entity({
        "program_id": program_id,
        "assessment_type": assessment_type or "SIX_MINUTE_WALK",
        "timing": timing,
        "distance_meters": distance,
        "status": "DRAFT",
    })
    DB["outcomes"][e["id"]] = e
    return respond(ser_outcome(e), 201)


@app.route("/rehab/outcomes/<oid>", methods=["GET"])
def get_outcome(oid):
    require_auth(ALL_ROLES)
    return respond(ser_outcome(_find("outcomes", oid, "ERR_OUTCOME_NOT_FOUND")))


@app.route("/rehab/outcomes", methods=["GET"])
def list_outcomes():
    require_auth(ALL_ROLES)
    items = list(DB["outcomes"].values())
    for key in ("program_id", "timing"):
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_outcome)


@app.route("/rehab/outcomes/<oid>/finalize", methods=["POST"])
def finalize_outcome(oid):
    require_auth(["RehabClinician"])
    o = _find("outcomes", oid, "ERR_OUTCOME_NOT_FOUND")
    b = get_body()
    final_distance = val_int(b, "final_distance_meters", required=False, min_val=0)
    if o["status"] != "DRAFT":
        raise ApiError("ERR_OUTCOME_NOT_DRAFT", 409, "Outcome is not DRAFT")
    if o["timing"] == "DISCHARGE":
        has_baseline = latest_finalized_baseline(o["program_id"]) is not None
        if not has_baseline:
            raise ApiError("ERR_BASELINE_OUTCOME_REQUIRED", 409,
                           "A FINALIZED BASELINE outcome is required")
    if final_distance is not None:
        o["distance_meters"] = final_distance
    o["status"] = "FINALIZED"
    touch(o)
    return respond(ser_outcome(o))


# ---- Billing Claims ----
@app.route("/rehab/claims", methods=["POST"])
def create_claim():
    require_auth(["BillingSpecialist"])
    b = get_body()
    program_id = val_str(b, "program_id")
    session_id = val_str(b, "session_id")
    authorization_id = val_str(b, "authorization_id")
    program = _find("programs", program_id, "ERR_PROGRAM_NOT_FOUND")
    session = _find("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    auth = _find("authorizations", authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")
    # session must be COMPLETED
    if session["status"] != "COMPLETED":
        raise ApiError("ERR_SESSION_NOT_COMPLETED", 409, "Referenced session is not COMPLETED")
    # cross-aggregate consistency
    if session["program_id"] != program_id or auth["program_id"] != program_id:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE", 409,
                       "Session or authorization belongs to a different program")
    # visit-limit
    if auth_visits_billed(authorization_id) >= auth["authorized_visits"]:
        raise ApiError("ERR_VISIT_LIMIT_REACHED", 409, "Payer visit limit reached")
    # pricing
    station = DB["stations"].get(session["station_id"])
    base = BASE_RATE_CENTS[session["session_type"]]
    mult = RISK_MULTIPLIER[program["risk_stratification"]]
    raw = int(round_half_up(Decimal(base) * mult, 0))
    if station is not None and station["station_type"] == "TELEMETRY":
        raw += TELEMETRY_SURCHARGE_CENTS
    billed = min(raw, MAX_BILLED_PER_SESSION_CENTS)
    est_reimb = max(0, min(billed, auth["allowed_amount_cents"]) - auth["copay_cents"])
    est_pr = billed - est_reimb
    e = new_entity({
        "program_id": program_id,
        "session_id": session_id,
        "authorization_id": authorization_id,
        "billed_amount_cents": billed,
        "estimated_reimbursement_cents": est_reimb,
        "estimated_patient_responsibility_cents": est_pr,
        "adjudicated_reimbursement_cents": None,
        "patient_responsibility_cents": est_pr,
        "denial_reason": None,
        "status": "DRAFT",
    })
    DB["claims"][e["id"]] = e
    touch(auth)
    return respond(ser_claim(e), 201)


@app.route("/rehab/claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_auth(ALL_ROLES)
    return respond(ser_claim(_find("claims", cid, "ERR_CLAIM_NOT_FOUND")))


@app.route("/rehab/claims", methods=["GET"])
def list_claims():
    require_auth(ALL_ROLES)
    items = list(DB["claims"].values())
    for key in ("program_id", "session_id", "authorization_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_claim)


@app.route("/rehab/claims/<cid>/submit", methods=["POST"])
def submit_claim(cid):
    require_auth(["BillingSpecialist"])
    c = _find("claims", cid, "ERR_CLAIM_NOT_FOUND")
    if c["status"] != "DRAFT":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTABLE", 409, "Claim is not DRAFT")
    c["status"] = "SUBMITTED"
    c["patient_responsibility_cents"] = c["estimated_patient_responsibility_cents"]
    touch(c)
    return respond(ser_claim(c))


@app.route("/rehab/claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    require_auth(["BillingSpecialist"])
    c = _find("claims", cid, "ERR_CLAIM_NOT_FOUND")
    b = get_body()
    outcome = val_enum(b, "outcome", ADJ_OUTCOMES)
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_ADJUDICABLE", 409, "Claim is not SUBMITTED")
    auth = DB["authorizations"].get(c["authorization_id"])
    copay = auth["copay_cents"] if auth else 0
    if outcome == "PAID":
        adjudicated_allowed = val_int(b, "adjudicated_allowed_cents", min_val=0)
        adj_reimb = max(0, adjudicated_allowed - copay)
        c["adjudicated_reimbursement_cents"] = adj_reimb
        c["patient_responsibility_cents"] = c["billed_amount_cents"] - adj_reimb
        c["status"] = "PAID"
    else:  # DENIED
        denial_reason = val_str(b, "denial_reason", required=False)
        c["denial_reason"] = denial_reason
        c["patient_responsibility_cents"] = c["billed_amount_cents"]
        c["status"] = "DENIED"
    touch(c)
    return respond(ser_claim(c))


@app.route("/rehab/claims/<cid>/resubmit", methods=["POST"])
def resubmit_claim(cid):
    require_auth(["BillingSpecialist"])
    c = _find("claims", cid, "ERR_CLAIM_NOT_FOUND")
    if c["status"] != "DENIED":
        raise ApiError("ERR_CLAIM_NOT_DENIED", 409, "Claim is not DENIED")
    c["status"] = "SUBMITTED"
    c["patient_responsibility_cents"] = c["estimated_patient_responsibility_cents"]
    touch(c)
    return respond(ser_claim(c))


@app.route("/rehab/claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    require_auth(["BillingSpecialist"])
    c = _find("claims", cid, "ERR_CLAIM_NOT_FOUND")
    if c["status"] not in ("DRAFT", "SUBMITTED", "DENIED"):
        raise ApiError("ERR_CLAIM_NOT_VOIDABLE", 409, "Claim is not voidable")
    c["status"] = "VOID"
    touch(c)
    auth = DB["authorizations"].get(c["authorization_id"])
    if auth is not None:
        touch(auth)
    return respond(ser_claim(c))


# ---- Maintenance Programs ----
@app.route("/rehab/maintenance-programs/<mid>", methods=["GET"])
def get_maintenance(mid):
    require_auth(ALL_ROLES)
    return respond(ser_maintenance(_find("maintenance", mid, "ERR_MAINTENANCE_NOT_FOUND")))


@app.route("/rehab/maintenance-programs", methods=["GET"])
def list_maintenance():
    require_auth(ALL_ROLES)
    items = list(DB["maintenance"].values())
    for key in ("program_id", "patient_id"):
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_maintenance)


@app.route("/rehab/maintenance-programs/<mid>/cancel", methods=["POST"])
def cancel_maintenance(mid):
    require_auth(["RehabCoordinator"])
    m = _find("maintenance", mid, "ERR_MAINTENANCE_NOT_FOUND")
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_MAINTENANCE_NOT_ACTIVE", 409, "Maintenance program is not ACTIVE")
    m["status"] = "CANCELLED"
    touch(m)
    return respond(ser_maintenance(m))


# ---- Logical clock (test-driving) ----
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["RehabCoordinator"])
    global _CLOCK
    b = get_body()
    to_iso = val_str(b, "to_iso8601")
    dt = parse_dt(to_iso)
    if dt is None:
        raise ApiError("ERR_VALIDATION", 400, "Invalid to_iso8601")
    _CLOCK = dt
    return respond({"current_utc": fmt_iso(_CLOCK)})


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
