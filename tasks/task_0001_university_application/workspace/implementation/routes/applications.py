"""Application routes."""

from flask import Blueprint, request

import db
import errors
import response as resp
import util
from middleware import require_auth
from routes._helpers import (
    get_json_body,
    parse_pagination,
    paginate,
    require_field,
)
from services import applications as applications_service
from services import calculations
from services.serializers import serialize_application


bp = Blueprint("applications", __name__)


VALID_PLANS = frozenset({"EARLY_DECISION", "EARLY_ACTION", "REGULAR", "ROLLING"})
VALID_STATUSES = frozenset({
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "ADMITTED", "WAITLISTED",
    "DENIED", "DEFERRED", "WITHDRAWN", "ENROLLED", "DECLINED_OFFER",
})
VALID_DECISIONS = frozenset({"ADMIT", "WAITLIST", "DENY", "DEFER"})


# --------------------------------------------------------------------------- #
# POST /applications  (Applicant)
# --------------------------------------------------------------------------- #

@bp.route("/applications", methods=["POST"])
@require_auth(["Applicant"])
def create_application():
    body = get_json_body()
    applicant_id = require_field(body, "applicant_id", kind="string")
    school_id = require_field(body, "school_id", kind="string")
    plan = require_field(body, "plan", kind="string")

    if plan not in VALID_PLANS:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"Field 'plan' must be one of {sorted(VALID_PLANS)}.")

    # FK resolution
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        errors.raise_error(errors.ERR_FK_NOT_FOUND, "Applicant not found.")
    school = db.schools.get(school_id)
    if school is None:
        errors.raise_error(errors.ERR_FK_NOT_FOUND, "School not found.")

    # Ownership: Applicant must equal Application.applicant_id
    user_id = request.headers.get("X-User-ID")
    if user_id != applicant_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only create applications for themselves.")

    # Body validation
    if plan == "ROLLING" and not school.get("rolling_open"):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "School does not accept rolling submissions.")

    # Uniqueness: (applicant_id, school_id)
    for existing in db.applications.values():
        if existing["applicant_id"] == applicant_id and existing["school_id"] == school_id:
            errors.raise_error(errors.ERR_DUPLICATE_RESOURCE,
                               "An application for this applicant and school already exists.")

    # Priority 11: ED binding rule — at creation time, at most one non-terminal ED
    if plan == "EARLY_DECISION":
        for existing in db.applications.values():
            if existing["applicant_id"] != applicant_id:
                continue
            if existing["plan"] == "EARLY_DECISION" and existing["status"] in applications_service.NON_TERMINAL_STATUSES:
                errors.raise_error(errors.ERR_ED_BINDING_VIOLATION,
                                   "Applicant already has a non-terminal ED application.")

    row = {
        "applicant_id": applicant_id,
        "school_id": school_id,
        "plan": plan,
        "status": "DRAFT",
        "submitted_at": None,
        "decision_at": None,
        "waitlist_rank": None,
        "waitlist_added_at": None,
    }
    util.stamp_create(row)
    db.applications[row["id"]] = row
    return resp.success_object(serialize_application(row), http_status=201)


# --------------------------------------------------------------------------- #
# GET /applications/{id}
# --------------------------------------------------------------------------- #

@bp.route("/applications/<app_id>", methods=["GET"])
@require_auth(["Applicant", "AdmissionsOfficer", "PlatformAdmin"])
def get_application(app_id):
    row = db.applications.get(app_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND,
                           "Application not found.")

    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role == "Applicant" and row["applicant_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only read their own applications.")

    variant = request.args.get("score_variant")
    if variant is not None:
        if variant not in ("PROVISIONAL", "FINAL"):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Query 'score_variant' must be PROVISIONAL or FINAL.")
    else:
        variant = calculations.default_score_variant(row["status"])

    score = calculations.compute_admission_probability_score(row, variant)
    return resp.success_object(
        serialize_application(row, admission_probability_score=score)
    )


# --------------------------------------------------------------------------- #
# GET /applications
# --------------------------------------------------------------------------- #

