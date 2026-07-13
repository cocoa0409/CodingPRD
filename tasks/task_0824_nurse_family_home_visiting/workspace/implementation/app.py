"""Nurse-Family Home Visiting API — Python + Flask, in-memory store.

All state lives in module-level dicts that start empty on every boot. The test
harness restarts this process via start.sh before every test, so no seeding,
no persistence, no wall-clock reads (a logical clock governs all time).
"""

import os
import random
import string
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
ROLES = {"IntakeCoordinator", "HomeVisitNurse", "Supervisor", "ProgramAdmin"}

GESTATIONAL_AGE_MAX_WEEKS = 28
DOSAGE_FLOOR_PCT = 60.0
ON_TIME_TOLERANCE_DAYS = 7
DOMAIN_FLAG_THRESHOLD = 10
ON_TRACK_MIN = 85
MONITOR_MIN = 70
HIGH_RISK_FLAG_THRESHOLD = 3
MODERATE_RISK_FLAG_THRESHOLD = 1
VISIT_TRAVEL_BUFFER = timedelta(minutes=30)
CASELOAD_MAX_WEIGHT = 25.0
HIGH_RISK_MULTIPLIER = Decimal("1.25")
PHASE_WEIGHT = {
    "PREGNANCY": Decimal("1.0"),
    "INFANCY": Decimal("0.8"),
    "TODDLERHOOD": Decimal("0.6"),
}

CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0)

# --------------------------------------------------------------------------
# In-memory store (empty on every boot)
# --------------------------------------------------------------------------
nurses = {}
supervisors = {}
clients = {}
enrollments = {}
assignments = {}
visits = {}
assessments = {}
referrals = {}
supervision_sessions = {}
outcome_measures = {}
miechv_reports = {}

_CLOCK = {"dt": CLOCK_DEFAULT}
_SEQ = {"n": 0}


def clock():
    return _CLOCK["dt"]


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --------------------------------------------------------------------------
# Time / formatting helpers
# --------------------------------------------------------------------------
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_instant(s):
    if not isinstance(s, str) or not s:
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    try:
        t = s.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_iso_date(s):
    if not isinstance(s, str) or not s:
        raise ApiError("ERR_VALIDATION", 422, "invalid date")
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "invalid date")


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# --------------------------------------------------------------------------
# Numeric helpers
# --------------------------------------------------------------------------
def q2(dec):
    return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pct(num, den):
    if den == 0:
        return None
    return float(q2(Decimal(num) * 100 / Decimal(den)))


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def envelope(data, response_type, meta_extra=None):
    meta = {"api_request_id": req_id(), "api_request_timestamp": iso(clock())}
    if meta_extra:
        meta.update(meta_extra)
    return {"meta": meta, "response_type": response_type, "data": data}


def ok(data, status=200, response_type="object", meta_extra=None):
    return jsonify(envelope(data, response_type, meta_extra)), status


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def list_response(items):
    limit, offset = pagination()
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    window = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok([serialize(x) for x in window], response_type="array", meta_extra=meta)


# --------------------------------------------------------------------------
# Entity / mutation helpers
# --------------------------------------------------------------------------
def base_entity():
    now = iso(clock())
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = iso(clock())


# --------------------------------------------------------------------------
# Auth / RBAC
# --------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or malformed auth headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this endpoint")


# --------------------------------------------------------------------------
# Body validation helpers
# --------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 422, "request body must be a JSON object")
    return b


def v_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"{name} is required and must be a non-empty string")
    return v


def v_bool(body, name, required=True, default=None):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"{name} is required")
        return default
    v = body.get(name)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a boolean")
    return v


def v_int(body, name, required=True, default=None, min_value=None):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"{name} is required")
        return default
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be an integer")
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be >= {min_value}")
    return v


def v_number(body, name, required=True, default=None, min_value=None):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"{name} is required")
        return default
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a number")
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be >= {min_value}")
    return float(v)


def v_enum(body, name, allowed, required=True, default=None):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"{name} is required")
        return default
    v = body.get(name)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be one of {sorted(allowed)}")
    return v


def pagination():
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 422, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 422, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 422, "offset must be >= 0")
    return limit, offset


def must_exist(store, key):
    if not isinstance(key, str) or key not in store:
        raise ApiError("ERR_NOT_FOUND", 404, "referenced entity does not exist")
    return store[key]


# --------------------------------------------------------------------------
# Domain calculations
# --------------------------------------------------------------------------
def tier_of(n):
    if n >= HIGH_RISK_FLAG_THRESHOLD:
        return "HIGH"
    if n >= MODERATE_RISK_FLAG_THRESHOLD:
        return "MODERATE"
    return "LOW"


def client_flag_counts(client_id):
    eids = {e["id"] for e in enrollments.values() if e["client_id"] == client_id}
    provisional = 0
    comprehensive = 0
    for a in assessments.values():
        if a["enrollment_id"] in eids:
            comprehensive += len(a["domain_flags"])
            if a["instrument_type"] == "INTAKE":
                provisional += len(a["domain_flags"])
    return provisional, comprehensive


