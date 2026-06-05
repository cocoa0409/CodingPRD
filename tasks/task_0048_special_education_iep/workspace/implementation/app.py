"""Special Education IEP Management API — Flask application.

Boots empty (no seeding). All state lives in process memory (db.store).
start.sh re-launches this on every test under per-test-server isolation.

Routes are mounted at the root (scaffold api_prefix == "").

Validation order (PRD §2.8), applied per endpoint in this fixed sequence:
  1  auth: headers present + known role            -> ERR_UNAUTHENTICATED (401)
  2  auth: role permitted for operation            -> ERR_FORBIDDEN (403)
  3  auth: segregation of duties (2 endpoints)     -> ERR_SEGREGATION_OF_DUTIES (403)
  10 existence: path resources exist L->R          -> ERR_NOT_FOUND (404)
  11 referential: body FKs exist                   -> ERR_FK_NOT_FOUND (404)
  20 body structural: required + well-typed + enum -> ERR_INVALID_REQUEST (400)
  21 numeric/range constraints                     -> ERR_INVALID_RANGE (422)
  30 state: transition defined from current state  -> ERR_INVALID_STATE (409)
  31 OCC: expected_iep_version matches             -> ERR_STALE_VERSION (412)
  40+ cross-entity business guards                 -> various 409
"""
import os
import uuid

from flask import Flask, request

from db import store
from errors import (
    ApiError, raise_err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_SEGREGATION_OF_DUTIES,
    ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_RANGE,
    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_CONSENT_NOT_GRANTED,
    ERR_STUDENT_NOT_ELIGIBLE, ERR_IEP_NOT_ACTIVE, ERR_TRANSITION_AGE_NOT_MET,
    ERR_ACTIVE_IEP_EXISTS,
)
from middleware import get_auth, require_role
from response import success_object, success_array, error_response
import calculations as calc
from calculations import (
    parse_iso_to_dt, eligibility_composite_score,
    goal_progress_provisional, goal_progress_cumulative,
    lre_general_ed_pct, lre_setting_bucket, add_days_iso, full_years_between,
    REEVAL_DAYS, TRANSITION_AGE, ELIGIBILITY_THRESHOLD,
)

app = Flask(__name__)
app.url_map.strict_slashes = False


# ============================================================
# Enums
# ============================================================
DISABILITY_CATEGORIES = {"SLD", "AUTISM", "SPEECH_LANGUAGE", "OHI", "EMOTIONAL", "INTELLECTUAL"}
EVAL_TYPES = {"INITIAL", "TRIENNIAL"}
GOAL_DOMAINS = {"READING", "MATH", "WRITING", "COMMUNICATION", "BEHAVIOR", "MOTOR"}
SERVICE_TYPES = {"OT", "PT", "SPEECH"}
CONSENT_DECISIONS = {"GRANT", "DENY"}


# ============================================================
# Global error handlers
# ============================================================

@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Path not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 400)


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", f"Internal error: {e}", 500)


# ============================================================
# Helpers
# ============================================================

def gen_id() -> str:
    return str(uuid.uuid4())


def clock_now() -> str:
    """The server logical clock — drives created_at/updated_at and all
    clock-derived computed timestamps (finalized_at, decided_at, activated_at,
    reeval-due, age)."""
    return store.current_utc


