"""
Diabetes Education & CGM Program (DSMES) API — Flask reference implementation.

In-memory only. State is wiped on every process start (per-test-server isolation).
No entity seeding at startup.
"""
import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
UNIT_MINUTES = 30
HOURS_PER_UNIT = 0.5
INDIVIDUAL_UNIT_RATE_CENTS = 5000
GROUP_UNIT_RATE_CENTS = 1500
A1C_REDUCTION_PER_HOUR = 0.1
A1C_FLOOR = 6.5
INITIAL_BENEFIT_HOURS = 10.0
FOLLOWUP_BENEFIT_HOURS = 2.0
DEVICE_LOAN_DAYS = 90
NO_SHOW_SUSPENSION_THRESHOLD = 3
ROOM_BUFFER_MINUTES = 15
BENEFIT_YEAR_DAYS = 365
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

VALID_ROLES = {"ProgramCoordinator", "Dietitian", "BillingSpecialist"}

ACCRED_BODY = {"ADA", "ADCES"}
ACCRED_STATUS = {"ACCREDITED", "PROBATION", "LAPSED"}
DIABETES_TYPE = {"TYPE_1", "TYPE_2", "GESTATIONAL", "PREDIABETES"}
CURRIC_FOCUS = DIABETES_TYPE | {"ANY"}
PAYER = {"MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY"}
CREDENTIAL = {"RD", "RN", "CDCES", "PHARMD"}
REFERRAL_REASON = {"NEWLY_DIAGNOSED", "POOR_CONTROL", "MEDICATION_CHANGE", "ANNUAL_FOLLOWUP"}
MODALITY = {"INDIVIDUAL", "GROUP"}
DEVICE_TYPE = {"CGM", "INSULIN_PUMP", "SMART_PEN"}
BILLING_DECISION = {"PAID", "DENIED"}
OUTCOME = {"MET", "NOT_MET"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
store = {
    "programs": {},
    "curricula": {},
    "patients": {},
    "dietitians": {},
    "referrals": {},
    "enrollments": {},
    "sessions": {},
    "group_classes": {},
    "device_enrollments": {},
    "device_readings": {},
    "care_plans": {},
}

_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# Logical clock: stored verbatim string + parsed datetime.
clock = {"str": DEFAULT_CLOCK, "dt": None}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_wall():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    try:
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def render_logical(dt):
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_dt():
    if clock["dt"] is not None:
        return clock["dt"]
    return parse_dt(clock["str"])


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round_half_up(value, places=1):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def units_from_minutes(minutes):
    return int(minutes) // UNIT_MINUTES


def hours_from_minutes(minutes):
    return units_from_minutes(minutes) * HOURS_PER_UNIT


def units_from_hours(hours):
    return int(round(hours * 2))


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_block(extra=None):
    m = {"api_request_id": gen_request_id(), "api_request_timestamp": now_wall()}
    if extra:
        m.update(extra)
    return m


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": meta_block(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    return ok([public(i) for i in items], 200, "array", page)


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
    g.user_id = user_id
    g.role = role
    return user_id, role


ALL_ROLES = ("ProgramCoordinator", "Dietitian", "BillingSpecialist")


# ---------------------------------------------------------------------------
# Body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.data and request.data.strip():
        b = request.get_json(silent=True)
        if b is None:
            err("ERR_VALIDATION", 400, "Malformed JSON body.")
        if not isinstance(b, dict):
            err("ERR_VALIDATION", 400, "Body must be a JSON object.")
        return b
    return {}


def require_present(body, field):
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", 400, f"Missing required field: {field}.")
    return body[field]


def val_string(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {field}.")
        return None
    v = body[field]
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 400, f"Field {field} must be a non-empty string.")
    return v


def val_enum(body, field, allowed, required=True):
    if field not in body or body[field] is None:
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {field}.")
        return None
    v = body[field]
    if v not in allowed:
        err("ERR_VALIDATION", 400, f"Field {field} must be one of {sorted(allowed)}.")
    return v


def val_number(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {field}.")
        return None
    v = body[field]
    if not is_number(v):
        err("ERR_VALIDATION", 400, f"Field {field} must be a number.")
    return v


def val_integer(body, field, required=True, minimum=None):
    if field not in body or body[field] is None:
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {field}.")
        return None
    v = body[field]
    if not is_int(v):
        err("ERR_VALIDATION", 400, f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 400, f"Field {field} must be >= {minimum}.")
    return v


def val_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 400, f"Field {field} must be a boolean.")
    return v


def val_datetime(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {field}.")
        return None
    v = body[field]
    dt = parse_dt(v)
    if dt is None:
        err("ERR_VALIDATION", 400, f"Field {field} must be a valid ISO 8601 datetime.")
    return v


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "limit must be an integer.")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 400, "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "offset must be an integer.")
        if offset < 0:
            err("ERR_VALIDATION", 400, "offset must be >= 0.")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda x: x["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_entity(with_common=True):
    ts = now_wall()
    e = {"id": new_id(), "created_at": ts, "_seq": next_seq()}
    if with_common:
        e["updated_at"] = ts
        e["version"] = 1
    return e


def touch(entity):
    entity["updated_at"] = now_wall()
    entity["version"] = entity.get("version", 1) + 1


def get_or_404(collection, rid, error_id):
    if not isinstance(rid, str):
        err(error_id, 404, "Resource not found.")
    obj = store[collection].get(rid)
    if obj is None:
        err(error_id, 404, "Resource not found.")
    return obj


# ---------------------------------------------------------------------------
# Enrollment aggregate recomputation
# ---------------------------------------------------------------------------
def enr_sig(enr):
    return {k: v for k, v in enr.items() if k not in ("version", "updated_at")}


def recompute_enrollment(enr):
    sessions = [s for s in store["sessions"].values() if s["enrollment_id"] == enr["id"]]
    prov = 0.0
    fin = 0.0
    nsc = 0
    for s in sessions:
        st = s["encounter_status"]
        if st in ("SCHEDULED", "CHECKED_IN", "COMPLETED"):
            prov += hours_from_minutes(s["planned_minutes"])
        if st == "COMPLETED" and s.get("actual_minutes") is not None:
            fin += hours_from_minutes(s["actual_minutes"])
        if st == "NO_SHOW":
            nsc += 1
    cap = INITIAL_BENEFIT_HOURS if enr["benefit_year_index"] == 0 else FOLLOWUP_BENEFIT_HOURS
    enr["benefit_hours_cap"] = cap
    enr["provisional_hours_used"] = prov
    enr["final_hours_used"] = fin
    enr["hours_remaining"] = cap - prov
    enr["no_show_count"] = nsc


def recompute_class_seats(cls):
    cnt = 0
    for s in store["sessions"].values():
        if s.get("group_class_id") == cls["id"] and s["encounter_status"] in (
            "SCHEDULED", "CHECKED_IN", "COMPLETED", "NO_SHOW"
        ):
            cnt += 1
    changed = cls["seats_taken"] != cnt
    cls["seats_taken"] = cnt
    return changed


def recompute_device(dev):
    readings = [r for r in store["device_readings"].values()
                if r["device_enrollment_id"] == dev["id"]]
    dev["readings_count"] = len(readings)
    if not readings:
        dev["avg_glucose_mgdl"] = None
        dev["latest_glucose_mgdl"] = None
        return
    total = Decimal("0")
    for r in readings:
        total += Decimal(str(r["glucose_mgdl"]))
    avg = total / Decimal(len(readings))
    dev["avg_glucose_mgdl"] = float(avg.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    # latest: max measured_at, tie-break earliest created (_seq asc)
    def key(r):
        return (parse_dt(r["measured_at"]), -r["_seq"])
    latest = max(readings, key=key)
    dev["latest_glucose_mgdl"] = latest["glucose_mgdl"]


def compute_projected_a1c(final_hours_used, baseline_a1c):
    raw = final_hours_used * A1C_REDUCTION_PER_HOUR
    cap = max(baseline_a1c - A1C_FLOOR, 0)
    return round_half_up(min(raw, cap), 1)


# ---------------------------------------------------------------------------
# Session cancellation (used by direct cancel and cascades)
# ---------------------------------------------------------------------------
def cancel_session_internal(sess):
    sess["encounter_status"] = "CANCELLED"
    touch(sess)
    if sess.get("group_class_id"):
        cls = store["group_classes"].get(sess["group_class_id"])
        if cls is not None and recompute_class_seats(cls):
            touch(cls)


# ---------------------------------------------------------------------------
# Enrollment lifecycle side effects
# ---------------------------------------------------------------------------
def suspend_enrollment(enr):
    enr["status"] = "SUSPENDED"
    for s in list(store["sessions"].values()):
        if s["enrollment_id"] == enr["id"] and s["encounter_status"] in ("SCHEDULED", "CHECKED_IN"):
            cancel_session_internal(s)
    recompute_enrollment(enr)


def complete_enrollment(enr):
    enr["status"] = "COMPLETED"
    for cp in store["care_plans"].values():
        if cp["enrollment_id"] == enr["id"] and cp["status"] == "OPEN":
            cp["projected_a1c_delta"] = compute_projected_a1c(
                enr["final_hours_used"], cp["baseline_a1c"]
            )
            touch(cp)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(("ProgramCoordinator",))
    body = get_body()
    val = require_present(body, "to_iso8601")
    dt = parse_dt(val)
    if dt is None:
        err("ERR_VALIDATION", 400, "to_iso8601 must be a valid ISO 8601 datetime.")
    clock["str"] = val
    clock["dt"] = dt
    return ok({}, 200, "object")


# ===========================================================================
# Program
# ===========================================================================
@app.route("/dsmes/programs", methods=["POST"])
def create_program():
    auth(("ProgramCoordinator",))
    body = get_body()
    name = val_string(body, "name")
    acc_body = val_enum(body, "accreditation_body", ACCRED_BODY)
    acc_status = val_enum(body, "accreditation_status", ACCRED_STATUS, required=False)
    acc_expires = val_datetime(body, "accreditation_expires_on", required=False)
    e = base_entity()
    e.update({
        "name": name,
        "accreditation_body": acc_body,
        "accreditation_status": acc_status if acc_status is not None else "ACCREDITED",
        "accreditation_expires_on": acc_expires,
    })
    store["programs"][e["id"]] = e
    return ok(public(e), 201)


@app.route("/dsmes/programs/<pid>", methods=["GET"])
def get_program(pid):
    auth(ALL_ROLES)
    e = get_or_404("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    return ok(public(e), 200)


# ===========================================================================
# Curriculum
# ===========================================================================
@app.route("/dsmes/curricula", methods=["POST"])
def create_curriculum():
    auth(("ProgramCoordinator",))
    body = get_body()
    name = val_string(body, "name")
    focus = val_enum(body, "diabetes_type_focus", CURRIC_FOCUS)
    required_hours = val_number(body, "required_hours")
    module_count = val_integer(body, "module_count")
    e = base_entity()
    e.update({
        "name": name,
        "diabetes_type_focus": focus,
        "required_hours": required_hours,
        "module_count": module_count,
    })
    store["curricula"][e["id"]] = e
    return ok(public(e), 201)


@app.route("/dsmes/curricula/<cid>", methods=["GET"])
def get_curriculum(cid):
    auth(ALL_ROLES)
    e = get_or_404("curricula", cid, "ERR_CURRICULUM_NOT_FOUND")
    return ok(public(e), 200)


# ===========================================================================
# Patient
# ===========================================================================
@app.route("/dsmes/patients", methods=["POST"])
def create_patient():
    auth(("ProgramCoordinator",))
    body = get_body()
    mrn = val_string(body, "mrn")
    full_name = val_string(body, "full_name")
    dob = val_datetime(body, "date_of_birth")
    dtype = val_enum(body, "diabetes_type", DIABETES_TYPE)
    payer = val_enum(body, "payer", PAYER)
    baseline_a1c = val_number(body, "baseline_a1c")
    e = base_entity()
    e.update({
        "mrn": mrn,
        "full_name": full_name,
        "date_of_birth": dob,
        "diabetes_type": dtype,
        "payer": payer,
        "baseline_a1c": baseline_a1c,
    })
    store["patients"][e["id"]] = e
    return ok(public(e), 201)


@app.route("/dsmes/patients/<pid>", methods=["GET"])
def get_patient(pid):
    auth(ALL_ROLES)
    e = get_or_404("patients", pid, "ERR_PATIENT_NOT_FOUND")
    return ok(public(e), 200)


# ===========================================================================
# Dietitian
# ===========================================================================
@app.route("/dsmes/dietitians", methods=["POST"])
def create_dietitian():
    auth(("ProgramCoordinator",))
    body = get_body()
    full_name = val_string(body, "full_name")
    npi = val_string(body, "npi")
    credential = val_enum(body, "credential", CREDENTIAL)
    active = val_bool(body, "active", default=True)
    e = base_entity()
    e.update({
        "full_name": full_name,
        "npi": npi,
        "credential": credential,
        "active": active,
    })
    store["dietitians"][e["id"]] = e
    return ok(public(e), 201)


@app.route("/dsmes/dietitians/<did>", methods=["GET"])
def get_dietitian(did):
    auth(ALL_ROLES)
    e = get_or_404("dietitians", did, "ERR_DIETITIAN_NOT_FOUND")
    return ok(public(e), 200)


# ===========================================================================
# Referral
# ===========================================================================
@app.route("/dsmes/referrals", methods=["POST"])
def create_referral():
    auth(("ProgramCoordinator",))
    body = get_body()
    # existence (body-referenced, in body order) before body well-formedness
    if body.get("program_id") is not None:
        get_or_404("programs", body["program_id"], "ERR_PROGRAM_NOT_FOUND")
    if body.get("patient_id") is not None:
        get_or_404("patients", body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    program_id = val_string(body, "program_id")
    patient_id = val_string(body, "patient_id")
    npi = val_string(body, "referring_provider_npi")
    reason = val_enum(body, "referral_reason", REFERRAL_REASON)
    e = base_entity()
    e.update({
        "program_id": program_id,
        "patient_id": patient_id,
        "referring_provider_npi": npi,
        "referral_reason": reason,
        "status": "RECEIVED",
        "assessment_completed_at": None,
        "assessed_a1c": None,
        "assessed_by_dietitian_id": None,
        "rejection_reason": None,
    })
    store["referrals"][e["id"]] = e
    return ok(public(e), 201)


@app.route("/dsmes/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    auth(ALL_ROLES)
    e = get_or_404("referrals", rid, "ERR_REFERRAL_NOT_FOUND")
    return ok(public(e), 200)


@app.route("/dsmes/referrals", methods=["GET"])
def list_referrals():
    auth(ALL_ROLES)
    items = list(store["referrals"].values())
    for f in ("program_id", "patient_id", "status"):
        if f in request.args:
            v = request.args.get(f)
            items = [i for i in items if i.get(f) == v]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/dsmes/referrals/<rid>/assess", methods=["POST"])
def assess_referral(rid):
    uid, _ = auth(("Dietitian",))
    ref = get_or_404("referrals", rid, "ERR_REFERRAL_NOT_FOUND")
    body = get_body()
    if ref["status"] != "RECEIVED":
        err("ERR_REFERRAL_INVALID_STATE", 409, "Referral must be RECEIVED to assess.")
    assessed_a1c = val_number(body, "assessed_a1c")
    ref["status"] = "ASSESSED"
    ref["assessment_completed_at"] = clock["str"]
    ref["assessed_a1c"] = assessed_a1c
    ref["assessed_by_dietitian_id"] = uid
    touch(ref)
    return ok(public(ref), 200)


@app.route("/dsmes/referrals/<rid>/reject", methods=["POST"])
def reject_referral(rid):
    auth(("ProgramCoordinator",))
    ref = get_or_404("referrals", rid, "ERR_REFERRAL_NOT_FOUND")
    body = get_body()
    if ref["status"] not in ("RECEIVED", "ASSESSED"):
        err("ERR_REFERRAL_INVALID_STATE", 409, "Referral cannot be rejected from its current state.")
    reason = val_string(body, "rejection_reason", required=False)
    ref["status"] = "REJECTED"
    ref["rejection_reason"] = reason
    touch(ref)
    return ok(public(ref), 200)


# ===========================================================================
# Enrollment
# ===========================================================================
@app.route("/dsmes/enrollments", methods=["POST"])
def create_enrollment():
    auth(("ProgramCoordinator",))
    body = get_body()
    if body.get("referral_id") is not None:
        get_or_404("referrals", body["referral_id"], "ERR_REFERRAL_NOT_FOUND")
    if body.get("curriculum_id") is not None:
        get_or_404("curricula", body["curriculum_id"], "ERR_CURRICULUM_NOT_FOUND")
    referral_id = val_string(body, "referral_id")
    curriculum_id = val_string(body, "curriculum_id")
    ref = store["referrals"][referral_id]
    cur = store["curricula"][curriculum_id]
    # referral assessed gate
    if ref["status"] != "ASSESSED":
        err("ERR_REFERRAL_NOT_ASSESSED", 409, "Referral must be ASSESSED to create an enrollment.")
    # curriculum type match
    patient = store["patients"].get(ref["patient_id"])
    if cur["diabetes_type_focus"] != "ANY" and (
        patient is None or cur["diabetes_type_focus"] != patient["diabetes_type"]
    ):
        err("ERR_CURRICULUM_TYPE_MISMATCH", 409, "Curriculum focus does not match patient's diabetes type.")
    e = base_entity()
    cap = INITIAL_BENEFIT_HOURS
    e.update({
        "referral_id": referral_id,
        "curriculum_id": curriculum_id,
        "patient_id": ref["patient_id"],
        "program_id": ref["program_id"],
        "benefit_year_index": 0,
        "benefit_year_start": None,
        "benefit_year_end": None,
        "benefit_hours_cap": cap,
        "required_curriculum_hours": cur["required_hours"],
        "provisional_hours_used": 0.0,
        "final_hours_used": 0.0,
        "hours_remaining": cap,
        "no_show_count": 0,
        "status": "PENDING",
    })
    store["enrollments"][e["id"]] = e
    # bubble-up: referral -> ENROLLED
    ref["status"] = "ENROLLED"
    touch(ref)
    return ok(public(e), 201)


@app.route("/dsmes/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    auth(ALL_ROLES)
    e = get_or_404("enrollments", eid, "ERR_ENROLLMENT_NOT_FOUND")
    return ok(public(e), 200)


@app.route("/dsmes/enrollments", methods=["GET"])
def list_enrollments():
    auth(ALL_ROLES)
    items = list(store["enrollments"].values())
    for f in ("referral_id", "patient_id", "curriculum_id", "program_id", "status"):
        if f in request.args:
            v = request.args.get(f)
            items = [i for i in items if i.get(f) == v]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/dsmes/enrollments/<eid>/activate", methods=["POST"])
def activate_enrollment(eid):
    auth(("ProgramCoordinator",))
    enr = get_or_404("enrollments", eid, "ERR_ENROLLMENT_NOT_FOUND")
    if enr["status"] != "PENDING":
        err("ERR_ENROLLMENT_INVALID_STATE", 409, "Enrollment must be PENDING to activate.")
    program = store["programs"].get(enr["program_id"])
    if program is None or program["accreditation_status"] != "ACCREDITED":
        err("ERR_PROGRAM_NOT_ACCREDITED", 403, "Program must be ACCREDITED to activate an enrollment.")
    enr["status"] = "ACTIVE"
    enr["benefit_year_start"] = clock["str"]
    start_dt = clock_dt()
    enr["benefit_year_end"] = render_logical(start_dt + timedelta(days=BENEFIT_YEAR_DAYS))
    touch(enr)
    return ok(public(enr), 200)


@app.route("/dsmes/enrollments/<eid>/reinstate", methods=["POST"])
def reinstate_enrollment(eid):
    auth(("ProgramCoordinator",))
    enr = get_or_404("enrollments", eid, "ERR_ENROLLMENT_NOT_FOUND")
    if enr["status"] != "SUSPENDED":
        err("ERR_ENROLLMENT_INVALID_STATE", 409, "Enrollment must be SUSPENDED to reinstate.")
    enr["status"] = "ACTIVE"  # no_show_count retained
    touch(enr)
    return ok(public(enr), 200)


@app.route("/dsmes/enrollments/<eid>/withdraw", methods=["POST"])
def withdraw_enrollment(eid):
    auth(("ProgramCoordinator",))
    enr = get_or_404("enrollments", eid, "ERR_ENROLLMENT_NOT_FOUND")
    get_body()  # optional withdraw_reason (not persisted as a field)
    if enr["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_ENROLLMENT_INVALID_STATE", 409, "Enrollment must be ACTIVE or SUSPENDED to withdraw.")
    enr["status"] = "WITHDRAWN"
    for s in list(store["sessions"].values()):
        if s["enrollment_id"] == enr["id"] and s["encounter_status"] in ("SCHEDULED", "CHECKED_IN"):
            cancel_session_internal(s)
    recompute_enrollment(enr)
    touch(enr)
    return ok(public(enr), 200)


# ===========================================================================
# Session (individual)
# ===========================================================================
@app.route("/dsmes/sessions", methods=["POST"])
def create_session():
    auth(("Dietitian",))
    body = get_body()
    # existence (body order: enrollment_id, dietitian_id)
    if body.get("enrollment_id") is not None:
        get_or_404("enrollments", body["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
    if body.get("dietitian_id") is not None:
        get_or_404("dietitians", body["dietitian_id"], "ERR_DIETITIAN_NOT_FOUND")
    # OCC (before body well-formedness) when parent exists and version supplied
    enr = store["enrollments"].get(body.get("enrollment_id")) if isinstance(body.get("enrollment_id"), str) else None
    if enr is not None and "expected_enrollment_version" in body and body["expected_enrollment_version"] is not None:
        if body["expected_enrollment_version"] != enr["version"]:
            err("ERR_STALE_VERSION", 412, "expected_enrollment_version does not match current version.")
    # body well-formedness
    enrollment_id = val_string(body, "enrollment_id")
    dietitian_id = val_string(body, "dietitian_id")
    modality = val_enum(body, "modality", MODALITY)
    scheduled_start = val_datetime(body, "scheduled_start")
    scheduled_end = val_datetime(body, "scheduled_end")
    is_telehealth = val_bool(body, "is_telehealth", default=False)
    val_integer(body, "expected_enrollment_version")  # required
    enr = store["enrollments"][enrollment_id]
    # time range
    sdt = parse_dt(scheduled_start)
    edt = parse_dt(scheduled_end)
    if not (edt > sdt):
        err("ERR_INVALID_TIME_RANGE", 400, "scheduled_end must be strictly after scheduled_start.")
    # enrollment active
    if enr["status"] != "ACTIVE":
        err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment must be ACTIVE to schedule a session.")
    # dietitian double-booked (non-terminal INDIVIDUAL sessions, half-open overlap)
    for s in store["sessions"].values():
        if s["dietitian_id"] == dietitian_id and s.get("modality") == "INDIVIDUAL" \
                and s["encounter_status"] in ("SCHEDULED", "CHECKED_IN"):
            os_s = parse_dt(s["scheduled_start"])
            os_e = parse_dt(s["scheduled_end"])
            if sdt < os_e and os_s < edt:
                err("ERR_DIETITIAN_DOUBLE_BOOKED", 409, "Dietitian already booked in that window.")
    # benefit budget
    planned_minutes = int((edt - sdt).total_seconds() // 60)
    provisional_hours = hours_from_minutes(planned_minutes)
    if enr["provisional_hours_used"] + provisional_hours > enr["benefit_hours_cap"]:
        err("ERR_BENEFIT_HOURS_EXCEEDED", 402, "Scheduling would exceed the benefit-hour cap.")
    # create
    e = base_entity()
    e.update({
        "enrollment_id": enrollment_id,
        "dietitian_id": dietitian_id,
        "group_class_id": None,
        "modality": modality,
        "is_telehealth": is_telehealth,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "planned_minutes": planned_minutes,
        "actual_minutes": None,
        "provisional_hours": provisional_hours,
        "final_hours": None,
        "billable_units": None,
        "charge_cents": None,
        "encounter_status": "SCHEDULED",
        "billing_status": "UNBILLED",
    })
    store["sessions"][e["id"]] = e
    recompute_enrollment(enr)
    touch(enr)  # individual schedule always bumps enrollment version (OCC anchor)
    return ok(public(e), 201)


@app.route("/dsmes/sessions/<sid>", methods=["GET"])
def get_session(sid):
    auth(ALL_ROLES)
    e = get_or_404("sessions", sid, "ERR_SESSION_NOT_FOUND")
    return ok(public(e), 200)


@app.route("/dsmes/sessions", methods=["GET"])
def list_sessions():
    auth(ALL_ROLES)
    items = list(store["sessions"].values())
    for f in ("enrollment_id", "dietitian_id", "group_class_id", "encounter_status", "billing_status"):
        if f in request.args:
            v = request.args.get(f)
            items = [i for i in items if i.get(f) == v]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/dsmes/sessions/<sid>/check-in", methods=["POST"])
def checkin_session(sid):
    auth(("Dietitian",))
    s = get_or_404("sessions", sid, "ERR_SESSION_NOT_FOUND")
    if s["encounter_status"] != "SCHEDULED":
        err("ERR_SESSION_INVALID_STATE", 409, "Session must be SCHEDULED to check in.")
    s["encounter_status"] = "CHECKED_IN"
    touch(s)
    return ok(public(s), 200)


@app.route("/dsmes/sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    auth(("Dietitian",))
    s = get_or_404("sessions", sid, "ERR_SESSION_NOT_FOUND")
    body = get_body()
    if s["encounter_status"] != "CHECKED_IN":
        err("ERR_SESSION_INVALID_STATE", 409, "Session must be CHECKED_IN to complete.")
    actual_minutes = val_integer(body, "actual_minutes", minimum=0)
    enr = store["enrollments"][s["enrollment_id"]]
    before_final = enr["final_hours_used"]
    # billing computed using benefit units remaining BEFORE this completion
    remaining_units_before = units_from_hours(enr["benefit_hours_cap"] - before_final)
    raw_units = units_from_minutes(actual_minutes)
    billable_units = min(raw_units, max(remaining_units_before, 0))
    unit_rate = INDIVIDUAL_UNIT_RATE_CENTS if s["modality"] == "INDIVIDUAL" else GROUP_UNIT_RATE_CENTS
    charge_cents = billable_units * unit_rate
    s["actual_minutes"] = actual_minutes
    s["final_hours"] = hours_from_minutes(actual_minutes)
    s["billable_units"] = billable_units
    s["charge_cents"] = charge_cents
    s["encounter_status"] = "COMPLETED"
    s["billing_status"] = "SUBMITTED"
    touch(s)
    sig = enr_sig(enr)
    recompute_enrollment(enr)
    if enr["status"] == "ACTIVE" and enr["final_hours_used"] >= enr["required_curriculum_hours"]:
        complete_enrollment(enr)
    if enr_sig(enr) != sig:
        touch(enr)
    return ok(public(s), 200)


@app.route("/dsmes/sessions/<sid>/no-show", methods=["POST"])
def noshow_session(sid):
    auth(("Dietitian",))
    s = get_or_404("sessions", sid, "ERR_SESSION_NOT_FOUND")
    if s["encounter_status"] != "SCHEDULED":
        err("ERR_SESSION_INVALID_STATE", 409, "Session must be SCHEDULED to mark no-show.")
    enr = store["enrollments"][s["enrollment_id"]]
    s["encounter_status"] = "NO_SHOW"
    touch(s)
    sig = enr_sig(enr)
    recompute_enrollment(enr)
    if enr["status"] == "ACTIVE" and enr["no_show_count"] >= NO_SHOW_SUSPENSION_THRESHOLD:
        suspend_enrollment(enr)
    if enr_sig(enr) != sig:
        touch(enr)
    return ok(public(s), 200)


@app.route("/dsmes/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    auth(("Dietitian",))
    s = get_or_404("sessions", sid, "ERR_SESSION_NOT_FOUND")
    get_body()  # optional cancel_reason
    if s["encounter_status"] not in ("SCHEDULED", "CHECKED_IN"):
        err("ERR_SESSION_INVALID_STATE", 409, "Session must be SCHEDULED or CHECKED_IN to cancel.")
    enr = store["enrollments"][s["enrollment_id"]]
    cancel_session_internal(s)
    sig = enr_sig(enr)
    recompute_enrollment(enr)
    if enr_sig(enr) != sig:
        touch(enr)
    return ok(public(s), 200)


@app.route("/dsmes/sessions/<sid>/adjudicate", methods=["POST"])
def adjudicate_session(sid):
    auth(("BillingSpecialist",))
    s = get_or_404("sessions", sid, "ERR_SESSION_NOT_FOUND")
    body = get_body()
    if s["billing_status"] != "SUBMITTED":
        err("ERR_BILLING_INVALID_STATE", 409, "Claim must be SUBMITTED to adjudicate.")
    decision = val_enum(body, "billing_decision", BILLING_DECISION)
    s["billing_status"] = decision
    touch(s)
    return ok(public(s), 200)


# ===========================================================================
# GroupClass
# ===========================================================================
@app.route("/dsmes/group-classes", methods=["POST"])
def create_group_class():
    auth(("ProgramCoordinator",))
    body = get_body()
    if body.get("curriculum_id") is not None:
        get_or_404("curricula", body["curriculum_id"], "ERR_CURRICULUM_NOT_FOUND")
    if body.get("dietitian_id") is not None:
        get_or_404("dietitians", body["dietitian_id"], "ERR_DIETITIAN_NOT_FOUND")
    curriculum_id = val_string(body, "curriculum_id")
    dietitian_id = val_string(body, "dietitian_id")
    room_id = val_string(body, "room_id")
    scheduled_start = val_datetime(body, "scheduled_start")
    scheduled_end = val_datetime(body, "scheduled_end")
    capacity = val_integer(body, "capacity", minimum=0)
    topic = val_string(body, "topic")
    sdt = parse_dt(scheduled_start)
    edt = parse_dt(scheduled_end)
    if not (edt > sdt):
        err("ERR_INVALID_TIME_RANGE", 400, "scheduled_end must be strictly after scheduled_start.")
    # room conflict: same room, must keep >= ROOM_BUFFER_MINUTES gap (closed interval + buffer)
    buf = timedelta(minutes=ROOM_BUFFER_MINUTES)
    for c in store["group_classes"].values():
        if c["room_id"] != room_id:
            continue
        os_s = parse_dt(c["scheduled_start"])
        os_e = parse_dt(c["scheduled_end"])
        if sdt < os_e + buf and os_s - buf < edt:
            err("ERR_ROOM_CONFLICT", 409, "Room is occupied within the buffer of another class.")
    e = base_entity()
    e.update({
        "curriculum_id": curriculum_id,
        "dietitian_id": dietitian_id,
        "room_id": room_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "capacity": capacity,
        "seats_taken": 0,
        "topic": topic,
    })
    store["group_classes"][e["id"]] = e
    return ok(public(e), 201)


@app.route("/dsmes/group-classes/<gid>", methods=["GET"])
def get_group_class(gid):
    auth(ALL_ROLES)
    e = get_or_404("group_classes", gid, "ERR_GROUP_CLASS_NOT_FOUND")
    return ok(public(e), 200)


@app.route("/dsmes/group-classes", methods=["GET"])
def list_group_classes():
    auth(ALL_ROLES)
    items = list(store["group_classes"].values())
    for f in ("curriculum_id", "dietitian_id"):
        if f in request.args:
            v = request.args.get(f)
            items = [i for i in items if i.get(f) == v]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/dsmes/group-classes/<gid>/sessions", methods=["POST"])
def reserve_group_seat(gid):
    auth(("Dietitian",))
    body = get_body()
    # existence: path class first, then body enrollment
    cls = get_or_404("group_classes", gid, "ERR_GROUP_CLASS_NOT_FOUND")
    if body.get("enrollment_id") is not None:
        get_or_404("enrollments", body["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
    # OCC on class before body well-formedness
    if "expected_group_class_version" in body and body["expected_group_class_version"] is not None:
        if body["expected_group_class_version"] != cls["version"]:
            err("ERR_STALE_VERSION", 412, "expected_group_class_version does not match current version.")
    enrollment_id = val_string(body, "enrollment_id")
    val_integer(body, "expected_group_class_version")  # required
    is_telehealth = val_bool(body, "is_telehealth", default=False)
    enr = store["enrollments"][enrollment_id]
    # enrollment active
    if enr["status"] != "ACTIVE":
        err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment must be ACTIVE to reserve a seat.")
    sdt = parse_dt(cls["scheduled_start"])
    edt = parse_dt(cls["scheduled_end"])
    # patient time conflict: patient's non-terminal sessions overlapping class window (half-open)
    for s in store["sessions"].values():
        s_enr = store["enrollments"].get(s["enrollment_id"])
        if s_enr is None or s_enr["patient_id"] != enr["patient_id"]:
            continue
        if s["encounter_status"] not in ("SCHEDULED", "CHECKED_IN"):
            continue
        os_s = parse_dt(s["scheduled_start"])
        os_e = parse_dt(s["scheduled_end"])
        if sdt < os_e and os_s < edt:
            err("ERR_PATIENT_TIME_CONFLICT", 409, "Patient already has a session overlapping the class window.")
    # seat capacity
    if cls["seats_taken"] >= cls["capacity"]:
        err("ERR_GROUP_CLASS_FULL", 409, "Group class is at capacity.")
    # benefit budget
    planned_minutes = int((edt - sdt).total_seconds() // 60)
    provisional_hours = hours_from_minutes(planned_minutes)
    if enr["provisional_hours_used"] + provisional_hours > enr["benefit_hours_cap"]:
        err("ERR_BENEFIT_HOURS_EXCEEDED", 402, "Reservation would exceed the benefit-hour cap.")
    e = base_entity()
    e.update({
        "enrollment_id": enrollment_id,
        "dietitian_id": cls["dietitian_id"],
        "group_class_id": cls["id"],
        "modality": "GROUP",
        "is_telehealth": is_telehealth,
        "scheduled_start": cls["scheduled_start"],
        "scheduled_end": cls["scheduled_end"],
        "planned_minutes": planned_minutes,
        "actual_minutes": None,
        "provisional_hours": provisional_hours,
        "final_hours": None,
        "billable_units": None,
        "charge_cents": None,
        "encounter_status": "SCHEDULED",
        "billing_status": "UNBILLED",
    })
    store["sessions"][e["id"]] = e
    recompute_class_seats(cls)
    touch(cls)  # reservation always bumps class version (OCC anchor)
    sig = enr_sig(enr)
    recompute_enrollment(enr)
    if enr_sig(enr) != sig:
        touch(enr)
    return ok(public(e), 201)


# ===========================================================================
# DeviceEnrollment
# ===========================================================================
@app.route("/dsmes/device-enrollments", methods=["POST"])
def create_device_enrollment():
    auth(("ProgramCoordinator",))
    body = get_body()
    if body.get("enrollment_id") is not None:
        get_or_404("enrollments", body["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
    enrollment_id = val_string(body, "enrollment_id")
    device_type = val_enum(body, "device_type", DEVICE_TYPE)
    serial_number = val_string(body, "serial_number")
    e = base_entity()
    e.update({
        "enrollment_id": enrollment_id,
        "device_type": device_type,
        "serial_number": serial_number,
        "status": "REQUESTED",
        "activated_at": None,
        "expires_on": None,
        "readings_count": 0,
        "latest_glucose_mgdl": None,
        "avg_glucose_mgdl": None,
    })
    store["device_enrollments"][e["id"]] = e
    return ok(public(e), 201)


@app.route("/dsmes/device-enrollments/<did>", methods=["GET"])
def get_device_enrollment(did):
    auth(ALL_ROLES)
    e = get_or_404("device_enrollments", did, "ERR_DEVICE_ENROLLMENT_NOT_FOUND")
    return ok(public(e), 200)


@app.route("/dsmes/device-enrollments", methods=["GET"])
def list_device_enrollments():
    auth(ALL_ROLES)
    items = list(store["device_enrollments"].values())
    for f in ("enrollment_id", "status"):
        if f in request.args:
            v = request.args.get(f)
            items = [i for i in items if i.get(f) == v]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/dsmes/device-enrollments/<did>/activate", methods=["POST"])
def activate_device(did):
    auth(("Dietitian",))
    dev = get_or_404("device_enrollments", did, "ERR_DEVICE_ENROLLMENT_NOT_FOUND")
    if dev["status"] != "REQUESTED":
        err("ERR_DEVICE_INVALID_STATE", 409, "Device must be REQUESTED to activate.")
    enr = store["enrollments"].get(dev["enrollment_id"])
    if enr is None or enr["status"] != "ACTIVE":
        err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Governing enrollment must be ACTIVE to activate a device.")
    dev["status"] = "ACTIVE"
    dev["activated_at"] = clock["str"]
    dev["expires_on"] = render_logical(clock_dt() + timedelta(days=DEVICE_LOAN_DAYS))
    touch(dev)
    return ok(public(dev), 200)


@app.route("/dsmes/device-enrollments/<did>/return", methods=["POST"])
def return_device(did):
    auth(("Dietitian",))
    dev = get_or_404("device_enrollments", did, "ERR_DEVICE_ENROLLMENT_NOT_FOUND")
    if dev["status"] != "ACTIVE":
        err("ERR_DEVICE_INVALID_STATE", 409, "Device must be ACTIVE to return.")
    dev["status"] = "RETURNED"
    touch(dev)
    return ok(public(dev), 200)


@app.route("/dsmes/device-enrollments/<did>/readings", methods=["POST"])
def ingest_reading(did):
    auth(("Dietitian",))
    dev = get_or_404("device_enrollments", did, "ERR_DEVICE_ENROLLMENT_NOT_FOUND")
    body = get_body()
    # device window / state
    if dev["status"] == "ACTIVE":
        exp = parse_dt(dev["expires_on"])
        if exp is not None and clock_dt() > exp:
            dev["status"] = "EXPIRED"
            touch(dev)
            err("ERR_DEVICE_EXPIRED", 409, "Device loan window has expired.")
    elif dev["status"] == "EXPIRED":
        err("ERR_DEVICE_EXPIRED", 409, "Device loan window has expired.")
    else:
        err("ERR_DEVICE_INVALID_STATE", 409, "Device must be ACTIVE to ingest readings.")
    glucose = val_number(body, "glucose_mgdl")
    measured_at = val_datetime(body, "measured_at")
    r = base_entity(with_common=False)
    r.update({
        "device_enrollment_id": dev["id"],
        "glucose_mgdl": glucose,
        "measured_at": measured_at,
    })
    store["device_readings"][r["id"]] = r
    recompute_device(dev)
    touch(dev)
    return ok(public(r), 201)


@app.route("/dsmes/device-enrollments/<did>/readings", methods=["GET"])
def list_readings(did):
    auth(ALL_ROLES)
    dev = get_or_404("device_enrollments", did, "ERR_DEVICE_ENROLLMENT_NOT_FOUND")
    items = [r for r in store["device_readings"].values() if r["device_enrollment_id"] == dev["id"]]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# CarePlan
# ===========================================================================
@app.route("/dsmes/care-plans", methods=["POST"])
def create_care_plan():
    auth(("Dietitian",))
    body = get_body()
    if body.get("enrollment_id") is not None:
        get_or_404("enrollments", body["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
    enrollment_id = val_string(body, "enrollment_id")
    goal_description = val_string(body, "goal_description")
    target_a1c = val_number(body, "target_a1c")
    enr = store["enrollments"][enrollment_id]
    patient = store["patients"].get(enr["patient_id"])
    baseline = patient["baseline_a1c"] if patient else 0.0
    e = base_entity()
    e.update({
        "enrollment_id": enrollment_id,
        "goal_description": goal_description,
        "target_a1c": target_a1c,
        "baseline_a1c": baseline,
        "projected_a1c_delta": compute_projected_a1c(enr["final_hours_used"], baseline),
        "measured_a1c": None,
        "final_a1c_delta": None,
        "revision_count": 0,
        "status": "OPEN",
    })
    store["care_plans"][e["id"]] = e
    return ok(public(e), 201)


@app.route("/dsmes/care-plans/<cid>", methods=["GET"])
def get_care_plan(cid):
    auth(ALL_ROLES)
    e = get_or_404("care_plans", cid, "ERR_CARE_PLAN_NOT_FOUND")
    return ok(public(e), 200)


@app.route("/dsmes/care-plans", methods=["GET"])
def list_care_plans():
    auth(ALL_ROLES)
    items = list(store["care_plans"].values())
    for f in ("enrollment_id", "status"):
        if f in request.args:
            v = request.args.get(f)
            items = [i for i in items if i.get(f) == v]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/dsmes/care-plans/<cid>/revise", methods=["POST"])
def revise_care_plan(cid):
    auth(("Dietitian",))
    cp = get_or_404("care_plans", cid, "ERR_CARE_PLAN_NOT_FOUND")
    body = get_body()
    if cp["status"] != "OPEN":
        err("ERR_CARE_PLAN_INVALID_STATE", 409, "Care plan must be OPEN to revise.")
    target_a1c = val_number(body, "target_a1c")
    cp["status"] = "REVISED"
    cp["target_a1c"] = target_a1c
    cp["revision_count"] += 1
    touch(cp)
    return ok(public(cp), 200)


@app.route("/dsmes/care-plans/<cid>/reopen", methods=["POST"])
def reopen_care_plan(cid):
    auth(("Dietitian",))
    cp = get_or_404("care_plans", cid, "ERR_CARE_PLAN_NOT_FOUND")
    if cp["status"] != "REVISED":
        err("ERR_CARE_PLAN_INVALID_STATE", 409, "Care plan must be REVISED to reopen.")
    enr = store["enrollments"].get(cp["enrollment_id"])
    final_hours = enr["final_hours_used"] if enr else 0.0
    cp["status"] = "OPEN"
    cp["projected_a1c_delta"] = compute_projected_a1c(final_hours, cp["baseline_a1c"])
    touch(cp)
    return ok(public(cp), 200)


@app.route("/dsmes/care-plans/<cid>/close", methods=["POST"])
def close_care_plan(cid):
    auth(("Dietitian",))
    cp = get_or_404("care_plans", cid, "ERR_CARE_PLAN_NOT_FOUND")
    body = get_body()
    if cp["status"] != "OPEN":
        err("ERR_CARE_PLAN_INVALID_STATE", 409, "Care plan must be OPEN to close.")
    outcome = val_enum(body, "outcome", OUTCOME)
    measured_a1c = val_number(body, "measured_a1c")
    cp["status"] = outcome
    cp["measured_a1c"] = measured_a1c
    cp["final_a1c_delta"] = round_half_up(cp["baseline_a1c"] - measured_a1c, 1)
    touch(cp)
    return ok(public(cp), 200)


# ===========================================================================
# Health / entry
# ===========================================================================
@app.route("/", methods=["GET"])
def root():
    return ok({"service": "dsmes"}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
