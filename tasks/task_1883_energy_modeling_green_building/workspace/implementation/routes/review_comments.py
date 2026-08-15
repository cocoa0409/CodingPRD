"""ReviewComment endpoints (PRD 3.5 clarification loop)."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth_headers, require_role
from response import ok
from services import (
    get_attempt,
    get_comment,
    ser_comment,
    stamp,
    sync_project_derived,
    touch,
)
from util import SEVERITIES, as_enum, as_str, body, required

bp = Blueprint("review_comments", __name__)


@bp.post("/review-comments")
def create_comment():
    _user_id, role = auth_headers()
    data = body()
    attempt_id = as_str(required(data, "credit_attempt_id"), "credit_attempt_id")
    severity = as_enum(required(data, "severity"), SEVERITIES, "severity")
    comment_text = as_str(required(data, "comment_text"), "comment_text")
    require_role(role, {"CertificationReviewer"})
    attempt = get_attempt(attempt_id)
    if attempt["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_CREDIT_ATTEMPT_STATE",
            409,
            "Comments can only be posted on an attempt UNDER_REVIEW",
        )
    rec = stamp(
        {
            "credit_attempt_id": attempt["id"],
            "round": attempt["submission_round"],
            "severity": severity,
            "comment_text": comment_text,
            "response_text": None,
            "status": "OPEN",
        }
    )
    DB["review_comments"][rec["id"]] = rec
    attempt["status"] = "CLARIFICATION_REQUESTED"
    touch(attempt)
    # The attempt leaves the optimistic input set; projected level recomputes.
    sync_project_derived(DB["projects"][attempt["project_id"]])
    return ok(ser_comment(rec), status=201)


@bp.post("/review-comments/<comment_id>/respond")
def respond_comment(comment_id):
    user_id, role = auth_headers()
    data = body()
    response_text = as_str(required(data, "response_text"), "response_text")
    require_role(role, {"DocumentationSpecialist"})
    comment = get_comment(comment_id)
    attempt = DB["credit_attempts"][comment["credit_attempt_id"]]
    if user_id != attempt["documentation_owner_id"]:
        raise ApiError(
            "ERR_NOT_DOCUMENTATION_OWNER",
            403,
            "Only the documentation owner may respond",
        )
    if comment["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(
            "ERR_INVALID_COMMENT_STATE", 409, "respond requires OPEN or REOPENED"
        )
    comment["status"] = "ADDRESSED"
    comment["response_text"] = response_text
    touch(comment)
    return ok(ser_comment(comment))


@bp.post("/review-comments/<comment_id>/accept")
def accept_comment(comment_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"CertificationReviewer"})
    comment = get_comment(comment_id)
    attempt = DB["credit_attempts"][comment["credit_attempt_id"]]
    if comment["status"] != "ADDRESSED":
        raise ApiError("ERR_INVALID_COMMENT_STATE", 409, "accept requires ADDRESSED")
    if attempt["status"] != "RESUBMITTED":
        raise ApiError(
            "ERR_INVALID_COMMENT_STATE",
            409,
            "accept requires the attempt to be RESUBMITTED",
        )
    comment["status"] = "ACCEPTED"
    touch(comment)
    return ok(ser_comment(comment))


@bp.post("/review-comments/<comment_id>/reopen")
def reopen_comment(comment_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"CertificationReviewer"})
    comment = get_comment(comment_id)
    attempt = DB["credit_attempts"][comment["credit_attempt_id"]]
    if comment["status"] != "ADDRESSED":
        raise ApiError("ERR_INVALID_COMMENT_STATE", 409, "reopen requires ADDRESSED")
    if attempt["status"] != "RESUBMITTED":
        raise ApiError(
            "ERR_INVALID_COMMENT_STATE",
            409,
            "reopen requires the attempt to be RESUBMITTED",
        )
    comment["status"] = "REOPENED"
    touch(comment)
    return ok(ser_comment(comment))