def get_json_body() -> dict:
    """Return JSON body as dict; {} if absent. ERR_INVALID_REQUEST on bad JSON."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body: dict, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def pagination_params():
    limit_str = request.args.get("limit")
    offset_str = request.args.get("offset")
    try:
        limit = int(limit_str) if limit_str is not None else 10
        offset = int(offset_str) if offset_str is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise_err(ERR_INVALID_REQUEST, "limit must be 1..100; offset >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def sort_key(obj):
    """Creation order: created_at then monotonic seq (stable under a pinned clock)."""
    return (obj["created_at"], obj.get("_seq", 0))


def common_create(obj: dict, with_version: bool = True) -> dict:
    """Stamp id, created_at, updated_at, version, _seq onto a new resource."""
    if "id" not in obj:
        obj["id"] = gen_id()
    now = clock_now()
    obj["created_at"] = now
    obj["updated_at"] = now
    if with_version:
        obj["version"] = 1
    obj["_seq"] = store.next_seq()
    return obj


def bump_version(obj: dict):
    obj["version"] = int(obj.get("version", 1)) + 1
    obj["updated_at"] = clock_now()


# ---- public view projections (strip private keys like _seq) ----

def _view(obj: dict, drop=("_seq",)) -> dict:
    return {k: v for k, v in obj.items() if k not in drop}


def student_view(s):
    return _view(s)


def evaluation_view(e):
    return _view(e)


def iep_view(i):
    return _view(i)


def goal_view(g):
    return _view(g)


def progress_report_view(p):
    return _view(p)


def related_service_view(r):
    return _view(r)


def consent_request_view(c):
    return _view(c)


def transition_plan_view(t):
    return _view(t)


# ---- existence helpers (path = ERR_NOT_FOUND, body FK = ERR_FK_NOT_FOUND) ----

def get_student_or_404(sid):
    s = store.students.get(sid)
    if not s:
        raise_err(ERR_NOT_FOUND, f"Student {sid} not found")
    return s


def get_evaluation_or_404(eid):
    e = store.evaluations.get(eid)
    if not e:
        raise_err(ERR_NOT_FOUND, f"Evaluation {eid} not found")
    return e


def get_iep_or_404(iid):
    i = store.ieps.get(iid)
    if not i:
        raise_err(ERR_NOT_FOUND, f"IEP {iid} not found")
    return i


def get_goal_or_404(gid):
    g = store.goals.get(gid)
    if not g:
        raise_err(ERR_NOT_FOUND, f"Goal {gid} not found")
    return g


def get_progress_report_or_404(pid):
    p = store.progress_reports.get(pid)
    if not p:
        raise_err(ERR_NOT_FOUND, f"ProgressReport {pid} not found")
    return p


def get_related_service_or_404(rid):
    r = store.related_services.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, f"RelatedService {rid} not found")
    return r


def get_consent_request_or_404(cid):
    c = store.consent_requests.get(cid)
    if not c:
        raise_err(ERR_NOT_FOUND, f"ConsentRequest {cid} not found")
    return c


def get_transition_plan_or_404(tid):
    t = store.transition_plans.get(tid)
    if not t:
        raise_err(ERR_NOT_FOUND, f"TransitionPlan {tid} not found")
    return t


# ---- numeric helpers ----

def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ============================================================
# Derived-field recompute helpers
# ============================================================

def recompute_iep_lre(iep: dict):
    """Recompute lre_general_ed_pct + lre_setting on the IEP from its ACTIVE
    pull-out services. Does NOT itself bump version (callers manage versioning)."""
    pullout = [
        r for r in store.related_services.values()
        if r["iep_id"] == iep["id"]
        and r["status"] == "ACTIVE"
        and r["delivered_in_general_ed"] is False
    ]
    pct = lre_general_ed_pct(pullout, iep["school_day_minutes"])
    iep["lre_general_ed_pct"] = pct
    iep["lre_setting"] = lre_setting_bucket(pct)


def recompute_goal_progress(goal: dict):
    """Recompute latest_progress_pct + cumulative_progress_pct on the goal."""
    reports = [p for p in store.progress_reports.values() if p["goal_id"] == goal["id"]]
    goal["latest_progress_pct"] = goal_progress_provisional(
        reports, goal["baseline_value"], goal["target_value"])
    goal["cumulative_progress_pct"] = goal_progress_cumulative(
        reports, goal["baseline_value"], goal["target_value"])


def recompute_student_from_evaluations(student: dict):
    """Recompute eligibility_status, disability_category, next_reeval_due_date
    from the student's FINALIZED evaluations (latest finalized wins)."""
    finalized = [
        e for e in store.evaluations.values()
        if e["student_id"] == student["id"]
        and e["status"] == "FINALIZED"
        and e.get("finalized_at")
    ]
    if not finalized:
        student["eligibility_status"] = "NOT_EVALUATED"
        student["disability_category"] = None
        student["next_reeval_due_date"] = None
        return
    finalized.sort(key=lambda e: (parse_iso_to_dt(e["finalized_at"]), e.get("_seq", 0)))
    latest = finalized[-1]
    student["eligibility_status"] = latest["outcome"]
    if latest["outcome"] == "ELIGIBLE":
        student["disability_category"] = latest["proposed_category"]
    else:
        student["disability_category"] = None
    student["next_reeval_due_date"] = add_days_iso(latest["finalized_at"], REEVAL_DAYS)


def placement_consent_for_iep(iep_id):
    """The most recent PLACEMENT ConsentRequest for this IEP (by creation order)."""
    matches = [
        c for c in store.consent_requests.values()
        if c["iep_id"] == iep_id and c["consent_type"] == "PLACEMENT"
    ]
    if not matches:
        return None
    matches.sort(key=sort_key)
    return matches[-1]


def evaluation_consent_for_student(student_id):
    """The most recent EVALUATION ConsentRequest for this student (by creation)."""
    matches = [
        c for c in store.consent_requests.values()
        if c["student_id"] == student_id and c["consent_type"] == "EVALUATION"
    ]
    if not matches:
        return None
    matches.sort(key=sort_key)
    return matches[-1]


# ============================================================
# Students
# ============================================================

