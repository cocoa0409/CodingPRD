"""MilestoneSubmission review and resubmission (scaffold section 1.5)."""
from flask import Blueprint

from db import DB, pub, touch
from errors import ApiError
from middleware import auth
from response import ok
from services import REQUIRED_MILESTONE_TYPES, submissions_of
from util import body, opt_str, req_enum, req_str

bp = Blueprint("milestones", __name__)


def _get_submission(submission_id):
    submission = DB["milestone_submissions"].get(submission_id)
    if submission is None:
        raise ApiError(
            "ERR_MILESTONE_SUBMISSION_NOT_FOUND", 404,
            "MilestoneSubmission id does not exist",
        )
    return submission


@bp.route("/interconnection/milestone-submissions/<submission_id>/review", methods=["POST"])
def review_submission(submission_id):
    auth(["QueueAdministrator"])
    submission = _get_submission(submission_id)

    # State: only a PENDING_REVIEW submission may be reviewed.
    if submission["status"] != "PENDING_REVIEW":
        raise ApiError(
            "ERR_MILESTONE_NOT_PENDING_REVIEW", 409,
            "Review requires submission in PENDING_REVIEW",
        )

    data = body()
    decision = req_enum(data, "decision", ("ACCEPTED", "REJECTED"))
    review_note = opt_str(data, "review_note")

    submission["status"] = decision
    submission["review_note"] = review_note
    touch(submission)

    # Acceptance cascade: when every required milestone type holds an ACCEPTED
    # submission, readiness flips satisfied; a QUEUED project advances to READY.
    if decision == "ACCEPTED":
        project = DB["projects"].get(submission["project_id"])
        if project is not None:
            accepted_types = {
                s["milestone_type"]
                for s in submissions_of(project["id"])
                if s["status"] == "ACCEPTED"
            }
            if all(t in accepted_types for t in REQUIRED_MILESTONE_TYPES):
                project["readiness_satisfied"] = True
                if project["status"] == "QUEUED":
                    project["status"] = "READY"
                touch(project)
    return ok(pub(submission), 200)


@bp.route("/interconnection/milestone-submissions/<submission_id>/resubmit", methods=["POST"])
def resubmit_submission(submission_id):
    user_id, _role = auth(["Developer"])
    submission = _get_submission(submission_id)

    # Ownership: only the developer who owns the parent project may resubmit.
    project = DB["projects"].get(submission["project_id"])
    if project is None or project["developer_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_RESOURCE_OWNERSHIP", 403,
            "Developer-role caller does not own the target project",
        )

    # State: resubmission requires REJECTED.
    if submission["status"] != "REJECTED":
        raise ApiError(
            "ERR_MILESTONE_NOT_REJECTED", 409,
            "Resubmit requires submission in REJECTED",
        )

    data = body()
    evidence_uri = req_str(data, "evidence_uri")

    # Fresh evidence replaces the old URI; the recorded review note clears.
    submission["evidence_uri"] = evidence_uri
    submission["review_note"] = None
    submission["status"] = "PENDING_REVIEW"
    touch(submission)
    return ok(pub(submission), 200)
