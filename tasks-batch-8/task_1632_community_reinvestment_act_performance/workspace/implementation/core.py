"""Core plumbing for the CRA Performance Management API.

Holds the Flask app, the in-memory store, the logical clock, the response
envelope helpers, auth/RBAC, request validators, serializers, and shared
domain helpers (cascades, recomputes, rounding).
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import Flask, jsonify, request

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message, status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status


def api_err(error_id, message, status):
    raise ApiError(error_id, message, status)


# ---------------------------------------------------------------------------
# Logical clock (never falls back to wall-clock time)
# ---------------------------------------------------------------------------
class _Clock:
    def __init__(self):
        self.dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def set(self, dt):
        self.dt = dt


CLOCK = _Clock()


def parse_datetime_str(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_str(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    return d.strftime("%Y-%m-%d")


def now_dt():
    return CLOCK.dt


def clock_today():
    return CLOCK.dt.date()


# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot; nothing is seeded)
# ---------------------------------------------------------------------------
STORE = {
    "assessment_areas": {},
    "demographic_profiles": {},
    "loan_records": {},
    "cd_activities": {},
    "branches": {},
    "public_comments": {},
    "public_files": {},
    "exam_cycles": {},
    "expansion_applications": {},
}
_SEQ = {"n": 0}


def _next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_entity():
    ts = fmt_ts(now_dt())
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": _next_seq(),
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = fmt_ts(now_dt())


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_ts(now_dt()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_body(e.error_id, e.message, e.status)


@app.errorhandler(404)
def _handle_404(e):
    return error_body("ERR_NOT_FOUND", "The requested path does not exist.", 404)


@app.errorhandler(405)
def _handle_405(e):
    return error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path.", 405)


@app.errorhandler(500)
def _handle_500(e):
    return error_body("ERR_INTERNAL", "Internal server error.", 500)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
ALL_ROLES = (
    "CRAOfficer",
    "ComplianceAnalyst",
    "QualificationReviewer",
    "BankExaminer",
    "BankExecutive",
    "PlatformAdmin",
)


def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        api_err(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
            401,
        )
    if role not in allowed_roles:
        api_err("ERR_FORBIDDEN", "The acting role is not permitted for this endpoint.", 403)
    return uid


# ---------------------------------------------------------------------------
# Request validation helpers
# ---------------------------------------------------------------------------
def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        api_err("ERR_VALIDATION", "Request body must be a JSON object.", 400)
    return data


def require(b, name):
    if name not in b or b[name] is None:
        api_err("ERR_VALIDATION", "Missing required field: %s." % name, 400)
    return b[name]


def optional(b, name):
    v = b.get(name)
    return None if v is None else v


def v_str(v, name):
    if not isinstance(v, str):
        api_err("ERR_VALIDATION", "Field %s must be a string." % name, 400)
    return v


def v_int(v, name, minimum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        api_err("ERR_VALIDATION", "Field %s must be an integer." % name, 400)
    if minimum is not None and v < minimum:
        api_err("ERR_VALIDATION", "Field %s is below its minimum." % name, 400)
    return v


def v_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        api_err("ERR_VALIDATION", "Field %s must be a number." % name, 400)
    return v


def v_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        api_err(
            "ERR_VALIDATION",
            "Field %s must be one of: %s." % (name, ", ".join(sorted(allowed))),
            400,
        )
    return v


def v_str_list(v, name):
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        api_err("ERR_VALIDATION", "Field %s must be an array of strings." % name, 400)
    return list(v)


def v_date(v, name):
    if parse_date_str(v) is None:
        api_err("ERR_VALIDATION", "Field %s must be an ISO date (YYYY-MM-DD)." % name, 400)
    return v


def pagination_params():
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except ValueError:
            api_err("ERR_VALIDATION", "limit must be an integer.", 400)
        if limit < 1:
            api_err("ERR_VALIDATION", "limit must be at least 1.", 400)
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except ValueError:
            api_err("ERR_VALIDATION", "offset must be an integer.", 400)
        if offset < 0:
            api_err("ERR_VALIDATION", "offset must be at least 0.", 400)
    return limit, offset


def q_enum(name, allowed):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        api_err(
            "ERR_VALIDATION",
            "Query parameter %s must be one of: %s." % (name, ", ".join(sorted(allowed))),
            400,
        )
    return v


def q_int(name):
    v = request.args.get(name)
    if v is None:
        return None
    try:
        return int(v.strip())
    except (ValueError, AttributeError):
        api_err("ERR_VALIDATION", "Query parameter %s must be an integer." % name, 400)


def list_response(records, serialize):
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Rounding helpers (half-up everywhere, per spec)
# ---------------------------------------------------------------------------
def ratio4(num, den):
    """round_half_up(num / den, 4); 0 when den == 0. Returns Decimal."""
    if den == 0:
        return Decimal("0")
    return (Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round2(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_cents(x):
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookup helpers (existence tier)
# ---------------------------------------------------------------------------
def get_area_or_404(area_id):
    area = STORE["assessment_areas"].get(area_id)
    if area is None:
        api_err("ERR_ASSESSMENT_AREA_NOT_FOUND", "Assessment area does not exist.", 404)
    return area


def get_loan_or_404(loan_id):
    loan = STORE["loan_records"].get(loan_id)
    if loan is None:
        api_err("ERR_LOAN_RECORD_NOT_FOUND", "Loan record does not exist.", 404)
    return loan


def get_activity_or_404(act_id):
    act = STORE["cd_activities"].get(act_id)
    if act is None:
        api_err("ERR_ACTIVITY_NOT_FOUND", "Community development activity does not exist.", 404)
    return act


def get_branch_or_404(branch_id):
    branch = STORE["branches"].get(branch_id)
    if branch is None:
        api_err("ERR_BRANCH_NOT_FOUND", "Branch does not exist.", 404)
    return branch


def get_comment_or_404(comment_id):
    comment = STORE["public_comments"].get(comment_id)
    if comment is None:
        api_err("ERR_PUBLIC_COMMENT_NOT_FOUND", "Public comment does not exist.", 404)
    return comment


def get_public_file_or_404(file_id):
    pf = STORE["public_files"].get(file_id)
    if pf is None:
        api_err("ERR_PUBLIC_FILE_NOT_FOUND", "Public file does not exist.", 404)
    return pf


def get_exam_or_404(exam_id):
    exam = STORE["exam_cycles"].get(exam_id)
    if exam is None:
        api_err("ERR_EXAM_CYCLE_NOT_FOUND", "Exam cycle does not exist.", 404)
    return exam


def get_application_or_404(app_id):
    appl = STORE["expansion_applications"].get(app_id)
    if appl is None:
        api_err("ERR_APPLICATION_NOT_FOUND", "Expansion application does not exist.", 404)
    return appl


def get_public_file():
    for pf in STORE["public_files"].values():
        return pf
    return None


# ---------------------------------------------------------------------------
# Domain helpers: cascades and recomputes
# ---------------------------------------------------------------------------
def pending_comment_count():
    return sum(1 for c in STORE["public_comments"].values() if c["status"] == "RECEIVED")


def public_file_posture(pf):
    if (
        pf["branch_list_current"]
        and pf["aa_list_current"]
        and pf["disclosure_statement_present"]
        and pending_comment_count() == 0
    ):
        return "COMPLETE"
    return "INCOMPLETE"


def cascade_public_file_stale(flag_field):
    """Set a public-file freshness flag to false (if a file exists), bumping the
    file's version/updated_at when the value actually changes."""
    pf = get_public_file()
    if pf is not None and pf[flag_field]:
        pf[flag_field] = False
        touch(pf)


