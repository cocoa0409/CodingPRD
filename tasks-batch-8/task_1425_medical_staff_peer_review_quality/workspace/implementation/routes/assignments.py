from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_roles
from response import success
from services import (
    CASE_TERMINAL, get_body, is_int, check_score_range, get_assignment,
    pub, touch, make_versioned, now_iso, submitted_assignments,
)

bp = Blueprint("assignments", __name__)

STAFF_ROLES = ("QualityDirector", "PeerReviewCoordinator", "CommitteeMember")


@bp.get("/peer-review/assignments/<aid>")
def get_one_assignment(aid):
    require_roles(*STAFF_ROLES)
    return success(pub(get_assignment(aid)))


def _validate_scores(b):
    """Stage 8: presence (ERR_VALIDATION) before range (ERR_SCORE_OUT_OF_RANGE)."""
    care_raw = b.get("care_appropriateness_score")
    if care_raw is None:
        raise ApiError("ERR_VALIDATION", 400, "care_appropriateness_score is required")
    ofi_raw = b.get("ofi_score")
    care = check_score_range(care_raw, "care_appropriateness_score")
    ofi = None
    if ofi_raw is not None:
        ofi = check_score_range(ofi_raw, "ofi_score")
    return care, ofi


@bp.post("/peer-review/assignments/<aid>/submit")
def submit_assignment(aid):
    actor = require_roles("CommitteeMember")
    asg = get_assignment(aid)
    # stage 4: ownership — only the assigned member may submit
    if asg["reviewer_id"] != actor.id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", 403, "only the assigned reviewer may submit")
    case = store.cases[asg["case_id"]]
    # stage 5: state legality (terminal variant first)
    if case["status"] in CASE_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "case is in a terminal state")
    if asg["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "assignment is not PENDING")
    if case["status"] not in ("ASSIGNED", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409, "case state does not allow submission")
    b = get_body()
    # stage 6: optimistic concurrency
    ecv = b.get("expected_case_version")
    if is_int(ecv) and ecv != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_case_version is stale")
    # stage 8: input shape
    if not is_int(ecv):
        raise ApiError("ERR_VALIDATION", 400, "expected_case_version is required and must be an integer")
    care, ofi = _validate_scores(b)
    # side effects (PRD 3.4): five things at once
    asg["status"] = "SUBMITTED"
    asg["submitted_at"] = now_iso()
    asg["care_appropriateness_score"] = care
    asg["ofi_score"] = ofi
    touch(asg)
    member = store.members.get(asg["reviewer_id"])
    if member is not None:
        member["reliability_completed_count"] += 1
        touch(member)
    if case["status"] == "ASSIGNED":
        case["status"] = "IN_REVIEW"
    touch(case)
    if case["status"] == "IN_REVIEW" and len(submitted_assignments(case["id"])) == 3:
        # third distinct submission: auto-open the Deliberation
        case["status"] = "DELIBERATION"
        d = make_versioned()
        d.update({
            "case_id": case["id"],
            "status": "OPEN",
            "rating": None,
            "rationale_note": None,
            "reconsideration_note": None,
            "opened_at": now_iso(),
            "finalized_at": None,
            "_finalized_dt": None,
            "reconsidered_at": None,
        })
        store.deliberations[d["id"]] = d
    return success(pub(asg))


@bp.post("/peer-review/assignments/<aid>/revise")
def revise_assignment(aid):
    actor = require_roles("CommitteeMember")
    asg = get_assignment(aid)
    if asg["reviewer_id"] != actor.id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", 403, "only the original reviewer may revise")
    case = store.cases[asg["case_id"]]
    if case["status"] in CASE_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "case is in a terminal state")
    if asg["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "assignment is not SUBMITTED")
    if case["status"] != "COMMITTEE_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "revision is only allowed during COMMITTEE_REVIEW")
    b = get_body()
    care, ofi = _validate_scores(b)
    asg["care_appropriateness_score"] = care
    asg["ofi_score"] = ofi  # overwrites both; submitted_at untouched
    touch(asg)
    touch(case)  # reliability_completed_count NOT incremented
    return success(pub(asg))
