"""
Lymphedema & Specialty Rehab Clinic API (Task 0905, Expert tier).
Single-file Python + Flask implementation. In-memory storage only, no seeding.
"""

import os
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
ROLES = {"Clinician", "Authorizer", "DMECoordinator", "ClinicAdmin"}

BODY_REGIONS = {"LEFT_ARM", "RIGHT_ARM", "LEFT_LEG", "RIGHT_LEG",
                "HEAD_NECK", "TRUNK", "GENITAL"}
ETIOLOGIES = {"PRIMARY", "SECONDARY"}
ISL_STAGES = {"STAGE_0", "STAGE_I", "STAGE_II", "STAGE_III"}
CDT_COMPONENTS = {"MLD", "COMPRESSION_BANDAGING", "EXERCISE", "SKIN_CARE", "EDUCATION"}
CREDENTIALS = {"CLT", "OT", "PT"}

PI = Decimal("3.141592653589793")
DOUBLE_BOOK_BUFFER = timedelta(minutes=15)
MAINTENANCE_THRESHOLD = Decimal("50")

BASE_CLASS = {"STAGE_0": 1, "STAGE_I": 1, "STAGE_II": 2, "STAGE_III": 3}
BUMP_THRESHOLD = {"ARM": Decimal("150"), "LEG": Decimal("500"), "OTHER": Decimal("150")}
CUSTOM_THRESHOLD = {"ARM": Decimal("400"), "LEG": Decimal("1200"), "OTHER": Decimal("400")}
GARMENT_TYPE = {
    "LEFT_ARM": "SLEEVE", "RIGHT_ARM": "SLEEVE",
    "LEFT_LEG": "STOCKING", "RIGHT_LEG": "STOCKING",
    "HEAD_NECK": "CHIN_STRAP", "TRUNK": "VEST", "GENITAL": "COMPRESSION_SHORT",
}
L_CODE_TABLE = {
    "SLEEVE": {False: "L8100", True: "L8102"},
    "STOCKING": {False: "L8110", True: "L8112"},
    "CHIN_STRAP": {False: "L8130", True: "L8130"},
    "VEST": {False: "L8140", True: "L8140"},
    "COMPRESSION_SHORT": {False: "L8150", True: "L8150"},
}

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.patients = {}
        self.evaluations = {}
        self.authorizations = {}
        self.plans = {}
        self.therapists = {}
        self.sessions = {}
        self.garment_orders = {}
        self.dme_items = {}
        self.dispenses = {}
        self.reassessments = {}
        self.adherence_logs = {}
        self.clock = DEFAULT_CLOCK
        self.seq = 0


db = Store()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Clock / helpers
# ---------------------------------------------------------------------------
def now():
    return db.clock


def iso_ms(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso_ms(now())


def next_seq():
    db.seq += 1
    return db.seq


def mint_id():
    return str(uuid.uuid4())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def new_record(extra, common=True):
    ts = now_iso()
    rec = {"id": mint_id(), "created_at": ts}
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec.update(extra)
    rec["_seq"] = next_seq()
    return rec


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}


def respond_object(data, code=200):
    return jsonify({"meta": meta_base(), "response_type": "object", "data": data}), code


def respond_array(items, limit, offset, total):
    meta = meta_base()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def check_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return role, uid


# ---------------------------------------------------------------------------
# Body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True, force=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return body


def present(body, field):
    return field in body and body[field] is not None


def require(body, field):
    if not present(body, field):
        raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
    return body[field]


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def require_int(body, field, minimum=None):
    v = require(body, field)
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be >= {minimum}")
    return v


def require_num(body, field, minimum=None, strict=False):
    v = require(body, field)
    if not is_num(v):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a number")
    if minimum is not None:
        if strict and not (v > minimum):
            raise ApiError("ERR_VALIDATION", 422, f"{field} must be > {minimum}")
        if not strict and v < minimum:
            raise ApiError("ERR_VALIDATION", 422, f"{field} must be >= {minimum}")
    return v


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a non-empty string")
    return v


def require_bool(body, field):
    v = require(body, field)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a boolean")
    return v


def require_enum(body, field, allowed):
    v = require(body, field)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a string")
    if v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, f"{field} has an invalid value")
    return v


def require_num_array(body, field):
    v = require(body, field)
    if not isinstance(v, list):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be an array")
    for x in v:
        if not is_num(x):
            raise ApiError("ERR_VALIDATION", 422, f"{field} must contain only numbers")
    return v


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "Invalid datetime format")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid date")
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "Invalid date format (expected YYYY-MM-DD)")


# ---------------------------------------------------------------------------
# Existence resolution
# ---------------------------------------------------------------------------
def resolve(store, key, error_id):
    """Existence check for a *present* FK id. Missing/None is deferred to
    well-formedness. Returns the record; raises the given not-found error."""
    if key is None:
        return None
    if not isinstance(key, str) or key not in store:
        raise ApiError(error_id, 404, "Referenced resource not found")
    return store[key]


def get_or_404(store, rid, error_id):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(error_id, 404, "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Rounding / calculations
# ---------------------------------------------------------------------------
def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)  # 10^-places
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def to_float(dec):
    return float(dec)


