import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# =============================================================================
# Constants
# =============================================================================
ROLES = {"IntakeCoordinator", "Clinician", "ClinicSupervisor"}
ALL_ROLES = ROLES

POLYPHARMACY_THRESHOLD = 4
HIGH_TIER_THRESHOLD = 50
MODERATE_TIER_THRESHOLD = 25
HAZARD_HIGH_THRESHOLD = 20
HAZARD_MODERATE_THRESHOLD = 10
ROOM_TURNOVER_BUFFER = timedelta(minutes=15)

TARGET_VISITS = {"HIGH": 12, "MODERATE": 8, "LOW": 4}

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


# =============================================================================
# In-memory store
# =============================================================================
class Store:
    def __init__(self):
        self.patients = {}
        self.referrals = {}
        self.clinicians = {}
        self.rooms = {}
        self.assessments = {}
        self.care_plans = {}
        self.authorizations = {}
        self.sessions = {}
        self.home_safety_evaluations = {}
        self.device_referrals = {}
        self.community_linkages = {}
        self.reassessments = {}
        self.clock = DEFAULT_CLOCK


store = Store()


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message, http_status):
    raise ApiError(error_id, message, http_status)


# =============================================================================
# Time / clock helpers
# =============================================================================
def clock_now():
    return store.clock


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(clock_now())


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


# =============================================================================
# Response envelope
# =============================================================================
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(extra=None):
    m = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def success(data, code=200, rtype="object", extra_meta=None):
    body = {"meta": make_meta(extra_meta), "response_type": rtype, "data": data}
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "method not allowed"},
    }
    return jsonify(body), 405


# =============================================================================
# Entity / common fields
# =============================================================================
def new_common():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# =============================================================================
# Auth
# =============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "missing or invalid authentication headers", 401)
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", "role not permitted for this operation", 403)


