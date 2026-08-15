"""PlanSubmission and PlanReviewComment endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, check_tenant_ownership, get_project_tenant_ownership
from response import success_object, success_created, success_list
from errors import (
    not_found, invalid_request, invalid_state, APIError,
    ERR_BLOCKING_COMMENTS_OPEN,
)
from services.util import (
    make_common_fields, bump_version, get_pagination_params, paginate,
    require_fields, is_str,
)

bp = Blueprint("plans", __name__)


def _get_sub_or_404(sid):
    s = store.plan_submissions.get(sid)
    if not s:
        raise not_found("PlanSubmission not found")
    return s


def _next_revision_no(project_id):
    existing = [
        s for s in store.plan_submissions.values() if s["project_id"] == project_id
    ]
    if not existing:
        return 1
    return max(s["revision_no"] for s in existing) + 1


@bp.route("/api/ti-projects/<id>/plan-submissions", methods=["POST"])
def create_plan_submission(id):
    user_id, role = require_roles("TenantRep")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")
    check_tenant_ownership(user_id, proj["lease_id"])
    if proj["status"] != "PLAN_REVIEW":
        raise invalid_state("Project must be in PLAN_REVIEW")

    body = request.get_json(silent=True) or {}
    require_fields(body, ["drawing_set_ref"])
    if not is_str(body["drawing_set_ref"]):
        raise invalid_request("drawing_set_ref must be a string")

    # Supersede prior REVISION_REQUIRED submission
    for s in store.plan_submissions.values():
        if s["project_id"] == id and s["status"] == "REVISION_REQUIRED":
            s["status"] = "SUPERSEDED"
            bump_version(s)

    rec = make_common_fields()
    rec.update({
        "project_id": id,
        "revision_no": _next_revision_no(id),
        "drawing_set_ref": body["drawing_set_ref"],
        "review_round": 0,
        "submitted_at": store.now(),
        "status": "SUBMITTED",
    })
    store.plan_submissions[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/ti-projects/<id>/plan-submissions", methods=["GET"])
def list_plan_submissions(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")
    if role == "TenantRep":
        check_tenant_ownership(user_id, proj["lease_id"])
    limit, offset = get_pagination_params()
    items = [s for s in store.plan_submissions.values() if s["project_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/plan-submissions/<id>", methods=["GET"])
def get_plan_submission(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    sub = _get_sub_or_404(id)
    if role == "TenantRep":
        get_project_tenant_ownership(user_id, sub["project_id"])
    return success_object(sub)


def _check_project_plan_review(sub):
    proj = store.ti_projects.get(sub["project_id"])
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] != "PLAN_REVIEW":
        raise invalid_state("Project must be in PLAN_REVIEW")


@bp.route("/api/plan-submissions/<id>/start-review", methods=["POST"])
def start_review(id):
    require_roles("LandlordPM")
    sub = _get_sub_or_404(id)
    _check_project_plan_review(sub)
    if sub["status"] != "SUBMITTED":
        raise invalid_state("PlanSubmission must be in SUBMITTED")
    sub["status"] = "UNDER_REVIEW"
    bump_version(sub)
    return success_object(sub)


@bp.route("/api/plan-submissions/<id>/approve", methods=["POST"])
def approve_submission(id):
    require_roles("LandlordPM")
    sub = _get_sub_or_404(id)
    _check_project_plan_review(sub)
    if sub["status"] != "UNDER_REVIEW":
        raise invalid_state("PlanSubmission must be in UNDER_REVIEW")
    # Block on OPEN BLOCKING comments
    for c in store.plan_review_comments.values():
        if (c["submission_id"] == id
                and c["status"] == "OPEN"
                and c["severity"] == "BLOCKING"):
            raise APIError(ERR_BLOCKING_COMMENTS_OPEN, 422,
                           "OPEN BLOCKING review comments exist")
    sub["status"] = "APPROVED"
    bump_version(sub)
    return success_object(sub)


@bp.route("/api/plan-submissions/<id>/request-revision", methods=["POST"])
def request_revision(id):
    require_roles("LandlordPM")
    sub = _get_sub_or_404(id)
    _check_project_plan_review(sub)
    if sub["status"] != "UNDER_REVIEW":
        raise invalid_state("PlanSubmission must be in UNDER_REVIEW")
    sub["status"] = "REVISION_REQUIRED"
    sub["review_round"] += 1
    bump_version(sub)
    return success_object(sub)


@bp.route("/api/plan-submissions/<id>/reject-final", methods=["POST"])
def reject_final(id):
    require_roles("LandlordPM")
    sub = _get_sub_or_404(id)
    _check_project_plan_review(sub)
    if sub["status"] != "UNDER_REVIEW":
        raise invalid_state("PlanSubmission must be in UNDER_REVIEW")
    sub["status"] = "REJECTED_FINAL"
    bump_version(sub)
    return success_object(sub)


# ---------------------------------------------------------------------------
# PlanReviewComment endpoints
# ---------------------------------------------------------------------------

@bp.route("/api/plan-submissions/<id>/comments", methods=["POST"])
def create_comment(id):
    require_roles("LandlordPM")
    sub = _get_sub_or_404(id)
    if sub["status"] != "UNDER_REVIEW":
        raise invalid_state("PlanSubmission must be in UNDER_REVIEW to add comments")

    body = request.get_json(silent=True) or {}
    require_fields(body, ["comment_text", "severity"])
    if not is_str(body["comment_text"]):
        raise invalid_request("comment_text must be a string")
    if body["severity"] not in ("INFO", "REQUIRED", "BLOCKING"):
        raise invalid_request("severity must be INFO, REQUIRED, or BLOCKING")

    rec = make_common_fields()
    rec.update({
        "submission_id": id,
        "comment_text": body["comment_text"],
        "severity": body["severity"],
        "status": "OPEN",
    })
    store.plan_review_comments[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/plan-submissions/<id>/comments", methods=["GET"])
def list_comments(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    sub = _get_sub_or_404(id)
    if role == "TenantRep":
        get_project_tenant_ownership(user_id, sub["project_id"])
    limit, offset = get_pagination_params()
    items = [c for c in store.plan_review_comments.values() if c["submission_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/plan-review-comments/<id>", methods=["GET"])
def get_comment(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    c = store.plan_review_comments.get(id)
    if not c:
        raise not_found("PlanReviewComment not found")
    if role == "TenantRep":
        sub = store.plan_submissions.get(c["submission_id"])
        if sub:
            get_project_tenant_ownership(user_id, sub["project_id"])
    return success_object(c)


@bp.route("/api/plan-review-comments/<id>/resolve", methods=["POST"])
def resolve_comment(id):
    require_roles("LandlordPM")
    c = store.plan_review_comments.get(id)
    if not c:
        raise not_found("PlanReviewComment not found")
    if c["status"] != "OPEN":
        raise invalid_state("PlanReviewComment must be in OPEN")
    sub = store.plan_submissions.get(c["submission_id"])
    if not sub or sub["status"] != "UNDER_REVIEW":
        raise invalid_state("PlanSubmission must be in UNDER_REVIEW")
    c["status"] = "RESOLVED"
    bump_version(c)
    return success_object(c)