@app.route("/students", methods=["POST"])
def create_student():
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin"])
    body = get_json_body()
    require_fields(body, ["full_name", "date_of_birth", "grade_level"])
    full_name = body["full_name"]
    dob = body["date_of_birth"]
    grade = body["grade_level"]

    if not isinstance(full_name, str) or not full_name.strip():
        raise_err(ERR_INVALID_REQUEST, "full_name must be a non-empty string")
    if not isinstance(dob, str):
        raise_err(ERR_INVALID_REQUEST, "date_of_birth must be an ISO 8601 string")
    try:
        parse_iso_to_dt(dob)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "date_of_birth must be a valid ISO 8601 date")
    if not _is_int(grade):
        raise_err(ERR_INVALID_REQUEST, "grade_level must be an integer")
    # grade_level range 0..12 -> ERR_INVALID_RANGE (priority 21)
    if grade < 0 or grade > 12:
        raise_err(ERR_INVALID_RANGE, "grade_level must be in 0..12")

    obj = {
        "full_name": full_name,
        "date_of_birth": dob,
        "grade_level": grade,
        "eligibility_status": "NOT_EVALUATED",
        "disability_category": None,
        "active_iep_id": None,
        "next_reeval_due_date": None,
    }
    common_create(obj)
    store.students[obj["id"]] = obj
    return success_object(student_view(obj), 201)


@app.route("/students/<sid>", methods=["GET"])
def get_student(sid):
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    s = get_student_or_404(sid)
    return success_object(student_view(s), 200)


@app.route("/students", methods=["GET"])
def list_students():
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator"])
    limit, offset = pagination_params()
    eligibility_status = request.args.get("eligibility_status")
    items = list(store.students.values())
    if eligibility_status is not None:
        items = [s for s in items if s["eligibility_status"] == eligibility_status]
    items.sort(key=sort_key)
    items, total = paginate(items, limit, offset)
    return success_array([student_view(s) for s in items], limit, offset, total)


# ============================================================
# Evaluations
# ============================================================

@app.route("/evaluations", methods=["POST"])
def create_evaluation():
    uid, role = get_auth()
    require_role(role, ["CaseManager"])
    body = get_json_body()
    # FK existence (priority 11) precedes structural validation (priority 20) per PRD §2.8
    require_fields(body, ["student_id"])
    student_id = body["student_id"]
    get_student_or_404_fk(student_id)

    require_fields(body, ["eval_type", "cognitive_score",
                          "academic_score", "adaptive_score", "proposed_category"])
    eval_type = body["eval_type"]
    cog = body["cognitive_score"]
    aca = body["academic_score"]
    ada = body["adaptive_score"]
    proposed = body["proposed_category"]

    # structural (priority 20)
    if eval_type not in EVAL_TYPES:
        raise_err(ERR_INVALID_REQUEST, "eval_type must be INITIAL or TRIENNIAL")
    if proposed not in DISABILITY_CATEGORIES:
        raise_err(ERR_INVALID_REQUEST, "proposed_category not in allowed set")
    for nm, val in (("cognitive_score", cog), ("academic_score", aca),
                    ("adaptive_score", ada)):
        if not _is_number(val):
            raise_err(ERR_INVALID_REQUEST, f"{nm} must be a number")
    # range (priority 21): each standard score 40..160
    for nm, val in (("cognitive_score", cog), ("academic_score", aca),
                    ("adaptive_score", ada)):
        if val < 40 or val > 160:
            raise_err(ERR_INVALID_RANGE, f"{nm} must be in 40..160")

    obj = {
        "student_id": student_id,
        "eval_type": eval_type,
        "cognitive_score": cog,
        "academic_score": aca,
        "adaptive_score": ada,
        "proposed_category": proposed,
        "status": "REQUESTED",
        "composite_eligibility_score": None,
        "outcome": None,
        "finalized_at": None,
        "requested_by_user_id": uid,
    }
    common_create(obj)
    store.evaluations[obj["id"]] = obj
    return success_object(evaluation_view(obj), 201)


def get_student_or_404_fk(sid):
    s = store.students.get(sid)
    if not s:
        raise_err(ERR_FK_NOT_FOUND, f"student_id {sid} does not reference an existing Student")
    return s


def get_iep_or_404_fk(iid):
    i = store.ieps.get(iid)
    if not i:
        raise_err(ERR_FK_NOT_FOUND, f"iep_id {iid} does not reference an existing IEP")
    return i


def get_goal_or_404_fk(gid):
    g = store.goals.get(gid)
    if not g:
        raise_err(ERR_FK_NOT_FOUND, f"goal_id {gid} does not reference an existing Goal")
    return g


@app.route("/evaluations", methods=["GET"])
def list_evaluations():
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator"])
    limit, offset = pagination_params()
    student_id = request.args.get("student_id")
    items = list(store.evaluations.values())
    if student_id is not None:
        items = [e for e in items if e["student_id"] == student_id]
    items.sort(key=sort_key)
    items, total = paginate(items, limit, offset)
    return success_array([evaluation_view(e) for e in items], limit, offset, total)


@app.route("/evaluations/<eid>", methods=["GET"])
def get_evaluation(eid):
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator"])
    e = get_evaluation_or_404(eid)
    return success_object(evaluation_view(e), 200)


