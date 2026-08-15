"""RegistrySubmission endpoints."""
from decimal import Decimal

from flask import Blueprint

from db import STORE, logical_now
from errors import (
    ApiError,
    ERR_CASE_INVALID_STATE,
    ERR_CASE_NOT_FOUND,
    ERR_DUPLICATE_SUBMISSION,
    ERR_INVALID_REQUEST,
    ERR_SUBMISSION_INCOMPLETE,
    ERR_SUBMISSION_INVALID_STATE,
    ERR_SUBMISSION_NOT_FOUND,
    ERR_SUBMISSION_WINDOW_EXPIRED,
)
from helpers import (
    DECISION_OUTCOMES,
    get_payload,
    new_id,
    opt_str,
    paginate,
    req_enum,
    req_str,
)
from middleware import ALL_ROLES, require_roles
from response import success
from services import (
    REGISTRY_NAMES,
    SUBMISSION_WINDOW,
    compute_completeness_pct,
    new_entity,
    submission_out,
    touch,
)

bp = Blueprint("registry", __name__)


def _get_submission_or_404(submission_id):
    submission = STORE["submissions"].get(submission_id)
    if submission is None:
        raise ApiError(
            ERR_SUBMISSION_NOT_FOUND, "No RegistrySubmission with the given id", 404
        )
    return submission


@bp.route("/cath-lab/cases/<case_id>/registry-submissions", methods=["POST"])
@require_roles("RegistryCoordinator")
def create_submission(case_id):
    case = STORE["cases"].get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "No CathCase with the given id", 404)
    if case["status"] != "COMPLETED":
        raise ApiError(
            ERR_CASE_INVALID_STATE,
            "A registry submission may only be opened for a COMPLETED case",
            409,
        )
    duplicate = any(
        s["case_id"] == case_id for s in STORE["submissions"].values()
    )
    if duplicate:
        raise ApiError(
            ERR_DUPLICATE_SUBMISSION,
            "A RegistrySubmission already exists for this case",
            409,
        )
    submission = new_entity()
    submission["id"] = new_id()
    submission.update(
        {
            "case_id": case_id,
            "registry_name": REGISTRY_NAMES[case["procedure_type"]],
            "completeness_pct": compute_completeness_pct(case),
            "submitted_at": None,
            "decided_at": None,
            "rejection_reason": None,
            "correction_note": None,
            "status": "DRAFT",
        }
    )
    STORE["submissions"][submission["id"]] = submission
    return success(submission_out(submission), 201)


@bp.route("/cath-lab/cases/<case_id>/registry-submissions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_case_submissions(case_id):
    case = STORE["cases"].get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "No CathCase with the given id", 404)
    items = [s for s in STORE["submissions"].values() if s["case_id"] == case_id]
    items.sort(key=lambda s: s["_seq"])
    page, pg = paginate(items)
    return success([submission_out(s) for s in page], 200, is_list=True, pagination=pg)


@bp.route("/cath-lab/registry-submissions/<submission_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_submission(submission_id):
    return success(submission_out(_get_submission_or_404(submission_id)), 200)


@bp.route("/cath-lab/registry-submissions/<submission_id>/submit", methods=["POST"])
@require_roles("RegistryCoordinator")
def submit_submission(submission_id):
    submission = _get_submission_or_404(submission_id)
    if submission["status"] != "DRAFT":
        raise ApiError(
            ERR_SUBMISSION_INVALID_STATE,
            "Only a DRAFT submission can be submitted",
            409,
        )
    case = STORE["cases"].get(submission["case_id"])
    completeness = compute_completeness_pct(case)
    if completeness != Decimal("100.0"):
        raise ApiError(
            ERR_SUBMISSION_INCOMPLETE,
            "Registry completeness is %s%%, exactly 100.0 is required" % completeness,
            409,
        )
    deadline = case["actual_end"] + SUBMISSION_WINDOW
    if logical_now() > deadline:
        raise ApiError(
            ERR_SUBMISSION_WINDOW_EXPIRED,
            "The 30-day registry submission window has elapsed",
            422,
        )
    submission["status"] = "SUBMITTED"
    submission["submitted_at"] = logical_now()
    submission["completeness_pct"] = completeness
    touch(submission)
    return success(submission_out(submission), 200)


@bp.route("/cath-lab/registry-submissions/<submission_id>/record-decision", methods=["POST"])
@require_roles("RegistryCoordinator")
def record_decision(submission_id):
    submission = _get_submission_or_404(submission_id)
    data = get_payload()
    outcome = req_enum(data, "outcome", DECISION_OUTCOMES)
    rejection_reason = None
    if outcome == "REJECTED":
        rejection_reason = req_str(data, "rejection_reason")
    else:
        rejection_reason = opt_str(data, "rejection_reason")
    if submission["status"] != "SUBMITTED":
        raise ApiError(
            ERR_SUBMISSION_INVALID_STATE,
            "Only a SUBMITTED submission can receive a decision",
            409,
        )
    if outcome == "ACCEPTED":
        submission["status"] = "ACCEPTED"
    else:
        submission["status"] = "REJECTED"
        submission["rejection_reason"] = rejection_reason
    submission["decided_at"] = logical_now()
    touch(submission)
    return success(submission_out(submission), 200)


@bp.route("/cath-lab/registry-submissions/<submission_id>/revise", methods=["POST"])
@require_roles("RegistryCoordinator")
def revise_submission(submission_id):
    submission = _get_submission_or_404(submission_id)
    data = get_payload()
    correction_note = req_str(data, "correction_note")
    if submission["status"] != "REJECTED":
        raise ApiError(
            ERR_SUBMISSION_INVALID_STATE,
            "Only a REJECTED submission can be revised",
            409,
        )
    submission["status"] = "DRAFT"
    submission["correction_note"] = correction_note
    submission["submitted_at"] = None
    submission["decided_at"] = None
    touch(submission)
    return success(submission_out(submission), 200)