def recompute_client_risk(client_id):
    if client_id not in clients:
        return
    c = clients[client_id]
    _, comprehensive = client_flag_counts(client_id)
    new_tier = tier_of(comprehensive)
    if new_tier != c["risk_tier"]:
        c["risk_tier"] = new_tier
        touch(c)


def assignment_weight(phase, high_needs):
    base = PHASE_WEIGHT[phase]
    mult = HIGH_RISK_MULTIPLIER if high_needs else Decimal("1")
    return q2(base * mult)


def recompute_nurse(nurse_id):
    n = nurses.get(nurse_id)
    if n is None:
        return
    total = Decimal("0")
    for a in assignments.values():
        if a["nurse_id"] == nurse_id and a["status"] == "ACTIVE":
            total += Decimal(str(a["caseload_weight"]))
    newv = float(q2(total))
    if newv != n["current_caseload_weight"]:
        n["current_caseload_weight"] = newv
        touch(n)


def compute_dosage(E):
    eid = E["id"]
    cd = clock().date()
    vs = [v for v in visits.values() if v["enrollment_id"] == eid]
    completed_td = sum(
        1 for v in vs
        if v["status"] == "COMPLETED" and parse_iso_date(v["target_date"]) <= cd
    )
    expected_td = sum(
        1 for v in vs
        if v["status"] in ("COMPLETED", "MISSED") and parse_iso_date(v["target_date"]) <= cd
    )
    dosage_to_date_pct = pct(completed_td, expected_td)
    completed_full = sum(1 for v in vs if v["status"] == "COMPLETED")
    expected_full = sum(1 for v in vs if v["status"] in ("COMPLETED", "MISSED", "SCHEDULED"))
    dosage_full_pct = pct(completed_full, expected_full)
    return dosage_to_date_pct, dosage_full_pct, completed_td, expected_td


def active_assignments_of(enrollment_id):
    return [
        a for a in assignments.values()
        if a["enrollment_id"] == enrollment_id and a["status"] == "ACTIVE"
    ]


def recompute_and_reconcile(E):
    """Recompute dosage_alert from the to-date variant and reconcile the
    review_required / pending_supervision_count cascade.

    Returns True when the enrollment's dosage_alert changed (caller decides
    whether to bump the enrollment version, since some callers mutate other
    enrollment fields in the same operation).
    """
    old = E["dosage_alert"]
    dtd, _, _, _ = compute_dosage(E)
    new = (dtd is not None and dtd < DOSAGE_FLOOR_PCT)
    if new == old:
        return False
    E["dosage_alert"] = new
    active = active_assignments_of(E["id"])
    if old and not new:
        for a in active:
            if a["review_required"]:
                a["review_required"] = False
                touch(a)
                n = nurses[a["nurse_id"]]
                n["pending_supervision_count"] = max(0, n["pending_supervision_count"] - 1)
                touch(n)
    else:  # not old and new
        for a in active:
            a["review_required"] = True
            touch(a)
            n = nurses[a["nurse_id"]]
            n["pending_supervision_count"] += 1
            touch(n)
    return True


def end_assignment(a):
    a["status"] = "ENDED"
    if a["review_required"]:
        n = nurses.get(a["nurse_id"])
        if n is not None:
            n["pending_supervision_count"] = max(0, n["pending_supervision_count"] - 1)
            touch(n)
    touch(a)
    recompute_nurse(a["nurse_id"])


def close_enrollment_cascade(E):
    for a in active_assignments_of(E["id"]):
        end_assignment(a)
    for v in list(visits.values()):
        if v["enrollment_id"] == E["id"] and v["status"] == "SCHEDULED":
            v["status"] = "CANCELED"
            touch(v)
    recompute_and_reconcile(E)


# --------------------------------------------------------------------------
# Error handlers
# --------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    body = envelope({"error_id": e.error_id, "message": e.message}, "error")
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = envelope({"error_id": "ERR_NOT_FOUND", "message": "resource not found"}, "error")
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = envelope({"error_id": "ERR_NOT_FOUND", "message": "method not allowed"}, "error")
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = envelope({"error_id": "ERR_INTERNAL", "message": str(e)}, "error")
    return jsonify(body), 500


# ==========================================================================
# Clock
# ==========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    body = get_body()
    dt = parse_instant(v_str(body, "to_iso8601"))
    _CLOCK["dt"] = dt
    return ok({"current_utc": iso(dt)})


# ==========================================================================
# Nurse
# ==========================================================================
@app.post("/nurses")
def create_nurse():
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    body = get_body()
    full_name = v_str(body, "full_name")
    credential_type = v_enum(body, "credential_type", {"RN", "BSN", "APRN"})
    status = v_enum(body, "status", {"ACTIVE", "ON_LEAVE", "INACTIVE"}, required=False, default="ACTIVE")
    max_caseload = v_number(body, "max_caseload_weight", required=False, default=CASELOAD_MAX_WEIGHT, min_value=0)
    n = base_entity()
    n.update({
        "full_name": full_name,
        "credential_type": credential_type,
        "status": status,
        "max_caseload_weight": float(max_caseload),
        "current_caseload_weight": 0.0,
        "pending_supervision_count": 0,
    })
    nurses[n["id"]] = n
    return ok(serialize(n), status=201)