@app.route("/evaluations/<eid>/request-consent", methods=["POST"])
def evaluation_request_consent(eid):
    _, role = get_auth()
    require_role(role, ["CaseManager"])
    e = get_evaluation_or_404(eid)
    # state (priority 30)
    if e["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, f"Evaluation status is {e['status']}, required REQUESTED")
    # side effect: create EVALUATION ConsentRequest (PENDING)
    cr = {
        "student_id": e["student_id"],
        "iep_id": None,
        "consent_type": "EVALUATION",
        "status": "PENDING",
        "decided_at": None,
    }
    common_create(cr)
    store.consent_requests[cr["id"]] = cr
    # transition
    e["status"] = "CONSENT_PENDING"
    bump_version(e)
    return success_object(evaluation_view(e), 200)


@app.route("/evaluations/<eid>/begin", methods=["POST"])
def evaluation_begin(eid):
    _, role = get_auth()
    require_role(role, ["Evaluator"])
    e = get_evaluation_or_404(eid)
    # state (priority 30)
    if e["status"] != "CONSENT_PENDING":
        raise_err(ERR_INVALID_STATE, f"Evaluation status is {e['status']}, required CONSENT_PENDING")
    # cross-entity guard (priority 40): EVALUATION consent for student GRANTED
    cr = evaluation_consent_for_student(e["student_id"])
    if cr is None or cr["status"] != "GRANTED":
        raise_err(ERR_CONSENT_NOT_GRANTED,
                  "EVALUATION consent for this student is not GRANTED")
    e["status"] = "IN_PROGRESS"
    bump_version(e)
    return success_object(evaluation_view(e), 200)


@app.route("/evaluations/<eid>/finalize", methods=["POST"])
def evaluation_finalize(eid):
    uid, role = get_auth()
    require_role(role, ["Evaluator"])
    e = get_evaluation_or_404(eid)
    # segregation of duties (priority 3): finalizing Evaluator must not be the
    # CaseManager recorded as requester.
    if e.get("requested_by_user_id") is not None and uid == e["requested_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "Finalizing Evaluator must not be the requesting CaseManager")
    # state (priority 30)
    if e["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE, f"Evaluation status is {e['status']}, required IN_PROGRESS")

    composite, outcome = eligibility_composite_score(
        e["cognitive_score"], e["academic_score"], e["adaptive_score"], e["eval_type"])
    e["composite_eligibility_score"] = composite
    e["outcome"] = outcome
    e["finalized_at"] = clock_now()
    e["status"] = "FINALIZED"
    bump_version(e)

    # reconcile student
    student = store.students.get(e["student_id"])
    if student is not None:
        recompute_student_from_evaluations(student)
        bump_version(student)
    return success_object(evaluation_view(e), 200)


# ============================================================
# Consent Requests
# ============================================================

@app.route("/consent-requests", methods=["GET"])
def list_consent_requests():
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    limit, offset = pagination_params()
    student_id = request.args.get("student_id")
    iep_id = request.args.get("iep_id")
    consent_type = request.args.get("consent_type")
    status = request.args.get("status")
    items = list(store.consent_requests.values())
    if student_id is not None:
        items = [c for c in items if c["student_id"] == student_id]
    if iep_id is not None:
        items = [c for c in items if c["iep_id"] == iep_id]
    if consent_type is not None:
        items = [c for c in items if c["consent_type"] == consent_type]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    # ordered by created_at ASC then id ASC (PRD §2.3)
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    items, total = paginate(items, limit, offset)
    return success_array([consent_request_view(c) for c in items], limit, offset, total)


@app.route("/consent-requests/<cid>", methods=["GET"])
def get_consent_request(cid):
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    c = get_consent_request_or_404(cid)
    return success_object(consent_request_view(c), 200)


@app.route("/consent-requests/<cid>/decide", methods=["POST"])
def consent_request_decide(cid):
    _, role = get_auth()
    require_role(role, ["Parent"])
    c = get_consent_request_or_404(cid)
    body = get_json_body()
    # structural (priority 20): decision required + in allowed set
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in CONSENT_DECISIONS:
        raise_err(ERR_INVALID_REQUEST, "decision must be GRANT or DENY")
    # state (priority 30)
    if c["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, f"ConsentRequest status is {c['status']}, required PENDING")
    c["status"] = "GRANTED" if decision == "GRANT" else "DENIED"
    c["decided_at"] = clock_now()
    bump_version(c)
    return success_object(consent_request_view(c), 200)


@app.route("/consent-requests/<cid>/revoke", methods=["POST"])
def consent_request_revoke(cid):
    _, role = get_auth()
    require_role(role, ["Parent"])
    c = get_consent_request_or_404(cid)
    # state (priority 30)
    if c["status"] != "GRANTED":
        raise_err(ERR_INVALID_STATE, f"ConsentRequest status is {c['status']}, required GRANTED")
    c["status"] = "REVOKED"
    bump_version(c)
    # cascade: PLACEMENT consent revocation on an ACTIVE linked IEP forces it to
    # AMENDMENT_PENDING and clears the student's active_iep_id.
    if c["consent_type"] == "PLACEMENT" and c.get("iep_id"):
        iep = store.ieps.get(c["iep_id"])
        if iep is not None and iep["status"] == "ACTIVE":
            iep["status"] = "AMENDMENT_PENDING"
            student = store.students.get(iep["student_id"])
            if student is not None:
                student["active_iep_id"] = None
                bump_version(student)
            bump_version(iep)
    return success_object(consent_request_view(c), 200)


# ============================================================
# IEPs
# ============================================================

@app.route("/ieps", methods=["POST"])
def create_iep():
    _, role = get_auth()
    require_role(role, ["CaseManager"])
    body = get_json_body()
    # FK existence (priority 11) precedes structural validation (priority 20) per PRD §2.8
    require_fields(body, ["student_id"])
    student_id = body["student_id"]
    get_student_or_404_fk(student_id)

    require_fields(body, ["school_day_minutes", "annual_review_due_date"])
    school_day_minutes = body["school_day_minutes"]
    annual_review_due_date = body["annual_review_due_date"]
    # structural (priority 20)
    if not _is_int(school_day_minutes):
        raise_err(ERR_INVALID_REQUEST, "school_day_minutes must be an integer")
    if not isinstance(annual_review_due_date, str):
        raise_err(ERR_INVALID_REQUEST, "annual_review_due_date must be an ISO 8601 string")
    try:
        parse_iso_to_dt(annual_review_due_date)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "annual_review_due_date must be valid ISO 8601")
    # range (priority 21): school_day_minutes > 0
    if school_day_minutes <= 0:
        raise_err(ERR_INVALID_RANGE, "school_day_minutes must be > 0")

    obj = {
        "student_id": student_id,
        "school_day_minutes": school_day_minutes,
        "annual_review_due_date": annual_review_due_date,
        "status": "DRAFT",
        "lre_general_ed_pct": 100.0,
        "lre_setting": "FULL_INCLUSION",
        "activated_at": None,
        "meeting_held_by_user_id": None,
    }
    common_create(obj)
    store.ieps[obj["id"]] = obj
    return success_object(iep_view(obj), 201)


@app.route("/ieps", methods=["GET"])
def list_ieps():
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    limit, offset = pagination_params()
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    items = list(store.ieps.values())
    if student_id is not None:
        items = [i for i in items if i["student_id"] == student_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=sort_key)
    items, total = paginate(items, limit, offset)
    return success_array([iep_view(i) for i in items], limit, offset, total)


@app.route("/ieps/<iid>", methods=["GET"])
def get_iep(iid):
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    i = get_iep_or_404(iid)
    return success_object(iep_view(i), 200)


@app.route("/ieps/<iid>/hold-meeting", methods=["POST"])
def iep_hold_meeting(iid):
    uid, role = get_auth()
    require_role(role, ["CaseManager"])
    iep = get_iep_or_404(iid)
    # state (priority 30)
    if iep["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"IEP status is {iep['status']}, required DRAFT")
    # cross-entity guard (priority 41): student must be ELIGIBLE
    student = store.students.get(iep["student_id"])
    if student is None or student["eligibility_status"] != "ELIGIBLE":
        raise_err(ERR_STUDENT_NOT_ELIGIBLE, "Student eligibility_status is not ELIGIBLE")
    # side effect: PLACEMENT ConsentRequest (PENDING)
    cr = {
        "student_id": iep["student_id"],
        "iep_id": iep["id"],
        "consent_type": "PLACEMENT",
        "status": "PENDING",
        "decided_at": None,
    }
    common_create(cr)
    store.consent_requests[cr["id"]] = cr
    # record convening CaseManager
    iep["meeting_held_by_user_id"] = uid
    iep["status"] = "MEETING_HELD"
    bump_version(iep)
    return success_object(iep_view(iep), 200)


@app.route("/ieps/<iid>/activate", methods=["POST"])
def iep_activate(iid):
    uid, role = get_auth()
    require_role(role, ["SpecialEdAdmin"])
    iep = get_iep_or_404(iid)
    # segregation of duties (priority 3): activating SpecialEdAdmin must not be
    # the CaseManager recorded as having held the meeting.
    if iep.get("meeting_held_by_user_id") is not None and uid == iep["meeting_held_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "Activating SpecialEdAdmin must not be the convening CaseManager")
    # state (priority 30): from MEETING_HELD or AMENDMENT_PENDING
    if iep["status"] not in ("MEETING_HELD", "AMENDMENT_PENDING"):
        raise_err(ERR_INVALID_STATE,
                  f"IEP status is {iep['status']}, required MEETING_HELD or AMENDMENT_PENDING")
    # cross-entity guard (priority 42): PLACEMENT consent GRANTED
    cr = placement_consent_for_iep(iep["id"])
    if cr is None or cr["status"] != "GRANTED":
        raise_err(ERR_CONSENT_NOT_GRANTED, "PLACEMENT consent for this IEP is not GRANTED")
    # cross-entity guard (priority 45): no other ACTIVE IEP for the student
    for other in store.ieps.values():
        if other["id"] != iep["id"] and other["student_id"] == iep["student_id"] \
                and other["status"] == "ACTIVE":
            raise_err(ERR_ACTIVE_IEP_EXISTS, "Student already has an ACTIVE IEP")

    iep["activated_at"] = clock_now()
    iep["status"] = "ACTIVE"
    student = store.students.get(iep["student_id"])
    if student is not None:
        student["active_iep_id"] = iep["id"]
        bump_version(student)
    bump_version(iep)
    return success_object(iep_view(iep), 200)


@app.route("/ieps/<iid>/open-amendment", methods=["POST"])
def iep_open_amendment(iid):
    _, role = get_auth()
    require_role(role, ["CaseManager"])
    iep = get_iep_or_404(iid)
    body = get_json_body()
    # structural (priority 20): expected_iep_version required + integer
    require_fields(body, ["expected_iep_version"])
    expected = body["expected_iep_version"]
    if not _is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "expected_iep_version must be an integer")
    # state (priority 30): must be ACTIVE
    if iep["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"IEP status is {iep['status']}, required ACTIVE")
    # OCC (priority 31)
    if expected != int(iep["version"]):
        raise_err(ERR_STALE_VERSION,
                  f"expected_iep_version {expected} does not match current {iep['version']}")
    iep["status"] = "AMENDMENT_PENDING"
    student = store.students.get(iep["student_id"])
    if student is not None:
        student["active_iep_id"] = None
        bump_version(student)
    bump_version(iep)
    return success_object(iep_view(iep), 200)


@app.route("/ieps/<iid>/archive", methods=["POST"])
def iep_archive(iid):
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin"])
    iep = get_iep_or_404(iid)
    # state (priority 30): must be ACTIVE
    if iep["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"IEP status is {iep['status']}, required ACTIVE")
    iep["status"] = "ARCHIVED"
    student = store.students.get(iep["student_id"])
    if student is not None:
        student["active_iep_id"] = None
        bump_version(student)
    # cascade: ACTIVE Goals -> DISCONTINUED
    for g in store.goals.values():
        if g["iep_id"] == iep["id"] and g["status"] == "ACTIVE":
            g["status"] = "DISCONTINUED"
            bump_version(g)
    # cascade: ACTIVE RelatedServices -> DISCONTINUED
    for r in store.related_services.values():
        if r["iep_id"] == iep["id"] and r["status"] == "ACTIVE":
            r["status"] = "DISCONTINUED"
            bump_version(r)
    bump_version(iep)
    return success_object(iep_view(iep), 200)


# ============================================================
# Goals
# ============================================================

@app.route("/goals", methods=["POST"])
def create_goal():
    _, role = get_auth()
    require_role(role, ["CaseManager"])
    body = get_json_body()
    # FK existence (priority 11) precedes structural body validation (priority 20)
    # per PRD §2.8. The FK field itself must be present to resolve it; only after
    # the body-FK existence check do we validate the remaining required fields.
    require_fields(body, ["iep_id"])
    iep_id = body["iep_id"]
    get_iep_or_404_fk(iep_id)

    require_fields(body, ["domain", "baseline_value", "target_value"])
    domain = body["domain"]
    baseline = body["baseline_value"]
    target = body["target_value"]
    # structural (priority 20)
    if domain not in GOAL_DOMAINS:
        raise_err(ERR_INVALID_REQUEST, "domain not in allowed set")
    if not _is_number(baseline):
        raise_err(ERR_INVALID_REQUEST, "baseline_value must be a number")
    if not _is_number(target):
        raise_err(ERR_INVALID_REQUEST, "target_value must be a number")
    # range (priority 21): baseline >= 0 and target strictly > baseline
    if baseline < 0:
        raise_err(ERR_INVALID_RANGE, "baseline_value must be >= 0")
    if not (target > baseline):
        raise_err(ERR_INVALID_RANGE, "target_value must be strictly greater than baseline_value")

    obj = {
        "iep_id": iep_id,
        "domain": domain,
        "baseline_value": baseline,
        "target_value": target,
        "status": "ACTIVE",
        "latest_progress_pct": 0.0,
        "cumulative_progress_pct": 0.0,
    }
    common_create(obj)
    store.goals[obj["id"]] = obj
    return success_object(goal_view(obj), 201)


@app.route("/goals", methods=["GET"])
def list_goals():
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    limit, offset = pagination_params()
    iep_id = request.args.get("iep_id")
    status = request.args.get("status")
    items = list(store.goals.values())
    if iep_id is not None:
        items = [g for g in items if g["iep_id"] == iep_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    items.sort(key=sort_key)
    items, total = paginate(items, limit, offset)
    return success_array([goal_view(g) for g in items], limit, offset, total)


@app.route("/goals/<gid>", methods=["GET"])
def get_goal(gid):
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    g = get_goal_or_404(gid)
    return success_object(goal_view(g), 200)


@app.route("/goals/<gid>/discontinue", methods=["POST"])
def goal_discontinue(gid):
    _, role = get_auth()
    require_role(role, ["CaseManager"])
    g = get_goal_or_404(gid)
    # state (priority 30)
    if g["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"Goal status is {g['status']}, required ACTIVE")
    g["status"] = "DISCONTINUED"
    bump_version(g)
    return success_object(goal_view(g), 200)


# ============================================================
# Progress Reports
# ============================================================

@app.route("/progress-reports", methods=["POST"])
def create_progress_report():
    _, role = get_auth()
    require_role(role, ["CaseManager"])
    body = get_json_body()
    # FK existence (priority 11) precedes structural validation (priority 20) per PRD §2.8
    require_fields(body, ["goal_id"])
    goal_id = body["goal_id"]
    goal = get_goal_or_404_fk(goal_id)

    require_fields(body, ["reporting_period", "measured_value"])
    reporting_period = body["reporting_period"]
    measured_value = body["measured_value"]
    # structural (priority 20)
    if not _is_int(reporting_period):
        raise_err(ERR_INVALID_REQUEST, "reporting_period must be an integer")
    if not _is_number(measured_value):
        raise_err(ERR_INVALID_REQUEST, "measured_value must be a number")
    # range (priority 21): reporting_period 1..4, measured_value >= 0
    if reporting_period < 1 or reporting_period > 4:
        raise_err(ERR_INVALID_RANGE, "reporting_period must be in 1..4")
    if measured_value < 0:
        raise_err(ERR_INVALID_RANGE, "measured_value must be >= 0")

    # ProgressReport is immutable: only id + created_at (no updated_at/version).
    obj = {
        "goal_id": goal_id,
        "reporting_period": reporting_period,
        "measured_value": measured_value,
    }
    obj["id"] = gen_id()
    obj["created_at"] = clock_now()
    obj["_seq"] = store.next_seq()
    store.progress_reports[obj["id"]] = obj

    # recompute goal progress + bubble-up to MET
    recompute_goal_progress(goal)
    if goal["status"] == "ACTIVE" and goal["cumulative_progress_pct"] >= 100.0:
        goal["status"] = "MET"
    bump_version(goal)
    return success_object(progress_report_view(obj), 201)


@app.route("/progress-reports", methods=["GET"])
def list_progress_reports():
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    limit, offset = pagination_params()
    goal_id = request.args.get("goal_id")
    items = list(store.progress_reports.values())
    if goal_id is not None:
        items = [p for p in items if p["goal_id"] == goal_id]
    items.sort(key=sort_key)
    items, total = paginate(items, limit, offset)
    return success_array([progress_report_view(p) for p in items], limit, offset, total)


@app.route("/progress-reports/<pid>", methods=["GET"])
def get_progress_report(pid):
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    p = get_progress_report_or_404(pid)
    return success_object(progress_report_view(p), 200)


# ============================================================
# Related Services
# ============================================================

@app.route("/related-services", methods=["POST"])
def create_related_service():
    _, role = get_auth()
    require_role(role, ["CaseManager"])
    body = get_json_body()
    # FK existence (priority 11) precedes structural validation (priority 20) per PRD §2.8
    require_fields(body, ["iep_id"])
    iep_id = body["iep_id"]
    iep = get_iep_or_404_fk(iep_id)

    require_fields(body, ["service_type", "minutes_per_week",
                          "delivered_in_general_ed", "expected_iep_version"])
    service_type = body["service_type"]
    minutes_per_week = body["minutes_per_week"]
    delivered = body["delivered_in_general_ed"]
    expected = body["expected_iep_version"]
    # structural (priority 20)
    if service_type not in SERVICE_TYPES:
        raise_err(ERR_INVALID_REQUEST, "service_type must be OT, PT, or SPEECH")
    if not _is_int(minutes_per_week):
        raise_err(ERR_INVALID_REQUEST, "minutes_per_week must be an integer")
    if not isinstance(delivered, bool):
        raise_err(ERR_INVALID_REQUEST, "delivered_in_general_ed must be a boolean")
    if not _is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "expected_iep_version must be an integer")
    # range (priority 21): minutes_per_week > 0
    if minutes_per_week <= 0:
        raise_err(ERR_INVALID_RANGE, "minutes_per_week must be > 0")
    # OCC (priority 31) — no state transition precondition on the IEP for adding a service
    if expected != int(iep["version"]):
        raise_err(ERR_STALE_VERSION,
                  f"expected_iep_version {expected} does not match current {iep['version']}")

    obj = {
        "iep_id": iep_id,
        "service_type": service_type,
        "minutes_per_week": minutes_per_week,
        "delivered_in_general_ed": delivered,
        "status": "ACTIVE",
    }
    common_create(obj)
    store.related_services[obj["id"]] = obj
    # recompute parent IEP LRE + bump IEP version
    recompute_iep_lre(iep)
    bump_version(iep)
    return success_object(related_service_view(obj), 201)


@app.route("/related-services", methods=["GET"])
def list_related_services():
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    limit, offset = pagination_params()
    iep_id = request.args.get("iep_id")
    status = request.args.get("status")
    items = list(store.related_services.values())
    if iep_id is not None:
        items = [r for r in items if r["iep_id"] == iep_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=sort_key)
    items, total = paginate(items, limit, offset)
    return success_array([related_service_view(r) for r in items], limit, offset, total)


@app.route("/related-services/<rid>", methods=["GET"])
def get_related_service(rid):
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    r = get_related_service_or_404(rid)
    return success_object(related_service_view(r), 200)


@app.route("/related-services/<rid>", methods=["DELETE"])
def delete_related_service(rid):
    _, role = get_auth()
    require_role(role, ["CaseManager"])
    r = get_related_service_or_404(rid)
    body = get_json_body()
    # DELETE requests cannot carry a JSON body through the standard test client,
    # which encodes the payload as query params; accept expected_iep_version from
    # either source so the field is honored however it arrives.
    if "expected_iep_version" not in body and "expected_iep_version" in request.args:
        raw = request.args.get("expected_iep_version")
        try:
            body["expected_iep_version"] = int(raw)
        except (TypeError, ValueError):
            body["expected_iep_version"] = raw
    # structural (priority 20): expected_iep_version required + integer
    require_fields(body, ["expected_iep_version"])
    expected = body["expected_iep_version"]
    if not _is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "expected_iep_version must be an integer")
    # state (priority 30): must be ACTIVE
    if r["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"RelatedService status is {r['status']}, required ACTIVE")
    iep = store.ieps.get(r["iep_id"])
    # OCC (priority 31)
    if iep is not None and expected != int(iep["version"]):
        raise_err(ERR_STALE_VERSION,
                  f"expected_iep_version {expected} does not match current {iep['version']}")
    r["status"] = "DISCONTINUED"
    bump_version(r)
    if iep is not None:
        recompute_iep_lre(iep)
        bump_version(iep)
    return success_object(related_service_view(r), 200)


# ============================================================
# Transition Plans
# ============================================================

@app.route("/transition-plans", methods=["POST"])
def create_transition_plan():
    _, role = get_auth()
    require_role(role, ["CaseManager"])
    body = get_json_body()
    # FK existence (priority 11) precedes structural validation (priority 20) per PRD §2.8
    require_fields(body, ["iep_id"])
    iep_id = body["iep_id"]
    iep = get_iep_or_404_fk(iep_id)

    require_fields(body, ["postsecondary_goal", "services_summary"])
    postsecondary_goal = body["postsecondary_goal"]
    services_summary = body["services_summary"]
    # structural (priority 20)
    if not isinstance(postsecondary_goal, str):
        raise_err(ERR_INVALID_REQUEST, "postsecondary_goal must be a string")
    if not isinstance(services_summary, str):
        raise_err(ERR_INVALID_REQUEST, "services_summary must be a string")
    # business temporal (priority 44): student age >= 16 at server clock
    student = store.students.get(iep["student_id"])
    if student is not None:
        age = full_years_between(student["date_of_birth"], clock_now())
        if age < TRANSITION_AGE:
            raise_err(ERR_TRANSITION_AGE_NOT_MET,
                      f"Student age {age} is below transition-planning age {TRANSITION_AGE}")

    obj = {
        "iep_id": iep_id,
        "postsecondary_goal": postsecondary_goal,
        "services_summary": services_summary,
        "status": "DRAFT",
    }
    common_create(obj)
    store.transition_plans[obj["id"]] = obj
    return success_object(transition_plan_view(obj), 201)


@app.route("/transition-plans", methods=["GET"])
def list_transition_plans():
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    limit, offset = pagination_params()
    iep_id = request.args.get("iep_id")
    items = list(store.transition_plans.values())
    if iep_id is not None:
        items = [t for t in items if t["iep_id"] == iep_id]
    items.sort(key=sort_key)
    items, total = paginate(items, limit, offset)
    return success_array([transition_plan_view(t) for t in items], limit, offset, total)


@app.route("/transition-plans/<tid>", methods=["GET"])
def get_transition_plan(tid):
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"])
    t = get_transition_plan_or_404(tid)
    return success_object(transition_plan_view(t), 200)


@app.route("/transition-plans/<tid>/adopt", methods=["POST"])
def transition_plan_adopt(tid):
    _, role = get_auth()
    require_role(role, ["CaseManager"])
    t = get_transition_plan_or_404(tid)
    # state (priority 30)
    if t["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"TransitionPlan status is {t['status']}, required DRAFT")
    # cross-entity guard (priority 43): parent IEP must be ACTIVE
    iep = store.ieps.get(t["iep_id"])
    if iep is None or iep["status"] != "ACTIVE":
        raise_err(ERR_IEP_NOT_ACTIVE, "Parent IEP is not ACTIVE")
    t["status"] = "ADOPTED"
    bump_version(t)
    return success_object(transition_plan_view(t), 200)


# ============================================================
# Test-driving clock
# ============================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_auth()
    require_role(role, ["SpecialEdAdmin"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    to_iso = body["to_iso8601"]
    if not isinstance(to_iso, str):
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 string")
    try:
        parse_iso_to_dt(to_iso)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be valid ISO 8601")
    store.current_utc = to_iso
    return success_object(None, 200)


# ============================================================
# Health
# ============================================================

@app.route("/", methods=["GET"])
def root():
    return success_object({"service": "special-education-iep"}, 200)


@app.route("/healthz", methods=["GET"])
def healthz():
    return success_object({"ok": True}, 200)


# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
