"""SurveySubmissions and SurveyJobMatches."""
from flask import Blueprint, g, request

from common import (
    ApiError, ALL_ROLES, actor_employee_id, body, current_date, db, emit_audit,
    filter_records, get_or_404, iso, new_record, ok, ok_list, parse_date, pub,
    require_roles, touch, v_str,
)

bp = Blueprint("flow", __name__)

MATCH_CONFIDENCES = ("HIGH", "MEDIUM", "LOW")


def _survey_of(sub):
    return db["surveys"][sub["survey_id"]]


def _check_weight(weight):
    if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1 or weight > 100:
        raise ApiError("ERR_INVALID_WEIGHT", 422,
                       "match_weight_pct must be an integer in [1, 100]")


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------
@bp.route("/surveys/<sid>/submissions", methods=["POST"])
@require_roles("CompAnalyst")
def create_submission(sid):
    survey = get_or_404("surveys", sid)
    b = body()
    submitted_by = v_str(b, "submitted_by_employee_id")
    snapshot = b.get("incumbent_snapshot")
    if not isinstance(snapshot, list):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "incumbent_snapshot must be an array")
    for entry in snapshot:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "incumbent_snapshot entries must be objects")
        for f in ("employee_id", "job_id", "geo_code"):
            if not isinstance(entry.get(f), str) or not entry.get(f):
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               f"incumbent_snapshot entry field {f} must be a non-empty string")
        amt = entry.get("base_salary_annual_cents")
        if isinstance(amt, bool) or not isinstance(amt, int):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "incumbent_snapshot entry base_salary_annual_cents must be an integer")
    rec = new_record()
    rec.update({
        "survey_id": survey["id"],
        "submitted_by_employee_id": submitted_by,
        "incumbent_snapshot": snapshot,
        "prepared_at": None,
        "submitted_at": None,
        "rejection_reason": None,
        "status": "DRAFT",
    })
    db["submissions"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/submissions/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_submission(sid):
    return ok(pub(get_or_404("submissions", sid)))


@bp.route("/submissions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_submissions():
    return ok_list(filter_records("submissions", {
        "survey_id": request.args.get("survey_id"),
        "submitted_by_employee_id": request.args.get("submitted_by_employee_id"),
        "status": request.args.get("status"),
    }))


@bp.route("/surveys/<sid>/submissions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_survey_submissions(sid):
    survey = get_or_404("surveys", sid)
    return ok_list(filter_records("submissions", {"survey_id": survey["id"]}))


@bp.route("/employees/<eid>/submissions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_employee_submissions(eid):
    emp = get_or_404("employees", eid)
    return ok_list(filter_records("submissions", {"submitted_by_employee_id": emp["id"]}))


@bp.route("/submissions/<sid>/mark_ready", methods=["POST"])
@require_roles("CompAnalyst")
def mark_ready(sid):
    sub = get_or_404("submissions", sid)
    if sub["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot mark ready a submission in status {sub['status']}")
    survey = _survey_of(sub)
    if survey["status"] != "OPEN":
        raise ApiError("ERR_SURVEY_NOT_OPEN", 409,
                       f"Survey is in status {survey['status']}, not OPEN")
    vendor = db["vendors"][survey["vendor_id"]]
    if vendor["data_use_scope"] != "FULL_PARTICIPATION":
        raise ApiError("ERR_VENDOR_SCOPE_FORBIDS_SUBMISSION", 409,
                       "Vendor data_use_scope forbids incumbent submissions")
    snapshot = sub["incumbent_snapshot"]
    if len(snapshot) < 1:
        raise ApiError("ERR_EMPTY_SUBMISSION", 422,
                       "incumbent_snapshot must contain at least one entry")
    for entry in snapshot:
        emp = db["employees"].get(entry["employee_id"])
        if emp is None or emp["org_id"] != survey["org_id"] or emp["status"] != "ACTIVE":
            raise ApiError("ERR_EMPLOYEE_NOT_ACTIVE", 422,
                           f"Employee {entry.get('employee_id')} is not an ACTIVE employee of this org")
    sub["status"] = "READY"
    sub["prepared_at"] = iso()
    touch(sub)
    return ok(pub(sub))


@bp.route("/submissions/<sid>/submit", methods=["POST"])
@require_roles("CompAnalyst")
def submit_submission(sid):
    sub = get_or_404("submissions", sid)
    if sub["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot submit a submission in status {sub['status']}")
    survey = _survey_of(sub)
    # Ladder rung 7 (survey gating) precedes rung 9 (temporal)
    if survey["status"] != "OPEN":
        raise ApiError("ERR_SURVEY_NOT_OPEN", 409,
                       f"Survey is in status {survey['status']}, not OPEN")
    if current_date() > parse_date(survey["submission_deadline"]):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED", 409,
                       "Current date is past the submission deadline")
    sub["status"] = "SUBMITTED"
    sub["submitted_at"] = iso()
    touch(sub)
    emit_audit(survey["org_id"], actor_employee_id(), "SURVEY_SUBMIT",
               "SurveySubmission", sub["id"], {"status": "SUBMITTED"})
    return ok(pub(sub))


@bp.route("/submissions/<sid>/accept", methods=["POST"])
@require_roles("VendorAdmin")
def accept_submission(sid):
    sub = get_or_404("submissions", sid)
    if sub["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot accept a submission in status {sub['status']}")
    sub["status"] = "ACCEPTED"
    touch(sub)
    survey = _survey_of(sub)
    emit_audit(survey["org_id"], None, "SUBMISSION_ACCEPT",
               "SurveySubmission", sub["id"], {"status": "ACCEPTED"})
    return ok(pub(sub))


@bp.route("/submissions/<sid>/return", methods=["POST"])
@require_roles("VendorAdmin")
def return_submission(sid):
    sub = get_or_404("submissions", sid)
    b = body()
    reason = v_str(b, "reason")
    if sub["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot return a submission in status {sub['status']}")
    sub["status"] = "RETURNED"
    sub["rejection_reason"] = reason
    touch(sub)
    return ok(pub(sub))


@bp.route("/submissions/<sid>/rework", methods=["POST"])
@require_roles("CompAnalyst")
def rework_submission(sid):
    sub = get_or_404("submissions", sid)
    if sub["status"] != "RETURNED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot rework a submission in status {sub['status']}")
    survey = _survey_of(sub)
    if survey["status"] != "OPEN":
        raise ApiError("ERR_SURVEY_NOT_OPEN", 409,
                       f"Survey is in status {survey['status']}, not OPEN")
    if current_date() > parse_date(survey["submission_deadline"]):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED", 409,
                       "Current date is past the submission deadline")
    sub["status"] = "DRAFT"
    sub["rejection_reason"] = None
    sub["prepared_at"] = None
    sub["submitted_at"] = None
    touch(sub)
    return ok(pub(sub))


# ---------------------------------------------------------------------------
# Survey job matches
# ---------------------------------------------------------------------------
@bp.route("/surveys/<sid>/matches", methods=["POST"])
@require_roles("CompAnalyst")
def create_match(sid):
    survey = get_or_404("surveys", sid)
    b = body()
    job_id = b.get("job_id")
    benchmark_id = b.get("benchmark_id")
    if not isinstance(job_id, str) or not job_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "job_id is required")
    if not isinstance(benchmark_id, str) or not benchmark_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "benchmark_id is required")
    confidence = b.get("match_confidence")
    if confidence not in MATCH_CONFIDENCES:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "match_confidence must be one of HIGH, MEDIUM, LOW")
    if "match_weight_pct" not in b:
        raise ApiError("ERR_INVALID_REQUEST", 400, "match_weight_pct is required")
    proposed_by = v_str(b, "proposed_by_employee_id")
    job = db["jobs"].get(job_id)
    if job is None or job["org_id"] != survey["org_id"]:
        raise ApiError("ERR_NOT_FOUND", 404, f"Job {job_id} not found in this organization")
    bench = db["benchmarks"].get(benchmark_id)
    if bench is None or bench["survey_id"] != survey["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, f"Benchmark {benchmark_id} not found under this survey")
    _check_weight(b["match_weight_pct"])
    rec = new_record()
    rec.update({
        "survey_id": survey["id"],
        "job_id": job_id,
        "benchmark_id": benchmark_id,
        "match_confidence": confidence,
        "match_weight_pct": b["match_weight_pct"],
        "proposed_by_employee_id": proposed_by,
        "reviewer_employee_id": None,
        "status": "PROPOSED",
    })
    db["matches"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/matches/<mid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_match(mid):
    return ok(pub(get_or_404("matches", mid)))


@bp.route("/matches", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_matches():
    return ok_list(filter_records("matches", {
        "survey_id": request.args.get("survey_id"),
        "job_id": request.args.get("job_id"),
        "benchmark_id": request.args.get("benchmark_id"),
        "proposed_by_employee_id": request.args.get("proposed_by_employee_id"),
        "reviewer_employee_id": request.args.get("reviewer_employee_id"),
        "status": request.args.get("status"),
    }))


@bp.route("/surveys/<sid>/matches", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_survey_matches(sid):
    survey = get_or_404("surveys", sid)
    return ok_list(filter_records("matches", {"survey_id": survey["id"]}))


@bp.route("/jobs/<jid>/matches", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_job_matches(jid):
    job = get_or_404("jobs", jid)
    return ok_list(filter_records("matches", {"job_id": job["id"]}))


@bp.route("/matches/<mid>/review", methods=["POST"])
@require_roles("CompManager")
def review_match(mid):
    m = get_or_404("matches", mid)
    if m["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot review a match in status {m['status']}")
    survey = db["surveys"][m["survey_id"]]
    if survey["status"] not in ("OPEN", "CLOSED", "SUBMITTED", "ACCEPTED"):
        raise ApiError("ERR_SURVEY_NOT_OPEN", 409,
                       f"Survey is in status {survey['status']}")
    _check_weight(m["match_weight_pct"])
    m["status"] = "REVIEWED"
    touch(m)
    return ok(pub(m))


@bp.route("/matches/<mid>/approve", methods=["POST"])
@require_roles("CompManager")
def approve_match(mid):
    m = get_or_404("matches", mid)
    if m["status"] != "REVIEWED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot approve a match in status {m['status']}")
    if g.user_id == m["proposed_by_employee_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 409,
                       "Approver must differ from the proposer")
    bench = db["benchmarks"][m["benchmark_id"]]
    if bench["sample_size"] < 5:
        raise ApiError("ERR_SAMPLE_SIZE_TOO_SMALL", 409,
                       "Benchmark sample_size is below the floor of 5")
    m["status"] = "APPROVED"
    m["reviewer_employee_id"] = g.user_id
    touch(m)
    survey = db["surveys"][m["survey_id"]]
    emit_audit(survey["org_id"], actor_employee_id(), "MATCH_APPROVE",
               "SurveyJobMatch", m["id"], {"status": "APPROVED"})
    return ok(pub(m))


@bp.route("/matches/<mid>/reject", methods=["POST"])
@require_roles("CompManager")
def reject_match(mid):
    m = get_or_404("matches", mid)
    if m["status"] != "REVIEWED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot reject a match in status {m['status']}")
    m["status"] = "REJECTED"
    touch(m)
    survey = db["surveys"][m["survey_id"]]
    emit_audit(survey["org_id"], actor_employee_id(), "MATCH_REJECT",
               "SurveyJobMatch", m["id"], {"status": "REJECTED"})
    return ok(pub(m))


@bp.route("/matches/<mid>/revise", methods=["POST"])
@require_roles("CompAnalyst")
def revise_match(mid):
    m = get_or_404("matches", mid)
    if m["status"] not in ("REVIEWED", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot revise a match in status {m['status']}")
    m["status"] = "PROPOSED"
    touch(m)
    return ok(pub(m))
