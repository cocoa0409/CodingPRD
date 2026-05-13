"""Review assignment routes: create, submit-scores, void, get."""
from flask import Blueprint

from clock import format_iso, get_now, parse_iso
from common import check_version, get_json_body, stamp_new, stamp_update
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.anonymity import assignment_view_for, mint_anonymized_alias, project_is_unmasked
from services.audit import emit_audit
from services.calculations import aggregated_score


bp = Blueprint("review_assignments", __name__)


def _project_for_stage(stage):
    return db.projects.get(stage.get("project_id")) if stage else None


@bp.route("/review-assignments", methods=["POST"])
def create_assignment():
    require_roles({"PlatformOps"})
    body = get_json_body()
    stage_id = body.get("review_stage_id")
    submission_id = body.get("submission_id")
    reviewer_id = body.get("reviewer_id")
    stage = db.review_stages.get(stage_id)
    if not stage:
        raise api_error("ERR_FK_NOT_FOUND", "review_stage_id not found")
    submission = db.submissions.get(submission_id)
    if not submission:
        raise api_error("ERR_FK_NOT_FOUND", "submission_id not found")
    # Submission must belong to the same project as the stage
    if submission.get("project_id") != stage.get("project_id"):
        raise api_error("ERR_FK_NOT_FOUND", "submission_id does not belong to stage's project")
    # Reviewer record check: a project Client may be configured as reviewer for FINAL.
    project = _project_for_stage(stage)
    is_client_reviewer = False
    if reviewer_id in db.reviewers:
        reviewer = db.reviewers[reviewer_id]
    elif project and reviewer_id == project.get("client_id"):
        is_client_reviewer = True
        reviewer = None
    else:
        raise api_error("ERR_FK_NOT_FOUND", "reviewer_id not found in reviewer pool")

    # Qualification check (only for pool reviewers).
    if not is_client_reviewer:
        if project and project.get("category_code") not in reviewer.get("categories", []):
            raise api_error("ERR_REVIEWER_NOT_QUALIFIED",
                            "reviewer's categories do not include this project's category")
        # Conflict of interest
        designer_id = submission.get("designer_id")
        if designer_id in reviewer.get("conflict_designer_ids", []):
            raise api_error("ERR_REVIEWER_CONFLICT_OF_INTEREST",
                            "reviewer is in conflict with the submission's designer")
        # Capacity
        pending = sum(
            1 for asn in db.review_assignments.values()
            if asn.get("reviewer_id") == reviewer_id and asn.get("status") == "PENDING"
        )
        if pending >= reviewer.get("max_concurrent_assignments", 20):
            raise api_error("ERR_REVIEWER_CAPACITY_EXCEEDED",
                            "reviewer has reached max_concurrent_assignments")
    else:
        # Client reviewer only allowed for FINAL when client_participates_final=true
        if stage.get("stage_kind") != "FINAL" or not project.get("client_participates_final", False):
            raise api_error("ERR_FORBIDDEN", "Client may only be assigned as reviewer for FINAL stage when client_participates_final=true")

    # Uniqueness across (review_stage_id, submission_id, reviewer_id)
    for asn in db.review_assignments.values():
        if (asn.get("review_stage_id") == stage_id
                and asn.get("submission_id") == submission_id
                and asn.get("reviewer_id") == reviewer_id):
            raise api_error("ERR_REVIEWER_ALREADY_ASSIGNED",
                            "this reviewer is already assigned to this submission in this stage")

    asn = stamp_new({
        "review_stage_id": stage_id,
        "submission_id": submission_id,
        "reviewer_id": reviewer_id,
        "anonymized_alias": mint_anonymized_alias(),
        "criterion_scores": None,
        "aggregated_score": None,
        "status": "PENDING",
        "submitted_at": None,
    })
    db.review_assignments[asn["id"]] = asn
    return success(asn, status=201)