def cascade_public_file_comments():
    """A comment was created or published; the (computed) pending count changed,
    which mutates the file's observable state."""
    pf = get_public_file()
    if pf is not None:
        touch(pf)


def recompute_confirmed_loan_count(area):
    n = sum(
        1
        for ln in STORE["loan_records"].values()
        if ln["assessment_area_id"] == area["id"] and ln["status"] in ("CONFIRMED", "REPORTED")
    )
    if n != area["confirmed_loan_count"]:
        area["confirmed_loan_count"] = n
        touch(area)


def recompute_qualified_cd_total(area):
    total = sum(
        a["qualified_amount_cents"]
        for a in STORE["cd_activities"].values()
        if a["assessment_area_id"] == area["id"] and a["status"] == "QUALIFIED"
    )
    if total != area["qualified_cd_total_cents"]:
        area["qualified_cd_total_cents"] = total
        touch(area)


def check_tract_exclusivity(area, tracts):
    """No tract may appear in two areas whose status is ACTIVE or UNDER_REVIEW.
    `area` is the area entering / sitting in the constrained set; exclude self."""
    others_tracts = set()
    for other in STORE["assessment_areas"].values():
        if other["id"] == area["id"]:
            continue
        if other["status"] in ("ACTIVE", "UNDER_REVIEW"):
            others_tracts.update(other["census_tracts"])
    for t in tracts:
        if t in others_tracts:
            api_err(
                "ERR_TRACT_OVERLAP",
                "Census tract %s already belongs to another ACTIVE or UNDER_REVIEW area." % t,
                409,
            )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def area_out(a):
    return {
        "id": a["id"],
        "area_code": a["area_code"],
        "name": a["name"],
        "msa_code": a["msa_code"],
        "state_code": a["state_code"],
        "census_tracts": list(a["census_tracts"]),
        "effective_start_date": a["effective_start_date"],
        "effective_end_date": a["effective_end_date"],
        "annual_cd_budget_cents": a["annual_cd_budget_cents"],
        "confirmed_loan_count": a["confirmed_loan_count"],
        "qualified_cd_total_cents": a["qualified_cd_total_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def profile_out(p):
    return {
        "id": p["id"],
        "assessment_area_id": p["assessment_area_id"],
        "data_year": p["data_year"],
        "total_tracts": p["total_tracts"],
        "low_income_tracts": p["low_income_tracts"],
        "moderate_income_tracts": p["moderate_income_tracts"],
        "total_population": p["total_population"],
        "lmi_population": p["lmi_population"],
        "median_family_income": p["median_family_income"],
        "lmi_population_pct": p["lmi_population_pct"],
        "lmi_tract_pct": p["lmi_tract_pct"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def loan_out(ln):
    area = STORE["assessment_areas"].get(ln["assessment_area_id"])
    inside = bool(area) and ln["census_tract"] in area["census_tracts"]
    return {
        "id": ln["id"],
        "assessment_area_id": ln["assessment_area_id"],
        "loan_type": ln["loan_type"],
        "loan_amount_cents": ln["loan_amount_cents"],
        "borrower_gross_annual_revenue_cents": ln["borrower_gross_annual_revenue_cents"],
        "action_date": ln["action_date"],
        "census_tract": ln["census_tract"],
        "tract_income_level": ln["tract_income_level"],
        "inside_assessment_area": inside,
        "small_revenue_flag": ln["small_revenue_flag"],
        "lmi_geography_flag": ln["lmi_geography_flag"],
        "reporting_year": ln["reporting_year"],
        "status": ln["status"],
        "created_at": ln["created_at"],
        "updated_at": ln["updated_at"],
        "version": ln["version"],
    }


def activity_out(a):
    return {
        "id": a["id"],
        "assessment_area_id": a["assessment_area_id"],
        "activity_type": a["activity_type"],
        "amount_cents": a["amount_cents"],
        "primary_purpose_category": a["primary_purpose_category"],
        "lmi_benefit_pct": a["lmi_benefit_pct"],
        "activity_date": a["activity_date"],
        "submitted_by_user_id": a["submitted_by_user_id"],
        "reviewed_by_user_id": a["reviewed_by_user_id"],
        "disqualify_reason": a["disqualify_reason"],
        "allocation_method": a["allocation_method"],
        "qualified_amount_cents": a["qualified_amount_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def branch_out(b):
    return {
        "id": b["id"],
        "branch_code": b["branch_code"],
        "assessment_area_id": b["assessment_area_id"],
        "census_tract": b["census_tract"],
        "tract_income_level": b["tract_income_level"],
        "expansion_application_id": b["expansion_application_id"],
        "opened_date": b["opened_date"],
        "closed_date": b["closed_date"],
        "notice_posted_date": b["notice_posted_date"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def comment_out(c):
    return {
        "id": c["id"],
        "commenter_name": c["commenter_name"],
        "channel": c["channel"],
        "subject_area": c["subject_area"],
        "content": c["content"],
        "received_at": c["received_at"],
        "response_text": c["response_text"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def public_file_out(pf):
    return {
        "id": pf["id"],
        "bank_name": pf["bank_name"],
        "branch_list_current": pf["branch_list_current"],
        "aa_list_current": pf["aa_list_current"],
        "disclosure_statement_present": pf["disclosure_statement_present"],
        "pending_comment_count": pending_comment_count(),
        "posture": public_file_posture(pf),
        "created_at": pf["created_at"],
        "updated_at": pf["updated_at"],
        "version": pf["version"],
    }


def exam_out(e):
    return {
        "id": e["id"],
        "exam_type": e["exam_type"],
        "evaluation_window_start": e["evaluation_window_start"],
        "evaluation_window_end": e["evaluation_window_end"],
        "performance_context_narrative": e["performance_context_narrative"],
        "lending_test_rating": e["lending_test_rating"],
        "investment_test_rating": e["investment_test_rating"],
        "service_test_rating": e["service_test_rating"],
        "composite_points": e["composite_points"],
        "composite_rating": e["composite_rating"],
        "appeal_reason": e["appeal_reason"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def application_out(a):
    return {
        "id": a["id"],
        "application_type": a["application_type"],
        "target_assessment_area_id": a["target_assessment_area_id"],
        "branch_code": a["branch_code"],
        "branch_census_tract": a["branch_census_tract"],
        "branch_tract_income_level": a["branch_tract_income_level"],
        "linked_branch_id": a["linked_branch_id"],
        "decision_reason": a["decision_reason"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


# Shared enum sets
TRACT_INCOME_LEVELS = ("LOW", "MODERATE", "MIDDLE", "UPPER")
LOAN_TYPES = ("SMALL_BUSINESS", "SMALL_FARM")
LOAN_STATUSES = ("DRAFT", "CONFIRMED", "REPORTED")
ACTIVITY_TYPES = ("CD_LOAN", "QUALIFIED_INVESTMENT", "CD_SERVICE")
ACTIVITY_STATUSES = ("SUBMITTED", "QUALIFIED", "DISQUALIFIED")
PURPOSE_CATEGORIES = (
    "AFFORDABLE_HOUSING",
    "COMMUNITY_SERVICES_LMI",
    "ECONOMIC_DEVELOPMENT",
    "REVITALIZATION_STABILIZATION",
)
BRANCH_STATUSES = ("PROPOSED", "OPEN", "CLOSED", "WITHDRAWN")
PROFILE_STATUSES = ("CURRENT", "SUPERSEDED")
COMMENT_CHANNELS = ("WRITTEN_LETTER", "EMAIL", "PUBLIC_MEETING")
COMMENT_SUBJECTS = ("LENDING", "INVESTMENT", "SERVICE", "BRANCH_ACCESS", "OTHER")
EXAM_TYPES = ("LARGE_BANK", "INTERMEDIATE_SMALL_BANK")
TEST_RATINGS = ("OUTSTANDING", "SATISFACTORY", "NEEDS_TO_IMPROVE", "SUBSTANTIAL_NONCOMPLIANCE")
APPLICATION_TYPES = ("BRANCH_OPENING", "BRANCH_CLOSURE", "MERGER")
APPLICATION_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "DENIED")
AREA_STATUSES = ("DRAFT", "ACTIVE", "UNDER_REVIEW", "RETIRED")

CRA_REPORTABLE_CAP_CENTS = 100000000  # $1MM
REGISTER_ROUND_UNIT_CENTS = 100000  # $1,000 in cents
SMALL_REVENUE_THRESHOLD_CENTS = 100000000  # $1MM gross annual revenue, inclusive
FULL_COUNT_LMI_THRESHOLD = Decimal("0.51")
