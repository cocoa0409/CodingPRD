"""Submission routes (PRD 3.3)."""

from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import (
    get_user_context, require_role, get_json_body, parse_pagination, paginate,
)
from response import object_response, array_response
from services import common, serialize, ownership

bp = Blueprint("submissions", __name__)

SUBMISSION_TARGETS = {"CLIENT_REVIEW", "OFFER_EXTENDED", "REJECTED", "WITHDRAWN"}


@bp.route("/staffing/submissions", methods=["POST"])
def create_submission():
    _, role = get_user_context()
    require_role(role, {"Recruiter"})
    body = get_json_body()

    job_order_id = common.require_str(body, "job_order_id")
    candidate_id = common.require_str(body, "candidate_id")
    submitted_pay_rate_cents = common.require_int(body, "submitted_pay_rate_cents")

    # Existence (priority 3), body FKs left-to-right per input order.
    jo = common.get_or_404(db.job_orders, job_order_id, errors.ERR_JOB_ORDER_NOT_FOUND)
    cand = common.get_or_404(db.candidates, candidate_id, errors.ERR_CANDIDATE_NOT_FOUND)

    # Skill match (priority 7): candidate must hold the order's required skill.
    if jo["required_skill_code"] not in cand["skill_codes"]:
        raise ApiError(errors.ERR_SKILL_MISMATCH, 409, "Candidate lacks the required skill.")

    rec = common.init_mutable({
        "job_order_id": job_order_id,
        "candidate_id": candidate_id,
        "submitted_pay_rate_cents": submitted_pay_rate_cents,
        "status": "SUBMITTED",
        "rejection_reason": None,
    })
    db.submissions[rec["id"]] = rec
    return object_response(serialize.submission(rec), 201)


@bp.route("/staffing/submissions", methods=["GET"])
def list_submissions():
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client"})
    limit, offset = parse_pagination()

    job_order_filter = request.args.get("job_order_id")
    candidate_filter = request.args.get("candidate_id")
    status_filter = request.args.get("status")

    rows = list(db.submissions.values())
    if job_order_filter is not None:
        rows = [r for r in rows if r["job_order_id"] == job_order_filter]
    if candidate_filter is not None:
        rows = [r for r in rows if r["candidate_id"] == candidate_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if role == "Client":
        rows = [r for r in rows if ownership.submission_client(r) == user_id]

    page, total = paginate(rows, limit, offset)
    return array_response([serialize.submission(r) for r in page], limit, offset, total)


@bp.route("/staffing/submissions/<sid>", methods=["GET"])
def get_submission(sid):
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client"})
    rec = common.get_or_404(db.submissions, sid, errors.ERR_SUBMISSION_NOT_FOUND)
    if role == "Client":
        ownership.client_owns(user_id, ownership.submission_client(rec))
    return object_response(serialize.submission(rec), 200)


@bp.route("/staffing/submissions/<sid>", methods=["PATCH"])
def patch_submission(sid):
    user_id, role = get_user_context()
    # Both Recruiter and Client may PATCH; the specific target governs which.
    require_role(role, {"Recruiter", "Client"})
    rec = common.get_or_404(db.submissions, sid, errors.ERR_SUBMISSION_NOT_FOUND)
    body = get_json_body()
    target = common.require_enum(body, "target_status", SUBMISSION_TARGETS)

    jo = db.job_orders.get(rec["job_order_id"])

    # RBAC by target (PRD 3.3 / roles matrix):
    #   Recruiter: CLIENT_REVIEW, WITHDRAWN
    #   Client:    OFFER_EXTENDED, REJECTED
    recruiter_targets = {"CLIENT_REVIEW", "WITHDRAWN"}
    client_targets = {"OFFER_EXTENDED", "REJECTED"}
    if target in recruiter_targets:
        require_role(role, {"Recruiter"})
    elif target in client_targets:
        require_role(role, {"Client"})
        ownership.client_owns(user_id, ownership.submission_client(rec))

    status = rec["status"]

    if target == "CLIENT_REVIEW":
        if status != "SUBMITTED":
            raise ApiError(errors.ERR_SUBMISSION_BAD_STATE, 409, "Submission is not SUBMITTED.")
        if jo is None or jo["status"] != "OPEN":
            raise ApiError(errors.ERR_JOB_ORDER_NOT_OPEN, 409, "Job order is not OPEN.")
        rec["status"] = "CLIENT_REVIEW"
        common.touch(rec)

    elif target == "OFFER_EXTENDED":
        if status != "INTERVIEWING":
            raise ApiError(errors.ERR_SUBMISSION_BAD_STATE, 409, "Submission is not INTERVIEWING.")
        passed = any(
            iv["submission_id"] == rec["id"] and iv["outcome"] == "PASSED"
            for iv in db.interviews.values()
        )
        if not passed:
            raise ApiError(errors.ERR_NO_PASSED_INTERVIEW, 409, "No interview has PASSED.")
        if jo is None or jo["status"] != "OPEN":
            raise ApiError(errors.ERR_JOB_ORDER_NOT_OPEN, 409, "Job order is not OPEN.")
        rec["status"] = "OFFER_EXTENDED"
        common.touch(rec)

    elif target == "REJECTED":
        if status not in ("CLIENT_REVIEW", "INTERVIEWING", "OFFER_EXTENDED"):
            raise ApiError(errors.ERR_SUBMISSION_BAD_STATE, 409, "Submission cannot be rejected from this state.")
        rec["status"] = "REJECTED"
        rec["rejection_reason"] = common.optional_str(body, "rejection_reason", None)
        common.touch(rec)

    elif target == "WITHDRAWN":
        if status not in ("SUBMITTED", "CLIENT_REVIEW", "INTERVIEWING"):
            raise ApiError(errors.ERR_SUBMISSION_BAD_STATE, 409, "Submission cannot be withdrawn from this state.")
        rec["status"] = "WITHDRAWN"
        common.touch(rec)

    return object_response(serialize.submission(rec), 200)
