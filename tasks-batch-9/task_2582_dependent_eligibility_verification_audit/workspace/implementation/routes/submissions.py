"""Proof submission, analyst decisions and the privacy cure (sections 3.5, 2.10)."""

from flask import Blueprint

import auth
import calc
import clock
import constants as K
import db
import derive
import response
import serialize
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("submissions", __name__)

READ_ROLES = ("ProgramAdmin", "VerificationAnalyst", "AppealReviewer")


def _submission_or_404(submission_id):
    submission = db.get("submissions", submission_id)
    if submission is None:
        raise ApiError("ERR_SUBMISSION_NOT_FOUND")
    return submission


@bp.route("/proof-submissions", methods=["POST"])
@endpoint("Employee", "VerificationAnalyst")
def create_submission():
    raw = validate.body()
    auth.soft_owner_check_case(raw.get("case_id"))
    auth.soft_owner_check_dependent(raw.get("dependent_id"))

    case_id = validate.req_id(raw, "case_id")
    dependent_id = validate.req_id(raw, "dependent_id")
    proof_type = validate.req_enum(raw, "proof_type", K.PROOF_TYPES)
    document_reference = validate.req_str(raw, "document_reference")
    document_date = validate.req_date(raw, "document_date")
    redaction_applied = validate.opt_bool(raw, "redaction_applied", False)

    case = db.get("cases", case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    dependent = db.get("dependents", dependent_id)
    if dependent is None:
        raise ApiError("ERR_DEPENDENT_NOT_FOUND")

    program = db.get("programs", case["program_id"])
    if program is None or program["status"] not in ("AMNESTY_OPEN", "RESPONSE_WINDOW"):
        raise ApiError("ERR_PROGRAM_PHASE_INVALID")
    if case["status"] not in ("NOTIFIED", "IN_PROGRESS"):
        raise ApiError("ERR_CASE_STATE_INVALID")
    if dependent["coverage_status"] != "PENDING_VERIFICATION" or dependent[
        "id"
    ] not in (case.get("in_scope_dependent_ids") or []):
        raise ApiError("ERR_DEPENDENT_STATE_INVALID")

    sensitive = proof_type in K.SENSITIVE_PROOF_TYPES
    if sensitive and not redaction_applied:
        raise ApiError("ERR_PRIVACY_REDACTION_REQUIRED")

    now = clock.now()
    deadline = program.get("response_deadline_at")
    if deadline is not None and now > deadline:
        raise ApiError("ERR_RESPONSE_WINDOW_CLOSED")

    rule = calc.find_rule(program["id"], dependent["relationship_type"], "AUDIT")
    if rule is None:
        raise ApiError("ERR_DOCUMENTATION_RULE_MISSING")
    if proof_type not in (rule.get("acceptable_proof_types") or []):
        raise ApiError("ERR_PROOF_TYPE_NOT_ACCEPTED")
    if proof_type in K.RECENCY_SCOPED_PROOF_TYPES:
        announced = program.get("announcement_at")
        if announced is not None:
            floor_date = clock.add_days(
                announced.date(), -rule["requires_recency_days"]
            )
            if clock.parse_date(document_date) < floor_date:
                raise ApiError("ERR_PROOF_STALE_DOCUMENT")

    submission = db.insert(
        "submissions",
        {
            "case_id": case["id"],
            "dependent_id": dependent["id"],
            "proof_type": proof_type,
            "document_reference": document_reference,
            "document_date": document_date,
            "redaction_applied": bool(redaction_applied),
            "review_status": "SUBMITTED",
            "privacy_status": "REDACTED"
            if (sensitive and redaction_applied)
            else "NOT_REQUIRED",
            "privacy_class": "SENSITIVE" if sensitive else "STANDARD",
            "reviewed_by_user_id": None,
            "decision_reason_code": None,
            "decided_at": None,
            "redacted_document_reference": None,
        },
    )

    derive.first_response(case)
    derive.refresh_all()
    return response.obj_out(serialize.submission, submission, 201)


@bp.route("/proof-submissions/<submission_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_submission(submission_id):
    submission = _submission_or_404(submission_id)
    return response.obj_out(serialize.submission, submission)


@bp.route("/proof-submissions", methods=["GET"])
@endpoint(*READ_ROLES)
def list_submissions():
    case_id = validate.query_filter("case_id")
    dependent_id = validate.query_filter("dependent_id")
    review_status = validate.query_filter("review_status")
    privacy_status = validate.query_filter("privacy_status")
    rows = db.ordered(
        "submissions",
        lambda s: (case_id is None or s["case_id"] == case_id)
        and (dependent_id is None or s["dependent_id"] == dependent_id)
        and (review_status is None or s["review_status"] == review_status)
        and (privacy_status is None or s["privacy_status"] == privacy_status),
    )
    return response.arr_out(serialize.submission, rows, validate.paginate(rows))


@bp.route("/proof-submissions/<submission_id>/decision", methods=["POST"])
@endpoint("VerificationAnalyst")
def decide_submission(submission_id):
    submission = _submission_or_404(submission_id)
    payload = validate.body()
    decision = validate.req_enum(payload, "decision", K.PROOF_DECISIONS)
    reason_code = validate.opt_enum(payload, "reason_code", K.DECISION_REASON_CODES)
    validate.opt_str(payload, "reviewer_note")

    case = db.get("cases", submission["case_id"])
    program = db.get("programs", case["program_id"]) if case is not None else None
    if program is None or program["status"] not in ("RESPONSE_WINDOW", "ESCALATION"):
        raise ApiError("ERR_PROGRAM_PHASE_INVALID")
    if submission["review_status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")
    if decision == "ACCEPT" and submission["privacy_status"] not in (
        "NOT_REQUIRED",
        "REDACTED",
    ):
        raise ApiError("ERR_PRIVACY_HOLD")

    now = clock.now()
    db.set_fields(
        submission,
        reviewed_by_user_id=auth.acting_user(),
        decided_at=now,
    )
    if reason_code is not None:
        db.set_fields(submission, decision_reason_code=reason_code)

    if decision == "ACCEPT":
        db.set_fields(submission, review_status="ACCEPTED")
        dependent = db.get("dependents", submission["dependent_id"])
        if dependent is not None:
            if derive.apply_completeness(dependent, program):
                if dependent["coverage_status"] == "PENDING_VERIFICATION":
                    db.set_fields(dependent, coverage_status="VERIFIED")
            if case is not None:
                derive.recompute_case(case)
                derive.maybe_complete_case(case)
    elif decision == "REJECT":
        db.set_fields(submission, review_status="REJECTED")
    else:
        db.set_fields(
            submission,
            review_status="UNDER_REVIEW",
            privacy_status="REDACTION_REQUIRED",
        )

    derive.refresh_all()
    return response.obj_out(serialize.submission, submission)


@bp.route("/proof-submissions/<submission_id>/redaction", methods=["POST"])
@endpoint("Employee", "VerificationAnalyst")
def upload_redaction(submission_id):
    submission = _submission_or_404(submission_id)
    dependent = db.get("dependents", submission["dependent_id"])
    auth.require_owns_dependent(dependent)

    payload = validate.body()
    reference = validate.req_str(payload, "redacted_document_reference")

    if submission["privacy_status"] != "REDACTION_REQUIRED" or submission[
        "review_status"
    ] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")

    # The upload cures the privacy obligation only; review_status is untouched.
    db.set_fields(
        submission, privacy_status="REDACTED", redacted_document_reference=reference
    )
    derive.refresh_all()
    return response.obj_out(serialize.submission, submission)
