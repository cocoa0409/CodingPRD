"""Census & Field-Survey Operations API — Python + Flask reference implementation.

Storage is in-memory only (see store.py). Nothing is seeded at startup; every
entity is built by the test suite through the declared endpoints.

Every behavioral rule here traces to a sentence in PRD.md. Section references in
comments point at the governing PRD paragraph.
"""

import math
import os
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, jsonify

import store

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Enumerations & constants (PRD §2.10, §3.x)
# ---------------------------------------------------------------------------
LANGS = {"EN", "ES", "ZH", "VI"}
ROLES = {"SurveyAdmin", "FieldSupervisor", "Enumerator", "QCReviewer"}
ATTEMPT_MODES = {"IN_PERSON", "PHONE"}
DISPOSITIONS = {"NO_ONE_HOME", "REFUSED", "VACANT", "LANGUAGE_BARRIER",
                "CONTACT_MADE", "APPOINTMENT_SET"}
LINE_TYPES = {"STIPEND", "MILEAGE", "BONUS"}
REINTERVIEW_REASONS = {"RANDOM_SAMPLE", "HIGH_FRAUD_SCORE", "MANUAL"}
FINALIZE_OUTCOMES = {"CONFIRMED", "DISCREPANT", "FRAUD"}

# fraud scoring constants (PRD §3.7 / scaffold §1.3)
FLAG_WEIGHT = 12
GPS_TOLERANCE_M = 50
GPS_STEP = 5
DURATION_FLOOR_MIN = 8
SHORT_DURATION_PENALTY = 25

# scheduling / cooldown (PRD §3.5)
REST_BUFFER_MINUTES = 240