def compute_volume(circumferences, interval_cm):
    h = Decimal(str(interval_cm))
    total = Decimal("0")
    twelve_pi = Decimal("12") * PI
    for i in range(len(circumferences) - 1):
        c0 = Decimal(str(circumferences[i]))
        c1 = Decimal(str(circumferences[i + 1]))
        seg = h * (c0 * c0 + c0 * c1 + c1 * c1) / twelve_pi
        seg = seg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += seg
    return total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def region_group(body_region):
    if body_region in ("LEFT_ARM", "RIGHT_ARM"):
        return "ARM"
    if body_region in ("LEFT_LEG", "RIGHT_LEG"):
        return "LEG"
    return "OTHER"


def classify_garment(evaluation):
    isl_stage = evaluation["isl_stage"]
    excess = Decimal(str(evaluation["excess_volume_ml"]))
    body_region = evaluation["body_region"]
    grp = region_group(body_region)
    base = BASE_CLASS[isl_stage]
    bumped = base + (1 if excess >= BUMP_THRESHOLD[grp] else 0)
    class_num = min(bumped, 4)
    custom = (class_num == 4) or (excess >= CUSTOM_THRESHOLD[grp])
    gtype = GARMENT_TYPE[body_region]
    l_code = L_CODE_TABLE[gtype][custom]
    return {
        "body_region": body_region,
        "garment_type": gtype,
        "compression_class": f"CLASS_{class_num}",
        "custom_fabrication": custom,
        "l_code": l_code,
    }


# ---------------------------------------------------------------------------
# Visit ledger
# ---------------------------------------------------------------------------
def recompute_ledger(auth):
    reserved = 0
    used = 0
    for s in db.sessions.values():
        if s["authorization_id"] != auth["id"]:
            continue
        cs = s["clinical_status"]
        if cs in ("SCHEDULED", "CHECKED_IN"):
            reserved += 1
        elif cs in ("COMPLETED", "NO_SHOW"):
            used += 1
    auth["visits_reserved"] = reserved
    auth["visits_used"] = used
    auth["visits_remaining"] = auth["visit_cap"] - reserved - used


def maybe_exhaust(auth):
    if auth["status"] == "APPROVED" and auth["visits_used"] >= auth["visit_cap"]:
        auth["status"] = "EXHAUSTED"
        for plan in db.plans.values():
            if plan["authorization_id"] == auth["id"] and plan["status"] == "ACTIVE":
                plan["status"] = "ON_HOLD"
                touch(plan)


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def paginate():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(store, filters=None):
    items = list(store.values())
    if filters:
        for field, val in filters.items():
            if val is not None:
                items = [r for r in items if r.get(field) == val]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = paginate()
    page = items[offset:offset + limit]
    return respond_array([public(r) for r in page], limit, offset, total)


# ===========================================================================
# PATIENTS
# ===========================================================================
@app.route("/patients", methods=["POST"])
def create_patient():
    check_auth({"ClinicAdmin"})
    body = get_body()
    full_name = require_str(body, "full_name")
    mrn = require_str(body, "mrn")
    dob = body.get("date_of_birth")
    if dob is not None and not isinstance(dob, str):
        raise ApiError("ERR_VALIDATION", 422, "date_of_birth must be a string")
    rec = new_record({
        "full_name": full_name,
        "mrn": mrn,
        "date_of_birth": dob,
        "status": "ACTIVE",
    })
    db.patients[rec["id"]] = rec
    return respond_object(public(rec), 201)


@app.route("/patients", methods=["GET"])
def list_patients():
    check_auth(ROLES)
    return list_response(db.patients)


@app.route("/patients/<rid>", methods=["GET"])
def get_patient(rid):
    check_auth(ROLES)
    rec = get_or_404(db.patients, rid, "ERR_PATIENT_NOT_FOUND")
    return respond_object(public(rec))