@app.get("/nurses/<nid>")
def get_nurse(nid):
    _, role = auth()
    require_role(role, ["ProgramAdmin", "Supervisor"])
    n = must_exist(nurses, nid)
    return ok(serialize(n))


# ==========================================================================
# Supervisor
# ==========================================================================
@app.post("/supervisors")
def create_supervisor():
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    body = get_body()
    full_name = v_str(body, "full_name")
    status = v_enum(body, "status", {"ACTIVE", "INACTIVE"}, required=False, default="ACTIVE")
    s = base_entity()
    s.update({"full_name": full_name, "status": status})
    supervisors[s["id"]] = s
    return ok(serialize(s), status=201)


# ==========================================================================
# Client
# ==========================================================================
@app.post("/clients")
def create_client():
    _, role = auth()
    require_role(role, ["IntakeCoordinator"])
    body = get_body()
    full_name = v_str(body, "full_name")
    mother_dob = v_str(body, "mother_dob")
    first_time_mother = v_bool(body, "first_time_mother")
    gestational_age_weeks = v_int(body, "gestational_age_weeks", min_value=0)
    c = base_entity()
    c.update({
        "full_name": full_name,
        "mother_dob": mother_dob,
        "first_time_mother": first_time_mother,
        "gestational_age_weeks": gestational_age_weeks,
        "consent_signed": False,
        "child_dob": None,
        "risk_tier": "LOW",
    })
    clients[c["id"]] = c
    return ok(serialize(c), status=201)