# =============================================================================
# Body validation
# =============================================================================
def get_body():
    b = request.get_json(force=True, silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        err("ERR_VALIDATION", "request body must be an object", 400)
    return b


def validate_body(body, specs):
    # Pass 1: presence + type
    for s in specs:
        name = s["name"]
        optional = s.get("optional", False)
        present = name in body and body[name] is not None
        if not present:
            if optional:
                continue
            err("ERR_VALIDATION", "missing required field: %s" % name, 400)
        v = body[name]
        kind = s["kind"]
        if kind in ("string", "enum"):
            if not isinstance(v, str):
                err("ERR_VALIDATION", "field %s must be a string" % name, 400)
        elif kind == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                err("ERR_VALIDATION", "field %s must be an integer" % name, 400)
        elif kind == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                err("ERR_VALIDATION", "field %s must be a number" % name, 400)
        elif kind == "datetime":
            if not isinstance(v, str) or parse_dt(v) is None:
                err("ERR_VALIDATION", "field %s must be an ISO 8601 datetime" % name, 400)
    # Pass 2: enum membership
    for s in specs:
        if s["kind"] == "enum":
            name = s["name"]
            if name in body and body[name] is not None:
                if body[name] not in s["members"]:
                    err("ERR_INVALID_ENUM", "field %s has an invalid value" % name, 422)


# =============================================================================
# Existence helpers
# =============================================================================
def resolve(coll, _id, err_id):
    ent = coll.get(_id)
    if ent is None:
        err(err_id, "referenced resource does not exist", 404)
    return ent


# =============================================================================
# Calculations
# =============================================================================
def round_half_up_cents(allowed_amount_cents, coinsurance_pct):
    val = Decimal(str(allowed_amount_cents)) * Decimal(str(coinsurance_pct))
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def screening_score(medication_count, self_report_fall_count):
    score = self_report_fall_count * 10
    if medication_count >= POLYPHARMACY_THRESHOLD:
        score += 15
    return score


def clinical_score(gait_speed_m_s, tug_seconds, berg_balance_score,
                   medication_count, self_report_fall_count):
    if gait_speed_m_s < 0.60:
        gait_pts = 30
    elif gait_speed_m_s < 0.80:
        gait_pts = 20
    elif gait_speed_m_s < 1.00:
        gait_pts = 10
    else:
        gait_pts = 0

    if tug_seconds >= 13.5:
        tug_pts = 30
    elif tug_seconds >= 12.0:
        tug_pts = 20
    elif tug_seconds >= 10.0:
        tug_pts = 10
    else:
        tug_pts = 0

    if berg_balance_score <= 20:
        berg_pts = 30
    elif berg_balance_score <= 40:
        berg_pts = 15
    else:
        berg_pts = 0

    med_pts = 10 if medication_count >= POLYPHARMACY_THRESHOLD else 0

    if self_report_fall_count >= 2:
        hist_pts = 10
    elif self_report_fall_count == 1:
        hist_pts = 5
    else:
        hist_pts = 0

    return gait_pts + tug_pts + berg_pts + med_pts + hist_pts


def tier_from_score(score):
    if score >= HIGH_TIER_THRESHOLD:
        return "HIGH"
    if score >= MODERATE_TIER_THRESHOLD:
        return "MODERATE"
    return "LOW"


def home_hazard_score(ev):
    return (ev["loose_rugs"] * 3 + ev["poor_lighting_rooms"] * 2
            + ev["missing_grab_bars"] * 5 + ev["unsecured_stairs"] * 5
            + ev["clutter_pathways"] * 2)


def hazard_tier_from_score(score):
    if score >= HAZARD_HIGH_THRESHOLD:
        return "HIGH"
    if score >= HAZARD_MODERATE_THRESHOLD:
        return "MODERATE"
    return "LOW"


# =============================================================================
# Derived-field reconciliation
# =============================================================================
def recompute_visits_used(auth):
    count = sum(
        1 for s in store.sessions.values()
        if s["authorization_id"] == auth["id"]
        and s["attendance_status"] in ("SCHEDULED", "ATTENDED", "NO_SHOW")
    )
    if auth["visits_used"] != count:
        auth["visits_used"] = count
        touch(auth)


def recompute_responsibility(plan):
    total = sum(
        s["copay_cents"] for s in store.sessions.values()
        if s["care_plan_id"] == plan["id"] and s["billing_status"] == "BILLED"
    )
    if plan["patient_responsibility_cents"] != total:
        plan["patient_responsibility_cents"] = total
        touch(plan)


# =============================================================================
# Listing helpers
# =============================================================================
def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return page, meta


def list_entities(coll, filters):
    args = request.args
    items = list(coll.values())
    for f in filters:
        val = args.get(f)
        if val is not None and val != "":
            items = [e for e in items if str(e.get(f)) == val]
    items.sort(key=lambda e: e["created_at"])
    return items


def list_response(coll, filters):
    items = list_entities(coll, filters)
    page, meta = paginate(items)
    return success(page, 200, "array", meta)


# =============================================================================
# Clock endpoint
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    body = get_body()
    validate_body(body, [{"name": "to_iso8601", "kind": "string"}])
    dt = parse_dt(body["to_iso8601"])
    if dt is None:
        err("ERR_VALIDATION", "to_iso8601 must be a valid ISO 8601 instant", 400)
    store.clock = dt
    return success({}, 200, "object")


# =============================================================================
# Patients
# =============================================================================
@app.route("/patients", methods=["POST"])
def create_patient():
    _uid, role = authenticate()
    authorize(role, {"IntakeCoordinator"})
    body = get_body()
    validate_body(body, [
        {"name": "full_name", "kind": "string"},
        {"name": "date_of_birth", "kind": "string"},
        {"name": "insurance_member_id", "kind": "string"},
    ])
    p = new_common()
    p.update({
        "full_name": body["full_name"],
        "date_of_birth": body["date_of_birth"],
        "insurance_member_id": body["insurance_member_id"],
        "status": "ACTIVE",
    })
    store.patients[p["id"]] = p
    return success(p, 201, "object")


@app.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    p = resolve(store.patients, pid, "ERR_PATIENT_NOT_FOUND")
    return success(p, 200, "object")


# =============================================================================
# Referrals
# =============================================================================
@app.route("/referrals", methods=["POST"])
def create_referral():
    _uid, role = authenticate()
    authorize(role, {"IntakeCoordinator"})
    body = get_body()
    validate_body(body, [
        {"name": "patient_id", "kind": "string"},
        {"name": "referral_source", "kind": "string"},
        {"name": "reason", "kind": "string"},
    ])
    resolve(store.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    r = new_common()
    r.update({
        "patient_id": body["patient_id"],
        "referral_source": body["referral_source"],
        "reason": body["reason"],
        "status": "RECEIVED",
    })
    store.referrals[r["id"]] = r
    return success(r, 201, "object")


@app.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    r = resolve(store.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    return success(r, 200, "object")


@app.route("/referrals", methods=["GET"])
def list_referrals():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(store.referrals, ["patient_id", "status"])


@app.route("/referrals/<rid>/decision", methods=["POST"])
def decide_referral(rid):
    _uid, role = authenticate()
    authorize(role, {"IntakeCoordinator", "ClinicSupervisor"})
    body = get_body()
    validate_body(body, [{"name": "decision", "kind": "enum", "members": {"ACCEPT", "DECLINE"}}])
    r = resolve(store.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    if r["status"] != "RECEIVED":
        err("ERR_INVALID_STATE", "referral not in RECEIVED", 409)
    r["status"] = "ACCEPTED" if body["decision"] == "ACCEPT" else "DECLINED"
    touch(r)
    return success(r, 200, "object")


# =============================================================================
# Clinicians
# =============================================================================
@app.route("/clinicians", methods=["POST"])
def create_clinician():
    _uid, role = authenticate()
    authorize(role, {"ClinicSupervisor"})
    body = get_body()
    validate_body(body, [
        {"name": "full_name", "kind": "string"},
        {"name": "discipline", "kind": "enum", "members": {"PT", "OT"}},
        {"name": "npi", "kind": "string"},
    ])
    c = new_common()
    c.update({
        "full_name": body["full_name"],
        "discipline": body["discipline"],
        "npi": body["npi"],
    })
    store.clinicians[c["id"]] = c
    return success(c, 201, "object")


@app.route("/clinicians/<cid>", methods=["GET"])
def get_clinician(cid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    c = resolve(store.clinicians, cid, "ERR_CLINICIAN_NOT_FOUND")
    return success(c, 200, "object")


# =============================================================================
# Rooms
# =============================================================================
@app.route("/rooms", methods=["POST"])
def create_room():
    _uid, role = authenticate()
    authorize(role, {"ClinicSupervisor"})
    body = get_body()
    validate_body(body, [
        {"name": "name", "kind": "string"},
        {"name": "room_type", "kind": "enum", "members": {"BALANCE_GYM", "EXAM", "GAIT_LAB"}},
    ])
    r = new_common()
    r.update({"name": body["name"], "room_type": body["room_type"]})
    store.rooms[r["id"]] = r
    return success(r, 201, "object")


@app.route("/rooms/<rid>", methods=["GET"])
def get_room(rid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    r = resolve(store.rooms, rid, "ERR_ROOM_NOT_FOUND")
    return success(r, 200, "object")


# =============================================================================
# Assessments
# =============================================================================
@app.route("/assessments", methods=["POST"])
def create_assessment():
    _uid, role = authenticate()
    authorize(role, {"Clinician"})
    body = get_body()
    validate_body(body, [
        {"name": "patient_id", "kind": "string"},
        {"name": "referral_id", "kind": "string"},
        {"name": "clinician_id", "kind": "string"},
        {"name": "gait_speed_m_s", "kind": "number"},
        {"name": "tug_seconds", "kind": "number"},
        {"name": "berg_balance_score", "kind": "int"},
        {"name": "medication_count", "kind": "int"},
        {"name": "self_report_fall_count", "kind": "int"},
    ])
    resolve(store.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    resolve(store.referrals, body["referral_id"], "ERR_REFERRAL_NOT_FOUND")
    resolve(store.clinicians, body["clinician_id"], "ERR_CLINICIAN_NOT_FOUND")
    a = new_common()
    a.update({
        "patient_id": body["patient_id"],
        "referral_id": body["referral_id"],
        "clinician_id": body["clinician_id"],
        "gait_speed_m_s": body["gait_speed_m_s"],
        "tug_seconds": body["tug_seconds"],
        "berg_balance_score": body["berg_balance_score"],
        "medication_count": body["medication_count"],
        "self_report_fall_count": body["self_report_fall_count"],
        "screening_score": screening_score(body["medication_count"], body["self_report_fall_count"]),
        "clinical_score": None,
        "fall_risk_tier": None,
        "status": "DRAFT",
    })
    store.assessments[a["id"]] = a
    return success(a, 201, "object")


@app.route("/assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    a = resolve(store.assessments, aid, "ERR_ASSESSMENT_NOT_FOUND")
    return success(a, 200, "object")


@app.route("/assessments", methods=["GET"])
def list_assessments():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(store.assessments, ["patient_id", "referral_id", "clinician_id", "status"])


@app.route("/assessments/<aid>/finalize", methods=["POST"])
def finalize_assessment(aid):
    uid, role = authenticate()
    authorize(role, {"Clinician"})
    a = resolve(store.assessments, aid, "ERR_ASSESSMENT_NOT_FOUND")
    if a["clinician_id"] != uid:
        err("ERR_NOT_OWNER", "acting clinician is not the owner", 403)
    if a["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "assessment not in DRAFT", 409)
    score = clinical_score(a["gait_speed_m_s"], a["tug_seconds"], a["berg_balance_score"],
                           a["medication_count"], a["self_report_fall_count"])
    a["clinical_score"] = score
    a["fall_risk_tier"] = tier_from_score(score)
    a["status"] = "FINALIZED"
    touch(a)
    return success(a, 200, "object")


# =============================================================================
# Care plans
# =============================================================================
@app.route("/care-plans", methods=["POST"])
def create_care_plan():
    _uid, role = authenticate()
    authorize(role, {"IntakeCoordinator", "ClinicSupervisor"})
    body = get_body()
    validate_body(body, [
        {"name": "patient_id", "kind": "string"},
        {"name": "assessment_id", "kind": "string"},
    ])
    resolve(store.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    a = resolve(store.assessments, body["assessment_id"], "ERR_ASSESSMENT_NOT_FOUND")
    if a["status"] != "FINALIZED":
        err("ERR_ASSESSMENT_NOT_FINALIZED", "assessment is not FINALIZED", 409)
    tier = a["fall_risk_tier"]
    cp = new_common()
    cp.update({
        "patient_id": body["patient_id"],
        "assessment_id": body["assessment_id"],
        "fall_risk_tier": tier,
        "target_visits": TARGET_VISITS[tier],
        "estimated_patient_responsibility_cents": None,
        "patient_responsibility_cents": 0,
        "status": "DRAFT",
    })
    store.care_plans[cp["id"]] = cp
    return success(cp, 201, "object")


@app.route("/care-plans/<cid>", methods=["GET"])
def get_care_plan(cid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    cp = resolve(store.care_plans, cid, "ERR_CARE_PLAN_NOT_FOUND")
    return success(cp, 200, "object")


@app.route("/care-plans", methods=["GET"])
def list_care_plans():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(store.care_plans, ["patient_id", "assessment_id", "status"])


@app.route("/care-plans/<cid>/activate", methods=["POST"])
def activate_care_plan(cid):
    _uid, role = authenticate()
    authorize(role, {"ClinicSupervisor"})
    cp = resolve(store.care_plans, cid, "ERR_CARE_PLAN_NOT_FOUND")
    if cp["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "care plan not in DRAFT", 409)
    cp["status"] = "ACTIVE"
    touch(cp)
    return success(cp, 200, "object")


@app.route("/care-plans/<cid>/discharge", methods=["POST"])
def discharge_care_plan(cid):
    _uid, role = authenticate()
    authorize(role, {"ClinicSupervisor"})
    cp = resolve(store.care_plans, cid, "ERR_CARE_PLAN_NOT_FOUND")
    if cp["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "care plan not in ACTIVE", 409)
    cp["status"] = "DISCHARGED"
    touch(cp)
    # cascade: cancel SCHEDULED sessions, release reserved visits
    affected_auths = set()
    for s in store.sessions.values():
        if s["care_plan_id"] == cp["id"] and s["attendance_status"] == "SCHEDULED":
            s["attendance_status"] = "CANCELLED"
            touch(s)
            affected_auths.add(s["authorization_id"])
    for auth_id in affected_auths:
        auth = store.authorizations.get(auth_id)
        if auth is not None:
            recompute_visits_used(auth)
    return success(cp, 200, "object")


@app.route("/care-plans/<cid>/outcome", methods=["GET"])
def care_plan_outcome(cid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    cp = resolve(store.care_plans, cid, "ERR_CARE_PLAN_NOT_FOUND")
    origin = store.assessments.get(cp["assessment_id"])
    tier_at_intake = origin["fall_risk_tier"] if origin else None
    origin_score = origin["clinical_score"] if origin else None

    finals = [r for r in store.reassessments.values()
              if r["care_plan_id"] == cp["id"] and r["status"] == "FINALIZED"]
    latest = None
    if finals:
        latest = max(finals, key=lambda r: (r["created_at"], r["version"]))

    if latest is not None and origin_score is not None:
        delta = latest["clinical_score"] - origin_score
    else:
        delta = None

    attended = sum(1 for s in store.sessions.values()
                   if s["care_plan_id"] == cp["id"] and s["attendance_status"] == "ATTENDED")

    summary = {
        "tier_at_intake": tier_at_intake,
        "tier_current": cp["fall_risk_tier"],
        "clinical_score_delta": delta,
        "attended_visit_count": attended,
        "total_patient_responsibility_cents": cp["patient_responsibility_cents"],
        "improvement_flag": (delta is not None and delta < 0),
    }
    return success(summary, 200, "object")


@app.route("/care-plans/<cid>/reassessments", methods=["POST"])
def create_reassessment(cid):
    _uid, role = authenticate()
    authorize(role, {"Clinician"})
    body = get_body()
    validate_body(body, [
        {"name": "clinician_id", "kind": "string"},
        {"name": "gait_speed_m_s", "kind": "number"},
        {"name": "tug_seconds", "kind": "number"},
        {"name": "berg_balance_score", "kind": "int"},
        {"name": "medication_count", "kind": "int"},
        {"name": "self_report_fall_count", "kind": "int"},
    ])
    cp = resolve(store.care_plans, cid, "ERR_CARE_PLAN_NOT_FOUND")
    resolve(store.clinicians, body["clinician_id"], "ERR_CLINICIAN_NOT_FOUND")
    if cp["status"] != "ACTIVE":
        err("ERR_PLAN_NOT_ACTIVE", "care plan not in ACTIVE", 409)
    r = new_common()
    r.update({
        "care_plan_id": cp["id"],
        "clinician_id": body["clinician_id"],
        "gait_speed_m_s": body["gait_speed_m_s"],
        "tug_seconds": body["tug_seconds"],
        "berg_balance_score": body["berg_balance_score"],
        "medication_count": body["medication_count"],
        "self_report_fall_count": body["self_report_fall_count"],
        "clinical_score": None,
        "fall_risk_tier": None,
        "status": "DRAFT",
    })
    store.reassessments[r["id"]] = r
    cp["status"] = "UNDER_REASSESSMENT"
    touch(cp)
    return success(r, 201, "object")


@app.route("/reassessments/<rid>", methods=["GET"])
def get_reassessment(rid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    r = resolve(store.reassessments, rid, "ERR_REASSESSMENT_NOT_FOUND")
    return success(r, 200, "object")


@app.route("/reassessments", methods=["GET"])
def list_reassessments():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(store.reassessments, ["care_plan_id", "clinician_id", "status"])


@app.route("/reassessments/<rid>/finalize", methods=["POST"])
def finalize_reassessment(rid):
    uid, role = authenticate()
    authorize(role, {"Clinician"})
    r = resolve(store.reassessments, rid, "ERR_REASSESSMENT_NOT_FOUND")
    if r["clinician_id"] != uid:
        err("ERR_NOT_OWNER", "acting clinician is not the owner", 403)
    cp = store.care_plans.get(r["care_plan_id"])
    if r["status"] != "DRAFT" or cp is None or cp["status"] != "UNDER_REASSESSMENT":
        err("ERR_INVALID_STATE", "reassessment or plan not in a finalizable state", 409)
    score = clinical_score(r["gait_speed_m_s"], r["tug_seconds"], r["berg_balance_score"],
                           r["medication_count"], r["self_report_fall_count"])
    tier = tier_from_score(score)
    r["clinical_score"] = score
    r["fall_risk_tier"] = tier
    r["status"] = "FINALIZED"
    touch(r)
    # cascade to plan
    cp["fall_risk_tier"] = tier
    cp["target_visits"] = TARGET_VISITS[tier]
    cp["status"] = "ACTIVE"
    touch(cp)
    return success(r, 200, "object")


# =============================================================================
# Insurance authorizations
# =============================================================================
@app.route("/authorizations", methods=["POST"])
def create_authorization():
    _uid, role = authenticate()
    authorize(role, {"IntakeCoordinator", "ClinicSupervisor"})
    body = get_body()
    validate_body(body, [
        {"name": "patient_id", "kind": "string"},
        {"name": "care_plan_id", "kind": "string"},
        {"name": "payer_name", "kind": "string"},
        {"name": "visits_authorized", "kind": "int"},
        {"name": "allowed_amount_cents", "kind": "int"},
        {"name": "coinsurance_pct", "kind": "number"},
    ])
    resolve(store.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    resolve(store.care_plans, body["care_plan_id"], "ERR_CARE_PLAN_NOT_FOUND")
    auth = new_common()
    auth.update({
        "patient_id": body["patient_id"],
        "care_plan_id": body["care_plan_id"],
        "payer_name": body["payer_name"],
        "visits_authorized": body["visits_authorized"],
        "allowed_amount_cents": body["allowed_amount_cents"],
        "coinsurance_pct": body["coinsurance_pct"],
        "visits_used": 0,
        "status": "PENDING",
    })
    store.authorizations[auth["id"]] = auth
    return success(auth, 201, "object")


@app.route("/authorizations/<aid>", methods=["GET"])
def get_authorization(aid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    auth = resolve(store.authorizations, aid, "ERR_AUTHORIZATION_NOT_FOUND")
    return success(auth, 200, "object")


@app.route("/authorizations", methods=["GET"])
def list_authorizations():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(store.authorizations, ["patient_id", "care_plan_id", "status"])


@app.route("/authorizations/<aid>/decision", methods=["POST"])
def decide_authorization(aid):
    _uid, role = authenticate()
    authorize(role, {"ClinicSupervisor"})
    body = get_body()
    validate_body(body, [{"name": "decision", "kind": "enum", "members": {"APPROVE", "DENY"}}])
    auth = resolve(store.authorizations, aid, "ERR_AUTHORIZATION_NOT_FOUND")
    if auth["status"] != "PENDING":
        err("ERR_INVALID_STATE", "authorization not in PENDING", 409)
    if body["decision"] == "APPROVE":
        auth["status"] = "APPROVED"
        touch(auth)
        cp = store.care_plans.get(auth["care_plan_id"])
        if cp is not None:
            per_visit = round_half_up_cents(auth["allowed_amount_cents"], auth["coinsurance_pct"])
            cp["estimated_patient_responsibility_cents"] = cp["target_visits"] * per_visit
            touch(cp)
    else:
        auth["status"] = "DENIED"
        touch(auth)
    return success(auth, 200, "object")


# =============================================================================
# Sessions
# =============================================================================
@app.route("/sessions", methods=["POST"])
def create_session():
    _uid, role = authenticate()
    authorize(role, {"IntakeCoordinator", "ClinicSupervisor"})
    body = get_body()
    validate_body(body, [
        {"name": "care_plan_id", "kind": "string"},
        {"name": "clinician_id", "kind": "string"},
        {"name": "room_id", "kind": "string"},
        {"name": "authorization_id", "kind": "string"},
        {"name": "scheduled_start", "kind": "datetime"},
        {"name": "scheduled_end", "kind": "datetime"},
        {"name": "cpt_code", "kind": "string"},
    ])
    cp = resolve(store.care_plans, body["care_plan_id"], "ERR_CARE_PLAN_NOT_FOUND")
    resolve(store.clinicians, body["clinician_id"], "ERR_CLINICIAN_NOT_FOUND")
    resolve(store.rooms, body["room_id"], "ERR_ROOM_NOT_FOUND")
    auth = resolve(store.authorizations, body["authorization_id"], "ERR_AUTHORIZATION_NOT_FOUND")

    if cp["status"] != "ACTIVE":
        err("ERR_PLAN_NOT_ACTIVE", "care plan not in ACTIVE", 409)
    if auth["status"] != "APPROVED":
        err("ERR_AUTH_NOT_APPROVED", "authorization not APPROVED", 409)

    start = parse_dt(body["scheduled_start"])
    end = parse_dt(body["scheduled_end"])
    if not (end > start):
        err("ERR_INVALID_TIME_RANGE", "scheduled_end must be strictly after scheduled_start", 400)

    # clinician double-booking (half-open overlap)
    for s in store.sessions.values():
        if s["clinician_id"] == body["clinician_id"] and s["attendance_status"] != "CANCELLED":
            es = parse_dt(s["scheduled_start"])
            ee = parse_dt(s["scheduled_end"])
            if es < end and start < ee:
                err("ERR_CLINICIAN_DOUBLE_BOOKED", "clinician double-booked", 409)

    # room turnover buffer (>= 15 min gap; overlap rejected)
    for s in store.sessions.values():
        if s["room_id"] == body["room_id"] and s["attendance_status"] != "CANCELLED":
            es = parse_dt(s["scheduled_start"])
            ee = parse_dt(s["scheduled_end"])
            if start < ee + ROOM_TURNOVER_BUFFER and es < end + ROOM_TURNOVER_BUFFER:
                err("ERR_ROOM_BUFFER_CONFLICT", "room turnover buffer conflict", 409)

    # visit cap
    if auth["visits_used"] >= auth["visits_authorized"]:
        err("ERR_VISIT_CAP_EXCEEDED", "authorization visit cap reached", 409)

    sess = new_common()
    sess.update({
        "care_plan_id": body["care_plan_id"],
        "clinician_id": body["clinician_id"],
        "room_id": body["room_id"],
        "authorization_id": body["authorization_id"],
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "cpt_code": body["cpt_code"],
        "copay_cents": 0,
        "attendance_status": "SCHEDULED",
        "billing_status": "UNBILLED",
    })
    store.sessions[sess["id"]] = sess
    recompute_visits_used(auth)
    return success(sess, 201, "object")


@app.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    s = resolve(store.sessions, sid, "ERR_SESSION_NOT_FOUND")
    return success(s, 200, "object")


@app.route("/sessions", methods=["GET"])
def list_sessions():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(store.sessions, [
        "care_plan_id", "clinician_id", "room_id", "authorization_id",
        "attendance_status", "billing_status",
    ])


@app.route("/sessions/<sid>/attend", methods=["POST"])
def attend_session(sid):
    uid, role = authenticate()
    authorize(role, {"Clinician"})
    s = resolve(store.sessions, sid, "ERR_SESSION_NOT_FOUND")
    if s["clinician_id"] != uid:
        err("ERR_NOT_OWNER", "acting clinician is not the owner", 403)
    if s["attendance_status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "session not in SCHEDULED", 409)
    auth = store.authorizations.get(s["authorization_id"])
    copay = round_half_up_cents(auth["allowed_amount_cents"], auth["coinsurance_pct"])
    s["attendance_status"] = "ATTENDED"
    s["billing_status"] = "BILLED"
    s["copay_cents"] = copay
    touch(s)
    cp = store.care_plans.get(s["care_plan_id"])
    if cp is not None:
        recompute_responsibility(cp)
    return success(s, 200, "object")


@app.route("/sessions/<sid>/no-show", methods=["POST"])
def noshow_session(sid):
    uid, role = authenticate()
    authorize(role, {"Clinician"})
    s = resolve(store.sessions, sid, "ERR_SESSION_NOT_FOUND")
    if s["clinician_id"] != uid:
        err("ERR_NOT_OWNER", "acting clinician is not the owner", 403)
    if s["attendance_status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "session not in SCHEDULED", 409)
    s["attendance_status"] = "NO_SHOW"
    touch(s)
    # billing unchanged; reserved visit retained (no visits_used change)
    return success(s, 200, "object")


@app.route("/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    s = resolve(store.sessions, sid, "ERR_SESSION_NOT_FOUND")
    prev = s["attendance_status"]
    if prev not in ("SCHEDULED", "ATTENDED"):
        err("ERR_INVALID_STATE", "session cannot be cancelled from its current state", 409)
    s["attendance_status"] = "CANCELLED"
    if prev == "ATTENDED":
        s["billing_status"] = "REVERSED"
    touch(s)
    cp = store.care_plans.get(s["care_plan_id"])
    if cp is not None:
        recompute_responsibility(cp)
    auth = store.authorizations.get(s["authorization_id"])
    if auth is not None:
        recompute_visits_used(auth)
    return success(s, 200, "object")


# =============================================================================
# Home-safety evaluations
# =============================================================================
@app.route("/home-safety-evaluations", methods=["POST"])
def create_home_safety():
    _uid, role = authenticate()
    authorize(role, {"Clinician"})
    body = get_body()
    validate_body(body, [
        {"name": "patient_id", "kind": "string"},
        {"name": "care_plan_id", "kind": "string"},
        {"name": "loose_rugs", "kind": "int"},
        {"name": "poor_lighting_rooms", "kind": "int"},
        {"name": "missing_grab_bars", "kind": "int"},
        {"name": "unsecured_stairs", "kind": "int"},
        {"name": "clutter_pathways", "kind": "int"},
    ])
    resolve(store.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    resolve(store.care_plans, body["care_plan_id"], "ERR_CARE_PLAN_NOT_FOUND")
    ev = new_common()
    ev.update({
        "patient_id": body["patient_id"],
        "care_plan_id": body["care_plan_id"],
        "loose_rugs": body["loose_rugs"],
        "poor_lighting_rooms": body["poor_lighting_rooms"],
        "missing_grab_bars": body["missing_grab_bars"],
        "unsecured_stairs": body["unsecured_stairs"],
        "clutter_pathways": body["clutter_pathways"],
        "home_hazard_score": None,
        "hazard_tier": None,
        "generated_device_referral_id": None,
        "status": "DRAFT",
    })
    store.home_safety_evaluations[ev["id"]] = ev
    return success(ev, 201, "object")


@app.route("/home-safety-evaluations/<eid>", methods=["GET"])
def get_home_safety(eid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    ev = resolve(store.home_safety_evaluations, eid, "ERR_HOME_SAFETY_NOT_FOUND")
    return success(ev, 200, "object")


@app.route("/home-safety-evaluations", methods=["GET"])
def list_home_safety():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(store.home_safety_evaluations, ["patient_id", "care_plan_id", "status"])


@app.route("/home-safety-evaluations/<eid>/finalize", methods=["POST"])
def finalize_home_safety(eid):
    _uid, role = authenticate()
    authorize(role, {"Clinician"})
    ev = resolve(store.home_safety_evaluations, eid, "ERR_HOME_SAFETY_NOT_FOUND")
    if ev["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "evaluation not in DRAFT", 409)
    score = home_hazard_score(ev)
    tier = hazard_tier_from_score(score)
    ev["home_hazard_score"] = score
    ev["hazard_tier"] = tier
    ev["status"] = "FINALIZED"
    if tier == "HIGH":
        ref = new_common()
        ref.update({
            "patient_id": ev["patient_id"],
            "care_plan_id": ev["care_plan_id"],
            "home_safety_evaluation_id": ev["id"],
            "device_type": "GRAB_BAR" if ev["missing_grab_bars"] > 0 else "ROLLATOR",
            "source": "AUTO_HAZARD",
            "status": "PENDING",
        })
        store.device_referrals[ref["id"]] = ref
        ev["generated_device_referral_id"] = ref["id"]
    touch(ev)
    return success(ev, 200, "object")


# =============================================================================
# Assistive-device referrals
# =============================================================================
@app.route("/device-referrals", methods=["POST"])
def create_device_referral():
    _uid, role = authenticate()
    authorize(role, {"Clinician", "ClinicSupervisor"})
    body = get_body()
    validate_body(body, [
        {"name": "patient_id", "kind": "string"},
        {"name": "care_plan_id", "kind": "string"},
        {"name": "device_type", "kind": "enum",
         "members": {"CANE", "WALKER", "ROLLATOR", "GRAB_BAR"}},
        {"name": "home_safety_evaluation_id", "kind": "string", "optional": True},
    ])
    resolve(store.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    resolve(store.care_plans, body["care_plan_id"], "ERR_CARE_PLAN_NOT_FOUND")
    hse_id = body.get("home_safety_evaluation_id")
    if hse_id is not None:
        resolve(store.home_safety_evaluations, hse_id, "ERR_HOME_SAFETY_NOT_FOUND")
    ref = new_common()
    ref.update({
        "patient_id": body["patient_id"],
        "care_plan_id": body["care_plan_id"],
        "home_safety_evaluation_id": hse_id,
        "device_type": body["device_type"],
        "source": "MANUAL",
        "status": "PENDING",
    })
    store.device_referrals[ref["id"]] = ref
    return success(ref, 201, "object")


@app.route("/device-referrals/<rid>", methods=["GET"])
def get_device_referral(rid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    ref = resolve(store.device_referrals, rid, "ERR_DEVICE_REFERRAL_NOT_FOUND")
    return success(ref, 200, "object")


@app.route("/device-referrals", methods=["GET"])
def list_device_referrals():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(store.device_referrals,
                         ["patient_id", "care_plan_id", "home_safety_evaluation_id", "status", "source"])


@app.route("/device-referrals/<rid>/decision", methods=["POST"])
def decide_device_referral(rid):
    _uid, role = authenticate()
    authorize(role, {"ClinicSupervisor"})
    body = get_body()
    validate_body(body, [{"name": "decision", "kind": "enum",
                          "members": {"APPROVE", "DECLINE", "DISPENSE"}}])
    ref = resolve(store.device_referrals, rid, "ERR_DEVICE_REFERRAL_NOT_FOUND")
    decision = body["decision"]
    status = ref["status"]
    if decision == "APPROVE" and status == "PENDING":
        ref["status"] = "APPROVED"
    elif decision == "DECLINE" and status == "PENDING":
        ref["status"] = "DECLINED"
    elif decision == "DISPENSE" and status == "APPROVED":
        ref["status"] = "DISPENSED"
    else:
        err("ERR_INVALID_STATE", "decision does not match referral state", 409)
    touch(ref)
    return success(ref, 200, "object")


# =============================================================================
# Community-program linkages
# =============================================================================
@app.route("/community-linkages", methods=["POST"])
def create_community_linkage():
    _uid, role = authenticate()
    authorize(role, {"IntakeCoordinator", "ClinicSupervisor"})
    body = get_body()
    validate_body(body, [
        {"name": "patient_id", "kind": "string"},
        {"name": "care_plan_id", "kind": "string"},
        {"name": "assessment_id", "kind": "string"},
        {"name": "program_name", "kind": "enum",
         "members": {"MATTER_OF_BALANCE", "TAI_CHI_MOVING_FOR_BETTER_BALANCE",
                     "STEPPING_ON", "OTAGO"}},
        {"name": "expected_care_plan_version", "kind": "int"},
    ])
    resolve(store.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    cp = resolve(store.care_plans, body["care_plan_id"], "ERR_CARE_PLAN_NOT_FOUND")
    a = resolve(store.assessments, body["assessment_id"], "ERR_ASSESSMENT_NOT_FOUND")

    if cp["status"] != "ACTIVE":
        err("ERR_PLAN_NOT_ACTIVE", "care plan not in ACTIVE", 409)
    if a["status"] != "FINALIZED" or a["fall_risk_tier"] not in ("MODERATE", "HIGH"):
        err("ERR_TIER_NOT_ELIGIBLE", "assessment tier not eligible for community linkage", 422)
    if body["expected_care_plan_version"] != cp["version"]:
        err("ERR_STALE_PLAN_VERSION", "care plan version mismatch", 412)

    # supersede prior non-terminal linkage on the same plan
    for lk in store.community_linkages.values():
        if lk["care_plan_id"] == cp["id"] and lk["status"] in ("REFERRED", "ENROLLED"):
            lk["status"] = "WITHDRAWN"
            touch(lk)

    linkage = new_common()
    linkage.update({
        "patient_id": body["patient_id"],
        "care_plan_id": body["care_plan_id"],
        "assessment_id": body["assessment_id"],
        "program_name": body["program_name"],
        "status": "REFERRED",
    })
    store.community_linkages[linkage["id"]] = linkage
    touch(cp)  # linkage create increments plan version
    return success(linkage, 201, "object")


@app.route("/community-linkages/<lid>", methods=["GET"])
def get_community_linkage(lid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    lk = resolve(store.community_linkages, lid, "ERR_LINKAGE_NOT_FOUND")
    return success(lk, 200, "object")


@app.route("/community-linkages", methods=["GET"])
def list_community_linkages():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(store.community_linkages,
                         ["patient_id", "care_plan_id", "assessment_id", "status"])


@app.route("/community-linkages/<lid>/status", methods=["POST"])
def advance_community_linkage(lid):
    _uid, role = authenticate()
    authorize(role, {"IntakeCoordinator", "ClinicSupervisor"})
    body = get_body()
    validate_body(body, [{"name": "new_status", "kind": "enum",
                          "members": {"REFERRED", "ENROLLED", "COMPLETED", "DECLINED", "WITHDRAWN"}}])
    lk = resolve(store.community_linkages, lid, "ERR_LINKAGE_NOT_FOUND")
    cur = lk["status"]
    new = body["new_status"]
    allowed = {
        ("REFERRED", "ENROLLED"),
        ("REFERRED", "DECLINED"),
        ("ENROLLED", "COMPLETED"),
        ("ENROLLED", "WITHDRAWN"),
    }
    if (cur, new) not in allowed:
        err("ERR_INVALID_STATE", "transition not permitted from current state", 409)
    lk["status"] = new
    touch(lk)
    return success(lk, 200, "object")


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