@bp.route("/review-assignments/<review_assignment_id>/submit-scores", methods=["POST"])
def submit_scores(review_assignment_id):
    user_id, role = require_roles({"Reviewer", "Client"})
    asn = db.review_assignments.get(review_assignment_id)
    if not asn:
        raise api_error("ERR_NOT_FOUND", "review assignment not found")
    if asn.get("reviewer_id") != user_id:
        raise api_error("ERR_FORBIDDEN", "only the assigned reviewer can submit scores")
    stage = db.review_stages.get(asn.get("review_stage_id"))
    if not stage:
        raise api_error("ERR_NOT_FOUND", "stage missing")
    project = _project_for_stage(stage)

    if role == "Client":
        if stage.get("stage_kind") != "FINAL" or not (project and project.get("client_participates_final")):
            raise api_error("ERR_FORBIDDEN", "Clients may only submit scores for FINAL stage of own project with client_participates_final=true")
        if project.get("client_id") != user_id:
            raise api_error("ERR_FORBIDDEN", "Clients may only submit scores for own project")

    body = get_json_body()
    check_version(asn, body)
    if asn.get("status") != "PENDING":
        raise api_error("ERR_INVALID_STATE", "only PENDING assignments accept score submissions")
    if get_now() >= parse_iso(stage["ends_at"]):
        raise api_error("ERR_REVIEW_WINDOW_CLOSED", "score submission window closed")

    # Re-evaluate conflict-of-interest (only for reviewer-pool members)
    if role == "Reviewer":
        reviewer = db.reviewers.get(user_id)
        submission = db.submissions.get(asn.get("submission_id"))
        if reviewer and submission and submission.get("designer_id") in reviewer.get("conflict_designer_ids", []):
            raise api_error("ERR_REVIEWER_CONFLICT_OF_INTEREST",
                            "reviewer is in conflict with the submission's designer")

    scores = body.get("criterion_scores")
    if not isinstance(scores, dict):
        raise api_error("ERR_CRITERION_SCORES_INVALID", "criterion_scores must be a map")
    rubric = stage.get("rubric") or {}
    if set(scores.keys()) != set(rubric.keys()):
        raise api_error("ERR_CRITERION_SCORES_INVALID", "criterion_scores keys must equal rubric keys")
    for code, val in scores.items():
        if not isinstance(val, (int, float)) or not (0 <= float(val) <= 100):
            raise api_error("ERR_CRITERION_SCORES_INVALID", f"score for {code} must be 0..100")

    agg = aggregated_score(scores, rubric)
    asn["criterion_scores"] = dict(scores)
    asn["aggregated_score"] = agg
    asn["status"] = "SUBMITTED"
    asn["submitted_at"] = format_iso(get_now())
    stamp_update(asn)
    emit_audit(
        "REVIEW_SUBMITTED",
        "REVIEWER" if role == "Reviewer" else "CLIENT",
        user_id,
        "REVIEW_ASSIGNMENT",
        asn["id"],
        {"aggregated_score": agg},
    )
    return success(asn)


@bp.route("/review-assignments/<review_assignment_id>/void", methods=["POST"])
def void_assignment(review_assignment_id):
    user_id, _ = require_roles({"PlatformOps"})
    asn = db.review_assignments.get(review_assignment_id)
    if not asn:
        raise api_error("ERR_NOT_FOUND", "review assignment not found")
    body = get_json_body()
    check_version(asn, body)
    stage = db.review_stages.get(asn.get("review_stage_id"))
    if not stage:
        raise api_error("ERR_NOT_FOUND", "stage missing")
    if asn.get("status") != "PENDING":
        raise api_error("ERR_INVALID_STATE", "only PENDING assignments can be voided here")
    if stage.get("status") not in {"OPEN", "AGGREGATING"}:
        raise api_error("ERR_INVALID_STATE", "stage must be OPEN or AGGREGATING to void")
    asn["status"] = "VOIDED"
    asn["void_reason"] = body.get("reason")
    stamp_update(asn)
    emit_audit(
        "REVIEW_VOIDED",
        "PLATFORM",
        user_id,
        "REVIEW_ASSIGNMENT",
        asn["id"],
        {"reason": body.get("reason")},
    )
    return success(asn)


@bp.route("/review-assignments/<review_assignment_id>", methods=["GET"])
def get_assignment(review_assignment_id):
    user_id, role = require_roles({"PlatformOps", "Reviewer", "Client"})
    asn = db.review_assignments.get(review_assignment_id)
    if not asn:
        raise api_error("ERR_NOT_FOUND", "review assignment not found")
    # Reviewer can only fetch own assignments; Client can fetch for own project
    stage = db.review_stages.get(asn.get("review_stage_id"))
    project = _project_for_stage(stage) if stage else None
    if role == "Reviewer" and asn.get("reviewer_id") != user_id:
        raise api_error("ERR_FORBIDDEN", "Reviewers can only fetch their own assignments")
    if role == "Client" and (not project or project.get("client_id") != user_id):
        raise api_error("ERR_FORBIDDEN", "Clients can only fetch assignments for their own projects")
    return success(assignment_view_for(asn, role))