# ===========================================================================
# EVALUATIONS
# ===========================================================================
@app.route("/evaluations", methods=["POST"])
def create_evaluation():
    check_auth({"Clinician"})
    body = get_body()
    # 3. existence (present FK)
    patient = resolve(db.patients, body.get("patient_id"), "ERR_PATIENT_NOT_FOUND")
    # 4. well-formedness
    patient_id = require_str(body, "patient_id")
    if patient is None:
        patient = resolve(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    body_region = require_enum(body, "body_region", BODY_REGIONS)
    etiology = require_enum(body, "etiology", ETIOLOGIES)
    isl_stage = require_enum(body, "isl_stage", ISL_STAGES)
    interval_cm = require_num(body, "interval_cm", minimum=0, strict=True)
    circumferences = require_num_array(body, "circumferences_cm")
    contralateral = require_num_array(body, "contralateral_circumferences_cm")
    expected_version = require_int(body, "expected_patient_version")
    # 5. OCC
    if expected_version != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION", 412, "Patient version is stale")
    # 9. measurement sufficiency
    if len(circumferences) < 2:
        raise ApiError("ERR_INSUFFICIENT_MEASUREMENT", 422, "At least two circumference points are required")
    if len(circumferences) != len(contralateral):
        raise ApiError("ERR_MEASUREMENT_LENGTH_MISMATCH", 422, "Affected and contralateral arrays differ in length")
    # compute
    limb_vol = compute_volume(circumferences, interval_cm)
    contra_vol = compute_volume(contralateral, interval_cm)
    excess = limb_vol - contra_vol
    if excess < 0:
        excess = Decimal("0")
    excess = excess.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    rec = new_record({
        "patient_id": patient_id,
        "body_region": body_region,
        "etiology": etiology,
        "isl_stage": isl_stage,
        "interval_cm": interval_cm,
        "circumferences_cm": circumferences,
        "contralateral_circumferences_cm": contralateral,
        "limb_volume_ml": to_float(limb_vol),
        "contralateral_volume_ml": to_float(contra_vol),
        "excess_volume_ml": to_float(excess),
        "status": "DRAFT",
    })
    db.evaluations[rec["id"]] = rec

    # supersede prior FINALIZED evaluation for same patient + region
    for ev in db.evaluations.values():
        if (ev["id"] != rec["id"] and ev["patient_id"] == patient_id
                and ev["body_region"] == body_region and ev["status"] == "FINALIZED"):
            ev["status"] = "SUPERSEDED"
            touch(ev)
    # patient version advances
    touch(patient)
    return respond_object(public(rec), 201)


@app.route("/evaluations", methods=["GET"])
def list_evaluations():
    check_auth({"Clinician", "Authorizer", "ClinicAdmin"})
    return list_response(db.evaluations, {"patient_id": request.args.get("patient_id")})


@app.route("/evaluations/<rid>", methods=["GET"])
def get_evaluation(rid):
    check_auth({"Clinician", "Authorizer", "ClinicAdmin"})
    rec = get_or_404(db.evaluations, rid, "ERR_EVALUATION_NOT_FOUND")
    return respond_object(public(rec))


@app.route("/evaluations/<rid>/finalize", methods=["POST"])
def finalize_evaluation(rid):
    check_auth({"Clinician"})
    rec = get_or_404(db.evaluations, rid, "ERR_EVALUATION_NOT_FOUND")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Evaluation is not in DRAFT")
    rec["status"] = "FINALIZED"
    touch(rec)
    return respond_object(public(rec))


# ===========================================================================
# AUTHORIZATIONS
# ===========================================================================
@app.route("/authorizations", methods=["POST"])
def create_authorization():
    check_auth({"Authorizer", "ClinicAdmin"})
    body = get_body()
    patient = resolve(db.patients, body.get("patient_id"), "ERR_PATIENT_NOT_FOUND")
    patient_id = require_str(body, "patient_id")
    if patient is None:
        resolve(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    body_region = require_enum(body, "body_region", BODY_REGIONS)
    payer_name = require_str(body, "payer_name")
    auth_number = require_str(body, "auth_number")
    visit_cap = require_int(body, "visit_cap", minimum=0)
    eff_start_raw = require_str(body, "effective_start_date")
    eff_end_raw = require_str(body, "effective_end_date")
    eff_start = parse_date(eff_start_raw)
    eff_end = parse_date(eff_end_raw)
    # 8. temporal: auth-window overlap for same patient+region
    for a in db.authorizations.values():
        if (a["patient_id"] == patient_id and a["body_region"] == body_region
                and a["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "EXHAUSTED")):
            a_start = parse_date(a["effective_start_date"])
            a_end = parse_date(a["effective_end_date"])
            if a_start <= eff_end and eff_start <= a_end:
                raise ApiError("ERR_AUTH_WINDOW_OVERLAP", 409, "Authorization window overlaps an existing authorization")
    rec = new_record({
        "patient_id": patient_id,
        "body_region": body_region,
        "payer_name": payer_name,
        "auth_number": auth_number,
        "visit_cap": visit_cap,
        "effective_start_date": eff_start_raw,
        "effective_end_date": eff_end_raw,
        "visits_reserved": 0,
        "visits_used": 0,
        "visits_remaining": visit_cap,
        "status": "DRAFT",
    })
    db.authorizations[rec["id"]] = rec
    return respond_object(public(rec), 201)


@app.route("/authorizations", methods=["GET"])
def list_authorizations():
    check_auth({"Clinician", "Authorizer", "ClinicAdmin"})
    return list_response(db.authorizations, {"patient_id": request.args.get("patient_id")})


@app.route("/authorizations/<rid>", methods=["GET"])
def get_authorization(rid):
    check_auth({"Clinician", "Authorizer", "ClinicAdmin"})
    rec = get_or_404(db.authorizations, rid, "ERR_AUTHORIZATION_NOT_FOUND")
    return respond_object(public(rec))


@app.route("/authorizations/<rid>/submit", methods=["POST"])
def submit_authorization(rid):
    check_auth({"Authorizer"})
    rec = get_or_404(db.authorizations, rid, "ERR_AUTHORIZATION_NOT_FOUND")
    if rec["status"] not in ("DRAFT", "DENIED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Authorization cannot be submitted from its current state")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return respond_object(public(rec))


@app.route("/authorizations/<rid>/approve", methods=["POST"])
def approve_authorization(rid):
    check_auth({"Authorizer"})
    rec = get_or_404(db.authorizations, rid, "ERR_AUTHORIZATION_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Authorization is not SUBMITTED")
    rec["status"] = "APPROVED"
    touch(rec)
    return respond_object(public(rec))


@app.route("/authorizations/<rid>/deny", methods=["POST"])
def deny_authorization(rid):
    check_auth({"Authorizer"})
    rec = get_or_404(db.authorizations, rid, "ERR_AUTHORIZATION_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Authorization is not SUBMITTED")
    rec["status"] = "DENIED"
    touch(rec)
    return respond_object(public(rec))


@app.route("/authorizations/<rid>/renew", methods=["POST"])
def renew_authorization(rid):
    check_auth({"Authorizer"})
    rec = get_or_404(db.authorizations, rid, "ERR_AUTHORIZATION_NOT_FOUND")
    body = get_body()
    additional = require_int(body, "additional_visits", minimum=0)
    if rec["status"] != "EXHAUSTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Authorization is not EXHAUSTED")
    rec["status"] = "APPROVED"
    rec["visit_cap"] += additional
    recompute_ledger(rec)
    touch(rec)
    # resume held plans
    for plan in db.plans.values():
        if plan["authorization_id"] == rec["id"] and plan["status"] == "ON_HOLD":
            plan["status"] = "ACTIVE"
            touch(plan)
    return respond_object(public(rec))


# ===========================================================================
# TREATMENT PLANS
# ===========================================================================
@app.route("/treatment-plans", methods=["POST"])
def create_plan():
    check_auth({"Clinician"})
    body = get_body()
    # existence L-to-R: patient, evaluation, authorization
    patient = resolve(db.patients, body.get("patient_id"), "ERR_PATIENT_NOT_FOUND")
    evaluation = resolve(db.evaluations, body.get("evaluation_id"), "ERR_EVALUATION_NOT_FOUND")
    authorization = resolve(db.authorizations, body.get("authorization_id"), "ERR_AUTHORIZATION_NOT_FOUND")
    # well-formedness
    patient_id = require_str(body, "patient_id")
    evaluation_id = require_str(body, "evaluation_id")
    authorization_id = require_str(body, "authorization_id")
    prescribed = require_int(body, "prescribed_daily_minutes", minimum=0)
    if patient is None:
        patient = resolve(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    if evaluation is None:
        evaluation = resolve(db.evaluations, evaluation_id, "ERR_EVALUATION_NOT_FOUND")
    if authorization is None:
        authorization = resolve(db.authorizations, authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")
    # 6. state: evaluation FINALIZED
    if evaluation["status"] != "FINALIZED":
        raise ApiError("ERR_EVALUATION_NOT_FINALIZED", 409, "Referenced evaluation is not FINALIZED")
    # 7. referential: evaluation belongs to patient
    if evaluation["patient_id"] != patient_id:
        raise ApiError("ERR_EVALUATION_PATIENT_MISMATCH", 409, "Evaluation does not belong to the patient")
    rec = new_record({
        "patient_id": patient_id,
        "evaluation_id": evaluation_id,
        "authorization_id": authorization_id,
        "prescribed_daily_minutes": prescribed,
        "phase": "PHASE_1_INTENSIVE",
        "adherence_rate": 0.0,
        "status": "DRAFT",
    })
    db.plans[rec["id"]] = rec
    return respond_object(public(rec), 201)


@app.route("/treatment-plans", methods=["GET"])
def list_plans():
    check_auth({"Clinician", "Authorizer", "ClinicAdmin"})
    return list_response(db.plans, {
        "patient_id": request.args.get("patient_id"),
        "evaluation_id": request.args.get("evaluation_id"),
        "authorization_id": request.args.get("authorization_id"),
    })


@app.route("/treatment-plans/<rid>", methods=["GET"])
def get_plan(rid):
    check_auth({"Clinician", "Authorizer", "ClinicAdmin"})
    rec = get_or_404(db.plans, rid, "ERR_PLAN_NOT_FOUND")
    return respond_object(public(rec))


@app.route("/treatment-plans/<rid>/activate", methods=["POST"])
def activate_plan(rid):
    check_auth({"Clinician"})
    rec = get_or_404(db.plans, rid, "ERR_PLAN_NOT_FOUND")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan is not in DRAFT")
    auth = db.authorizations.get(rec["authorization_id"])
    if auth is None or auth["status"] != "APPROVED":
        raise ApiError("ERR_AUTH_NOT_APPROVED", 409, "Governing authorization is not APPROVED")
    rec["status"] = "ACTIVE"
    touch(rec)
    return respond_object(public(rec))


@app.route("/treatment-plans/<rid>/complete", methods=["POST"])
def complete_plan(rid):
    check_auth({"Clinician"})
    rec = get_or_404(db.plans, rid, "ERR_PLAN_NOT_FOUND")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan is not ACTIVE")
    for s in db.sessions.values():
        if s["plan_id"] == rec["id"] and s["clinical_status"] in ("SCHEDULED", "CHECKED_IN"):
            raise ApiError("ERR_OPEN_SESSIONS_EXIST", 409, "Plan has open sessions")
    rec["status"] = "COMPLETED"
    touch(rec)
    return respond_object(public(rec))


# ===========================================================================
# THERAPISTS
# ===========================================================================
@app.route("/therapists", methods=["POST"])
def create_therapist():
    check_auth({"ClinicAdmin"})
    body = get_body()
    full_name = require_str(body, "full_name")
    credential = require_enum(body, "credential", CREDENTIALS)
    rec = new_record({
        "full_name": full_name,
        "credential": credential,
        "status": "ACTIVE",
    })
    db.therapists[rec["id"]] = rec
    return respond_object(public(rec), 201)


@app.route("/therapists", methods=["GET"])
def list_therapists():
    check_auth(ROLES)
    return list_response(db.therapists)


@app.route("/therapists/<rid>", methods=["GET"])
def get_therapist(rid):
    check_auth(ROLES)
    rec = get_or_404(db.therapists, rid, "ERR_THERAPIST_NOT_FOUND")
    return respond_object(public(rec))


# ===========================================================================
# SESSIONS
# ===========================================================================
@app.route("/sessions", methods=["POST"])
def create_session():
    check_auth({"Clinician"})
    body = get_body()
    # 3. existence L-to-R: plan, authorization, therapist
    plan = resolve(db.plans, body.get("plan_id"), "ERR_PLAN_NOT_FOUND")
    auth = resolve(db.authorizations, body.get("authorization_id"), "ERR_AUTHORIZATION_NOT_FOUND")
    therapist = resolve(db.therapists, body.get("therapist_id"), "ERR_THERAPIST_NOT_FOUND")
    # 4. well-formedness
    plan_id = require_str(body, "plan_id")
    authorization_id = require_str(body, "authorization_id")
    therapist_id = require_str(body, "therapist_id")
    start_raw = require_str(body, "scheduled_start")
    end_raw = require_str(body, "scheduled_end")
    cdt_component = require_enum(body, "cdt_component", CDT_COMPONENTS)
    if plan is None:
        plan = resolve(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if auth is None:
        auth = resolve(db.authorizations, authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")
    if therapist is None:
        therapist = resolve(db.therapists, therapist_id, "ERR_THERAPIST_NOT_FOUND")
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if not (end_dt > start_dt):
        raise ApiError("ERR_VALIDATION", 422, "scheduled_end must be after scheduled_start")
    # 6. state: plan ACTIVE, then auth APPROVED
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    if auth["status"] != "APPROVED":
        raise ApiError("ERR_AUTH_NOT_APPROVED", 409, "Authorization is not APPROVED")
    # 7. referential: session.authorization_id == plan.authorization_id
    if authorization_id != plan["authorization_id"]:
        raise ApiError("ERR_AUTH_PLAN_MISMATCH", 409, "Session authorization does not match plan authorization")
    # 8. temporal: session within auth window, then therapist double-book
    eff_start = parse_date(auth["effective_start_date"])
    eff_end = parse_date(auth["effective_end_date"])
    if not (start_dt.date() >= eff_start and end_dt.date() <= eff_end):
        raise ApiError("ERR_SESSION_OUTSIDE_AUTH_WINDOW", 409, "Session falls outside the authorization window")
    for s in db.sessions.values():
        if s["therapist_id"] != therapist_id:
            continue
        if s["clinical_status"] not in ("SCHEDULED", "CHECKED_IN", "COMPLETED"):
            continue
        es = parse_dt(s["scheduled_start"])
        ee = parse_dt(s["scheduled_end"])
        if start_dt < ee + DOUBLE_BOOK_BUFFER and es < end_dt + DOUBLE_BOOK_BUFFER:
            raise ApiError("ERR_THERAPIST_DOUBLE_BOOKED", 409, "Therapist is double-booked")
    # 10. visit cap
    if auth["visits_reserved"] + auth["visits_used"] >= auth["visit_cap"]:
        raise ApiError("ERR_VISIT_CAP_EXCEEDED", 409, "Authorization visit cap is exhausted")
    rec = new_record({
        "plan_id": plan_id,
        "authorization_id": authorization_id,
        "therapist_id": therapist_id,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "cdt_component": cdt_component,
        "clinical_status": "SCHEDULED",
        "billing_status": "RESERVED",
    })
    db.sessions[rec["id"]] = rec
    recompute_ledger(auth)
    touch(auth)
    return respond_object(public(rec), 201)


@app.route("/sessions", methods=["GET"])
def list_sessions():
    check_auth({"Clinician", "Authorizer", "ClinicAdmin"})
    return list_response(db.sessions, {
        "plan_id": request.args.get("plan_id"),
        "authorization_id": request.args.get("authorization_id"),
        "therapist_id": request.args.get("therapist_id"),
    })


@app.route("/sessions/<rid>", methods=["GET"])
def get_session(rid):
    check_auth({"Clinician", "Authorizer", "ClinicAdmin"})
    rec = get_or_404(db.sessions, rid, "ERR_SESSION_NOT_FOUND")
    return respond_object(public(rec))


@app.route("/sessions/<rid>/check-in", methods=["POST"])
def checkin_session(rid):
    check_auth({"Clinician"})
    rec = get_or_404(db.sessions, rid, "ERR_SESSION_NOT_FOUND")
    if rec["clinical_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Session is not SCHEDULED")
    rec["clinical_status"] = "CHECKED_IN"
    touch(rec)
    auth = db.authorizations.get(rec["authorization_id"])
    if auth is not None:
        recompute_ledger(auth)
        touch(auth)
    return respond_object(public(rec))


@app.route("/sessions/<rid>/complete", methods=["POST"])
def complete_session(rid):
    check_auth({"Clinician"})
    rec = get_or_404(db.sessions, rid, "ERR_SESSION_NOT_FOUND")
    if rec["clinical_status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Session is not CHECKED_IN")
    rec["clinical_status"] = "COMPLETED"
    rec["billing_status"] = "BILLED"
    touch(rec)
    auth = db.authorizations.get(rec["authorization_id"])
    if auth is not None:
        recompute_ledger(auth)
        touch(auth)
        maybe_exhaust(auth)
    return respond_object(public(rec))


@app.route("/sessions/<rid>/cancel", methods=["POST"])
def cancel_session(rid):
    check_auth({"Clinician"})
    rec = get_or_404(db.sessions, rid, "ERR_SESSION_NOT_FOUND")
    if rec["clinical_status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "Session cannot be cancelled from its current state")
    rec["clinical_status"] = "CANCELLED"
    rec["billing_status"] = "VOID"
    touch(rec)
    auth = db.authorizations.get(rec["authorization_id"])
    if auth is not None:
        recompute_ledger(auth)
        touch(auth)
    return respond_object(public(rec))


@app.route("/sessions/<rid>/no-show", methods=["POST"])
def noshow_session(rid):
    check_auth({"Clinician"})
    rec = get_or_404(db.sessions, rid, "ERR_SESSION_NOT_FOUND")
    if rec["clinical_status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "Session cannot be marked no-show from its current state")
    rec["clinical_status"] = "NO_SHOW"
    rec["billing_status"] = "BILLED"
    touch(rec)
    auth = db.authorizations.get(rec["authorization_id"])
    if auth is not None:
        recompute_ledger(auth)
        touch(auth)
        maybe_exhaust(auth)
    return respond_object(public(rec))


# ===========================================================================
# GARMENT ORDERS
# ===========================================================================
@app.route("/garment-orders", methods=["POST"])
def create_garment_order():
    check_auth({"Clinician"})
    body = get_body()
    # 3. existence L-to-R: patient, evaluation
    patient = resolve(db.patients, body.get("patient_id"), "ERR_PATIENT_NOT_FOUND")
    evaluation = resolve(db.evaluations, body.get("evaluation_id"), "ERR_EVALUATION_NOT_FOUND")
    # 4. well-formedness
    patient_id = require_str(body, "patient_id")
    evaluation_id = require_str(body, "evaluation_id")
    quantity = require_int(body, "quantity", minimum=1)
    expected_version = require_int(body, "expected_patient_version")
    if patient is None:
        patient = resolve(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    if evaluation is None:
        evaluation = resolve(db.evaluations, evaluation_id, "ERR_EVALUATION_NOT_FOUND")
    # 5. OCC
    if expected_version != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION", 412, "Patient version is stale")
    # 6. state: evaluation FINALIZED
    if evaluation["status"] != "FINALIZED":
        raise ApiError("ERR_EVALUATION_NOT_FINALIZED", 409, "Referenced evaluation is not FINALIZED")
    # 7. referential: evaluation belongs to patient
    if evaluation["patient_id"] != patient_id:
        raise ApiError("ERR_EVALUATION_PATIENT_MISMATCH", 409, "Evaluation does not belong to the patient")
    cls = classify_garment(evaluation)
    rec = new_record({
        "patient_id": patient_id,
        "evaluation_id": evaluation_id,
        "body_region": cls["body_region"],
        "quantity": quantity,
        "garment_type": cls["garment_type"],
        "compression_class": cls["compression_class"],
        "l_code": cls["l_code"],
        "custom_fabrication": cls["custom_fabrication"],
        "status": "DRAFT",
    })
    db.garment_orders[rec["id"]] = rec
    # supersede prior DRAFT/APPROVED order for same patient+region
    for o in db.garment_orders.values():
        if (o["id"] != rec["id"] and o["patient_id"] == patient_id
                and o["body_region"] == cls["body_region"] and o["status"] in ("DRAFT", "APPROVED")):
            o["status"] = "SUPERSEDED"
            touch(o)
    touch(patient)
    return respond_object(public(rec), 201)


@app.route("/garment-orders", methods=["GET"])
def list_garment_orders():
    check_auth(ROLES)
    return list_response(db.garment_orders, {
        "patient_id": request.args.get("patient_id"),
        "evaluation_id": request.args.get("evaluation_id"),
    })


@app.route("/garment-orders/<rid>", methods=["GET"])
def get_garment_order(rid):
    check_auth(ROLES)
    rec = get_or_404(db.garment_orders, rid, "ERR_GARMENT_ORDER_NOT_FOUND")
    return respond_object(public(rec))


@app.route("/garment-orders/<rid>/approve", methods=["POST"])
def approve_garment_order(rid):
    check_auth({"Authorizer"})
    rec = get_or_404(db.garment_orders, rid, "ERR_GARMENT_ORDER_NOT_FOUND")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Garment order is not DRAFT")
    rec["status"] = "APPROVED"
    touch(rec)
    return respond_object(public(rec))


@app.route("/garment-orders/<rid>/deny", methods=["POST"])
def deny_garment_order(rid):
    check_auth({"Authorizer"})
    rec = get_or_404(db.garment_orders, rid, "ERR_GARMENT_ORDER_NOT_FOUND")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Garment order is not DRAFT")
    rec["status"] = "DENIED"
    touch(rec)
    return respond_object(public(rec))


# ===========================================================================
# DME ITEMS
# ===========================================================================
@app.route("/dme-items", methods=["POST"])
def create_dme_item():
    check_auth({"DMECoordinator", "ClinicAdmin"})
    body = get_body()
    sku = require_str(body, "sku")
    l_code = require_str(body, "l_code")
    initial = require_int(body, "initial_stock_qty", minimum=0)
    description = body.get("description")
    if description is not None and not isinstance(description, str):
        raise ApiError("ERR_VALIDATION", 422, "description must be a string")
    rec = new_record({
        "sku": sku,
        "description": description,
        "l_code": l_code,
        "initial_stock_qty": initial,
        "outstanding_dispensed_qty": 0,
        "on_hand_qty": initial,
    })
    db.dme_items[rec["id"]] = rec
    return respond_object(public(rec), 201)


@app.route("/dme-items", methods=["GET"])
def list_dme_items():
    check_auth({"Clinician", "DMECoordinator", "ClinicAdmin"})
    return list_response(db.dme_items, {"l_code": request.args.get("l_code")})


@app.route("/dme-items/<rid>", methods=["GET"])
def get_dme_item(rid):
    check_auth({"Clinician", "DMECoordinator", "ClinicAdmin"})
    rec = get_or_404(db.dme_items, rid, "ERR_DME_ITEM_NOT_FOUND")
    return respond_object(public(rec))


# ===========================================================================
# DISPENSES
# ===========================================================================
@app.route("/dispenses", methods=["POST"])
def create_dispense():
    check_auth({"DMECoordinator"})
    body = get_body()
    # 3. existence L-to-R: garment_order, dme_item
    order = resolve(db.garment_orders, body.get("garment_order_id"), "ERR_GARMENT_ORDER_NOT_FOUND")
    item = resolve(db.dme_items, body.get("dme_item_id"), "ERR_DME_ITEM_NOT_FOUND")
    # 4. well-formedness
    garment_order_id = require_str(body, "garment_order_id")
    dme_item_id = require_str(body, "dme_item_id")
    quantity = require_int(body, "quantity", minimum=1)
    if order is None:
        order = resolve(db.garment_orders, garment_order_id, "ERR_GARMENT_ORDER_NOT_FOUND")
    if item is None:
        item = resolve(db.dme_items, dme_item_id, "ERR_DME_ITEM_NOT_FOUND")
    # 6. state: order APPROVED
    if order["status"] != "APPROVED":
        raise ApiError("ERR_GARMENT_ORDER_NOT_APPROVED", 409, "Garment order is not APPROVED")
    # 7. referential: item l_code == order l_code
    if item["l_code"] != order["l_code"]:
        raise ApiError("ERR_DME_LCODE_MISMATCH", 409, "DME item L-code does not match garment order L-code")
    # 9. stock sufficiency
    if quantity > item["on_hand_qty"]:
        raise ApiError("ERR_DME_INSUFFICIENT_STOCK", 409, "Dispense quantity exceeds on-hand stock")
    rec = new_record({
        "garment_order_id": garment_order_id,
        "dme_item_id": dme_item_id,
        "quantity": quantity,
        "l_code": item["l_code"],
        "status": "DISPENSED",
    })
    db.dispenses[rec["id"]] = rec
    item["outstanding_dispensed_qty"] += quantity
    item["on_hand_qty"] = item["initial_stock_qty"] - item["outstanding_dispensed_qty"]
    touch(item)
    return respond_object(public(rec), 201)


@app.route("/dispenses", methods=["GET"])
def list_dispenses():
    check_auth({"Clinician", "DMECoordinator", "ClinicAdmin"})
    return list_response(db.dispenses, {
        "garment_order_id": request.args.get("garment_order_id"),
        "dme_item_id": request.args.get("dme_item_id"),
    })


@app.route("/dispenses/<rid>", methods=["GET"])
def get_dispense(rid):
    check_auth({"Clinician", "DMECoordinator", "ClinicAdmin"})
    rec = get_or_404(db.dispenses, rid, "ERR_DISPENSE_NOT_FOUND")
    return respond_object(public(rec))


@app.route("/dispenses/<rid>/return", methods=["POST"])
def return_dispense(rid):
    check_auth({"DMECoordinator"})
    rec = get_or_404(db.dispenses, rid, "ERR_DISPENSE_NOT_FOUND")
    if rec["status"] != "DISPENSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispense is not DISPENSED")
    rec["status"] = "RETURNED"
    touch(rec)
    item = db.dme_items.get(rec["dme_item_id"])
    if item is not None:
        item["outstanding_dispensed_qty"] -= rec["quantity"]
        item["on_hand_qty"] = item["initial_stock_qty"] - item["outstanding_dispensed_qty"]
        touch(item)
    return respond_object(public(rec))


# ===========================================================================
# REASSESSMENTS
# ===========================================================================
@app.route("/reassessments", methods=["POST"])
def create_reassessment():
    check_auth({"Clinician"})
    body = get_body()
    # 3. existence L-to-R: plan, baseline_evaluation, current_evaluation
    plan = resolve(db.plans, body.get("plan_id"), "ERR_PLAN_NOT_FOUND")
    baseline = resolve(db.evaluations, body.get("baseline_evaluation_id"), "ERR_EVALUATION_NOT_FOUND")
    current = resolve(db.evaluations, body.get("current_evaluation_id"), "ERR_EVALUATION_NOT_FOUND")
    # 4. well-formedness
    plan_id = require_str(body, "plan_id")
    baseline_id = require_str(body, "baseline_evaluation_id")
    current_id = require_str(body, "current_evaluation_id")
    if plan is None:
        plan = resolve(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if baseline is None:
        baseline = resolve(db.evaluations, baseline_id, "ERR_EVALUATION_NOT_FOUND")
    if current is None:
        current = resolve(db.evaluations, current_id, "ERR_EVALUATION_NOT_FOUND")
    # 6. state: both evaluations progressed past DRAFT
    if baseline["status"] not in ("FINALIZED", "SUPERSEDED"):
        raise ApiError("ERR_EVALUATION_NOT_FINALIZED", 409, "Baseline evaluation is not finalized")
    if current["status"] not in ("FINALIZED", "SUPERSEDED"):
        raise ApiError("ERR_EVALUATION_NOT_FINALIZED", 409, "Current evaluation is not finalized")
    rec = new_record({
        "plan_id": plan_id,
        "baseline_evaluation_id": baseline_id,
        "current_evaluation_id": current_id,
        "volume_reduction_pct": None,
        "perv_pct": None,
        "outcome_category": None,
        "status": "DRAFT",
    })
    db.reassessments[rec["id"]] = rec
    return respond_object(public(rec), 201)


@app.route("/reassessments", methods=["GET"])
def list_reassessments():
    check_auth({"Clinician", "Authorizer", "ClinicAdmin"})
    return list_response(db.reassessments, {
        "plan_id": request.args.get("plan_id"),
        "baseline_evaluation_id": request.args.get("baseline_evaluation_id"),
        "current_evaluation_id": request.args.get("current_evaluation_id"),
    })


@app.route("/reassessments/<rid>", methods=["GET"])
def get_reassessment(rid):
    check_auth({"Clinician", "Authorizer", "ClinicAdmin"})
    rec = get_or_404(db.reassessments, rid, "ERR_REASSESSMENT_NOT_FOUND")
    return respond_object(public(rec))


@app.route("/reassessments/<rid>/finalize", methods=["POST"])
def finalize_reassessment(rid):
    check_auth({"Clinician"})
    rec = get_or_404(db.reassessments, rid, "ERR_REASSESSMENT_NOT_FOUND")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Reassessment is not DRAFT")
    baseline = db.evaluations[rec["baseline_evaluation_id"]]
    current = db.evaluations[rec["current_evaluation_id"]]
    b_vol = Decimal(str(baseline["limb_volume_ml"]))
    c_vol = Decimal(str(current["limb_volume_ml"]))
    b_excess = Decimal(str(baseline["excess_volume_ml"]))
    c_excess = Decimal(str(current["excess_volume_ml"]))
    if b_vol == 0:
        vol_reduction = Decimal("0.0")
    else:
        vol_reduction = round_half_up((b_vol - c_vol) / b_vol * 100, 1)
    if b_excess == 0:
        perv = Decimal("0.0")
    else:
        perv = round_half_up((b_excess - c_excess) / b_excess * 100, 1)
    if perv >= 50:
        category = "EXCELLENT"
    elif perv >= 25:
        category = "GOOD"
    elif perv >= 0:
        category = "PARTIAL"
    else:
        category = "REGRESSION"
    rec["volume_reduction_pct"] = to_float(vol_reduction)
    rec["perv_pct"] = to_float(perv)
    rec["outcome_category"] = category
    rec["status"] = "FINALIZED"
    touch(rec)
    # phase advancement
    if perv >= MAINTENANCE_THRESHOLD:
        plan = db.plans.get(rec["plan_id"])
        if plan is not None and plan["phase"] == "PHASE_1_INTENSIVE":
            plan["phase"] = "PHASE_2_MAINTENANCE"
            touch(plan)
    return respond_object(public(rec))


# ===========================================================================
# ADHERENCE LOGS
# ===========================================================================
def recompute_adherence(plan):
    logs = [l for l in db.adherence_logs.values() if l["plan_id"] == plan["id"]]
    total = len(logs)
    if total == 0:
        plan["adherence_rate"] = 0.0
        return
    compliant = sum(1 for l in logs
                    if l["wore_garment"] and l["minutes_completed"] >= plan["prescribed_daily_minutes"])
    rate = round_half_up(Decimal(compliant) / Decimal(total) * 100, 1)
    plan["adherence_rate"] = to_float(rate)


@app.route("/adherence-logs", methods=["POST"])
def create_adherence_log():
    check_auth({"Clinician"})
    body = get_body()
    plan = resolve(db.plans, body.get("plan_id"), "ERR_PLAN_NOT_FOUND")
    plan_id = require_str(body, "plan_id")
    log_date = require_str(body, "log_date")
    minutes = require_int(body, "minutes_completed", minimum=0)
    wore = require_bool(body, "wore_garment")
    if plan is None:
        plan = resolve(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    rec = new_record({
        "plan_id": plan_id,
        "log_date": log_date,
        "minutes_completed": minutes,
        "wore_garment": wore,
    }, common=False)
    db.adherence_logs[rec["id"]] = rec
    recompute_adherence(plan)
    touch(plan)
    return respond_object(public(rec), 201)


@app.route("/adherence-logs", methods=["GET"])
def list_adherence_logs():
    check_auth({"Clinician", "ClinicAdmin"})
    return list_response(db.adherence_logs, {"plan_id": request.args.get("plan_id")})


@app.route("/adherence-logs/<rid>", methods=["GET"])
def get_adherence_log(rid):
    check_auth({"Clinician", "ClinicAdmin"})
    rec = db.adherence_logs.get(rid)
    if rec is None:
        raise ApiError("ERR_ADHERENCE_LOG_NOT_FOUND", 404, "Adherence log not found")
    return respond_object(public(rec))


# ===========================================================================
# LOGICAL CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    check_auth({"ClinicAdmin"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    db.clock = parse_dt(to_iso)
    return respond_object({"current_utc": now_iso()})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