# overtime (PRD §3.9)
OT_PREMIUM_RATE = Decimal("0.5")


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Envelope helpers (PRD §2.2)
# ---------------------------------------------------------------------------
def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth & RBAC (PRD §2.1, §2.11)
# ---------------------------------------------------------------------------
def require(*allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers are required and must be valid.")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       "Role is not permitted to perform this operation.")
    return uid, role


# ---------------------------------------------------------------------------
# Body / field validation helpers (PRD §2.11 priority 5 -> ERR_VALIDATION)
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object.")
    return body


def _fail_validation(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        _fail_validation(f"'{key}' must be a non-empty string.")
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        _fail_validation(f"'{key}' must be one of {sorted(allowed)}.")
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int(body, key, minv=None, maxv=None):
    v = body.get(key)
    if not is_int(v):
        _fail_validation(f"'{key}' must be an integer.")
    if minv is not None and v < minv:
        _fail_validation(f"'{key}' must be >= {minv}.")
    if maxv is not None and v > maxv:
        _fail_validation(f"'{key}' must be <= {maxv}.")
    return v


def opt_int(body, key, default, minv=None, maxv=None):
    if key not in body or body.get(key) is None:
        return default
    return req_int(body, key, minv, maxv)


def req_number(body, key, minv=None):
    v = body.get(key)
    if not is_number(v):
        _fail_validation(f"'{key}' must be a number.")
    if minv is not None and v < minv:
        _fail_validation(f"'{key}' must be >= {minv}.")
    return v


def opt_number(body, key, default, minv=None):
    if key not in body or body.get(key) is None:
        return default
    return req_number(body, key, minv)


def parse_dt(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        _fail_validation(f"'{key}' must be an ISO 8601 datetime string.")
    t = v.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _fail_validation(f"'{key}' must be a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Entity lifecycle helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def new_entity(**fields):
    ts = now_iso()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    ent.update(fields)
    return ent


def touch(entity):
    """A mutation refreshes updated_at and increments version (PRD §2.4)."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Lookup helpers (PRD §2.6 — path existence left-to-right)
# ---------------------------------------------------------------------------
def get_project(pid):
    p = store.projects.get(pid)
    if p is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "Survey project not found.")
    return p


def get_area(aid):
    a = store.areas.get(aid)
    if a is None:
        raise ApiError("ERR_AREA_NOT_FOUND", 404, "Assignment area not found.")
    return a


def get_case(cid):
    c = store.cases.get(cid)
    if c is None:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "Case not found.")
    return c


def get_enumerator(eid, err="ERR_ENUMERATOR_NOT_FOUND"):
    e = store.enumerators.get(eid)
    if e is None:
        raise ApiError(err, 404, "Enumerator not found.")
    return e


def get_attempt(aid):
    a = store.attempts.get(aid)
    if a is None:
        raise ApiError("ERR_ATTEMPT_NOT_FOUND", 404, "Attempt not found.")
    return a


def get_response(rid):
    r = store.responses.get(rid)
    if r is None:
        raise ApiError("ERR_RESPONSE_NOT_FOUND", 404, "Response not found.")
    return r


def get_reinterview(rid):
    r = store.reinterviews.get(rid)
    if r is None:
        raise ApiError("ERR_REINTERVIEW_NOT_FOUND", 404, "Reinterview not found.")
    return r


def get_pay_period(pid):
    p = store.pay_periods.get(pid)
    if p is None:
        raise ApiError("ERR_PAY_PERIOD_NOT_FOUND", 404, "Pay period not found.")
    return p


def get_pay_line(lid):
    l = store.pay_lines.get(lid)
    if l is None:
        raise ApiError("ERR_PAY_LINE_NOT_FOUND", 404, "Pay line not found.")
    return l


def area_of_case(case):
    return store.areas[case["assignment_area_id"]]


def project_of_area(area):
    return store.projects[area["survey_project_id"]]


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def paginate(items):
    """items: list already sorted by creation order. Returns (page, limit, offset, total)."""
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
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sorted_by_seq(items):
    return sorted(items, key=lambda e: e["_seq"])


def list_out(items):
    ordered = sorted_by_seq(items)
    page, limit, offset, total = paginate(ordered)
    return ok_array([serialize(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Money / rate helpers (PRD §2.8)
# ---------------------------------------------------------------------------
def rhu_cents(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def coverage_rate(numerator, denominator):
    if denominator == 0:
        return 0.0
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Area recomputation (PRD §2.5, §2.9, §3.2) — caller is responsible for touch()
# ---------------------------------------------------------------------------
def recompute_area(area):
    cs = [c for c in store.cases.values() if c["assignment_area_id"] == area["id"]]
    total = len(cs)
    pending = sum(1 for c in cs if c["status"] in ("UNASSIGNED", "ASSIGNED"))
    in_prog = sum(1 for c in cs if c["status"] == "IN_PROGRESS")
    complete = sum(1 for c in cs if c["status"] == "COMPLETE")
    refused = sum(1 for c in cs if c["status"] == "REFUSED")
    vacant = sum(1 for c in cs if c["status"] == "VACANT")
    max_att = sum(1 for c in cs if c["status"] == "MAX_ATTEMPTS")

    area["total_case_count"] = total
    area["pending_case_count"] = pending
    area["in_progress_case_count"] = in_prog
    area["complete_case_count"] = complete
    area["refused_case_count"] = refused
    area["vacant_case_count"] = vacant
    area["max_attempts_case_count"] = max_att

    area["projected_coverage_rate"] = coverage_rate(complete + in_prog, total)
    area["final_coverage_rate"] = coverage_rate(complete, total)

    # Budget ledger: sum of pay_committed over LOGGED (non-cancelled) attempts.
    committed = 0
    case_ids = {c["id"] for c in cs}
    for at in store.attempts.values():
        if at["case_id"] in case_ids and at["status"] == "LOGGED":
            committed += at["pay_committed_cents"]
    area["budget_committed_cents"] = committed
    area["budget_remaining_cents"] = area["budget_cents"] - committed


# ---------------------------------------------------------------------------
# Enumerator / pay-period derived figures (PRD §3.3, §3.9)
# ---------------------------------------------------------------------------
def recompute_enumerator_pay(enum):
    lines = [l for l in store.pay_lines.values() if l["enumerator_id"] == enum["id"]]
    gross = sum(l["amount_cents"] for l in lines)              # every line ever created
    reversed_ = sum(l["amount_cents"] for l in lines if l["status"] == "REVERSED")
    enum["gross_pay_cents"] = gross
    enum["reversed_pay_cents"] = reversed_
    enum["net_pay_cents"] = gross - reversed_


def recompute_period_provisional(period):
    total = sum(l["amount_cents"] for l in store.pay_lines.values()
                if l["pay_period_id"] == period["id"] and l["status"] == "ACCRUED")
    period["provisional_total_cents"] = total


def active_assignment_of_case(case):
    for a in store.assignments.values():
        if a["case_id"] == case["id"] and a["status"] == "ACTIVE":
            return a
    return None


def release_active_assignment(case):
    a = active_assignment_of_case(case)
    if a is not None:
        a["status"] = "RELEASED"
        touch(a)


# ===========================================================================
# SurveyProject
# ===========================================================================
@app.route("/survey-projects", methods=["POST"])
def create_project():
    require("SurveyAdmin")
    body = get_body()
    name = req_str(body, "name")
    region_code = req_str(body, "region_code")
    default_language = req_enum(body, "default_language", LANGS)
    supported = body.get("supported_languages")
    if not isinstance(supported, list) or len(supported) == 0 or \
            any(x not in LANGS for x in supported):
        _fail_validation("'supported_languages' must be a non-empty list of valid language codes.")
    fraud_threshold = opt_int(body, "fraud_score_threshold", 60, 0, 100)
    max_attempts = opt_int(body, "max_attempts", 6, 1, None)
    mileage_rate = opt_int(body, "mileage_rate_cents_per_mile", 67, 0, None)

    # Language admissibility (PRD §2.10, priority 6)
    if default_language not in supported:
        raise ApiError("ERR_UNSUPPORTED_LANGUAGE", 400,
                       "default_language must be a member of supported_languages.")

    p = new_entity(
        name=name, region_code=region_code, default_language=default_language,
        supported_languages=list(supported), fraud_score_threshold=fraud_threshold,
        max_attempts=max_attempts, mileage_rate_cents_per_mile=mileage_rate,
        status="PLANNING",
    )
    store.projects[p["id"]] = p
    return ok_object(serialize(p), 201)


@app.route("/survey-projects/<pid>", methods=["GET"])
def get_project_route(pid):
    require()
    return ok_object(serialize(get_project(pid)))


@app.route("/survey-projects/<pid>/open", methods=["POST"])
def open_project(pid):
    require("SurveyAdmin")
    p = get_project(pid)
    if p["status"] != "PLANNING":
        raise ApiError("ERR_PROJECT_INVALID_STATE", 409, "Project is not in PLANNING.")
    p["status"] = "IN_FIELD"
    touch(p)
    return ok_object(serialize(p))


@app.route("/survey-projects/<pid>/close", methods=["POST"])
def close_project(pid):
    require("SurveyAdmin")
    p = get_project(pid)
    if p["status"] != "IN_FIELD":
        raise ApiError("ERR_PROJECT_INVALID_STATE", 409, "Project is not in IN_FIELD.")
    p["status"] = "CLOSED"
    touch(p)
    return ok_object(serialize(p))


# ===========================================================================
# AssignmentArea
# ===========================================================================
@app.route("/survey-projects/<pid>/assignment-areas", methods=["POST"])
def create_area(pid):
    require("SurveyAdmin")
    p = get_project(pid)
    body = get_body()
    area_code = req_str(body, "area_code")
    budget_cents = req_int(body, "budget_cents", 0, None)
    a = new_entity(
        survey_project_id=p["id"], area_code=area_code, budget_cents=budget_cents,
        budget_committed_cents=0, budget_remaining_cents=budget_cents,
        total_case_count=0, pending_case_count=0, in_progress_case_count=0,
        complete_case_count=0, refused_case_count=0, vacant_case_count=0,
        max_attempts_case_count=0, projected_coverage_rate=0.0,
        final_coverage_rate=0.0, status="DRAFT",
    )
    store.areas[a["id"]] = a
    return ok_object(serialize(a), 201)


@app.route("/survey-projects/<pid>/assignment-areas", methods=["GET"])
def list_areas(pid):
    require()
    p = get_project(pid)
    items = [a for a in store.areas.values() if a["survey_project_id"] == p["id"]]
    return list_out(items)


@app.route("/assignment-areas/<aid>", methods=["GET"])
def get_area_route(aid):
    require()
    return ok_object(serialize(get_area(aid)))


@app.route("/assignment-areas/<aid>/open", methods=["POST"])
def open_area(aid):
    require("SurveyAdmin")
    a = get_area(aid)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_AREA_INVALID_STATE", 409, "Area is not in DRAFT.")
    project = project_of_area(a)
    if project["status"] != "IN_FIELD":
        raise ApiError("ERR_PROJECT_NOT_IN_FIELD", 409,
                       "Parent project must be IN_FIELD to open an area.")
    a["status"] = "IN_FIELD"
    touch(a)
    return ok_object(serialize(a))


@app.route("/assignment-areas/<aid>/freeze", methods=["POST"])
def freeze_area(aid):
    require("SurveyAdmin")
    a = get_area(aid)
    if a["status"] != "IN_FIELD":
        raise ApiError("ERR_AREA_INVALID_STATE", 409, "Area is not in IN_FIELD.")
    a["status"] = "FROZEN"
    touch(a)
    return ok_object(serialize(a))


@app.route("/assignment-areas/<aid>/unfreeze", methods=["POST"])
def unfreeze_area(aid):
    require("SurveyAdmin")
    a = get_area(aid)
    if a["status"] != "FROZEN":
        raise ApiError("ERR_AREA_INVALID_STATE", 409, "Area is not in FROZEN.")
    a["status"] = "IN_FIELD"
    touch(a)
    return ok_object(serialize(a))


@app.route("/assignment-areas/<aid>/coverage-report", methods=["GET"])
def coverage_report(aid):
    require()
    a = get_area(aid)
    data = {
        "area_id": a["id"],
        "total_case_count": a["total_case_count"],
        "complete_case_count": a["complete_case_count"],
        "in_progress_case_count": a["in_progress_case_count"],
        "projected_coverage_rate": a["projected_coverage_rate"],
        "final_coverage_rate": a["final_coverage_rate"],
    }
    return ok_object(data)


# ===========================================================================
# Case
# ===========================================================================
@app.route("/assignment-areas/<aid>/cases", methods=["POST"])
def create_case(aid):
    require("SurveyAdmin")
    a = get_area(aid)
    project = project_of_area(a)
    body = get_body()
    address = req_str(body, "address")
    respondent_language = req_enum(body, "respondent_language", LANGS)
    # Language admissibility against project's supported list (PRD §2.10, priority 6)
    if respondent_language not in project["supported_languages"]:
        raise ApiError("ERR_UNSUPPORTED_LANGUAGE", 400,
                       "respondent_language must be one of the project's supported_languages.")
    c = new_entity(
        assignment_area_id=a["id"], address=address,
        respondent_language=respondent_language, assigned_enumerator_id=None,
        attempt_count=0, status="UNASSIGNED",
    )
    store.cases[c["id"]] = c
    recompute_area(a)
    touch(a)
    return ok_object(serialize(c), 201)


@app.route("/assignment-areas/<aid>/cases", methods=["GET"])
def list_cases(aid):
    require()
    a = get_area(aid)
    items = [c for c in store.cases.values() if c["assignment_area_id"] == a["id"]]
    return list_out(items)


@app.route("/cases/<cid>", methods=["GET"])
def get_case_route(cid):
    require()
    return ok_object(serialize(get_case(cid)))


@app.route("/cases/<cid>/assignments", methods=["POST"])
def create_assignment(cid):
    require("FieldSupervisor")
    case = get_case(cid)
    body = get_body()
    # priority 4: body FK existence
    enumerator_id = body.get("enumerator_id")
    if not isinstance(enumerator_id, str) or enumerator_id == "":
        _fail_validation("'enumerator_id' is required.")
    enum = get_enumerator(enumerator_id)  # ERR_ENUMERATOR_NOT_FOUND
    # priority 5: validation of expected_case_version
    expected = req_int(body, "expected_case_version")
    # priority 7: OCC
    if expected != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION", 412,
                       "expected_case_version does not match the case's current version.")
    # priority 8: legal source state (area IN_FIELD; case UNASSIGNED/ASSIGNED)
    area = area_of_case(case)
    if area["status"] != "IN_FIELD":
        raise ApiError("ERR_AREA_NOT_IN_FIELD", 409, "Area must be IN_FIELD for assignment.")
    if case["status"] not in ("UNASSIGNED", "ASSIGNED"):
        raise ApiError("ERR_CASE_INVALID_STATE", 409,
                       "Case is not in a legal state for assignment.")
    # priority 10: target enumerator ACTIVE
    if enum["status"] != "ACTIVE":
        raise ApiError("ERR_ENUMERATOR_NOT_ACTIVE", 409,
                       "Target enumerator is not ACTIVE.")

    # Reassignment: supersede prior ACTIVE assignment (PRD §3.4)
    prior = active_assignment_of_case(case)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    assignment = new_entity(case_id=case["id"], enumerator_id=enum["id"], status="ACTIVE")
    store.assignments[assignment["id"]] = assignment

    case["assigned_enumerator_id"] = enum["id"]
    if case["status"] == "UNASSIGNED":
        case["status"] = "ASSIGNED"
    touch(case)  # increments Case.version by 1
    # pending_case_count unchanged (both UNASSIGNED and ASSIGNED are pending);
    # no area count change, so the area is not mutated here.
    return ok_object(serialize(assignment), 201)


@app.route("/cases/<cid>/assignments", methods=["GET"])
def list_case_assignments(cid):
    require()
    case = get_case(cid)
    items = [a for a in store.assignments.values() if a["case_id"] == case["id"]]
    return list_out(items)


# ===========================================================================
# Enumerator
# ===========================================================================
@app.route("/survey-projects/<pid>/enumerators", methods=["POST"])
def create_enumerator(pid):
    require("SurveyAdmin")
    p = get_project(pid)
    body = get_body()
    full_name = req_str(body, "full_name")
    languages = body.get("languages")
    if not isinstance(languages, list) or len(languages) == 0 or \
            any(x not in LANGS for x in languages):
        _fail_validation("'languages' must be a non-empty list of valid language codes.")
    hourly_rate = req_int(body, "hourly_rate_cents", 0, None)
    e = new_entity(
        survey_project_id=p["id"], full_name=full_name, languages=list(languages),
        hourly_rate_cents=hourly_rate, gross_pay_cents=0, reversed_pay_cents=0,
        net_pay_cents=0, fraud_flag=False, status="APPLICANT",
    )
    store.enumerators[e["id"]] = e
    return ok_object(serialize(e), 201)


@app.route("/survey-projects/<pid>/enumerators", methods=["GET"])
def list_enumerators(pid):
    require()
    p = get_project(pid)
    items = [e for e in store.enumerators.values() if e["survey_project_id"] == p["id"]]
    return list_out(items)


@app.route("/enumerators/<eid>", methods=["GET"])
def get_enumerator_route(eid):
    require()
    return ok_object(serialize(get_enumerator(eid)))


def _enumerator_transition(eid, from_state, to_state):
    e = get_enumerator(eid)
    if e["status"] != from_state:
        raise ApiError("ERR_ENUMERATOR_INVALID_STATE", 409,
                       f"Enumerator is not in {from_state}.")
    e["status"] = to_state
    touch(e)
    return e


@app.route("/enumerators/<eid>/hire", methods=["POST"])
def hire_enumerator(eid):
    require("SurveyAdmin")
    return ok_object(serialize(_enumerator_transition(eid, "APPLICANT", "HIRED")))


@app.route("/enumerators/<eid>/activate", methods=["POST"])
def activate_enumerator(eid):
    require("SurveyAdmin")
    return ok_object(serialize(_enumerator_transition(eid, "HIRED", "ACTIVE")))


@app.route("/enumerators/<eid>/suspend", methods=["POST"])
def suspend_enumerator(eid):
    require("SurveyAdmin")
    e = get_enumerator(eid)
    if e["status"] != "ACTIVE":
        raise ApiError("ERR_ENUMERATOR_INVALID_STATE", 409, "Enumerator is not in ACTIVE.")
    e["status"] = "SUSPENDED"
    touch(e)
    # Cascade: release ACTIVE assignments; clear affected cases' assigned_enumerator_id (PRD §3.3)
    for a in store.assignments.values():
        if a["enumerator_id"] == e["id"] and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            touch(a)
            case = store.cases.get(a["case_id"])
            if case is not None and case["assigned_enumerator_id"] == e["id"]:
                case["assigned_enumerator_id"] = None
                touch(case)
    return ok_object(serialize(e))


@app.route("/enumerators/<eid>/reinstate", methods=["POST"])
def reinstate_enumerator(eid):
    require("SurveyAdmin")
    return ok_object(serialize(_enumerator_transition(eid, "SUSPENDED", "ACTIVE")))


@app.route("/enumerators/<eid>/case-assignments", methods=["GET"])
def list_enumerator_assignments(eid):
    require()
    e = get_enumerator(eid)
    items = [a for a in store.assignments.values() if a["enumerator_id"] == e["id"]]
    return list_out(items)


@app.route("/enumerators/<eid>/pay-lines", methods=["GET"])
def list_enumerator_pay_lines(eid):
    require()
    e = get_enumerator(eid)
    items = [l for l in store.pay_lines.values() if l["enumerator_id"] == e["id"]]
    return list_out(items)


# ===========================================================================
# Attempt (PRD §3.5, §3.6)
# ===========================================================================
def windows_overlap(s1, e1, s2, e2):
    """Half-open [start, end) overlap. Adjacency (end==start) does not overlap."""
    return s1 < e2 and s2 < e1


@app.route("/cases/<cid>/attempts", methods=["POST"])
def create_attempt(cid):
    uid, role = require("Enumerator")
    case = get_case(cid)
    area = area_of_case(case)
    project = project_of_area(area)
    body = get_body()

    # priority 5: structural validation
    mode = req_enum(body, "mode", ATTEMPT_MODES)
    window_start = parse_dt(body, "window_start")
    window_end = parse_dt(body, "window_end")
    if not (window_end > window_start):
        _fail_validation("window_end must be strictly after window_start.")
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    mileage_miles = opt_number(body, "mileage_miles", 0, 0)

    # priority 8 (area portion): area IN_FIELD and not frozen
    if area["status"] == "FROZEN":
        raise ApiError("ERR_AREA_FROZEN", 409, "Area is FROZEN; attempts are blocked.")
    if area["status"] != "IN_FIELD":
        raise ApiError("ERR_AREA_NOT_IN_FIELD", 409, "Area must be IN_FIELD for attempts.")

    # priority 9: ownership (assigned_enumerator_id retained through terminal closes)
    if case["assigned_enumerator_id"] != uid:
        raise ApiError("ERR_NOT_ASSIGNED_ENUMERATOR", 403,
                       "Acting enumerator is not the case's assigned enumerator.")

    # priority 11: max-attempts boundary — evaluated before generic case-state (PRD §2.11)
    if case["status"] == "MAX_ATTEMPTS" or case["attempt_count"] >= project["max_attempts"]:
        raise ApiError("ERR_MAX_ATTEMPTS_REACHED", 409,
                       "Case has reached the maximum number of attempts.")
    # generic legal source state for the attempt
    if case["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        raise ApiError("ERR_CASE_INVALID_STATE", 409,
                       "Case is not in a legal state for a new attempt.")

    # priority 12: enumerator schedule conflict (same enumerator, all LOGGED, any case)
    for at in store.attempts.values():
        if at["status"] == "LOGGED" and at["acting_enumerator_id"] == uid:
            if windows_overlap(window_start, window_end, at["_ws"], at["_we"]):
                raise ApiError("ERR_ENUMERATOR_SCHEDULE_CONFLICT", 409,
                               "Attempt window overlaps another logged attempt by this enumerator.")

    # priority 13: case contact cooldown (same case, all LOGGED, 240-min gap)
    buffer_seconds = REST_BUFFER_MINUTES * 60
    for at in store.attempts.values():
        if at["status"] == "LOGGED" and at["case_id"] == case["id"]:
            if window_start >= at["_ws"]:
                earlier_end, later_start = at["_we"], window_start
            else:
                earlier_end, later_start = window_end, at["_ws"]
            gap = (later_start - earlier_end).total_seconds()
            if gap < buffer_seconds:
                raise ApiError("ERR_CASE_CONTACT_COOLDOWN", 409,
                               "Attempt window is within the contact cooldown of another attempt on the case.")

    # Attempt pay commitment (PRD §3.6) — round each component independently.
    attempt_minutes = int(math.floor((window_end - window_start).total_seconds() / 60))
    hourly_rate = store.enumerators[uid]["hourly_rate_cents"]
    stipend_cents = rhu_cents(Decimal(hourly_rate) * attempt_minutes / Decimal(60))
    if mode == "IN_PERSON":
        mileage_cents = rhu_cents(Decimal(str(mileage_miles)) * Decimal(project["mileage_rate_cents_per_mile"]))
    else:
        mileage_cents = 0
    pay_committed = stipend_cents + mileage_cents

    # priority 18: area budget check
    if area["budget_remaining_cents"] < pay_committed:
        raise ApiError("ERR_AREA_BUDGET_EXCEEDED", 402,
                       "Attempt committed cost exceeds the area's remaining budget.")

    # Commit
    attempt = new_entity(
        case_id=case["id"], acting_enumerator_id=uid, mode=mode,
        window_start=body["window_start"], window_end=body["window_end"],
        disposition=disposition, mileage_miles=mileage_miles,
        pay_committed_cents=pay_committed, status="LOGGED",
    )
    attempt["_ws"] = window_start
    attempt["_we"] = window_end
    store.attempts[attempt["id"]] = attempt

    case["attempt_count"] += 1
    _apply_attempt_disposition(case, project, disposition)
    touch(case)

    recompute_area(area)
    touch(area)
    return ok_object(serialize(attempt), 201)


def _apply_attempt_disposition(case, project, disposition):
    """Move the case per its disposition (PRD §3.5). Case already has attempt_count bumped."""
    # First attempt on an ASSIGNED case moves it to IN_PROGRESS.
    if case["status"] == "ASSIGNED":
        case["status"] = "IN_PROGRESS"
    # Now the case is IN_PROGRESS — apply disposition outcome.
    if disposition == "REFUSED":
        case["status"] = "REFUSED"
        release_active_assignment(case)
    elif disposition == "VACANT":
        case["status"] = "VACANT"
        release_active_assignment(case)
    elif disposition == "CONTACT_MADE":
        pass  # stays IN_PROGRESS so a response can be captured
    else:  # NO_ONE_HOME | APPOINTMENT_SET | LANGUAGE_BARRIER
        if case["attempt_count"] >= project["max_attempts"]:
            case["status"] = "MAX_ATTEMPTS"
            release_active_assignment(case)
        # else stays IN_PROGRESS (revisit loop)


@app.route("/cases/<cid>/attempts", methods=["GET"])
def list_attempts(cid):
    require()
    case = get_case(cid)
    items = [a for a in store.attempts.values() if a["case_id"] == case["id"]]
    return list_out(items)


@app.route("/attempts/<aid>/cancel", methods=["POST"])
def cancel_attempt(aid):
    require("FieldSupervisor")
    attempt = get_attempt(aid)
    if attempt["status"] != "LOGGED":
        raise ApiError("ERR_ATTEMPT_NOT_CANCELLABLE", 409,
                       "Attempt is not LOGGED and cannot be cancelled.")
    attempt["status"] = "CANCELLED"
    touch(attempt)
    case = store.cases.get(attempt["case_id"])
    if case is not None:
        if case["attempt_count"] > 0:
            case["attempt_count"] -= 1
        touch(case)
        area = area_of_case(case)
        recompute_area(area)  # compensating budget reversal (PRD §3.6)
        touch(area)
    return ok_object(serialize(attempt))


# ===========================================================================
# Response (PRD §3.7)
# ===========================================================================
@app.route("/cases/<cid>/responses", methods=["POST"])
def create_response(cid):
    uid, role = require("Enumerator")
    case = get_case(cid)
    area = area_of_case(case)
    project = project_of_area(area)
    body = get_body()

    # priority 5: structural validation
    mode = req_enum(body, "mode", ATTEMPT_MODES)
    language_used = req_enum(body, "language_used", LANGS)
    duration_minutes = req_int(body, "duration_minutes", 0, None)
    flagged_answer_count = req_int(body, "flagged_answer_count", 0, None)
    gps_variance_meters = req_number(body, "gps_variance_meters", 0)

    # priority 8: area IN_FIELD and not frozen; case IN_PROGRESS
    if area["status"] == "FROZEN":
        raise ApiError("ERR_AREA_FROZEN", 409, "Area is FROZEN; responses are blocked.")
    if area["status"] != "IN_FIELD":
        raise ApiError("ERR_AREA_NOT_IN_FIELD", 409, "Area must be IN_FIELD for responses.")
    if case["status"] != "IN_PROGRESS":
        raise ApiError("ERR_CASE_INVALID_STATE", 409,
                       "Case is not IN_PROGRESS; a response cannot be captured.")

    # priority 9: ownership
    if case["assigned_enumerator_id"] != uid:
        raise ApiError("ERR_NOT_ASSIGNED_ENUMERATOR", 403,
                       "Acting enumerator is not the case's assigned enumerator.")

    # priority 14: language capability of the capturing enumerator
    capturing = store.enumerators.get(uid)
    if capturing is None or language_used not in capturing["languages"]:
        raise ApiError("ERR_LANGUAGE_NOT_SUPPORTED", 422,
                       "language_used is not one of the capturing enumerator's languages.")

    # priority 15: at least one LOGGED CONTACT_MADE attempt
    has_contact = any(
        at["case_id"] == case["id"] and at["status"] == "LOGGED"
        and at["disposition"] == "CONTACT_MADE"
        for at in store.attempts.values()
    )
    if not has_contact:
        raise ApiError("ERR_NO_CONTACT_MADE", 409,
                       "Case has no LOGGED CONTACT_MADE attempt.")

    # Fraud scoring (PRD §3.7)
    base = FLAG_WEIGHT * flagged_answer_count
    if mode == "IN_PERSON":
        steps = (Decimal(str(gps_variance_meters)) - GPS_TOLERANCE_M) / Decimal(10)
        steps = int(steps.to_integral_value(rounding=ROUND_CEILING))
        gps_component = max(0, steps) * GPS_STEP
    else:
        gps_component = 0
    duration_penalty = SHORT_DURATION_PENALTY if duration_minutes < DURATION_FLOOR_MIN else 0
    raw = base + gps_component + duration_penalty
    fraud_score = min(100, max(0, raw))
    needs_reinterview = fraud_score >= project["fraud_score_threshold"]

    resp = new_entity(
        case_id=case["id"], capturing_enumerator_id=uid, mode=mode,
        language_used=language_used, duration_minutes=duration_minutes,
        flagged_answer_count=flagged_answer_count, gps_variance_meters=gps_variance_meters,
        fraud_score=fraud_score, needs_reinterview=needs_reinterview, status="CAPTURED",
    )
    store.responses[resp["id"]] = resp

    # Case IN_PROGRESS -> COMPLETE (PRD §3.7)
    case["status"] = "COMPLETE"
    touch(case)

    recompute_area(area)
    # Bubble-up: if no case remains pending or in progress, area IN_FIELD -> COMPLETE.
    if area["status"] == "IN_FIELD" and \
            (area["pending_case_count"] + area["in_progress_case_count"]) == 0:
        area["status"] = "COMPLETE"
    touch(area)
    return ok_object(serialize(resp), 201)


@app.route("/cases/<cid>/responses", methods=["GET"])
def list_responses(cid):
    require()
    case = get_case(cid)
    items = [r for r in store.responses.values() if r["case_id"] == case["id"]]
    return list_out(items)


@app.route("/responses/<rid>", methods=["GET"])
def get_response_route(rid):
    require()
    return ok_object(serialize(get_response(rid)))


# ===========================================================================
# ReinterviewCase (PRD §3.8)
# ===========================================================================
@app.route("/responses/<rid>/reinterviews", methods=["POST"])
def create_reinterview(rid):
    require("QCReviewer")
    resp = get_response(rid)
    body = get_body()
    # priority 4: body FK existence
    reviewer_id = body.get("reviewer_enumerator_id")
    if not isinstance(reviewer_id, str) or reviewer_id == "":
        _fail_validation("'reviewer_enumerator_id' is required.")
    reviewer = get_enumerator(reviewer_id)  # ERR_ENUMERATOR_NOT_FOUND
    # priority 5: validation
    reason = req_enum(body, "reason", REINTERVIEW_REASONS)
    finding_note = body.get("finding_note")
    if finding_note is not None and not isinstance(finding_note, str):
        _fail_validation("'finding_note' must be a string when provided.")
    # priority 16: reviewer ACTIVE
    if reviewer["status"] != "ACTIVE":
        raise ApiError("ERR_REVIEWER_NOT_ACTIVE", 422,
                       "reviewer_enumerator_id must reference an ACTIVE enumerator.")
    # priority 17: segregation of duties
    if reviewer_id == resp["capturing_enumerator_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                       "Reviewer may not audit their own captured response.")

    ri = new_entity(
        response_id=resp["id"], reviewer_enumerator_id=reviewer_id, reason=reason,
        finding_note=finding_note, status="OPEN",
    )
    store.reinterviews[ri["id"]] = ri
    return ok_object(serialize(ri), 201)


@app.route("/responses/<rid>/reinterviews", methods=["GET"])
def list_reinterviews(rid):
    require()
    resp = get_response(rid)
    items = [r for r in store.reinterviews.values() if r["response_id"] == resp["id"]]
    return list_out(items)


@app.route("/reinterviews/<rid>", methods=["GET"])
def get_reinterview_route(rid):
    require()
    return ok_object(serialize(get_reinterview(rid)))


@app.route("/reinterviews/<rid>/start", methods=["POST"])
def start_reinterview(rid):
    require("QCReviewer")
    ri = get_reinterview(rid)
    if ri["status"] != "OPEN":
        raise ApiError("ERR_REINTERVIEW_INVALID_STATE", 409, "Reinterview is not OPEN.")
    ri["status"] = "IN_REVIEW"
    touch(ri)
    return ok_object(serialize(ri))


@app.route("/reinterviews/<rid>/finalize", methods=["POST"])
def finalize_reinterview(rid):
    require("QCReviewer")
    ri = get_reinterview(rid)
    body = get_body()
    # priority 5: outcome validity (ERR_INVALID_OUTCOME)
    outcome = body.get("outcome")
    if outcome not in FINALIZE_OUTCOMES:
        raise ApiError("ERR_INVALID_OUTCOME", 400,
                       "outcome must be one of CONFIRMED|DISCREPANT|FRAUD.")
    finding_note = body.get("finding_note")
    if finding_note is not None and not isinstance(finding_note, str):
        _fail_validation("'finding_note' must be a string when provided.")
    # priority 8: state
    if ri["status"] != "IN_REVIEW":
        raise ApiError("ERR_REINTERVIEW_INVALID_STATE", 409, "Reinterview is not IN_REVIEW.")

    if finding_note is not None:
        ri["finding_note"] = finding_note
    ri["status"] = outcome
    touch(ri)

    resp = store.responses.get(ri["response_id"])
    if outcome == "CONFIRMED":
        if resp is not None and resp["status"] == "CAPTURED":
            resp["status"] = "ACCEPTED"
            touch(resp)
    elif outcome == "DISCREPANT":
        pass  # no cascade; response remains CAPTURED
    else:  # FRAUD — depth-3 cascade (PRD §3.8)
        if resp is not None:
            if resp["status"] == "CAPTURED":
                resp["status"] = "INVALIDATED"
                touch(resp)
            # link 2: reopen parent case COMPLETE -> IN_PROGRESS
            case = store.cases.get(resp["case_id"])
            if case is not None and case["status"] == "COMPLETE":
                case["status"] = "IN_PROGRESS"
                touch(case)
                area = area_of_case(case)
                recompute_area(area)
                # link 3: revert area COMPLETE -> IN_FIELD
                if area["status"] == "COMPLETE":
                    area["status"] = "IN_FIELD"
                touch(area)
            # fan-out: capturing enumerator fraud_flag = true
            cap = store.enumerators.get(resp["capturing_enumerator_id"])
            if cap is not None:
                cap["fraud_flag"] = True
                touch(cap)
    return ok_object(serialize(ri))


# ===========================================================================
# PayPeriod (PRD §3.9)
# ===========================================================================
@app.route("/survey-projects/<pid>/pay-periods", methods=["POST"])
def create_pay_period(pid):
    require("SurveyAdmin")
    p = get_project(pid)
    body = get_body()
    label = req_str(body, "label")
    overtime_threshold = opt_int(body, "overtime_threshold_cents", 200000, 0, None)
    period = new_entity(
        survey_project_id=p["id"], label=label,
        overtime_threshold_cents=overtime_threshold,
        provisional_total_cents=0, final_total_cents=0, status="OPEN",
    )
    store.pay_periods[period["id"]] = period
    return ok_object(serialize(period), 201)


@app.route("/survey-projects/<pid>/pay-periods", methods=["GET"])
def list_pay_periods(pid):
    require()
    p = get_project(pid)
    items = [pp for pp in store.pay_periods.values() if pp["survey_project_id"] == p["id"]]
    return list_out(items)


@app.route("/pay-periods/<pid>", methods=["GET"])
def get_pay_period_route(pid):
    require()
    return ok_object(serialize(get_pay_period(pid)))


@app.route("/pay-periods/<pid>/lock", methods=["POST"])
def lock_pay_period(pid):
    require("SurveyAdmin")
    period = get_pay_period(pid)
    if period["status"] != "OPEN":
        raise ApiError("ERR_PAY_PERIOD_INVALID_STATE", 409, "Pay period is not OPEN.")

    lines = [l for l in store.pay_lines.values() if l["pay_period_id"] == period["id"]]
    accrued = [l for l in lines if l["status"] == "ACCRUED"]
    provisional = sum(l["amount_cents"] for l in accrued)

    premium_total = 0
    enum_ids = {l["enumerator_id"] for l in accrued}
    for eid in enum_ids:
        stipend_sum = sum(l["amount_cents"] for l in accrued
                          if l["enumerator_id"] == eid and l["line_type"] == "STIPEND")
        if stipend_sum > period["overtime_threshold_cents"]:
            excess = stipend_sum - period["overtime_threshold_cents"]
            premium_total += rhu_cents(Decimal(excess) * OT_PREMIUM_RATE)

    period["provisional_total_cents"] = provisional
    period["final_total_cents"] = provisional + premium_total
    period["status"] = "LOCKED"
    touch(period)
    return ok_object(serialize(period))


@app.route("/pay-periods/<pid>/pay", methods=["POST"])
def pay_pay_period(pid):
    require("SurveyAdmin")
    period = get_pay_period(pid)
    if period["status"] != "LOCKED":
        raise ApiError("ERR_PAY_PERIOD_INVALID_STATE", 409, "Pay period is not LOCKED.")
    period["status"] = "PAID"
    touch(period)
    return ok_object(serialize(period))


# ===========================================================================
# PayLine (PRD §3.9)
# ===========================================================================
@app.route("/pay-periods/<pid>/pay-lines", methods=["POST"])
def create_pay_line(pid):
    require("SurveyAdmin")
    period = get_pay_period(pid)
    body = get_body()
    # priority 4: body FK existence
    enumerator_id = body.get("enumerator_id")
    if not isinstance(enumerator_id, str) or enumerator_id == "":
        _fail_validation("'enumerator_id' is required.")
    enum = get_enumerator(enumerator_id)  # ERR_ENUMERATOR_NOT_FOUND
    # priority 5: validation
    line_type = req_enum(body, "line_type", LINE_TYPES)
    amount_cents = req_int(body, "amount_cents", 1, None)  # strictly > 0
    # priority 8: period must be OPEN
    if period["status"] != "OPEN":
        raise ApiError("ERR_PAY_PERIOD_INVALID_STATE", 409, "Pay period is not OPEN.")

    line = new_entity(
        enumerator_id=enum["id"], pay_period_id=period["id"], line_type=line_type,
        amount_cents=amount_cents, status="ACCRUED",
    )
    store.pay_lines[line["id"]] = line

    recompute_period_provisional(period)
    touch(period)
    recompute_enumerator_pay(enum)
    touch(enum)
    return ok_object(serialize(line), 201)


@app.route("/pay-periods/<pid>/pay-lines", methods=["GET"])
def list_pay_lines(pid):
    require()
    period = get_pay_period(pid)
    items = [l for l in store.pay_lines.values() if l["pay_period_id"] == period["id"]]
    return list_out(items)


@app.route("/pay-lines/<lid>/reverse", methods=["POST"])
def reverse_pay_line(lid):
    require("SurveyAdmin")
    line = get_pay_line(lid)
    # priority 8: line ACCRUED, then parent period OPEN (PRD §3.9 order)
    if line["status"] != "ACCRUED":
        raise ApiError("ERR_PAY_LINE_ALREADY_REVERSED", 409, "Pay line is already REVERSED.")
    period = store.pay_periods.get(line["pay_period_id"])
    if period is None or period["status"] != "OPEN":
        raise ApiError("ERR_PAY_PERIOD_INVALID_STATE", 409, "Parent pay period is not OPEN.")

    line["status"] = "REVERSED"
    touch(line)
    recompute_period_provisional(period)
    touch(period)
    enum = store.enumerators.get(line["enumerator_id"])
    if enum is not None:
        recompute_enumerator_pay(enum)  # gross untouched by design; reversed/net updated
        touch(enum)
    return ok_object(serialize(line))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