@bp.route("/applications", methods=["GET"])
@require_auth(["Applicant", "AdmissionsOfficer", "PlatformAdmin"])
def list_applications():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    school_filter = request.args.get("school_id")
    status_filter = request.args.get("status")
    plan_filter = request.args.get("plan")

    if status_filter is not None and status_filter not in VALID_STATUSES:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"Query 'status' must be one of {sorted(VALID_STATUSES)}.")
    if plan_filter is not None and plan_filter not in VALID_PLANS:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"Query 'plan' must be one of {sorted(VALID_PLANS)}.")

    limit, offset = parse_pagination()

    rows = list(db.applications.values())
    # Applicants only see their own
    if role == "Applicant":
        rows = [r for r in rows if r["applicant_id"] == user_id]
    if school_filter is not None:
        rows = [r for r in rows if r["school_id"] == school_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if plan_filter is not None:
        rows = [r for r in rows if r["plan"] == plan_filter]

    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)

    payload = []
    for r in page:
        variant = calculations.default_score_variant(r["status"])
        score = calculations.compute_admission_probability_score(r, variant)
        payload.append(serialize_application(r, admission_probability_score=score))

    return resp.success_array(
        payload, limit=limit, offset=offset, total_count=total,
    )


# --------------------------------------------------------------------------- #
# Helpers for state-transition endpoints
# --------------------------------------------------------------------------- #

def _require_application(app_id):
    row = db.applications.get(app_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "Application not found.")
    return row


def _require_applicant_owner(row):
    user_id = request.headers.get("X-User-ID")
    if row["applicant_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only act on their own applications.")


def _respond_application(row):
    variant = calculations.default_score_variant(row["status"])
    score = calculations.compute_admission_probability_score(row, variant)
    return resp.success_object(
        serialize_application(row, admission_probability_score=score)
    )


# --------------------------------------------------------------------------- #
# POST /applications/{id}/submit
# --------------------------------------------------------------------------- #

@bp.route("/applications/<app_id>/submit", methods=["POST"])
@require_auth(["Applicant"])
def submit_application(app_id):
    row = _require_application(app_id)
    _require_applicant_owner(row)
    applications_service.do_submit(row)
    return _respond_application(row)


# --------------------------------------------------------------------------- #
# POST /applications/{id}/withdraw
# --------------------------------------------------------------------------- #

@bp.route("/applications/<app_id>/withdraw", methods=["POST"])
@require_auth(["Applicant"])
def withdraw_application(app_id):
    row = _require_application(app_id)
    _require_applicant_owner(row)
    applications_service.do_withdraw(row)
    return _respond_application(row)


# --------------------------------------------------------------------------- #
# POST /applications/{id}/start-review
# --------------------------------------------------------------------------- #

@bp.route("/applications/<app_id>/start-review", methods=["POST"])
@require_auth(["AdmissionsOfficer"])
def start_review_application(app_id):
    row = _require_application(app_id)
    applications_service.do_start_review(row)
    return _respond_application(row)


# --------------------------------------------------------------------------- #
# POST /applications/{id}/decide  (with OCC)
# --------------------------------------------------------------------------- #

@bp.route("/applications/<app_id>/decide", methods=["POST"])
@require_auth(["AdmissionsOfficer"])
def decide_application(app_id):
    row = _require_application(app_id)
    body = get_json_body()
    decision = require_field(body, "decision", kind="string")
    expected_version = require_field(body, "expected_application_version", kind="integer")

    if decision not in VALID_DECISIONS:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"Field 'decision' must be one of {sorted(VALID_DECISIONS)}.")

    # Priority 9: OCC check
    if expected_version != row["version"]:
        errors.raise_error(errors.ERR_STALE_APPLICATION_VERSION,
                           "Provided expected_application_version is stale.")

    applications_service.do_decide(row, decision)
    return _respond_application(row)


# --------------------------------------------------------------------------- #
# POST /applications/{id}/accept-offer
# --------------------------------------------------------------------------- #

@bp.route("/applications/<app_id>/accept-offer", methods=["POST"])
@require_auth(["Applicant"])
def accept_offer(app_id):
    row = _require_application(app_id)
    _require_applicant_owner(row)
    applications_service.do_accept_offer(row)
    return _respond_application(row)


# --------------------------------------------------------------------------- #
# POST /applications/{id}/decline-offer
# --------------------------------------------------------------------------- #

@bp.route("/applications/<app_id>/decline-offer", methods=["POST"])
@require_auth(["Applicant"])
def decline_offer(app_id):
    row = _require_application(app_id)
    _require_applicant_owner(row)
    applications_service.do_decline_offer(row)
    return _respond_application(row)


# --------------------------------------------------------------------------- #
# POST /applications/{id}/revoke-enrollment
# --------------------------------------------------------------------------- #

@bp.route("/applications/<app_id>/revoke-enrollment", methods=["POST"])
@require_auth(["Applicant"])
def revoke_enrollment(app_id):
    row = _require_application(app_id)
    _require_applicant_owner(row)
    applications_service.do_revoke_enrollment(row)
    return _respond_application(row)