@app.get("/clients/<cid>")
def get_client(cid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator", "Supervisor"])
    c = must_exist(clients, cid)
    return ok(serialize(c))


@app.get("/clients")
def list_clients():
    _, role = auth()
    require_role(role, ["IntakeCoordinator", "Supervisor"])
    return list_response(list(clients.values()))


@app.post("/clients/<cid>/consent")
def record_consent(cid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator"])
    c = must_exist(clients, cid)
    if not c["consent_signed"]:
        c["consent_signed"] = True
        touch(c)
    return ok(serialize(c))


@app.get("/clients/<cid>/risk")
def client_risk(cid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator", "Supervisor"])
    c = must_exist(clients, cid)
    basis = request.args.get("basis", "comprehensive")
    provisional, comprehensive = client_flag_counts(cid)
    if basis == "provisional":
        tier = tier_of(provisional)
    else:
        tier = tier_of(comprehensive)
    return ok({
        "tier": tier,
        "provisional_flags": provisional,
        "comprehensive_flags": comprehensive,
    })


# ==========================================================================
# Enrollment
# ==========================================================================
@app.post("/enrollments")
def create_enrollment():
    _, role = auth()
    require_role(role, ["IntakeCoordinator"])
    body = get_body()
    client_id = v_str(body, "client_id")
    c = must_exist(clients, client_id)
    # business rules (PRD 3.2 order: first-time, gestational, uniqueness)
    if not c["first_time_mother"]:
        raise ApiError("ERR_NOT_FIRST_TIME_MOTHER", 422, "client is not a first-time mother")
    if c["gestational_age_weeks"] > GESTATIONAL_AGE_MAX_WEEKS:
        raise ApiError("ERR_GESTATIONAL_AGE_INELIGIBLE", 422, "gestational age exceeds the intake ceiling")
    for e in enrollments.values():
        if e["client_id"] == client_id and e["status"] != "EXITED":
            raise ApiError("ERR_ENROLLMENT_EXISTS", 409, "client already has a non-exited enrollment")
    e = base_entity()
    e.update({
        "client_id": client_id,
        "status": "PROSPECT",
        "program_phase": "PREGNANCY",
        "gestational_age_at_enrollment": c["gestational_age_weeks"],
        "completed_visit_count": 0,
        "dosage_alert": False,
        "risk_tier_at_enrollment": c["risk_tier"],
    })
    enrollments[e["id"]] = e
    return ok(serialize(e), status=201)


@app.get("/enrollments/<eid>")
def get_enrollment(eid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator", "Supervisor", "HomeVisitNurse"])
    e = must_exist(enrollments, eid)
    return ok(serialize(e))


@app.get("/enrollments")
def list_enrollments():
    _, role = auth()
    require_role(role, ["IntakeCoordinator", "Supervisor"])
    items = list(enrollments.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [e for e in items if e["client_id"] == client_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return list_response(items)


@app.post("/enrollments/<eid>/activate-enrollment")
def activate_enrollment(eid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator"])
    e = must_exist(enrollments, eid)
    if e["status"] != "PROSPECT":
        raise ApiError("ERR_INVALID_STATE", 409, "enrollment is not in PROSPECT status")
    c = clients[e["client_id"]]
    if not c["consent_signed"]:
        raise ApiError("ERR_CONSENT_REQUIRED", 422, "consent has not been recorded")
    if not c["first_time_mother"]:
        raise ApiError("ERR_NOT_FIRST_TIME_MOTHER", 422, "client is not a first-time mother")
    if e["gestational_age_at_enrollment"] > GESTATIONAL_AGE_MAX_WEEKS:
        raise ApiError("ERR_GESTATIONAL_AGE_INELIGIBLE", 422, "gestational age exceeds the intake ceiling")
    e["status"] = "ENROLLED"
    touch(e)
    return ok(serialize(e))


@app.post("/enrollments/<eid>/record-birth")
def record_birth(eid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator"])
    e = must_exist(enrollments, eid)
    body = get_body()
    child_dob = v_str(body, "child_dob")
    parse_iso_date(child_dob)
    if e["program_phase"] != "PREGNANCY":
        raise ApiError("ERR_INVALID_STATE", 409, "program phase is not PREGNANCY")
    c = clients[e["client_id"]]
    c["child_dob"] = child_dob
    touch(c)
    e["program_phase"] = "INFANCY"
    touch(e)
    return ok(serialize(e))


@app.post("/enrollments/<eid>/advance-phase")
def advance_phase(eid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator"])
    e = must_exist(enrollments, eid)
    if e["program_phase"] != "INFANCY":
        raise ApiError("ERR_INVALID_STATE", 409, "program phase is not INFANCY")
    e["program_phase"] = "TODDLERHOOD"
    touch(e)
    return ok(serialize(e))


@app.post("/enrollments/<eid>/graduate")
def graduate(eid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator"])
    e = must_exist(enrollments, eid)
    if e["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "enrollment is not ACTIVE")
    if e["program_phase"] != "TODDLERHOOD":
        raise ApiError("ERR_GRADUATION_TOO_EARLY", 409, "program phase is not TODDLERHOOD")
    close_enrollment_cascade(e)
    e["status"] = "GRADUATED"
    touch(e)
    return ok(serialize(e))


@app.post("/enrollments/<eid>/disenroll")
def disenroll(eid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator"])
    e = must_exist(enrollments, eid)
    if e["status"] not in ("PROSPECT", "ENROLLED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "enrollment is already terminal")
    close_enrollment_cascade(e)
    e["status"] = "EXITED"
    touch(e)
    return ok(serialize(e))


@app.get("/enrollments/<eid>/dosage")
def get_dosage(eid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator", "Supervisor", "HomeVisitNurse"])
    e = must_exist(enrollments, eid)
    dtd, dfp, ctd, etd = compute_dosage(e)
    return ok({
        "dosage_to_date_pct": dtd,
        "dosage_full_pct": dfp,
        "completed_to_date": ctd,
        "expected_to_date": etd,
        "dosage_alert": e["dosage_alert"],
    })


# ==========================================================================
# Assignment
# ==========================================================================
@app.post("/assignments")
def create_assignment():
    _, role = auth()
    require_role(role, ["Supervisor"])
    body = get_body()
    enrollment_id = v_str(body, "enrollment_id")
    nurse_id = v_str(body, "nurse_id")
    expected_version = v_int(body, "expected_enrollment_version")
    high_needs = v_bool(body, "high_needs", required=False, default=False)
    # existence, left-to-right
    e = must_exist(enrollments, enrollment_id)
    n = must_exist(nurses, nurse_id)
    # state / business ordering (PRD 3.4)
    if e["status"] not in ("ENROLLED", "ACTIVE"):
        raise ApiError("ERR_ENROLLMENT_NOT_ASSIGNABLE", 409, "enrollment is not assignable")
    if n["status"] != "ACTIVE":
        raise ApiError("ERR_NURSE_NOT_ACTIVE", 422, "target nurse is not ACTIVE")
    new_w = assignment_weight(e["program_phase"], high_needs)
    would_be = q2(Decimal(str(n["current_caseload_weight"])) + new_w)
    if would_be > Decimal(str(n["max_caseload_weight"])):
        raise ApiError("ERR_CASELOAD_EXCEEDED", 422, "assignment would exceed the nurse caseload cap")
    if expected_version != e["version"]:
        raise ApiError("ERR_STALE_ENROLLMENT_VERSION", 412, "stale enrollment version")
    # success: supersede prior active assignments on this enrollment
    for prior in active_assignments_of(enrollment_id):
        end_assignment(prior)
    a = base_entity()
    a.update({
        "enrollment_id": enrollment_id,
        "nurse_id": nurse_id,
        "phase_at_assignment": e["program_phase"],
        "high_needs": high_needs,
        "caseload_weight": float(new_w),
        "status": "ACTIVE",
        "review_required": False,
    })
    assignments[a["id"]] = a
    recompute_nurse(nurse_id)
    if e["status"] == "ENROLLED":
        e["status"] = "ACTIVE"
    touch(e)  # version advances by 1 for the OCC contract
    return ok(serialize(a), status=201)


@app.get("/assignments/<aid>")
def get_assignment(aid):
    _, role = auth()
    require_role(role, ["Supervisor", "ProgramAdmin"])
    a = must_exist(assignments, aid)
    return ok(serialize(a))


@app.get("/assignments")
def list_assignments():
    _, role = auth()
    require_role(role, ["Supervisor", "ProgramAdmin"])
    items = list(assignments.values())
    for field in ("enrollment_id", "nurse_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a[field] == val]
    return list_response(items)


@app.post("/assignments/<aid>/end")
def end_assignment_endpoint(aid):
    _, role = auth()
    require_role(role, ["Supervisor"])
    a = must_exist(assignments, aid)
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "assignment is not ACTIVE")
    end_assignment(a)
    return ok(serialize(a))


# ==========================================================================
# Visit
# ==========================================================================
def check_visit_window(start_s, end_s):
    start = parse_instant(start_s)
    end = parse_instant(end_s)
    if not (end > start):
        raise ApiError("ERR_SCHEDULE_WINDOW_INVALID", 422, "scheduled_end must be strictly after scheduled_start")
    return start, end


def check_nurse_conflict(nurse_id, start, end, exclude_visit_id=None):
    for v in visits.values():
        if v["id"] == exclude_visit_id:
            continue
        if v["nurse_id"] != nurse_id:
            continue
        if v["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        ex_start = parse_instant(v["scheduled_start"])
        ex_end = parse_instant(v["scheduled_end"])
        if start < ex_end + VISIT_TRAVEL_BUFFER and ex_start < end + VISIT_TRAVEL_BUFFER:
            raise ApiError("ERR_VISIT_OVERLAP", 409, "visit double-books the nurse")


def check_duplicate_target_date(enrollment_id, target_date, exclude_visit_id=None):
    for v in visits.values():
        if v["id"] == exclude_visit_id:
            continue
        if v["enrollment_id"] != enrollment_id:
            continue
        if v["status"] in ("SCHEDULED", "COMPLETED") and v["target_date"] == target_date:
            raise ApiError("ERR_DUPLICATE_TARGET_DATE", 409, "another non-terminal visit shares this target_date")


@app.post("/visits")
def create_visit():
    _, role = auth()
    require_role(role, ["HomeVisitNurse"])
    body = get_body()
    enrollment_id = v_str(body, "enrollment_id")
    nurse_id = v_str(body, "nurse_id")
    phase = v_enum(body, "phase", {"PREGNANCY", "INFANCY", "TODDLERHOOD"})
    target_date = v_str(body, "target_date")
    parse_iso_date(target_date)
    scheduled_start = v_str(body, "scheduled_start")
    scheduled_end = v_str(body, "scheduled_end")
    e = must_exist(enrollments, enrollment_id)
    must_exist(nurses, nurse_id)
    start, end = check_visit_window(scheduled_start, scheduled_end)
    check_nurse_conflict(nurse_id, start, end)
    check_duplicate_target_date(enrollment_id, target_date)
    v = base_entity()
    v.update({
        "enrollment_id": enrollment_id,
        "nurse_id": nurse_id,
        "phase": phase,
        "target_date": target_date,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "completed_date": None,
        "on_time": False,
        "rescheduled_from_visit_id": None,
    })
    visits[v["id"]] = v
    return ok(serialize(v), status=201)


@app.get("/visits/<vid>")
def get_visit(vid):
    _, role = auth()
    require_role(role, ["HomeVisitNurse", "Supervisor", "IntakeCoordinator"])
    v = must_exist(visits, vid)
    return ok(serialize(v))


@app.get("/visits")
def list_visits():
    _, role = auth()
    require_role(role, ["HomeVisitNurse", "Supervisor", "IntakeCoordinator"])
    items = list(visits.values())
    for field in ("enrollment_id", "nurse_id", "rescheduled_from_visit_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [v for v in items if v[field] == val]
    return list_response(items)


def require_visit_owner(uid, v):
    if uid != v["nurse_id"]:
        raise ApiError("ERR_NOT_VISIT_OWNER", 403, "acting nurse does not own this visit")


@app.post("/visits/<vid>/complete")
def complete_visit(vid):
    uid, role = auth()
    require_role(role, ["HomeVisitNurse"])
    v = must_exist(visits, vid)
    require_visit_owner(uid, v)
    if v["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "visit is not SCHEDULED")
    e = enrollments[v["enrollment_id"]]
    if e["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409, "enrollment is not ACTIVE")
    body = get_body()
    completed_date = v_str(body, "completed_date")
    cd = parse_iso_date(completed_date)
    if cd > clock().date():
        raise ApiError("ERR_VALIDATION", 422, "completed_date is in the future")
    td = parse_iso_date(v["target_date"])
    v["status"] = "COMPLETED"
    v["completed_date"] = completed_date
    v["on_time"] = abs((cd - td).days) <= ON_TIME_TOLERANCE_DAYS
    touch(v)
    e["completed_visit_count"] += 1
    recompute_and_reconcile(e)
    touch(e)
    return ok(serialize(v))


@app.post("/visits/<vid>/revert-completion")
def revert_completion(vid):
    uid, role = auth()
    require_role(role, ["HomeVisitNurse"])
    v = must_exist(visits, vid)
    require_visit_owner(uid, v)
    if v["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "visit is not COMPLETED")
    e = enrollments[v["enrollment_id"]]
    v["status"] = "SCHEDULED"
    v["completed_date"] = None
    v["on_time"] = False
    touch(v)
    e["completed_visit_count"] -= 1
    recompute_and_reconcile(e)
    touch(e)
    return ok(serialize(v))


@app.post("/visits/<vid>/mark-missed")
def mark_missed(vid):
    uid, role = auth()
    require_role(role, ["HomeVisitNurse"])
    v = must_exist(visits, vid)
    require_visit_owner(uid, v)
    if v["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "visit is not SCHEDULED")
    e = enrollments[v["enrollment_id"]]
    v["status"] = "MISSED"
    touch(v)
    if recompute_and_reconcile(e):
        touch(e)
    return ok(serialize(v))


@app.post("/visits/<vid>/cancel")
def cancel_visit(vid):
    _, role = auth()
    require_role(role, ["IntakeCoordinator"])
    v = must_exist(visits, vid)
    if v["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "visit is not SCHEDULED")
    e = enrollments[v["enrollment_id"]]
    v["status"] = "CANCELED"
    touch(v)
    if recompute_and_reconcile(e):
        touch(e)
    return ok(serialize(v))


@app.post("/visits/<vid>/reschedule")
def reschedule_visit(vid):
    uid, role = auth()
    require_role(role, ["HomeVisitNurse"])
    v = must_exist(visits, vid)
    require_visit_owner(uid, v)
    if v["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "visit is not SCHEDULED")
    body = get_body()
    target_date = v_str(body, "target_date")
    parse_iso_date(target_date)
    scheduled_start = v_str(body, "scheduled_start")
    scheduled_end = v_str(body, "scheduled_end")
    start, end = check_visit_window(scheduled_start, scheduled_end)
    check_nurse_conflict(v["nurse_id"], start, end, exclude_visit_id=v["id"])
    check_duplicate_target_date(v["enrollment_id"], target_date, exclude_visit_id=v["id"])
    v["status"] = "RESCHEDULED"
    touch(v)
    replacement = base_entity()
    replacement.update({
        "enrollment_id": v["enrollment_id"],
        "nurse_id": v["nurse_id"],
        "phase": v["phase"],
        "target_date": target_date,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "completed_date": None,
        "on_time": False,
        "rescheduled_from_visit_id": v["id"],
    })
    visits[replacement["id"]] = replacement
    e = enrollments[v["enrollment_id"]]
    if recompute_and_reconcile(e):
        touch(e)
    return ok(serialize(replacement))


# ==========================================================================
# Assessment
# ==========================================================================
@app.post("/assessments")
def create_assessment():
    _, role = auth()
    require_role(role, ["HomeVisitNurse"])
    body = get_body()
    visit_id = v_str(body, "visit_id")
    enrollment_id = v_str(body, "enrollment_id")
    instrument_type = v_enum(body, "instrument_type", {"INTAKE", "ASQ", "EDINBURGH", "ASQ_SE"})
    raw_scores = body.get("raw_scores")
    if not isinstance(raw_scores, dict) or not raw_scores:
        raise ApiError("ERR_VALIDATION", 422, "raw_scores must be a non-empty object")
    for k, val in raw_scores.items():
        if isinstance(val, bool) or not isinstance(val, int):
            raise ApiError("ERR_VALIDATION", 422, "raw_scores values must be integers")
    v = must_exist(visits, visit_id)
    must_exist(enrollments, enrollment_id)
    if v["status"] != "COMPLETED":
        raise ApiError("ERR_VISIT_NOT_COMPLETED", 409, "referenced visit is not COMPLETED")
    if enrollment_id != v["enrollment_id"]:
        raise ApiError("ERR_ASSESSMENT_VISIT_MISMATCH", 422, "enrollment_id does not match the visit")
    total = sum(raw_scores.values())
    if total >= ON_TRACK_MIN:
        result_band = "ON_TRACK"
    elif total >= MONITOR_MIN:
        result_band = "MONITOR"
    else:
        result_band = "REFER"
    domain_flags = sorted([d for d, sc in raw_scores.items() if sc < DOMAIN_FLAG_THRESHOLD])
    a = base_entity()
    a.update({
        "visit_id": visit_id,
        "enrollment_id": enrollment_id,
        "instrument_type": instrument_type,
        "raw_scores": raw_scores,
        "result_band": result_band,
        "domain_flags": domain_flags,
    })
    assessments[a["id"]] = a
    # recompute client risk (comprehensive) and mirror onto enrollment snapshot
    e = enrollments[enrollment_id]
    recompute_client_risk(e["client_id"])
    new_snapshot = clients[e["client_id"]]["risk_tier"]
    if e["risk_tier_at_enrollment"] != new_snapshot:
        e["risk_tier_at_enrollment"] = new_snapshot
        touch(e)
    return ok(serialize(a), status=201)


@app.get("/assessments/<aid>")
def get_assessment(aid):
    _, role = auth()
    require_role(role, ["HomeVisitNurse", "Supervisor"])
    a = must_exist(assessments, aid)
    return ok(serialize(a))


@app.get("/assessments")
def list_assessments():
    _, role = auth()
    require_role(role, ["HomeVisitNurse", "Supervisor"])
    items = list(assessments.values())
    for field in ("visit_id", "enrollment_id"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a[field] == val]
    return list_response(items)


# ==========================================================================
# Referral
# ==========================================================================
@app.post("/referrals")
def create_referral():
    _, role = auth()
    require_role(role, ["HomeVisitNurse"])
    body = get_body()
    enrollment_id = v_str(body, "enrollment_id")
    benefit_type = v_enum(body, "benefit_type", {"WIC", "MEDICAID", "HOUSING", "CHILDCARE", "MENTAL_HEALTH"})
    e = must_exist(enrollments, enrollment_id)
    c = clients[e["client_id"]]
    if not c["consent_signed"]:
        raise ApiError("ERR_CONSENT_REQUIRED", 422, "consent has not been recorded")
    for r in referrals.values():
        if (r["enrollment_id"] == enrollment_id and r["benefit_type"] == benefit_type
                and r["status"] in ("OPEN", "CONTACTED")):
            raise ApiError("ERR_DUPLICATE_REFERRAL", 409, "a non-terminal referral of this benefit already exists")
    r = base_entity()
    r.update({
        "enrollment_id": enrollment_id,
        "benefit_type": benefit_type,
        "status": "OPEN",
        "attempts": 0,
        "connected_at": None,
    })
    referrals[r["id"]] = r
    return ok(serialize(r), status=201)


@app.get("/referrals/<rid>")
def get_referral(rid):
    _, role = auth()
    require_role(role, ["HomeVisitNurse", "Supervisor"])
    r = must_exist(referrals, rid)
    return ok(serialize(r))


@app.get("/referrals")
def list_referrals():
    _, role = auth()
    require_role(role, ["HomeVisitNurse", "Supervisor"])
    items = list(referrals.values())
    for field in ("enrollment_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [r for r in items if r[field] == val]
    return list_response(items)


def referral_transition(rid, allowed_from):
    r = must_exist(referrals, rid)
    if r["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409, "referral is not in a valid state for this transition")
    return r


@app.post("/referrals/<rid>/contact")
def referral_contact(rid):
    _, role = auth()
    require_role(role, ["HomeVisitNurse"])
    r = referral_transition(rid, ("OPEN",))
    r["status"] = "CONTACTED"
    r["attempts"] += 1
    touch(r)
    return ok(serialize(r))


@app.post("/referrals/<rid>/connect")
def referral_connect(rid):
    _, role = auth()
    require_role(role, ["HomeVisitNurse"])
    r = referral_transition(rid, ("CONTACTED",))
    r["status"] = "CONNECTED"
    r["connected_at"] = iso(clock())
    touch(r)
    return ok(serialize(r))


@app.post("/referrals/<rid>/decline")
def referral_decline(rid):
    _, role = auth()
    require_role(role, ["HomeVisitNurse"])
    r = referral_transition(rid, ("CONTACTED",))
    r["status"] = "DECLINED"
    touch(r)
    return ok(serialize(r))


@app.post("/referrals/<rid>/reopen")
def referral_reopen(rid):
    _, role = auth()
    require_role(role, ["HomeVisitNurse"])
    r = referral_transition(rid, ("CONTACTED",))
    r["status"] = "OPEN"
    touch(r)
    return ok(serialize(r))


@app.post("/referrals/<rid>/close")
def referral_close(rid):
    _, role = auth()
    require_role(role, ["HomeVisitNurse"])
    r = referral_transition(rid, ("OPEN", "CONTACTED"))
    r["status"] = "CLOSED"
    touch(r)
    return ok(serialize(r))


# ==========================================================================
# SupervisionSession
# ==========================================================================
@app.post("/supervision-sessions")
def create_supervision_session():
    _, role = auth()
    require_role(role, ["Supervisor"])
    body = get_body()
    nurse_id = v_str(body, "nurse_id")
    supervisor_id = v_str(body, "supervisor_id")
    period_start = v_str(body, "period_start")
    parse_iso_date(period_start)
    period_end = v_str(body, "period_end")
    parse_iso_date(period_end)
    reviewed = body.get("reviewed_enrollment_ids")
    if not isinstance(reviewed, list):
        raise ApiError("ERR_VALIDATION", 422, "reviewed_enrollment_ids must be an array")
    must_exist(nurses, nurse_id)
    must_exist(supervisors, supervisor_id)
    for eid in reviewed:
        must_exist(enrollments, eid)
    s = base_entity()
    s.update({
        "nurse_id": nurse_id,
        "supervisor_id": supervisor_id,
        "period_start": period_start,
        "period_end": period_end,
        "reviewed_enrollment_ids": list(reviewed),
        "status": "DRAFT",
    })
    supervision_sessions[s["id"]] = s
    return ok(serialize(s), status=201)


@app.get("/supervision-sessions/<sid>")
def get_supervision_session(sid):
    _, role = auth()
    require_role(role, ["Supervisor", "ProgramAdmin"])
    s = must_exist(supervision_sessions, sid)
    return ok(serialize(s))


@app.get("/supervision-sessions")
def list_supervision_sessions():
    _, role = auth()
    require_role(role, ["Supervisor", "ProgramAdmin"])
    items = list(supervision_sessions.values())
    for field in ("nurse_id", "supervisor_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s[field] == val]
    return list_response(items)


@app.post("/supervision-sessions/<sid>/sign")
def sign_supervision_session(sid):
    uid, role = auth()
    require_role(role, ["Supervisor"])
    s = must_exist(supervision_sessions, sid)
    if uid != s["supervisor_id"]:
        raise ApiError("ERR_NOT_SESSION_OWNER", 403, "acting supervisor does not own this session")
    if s["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "session is not in DRAFT status")
    sup = supervisors.get(s["supervisor_id"])
    if sup is None or sup["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "acting supervisor is not ACTIVE")
    for eid in s["reviewed_enrollment_ids"]:
        e = enrollments.get(eid)
        if e is None or not e["dosage_alert"]:
            continue
        for a in assignments.values():
            if (a["enrollment_id"] == eid and a["nurse_id"] == s["nurse_id"]
                    and a["status"] == "ACTIVE" and a["review_required"]):
                a["review_required"] = False
                touch(a)
                n = nurses.get(a["nurse_id"])
                if n is not None:
                    n["pending_supervision_count"] = max(0, n["pending_supervision_count"] - 1)
                    touch(n)
    s["status"] = "SIGNED"
    touch(s)
    return ok(serialize(s))


# ==========================================================================
# OutcomeMeasure
# ==========================================================================
def completed_visits_in_period(enrollment_id, ps, pe):
    result = []
    for v in visits.values():
        if v["enrollment_id"] != enrollment_id:
            continue
        if v["status"] != "COMPLETED" or not v["completed_date"]:
            continue
        cd = parse_iso_date(v["completed_date"])
        if ps <= cd <= pe:
            result.append(v)
    return result


@app.post("/outcome-measures")
def create_outcome_measure():
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    body = get_body()
    enrollment_id = v_str(body, "enrollment_id")
    measure_type = v_enum(body, "measure_type", {"ON_TIME_VISIT_RATE", "DOSAGE_TO_DATE", "BREASTFEEDING_INITIATED"})
    period_start = v_str(body, "period_start")
    ps = parse_iso_date(period_start)
    period_end = v_str(body, "period_end")
    pe = parse_iso_date(period_end)
    must_exist(enrollments, enrollment_id)

    if measure_type == "ON_TIME_VISIT_RATE":
        completed = completed_visits_in_period(enrollment_id, ps, pe)
        denominator = len(completed)
        numerator = sum(1 for v in completed if v["on_time"])
    elif measure_type == "DOSAGE_TO_DATE":
        numerator = 0
        denominator = 0
        for v in visits.values():
            if v["enrollment_id"] != enrollment_id:
                continue
            if v["status"] not in ("COMPLETED", "MISSED"):
                continue
            td = parse_iso_date(v["target_date"])
            if ps <= td <= pe:
                denominator += 1
                if v["status"] == "COMPLETED":
                    numerator += 1
    else:  # BREASTFEEDING_INITIATED — no source data in the model
        numerator = 0
        denominator = 0

    om = base_entity()
    om.update({
        "enrollment_id": enrollment_id,
        "measure_type": measure_type,
        "period_start": period_start,
        "period_end": period_end,
        "numerator": numerator,
        "denominator": denominator,
        "rate_pct": pct(numerator, denominator),
    })
    outcome_measures[om["id"]] = om
    return ok(serialize(om), status=201)


@app.get("/outcome-measures/<oid>")
def get_outcome_measure(oid):
    _, role = auth()
    require_role(role, ["ProgramAdmin", "Supervisor"])
    om = must_exist(outcome_measures, oid)
    return ok(serialize(om))


@app.get("/outcome-measures")
def list_outcome_measures():
    _, role = auth()
    require_role(role, ["ProgramAdmin", "Supervisor"])
    items = list(outcome_measures.values())
    val = request.args.get("enrollment_id")
    if val is not None:
        items = [o for o in items if o["enrollment_id"] == val]
    return list_response(items)


# ==========================================================================
# MiechvReport
# ==========================================================================
@app.post("/miechv-reports")
def create_miechv_report():
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    body = get_body()
    period_start = v_str(body, "period_start")
    parse_iso_date(period_start)
    period_end = v_str(body, "period_end")
    parse_iso_date(period_end)
    m = base_entity()
    m.update({
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "program_on_time_rate_pct": None,
        "enrolled_count": 0,
        "dosage_alert_count": 0,
    })
    miechv_reports[m["id"]] = m
    return ok(serialize(m), status=201)


@app.get("/miechv-reports/<mid>")
def get_miechv_report(mid):
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    m = must_exist(miechv_reports, mid)
    return ok(serialize(m))


@app.post("/miechv-reports/<mid>/finalize")
def finalize_miechv_report(mid):
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    m = must_exist(miechv_reports, mid)
    if m["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "report is not in DRAFT status")
    ps = parse_iso_date(m["period_start"])
    pe = parse_iso_date(m["period_end"])
    scope = [e for e in enrollments.values() if e["status"] in ("ACTIVE", "GRADUATED")]
    numerator = 0
    denominator = 0
    for e in scope:
        for v in completed_visits_in_period(e["id"], ps, pe):
            denominator += 1
            if v["on_time"]:
                numerator += 1
    m["program_on_time_rate_pct"] = pct(numerator, denominator)
    m["enrolled_count"] = len(scope)
    m["dosage_alert_count"] = sum(1 for e in enrollments.values() if e["dosage_alert"])
    m["status"] = "FINALIZED"
    touch(m)
    return ok(serialize(m))


# --------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
