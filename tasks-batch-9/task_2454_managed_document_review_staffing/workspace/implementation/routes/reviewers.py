"""Reviewer sourcing, the credential axis and the scorecard (PRD 3.3)."""

from flask import Blueprint, request

from db import base_row, by_creation, db, touch
from errors import ApiError
from middleware import (
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QC_LEAD,
    ROLE_REVIEWER,
    ROLE_STAFFING_COORDINATOR,
    body,
    require_roles,
)
from response import created_response, object_response, paginated
from services import cascade, compute
from validation import (
    bad,
    opt_bool,
    opt_int,
    present,
    req_code_array,
    req_enum,
    req_int,
    req_str,
    req_tag_array,
)

bp = Blueprint("reviewers", __name__)

TIERS = ("FIRST_PASS", "SECOND_LEVEL")
CREDENTIAL_STATUSES = ("UNVERIFIED", "VERIFIED", "LAPSED")
WEIGHTINGS = ("SAMPLE_WEIGHTED", "ASSIGNMENT_MEAN")
EVENT_TYPES = ("PACE_SHORTFALL", "ACCURACY_MISS", "PRIVILEGE_MISS", "QC_FAILURE",
               "REMOVAL", "CLEARED_STRIKE")


@bp.route("/reviewers", methods=["POST"])
def create_reviewer():
    require_roles(ROLE_STAFFING_COORDINATOR)
    payload = body()
    full_name = req_str(payload, "full_name", 1, 120)
    bar_admissions = req_code_array(payload, "bar_admissions", allow_empty=True)
    languages = req_code_array(payload, "languages", allow_empty=False, must_include="EN")
    subject_matter_tags = req_tag_array(payload, "subject_matter_tags", allow_empty=True)
    tier = req_enum(payload, "tier", TIERS)
    hourly_cost_cents = req_int(payload, "hourly_cost_cents", 1)
    max_concurrent_batches = opt_int(payload, "max_concurrent_batches", 1, None, 2)
    remote_work_authorized = opt_bool(payload, "remote_work_authorized", False)

    row = base_row()
    row.update({
        "full_name": full_name,
        "bar_admissions": bar_admissions,
        "languages": languages,
        "subject_matter_tags": subject_matter_tags,
        "tier": tier,
        "hourly_cost_cents": hourly_cost_cents,
        "max_concurrent_batches": max_concurrent_batches,
        "remote_work_authorized": remote_work_authorized,
        "credential_status": "UNVERIFIED",
        "engagement_status": "SOURCED",
        "removed_at": None,
    })
    db.reviewers[row["id"]] = row
    return created_response(compute.reviewer_out(row))


@bp.route("/reviewers/<reviewer_id>", methods=["GET"])
def read_reviewer(reviewer_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_REVIEWER)
    reviewer = compute.get_reviewer(reviewer_id)
    return object_response(compute.reviewer_out(reviewer))


@bp.route("/reviewers", methods=["GET"])
def list_reviewers():
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR, ROLE_QC_LEAD)
    rows = by_creation(list(db.reviewers.values()))
    engagement_status = request.args.get("engagement_status")
    credential_status = request.args.get("credential_status")
    tier = request.args.get("tier")
    if engagement_status:
        rows = [r for r in rows if r["engagement_status"] == engagement_status]
    if credential_status:
        rows = [r for r in rows if r["credential_status"] == credential_status]
    if tier:
        rows = [r for r in rows if r["tier"] == tier]
    return paginated(rows, compute.reviewer_out)


@bp.route("/reviewers/<reviewer_id>/credential-status", methods=["POST"])
def set_credential_status(reviewer_id):
    require_roles(ROLE_STAFFING_COORDINATOR)
    reviewer = compute.get_reviewer(reviewer_id)
    payload = body()
    to_status = req_enum(payload, "to_status", CREDENTIAL_STATUSES)
    bar_admissions = None
    if present(payload, "bar_admissions"):
        bar_admissions = req_code_array(payload, "bar_admissions", allow_empty=True)

    current = reviewer["credential_status"]
    if to_status == "VERIFIED":
        if current not in ("UNVERIFIED", "LAPSED"):
            raise ApiError("ERR_INVALID_STATE",
                           "VERIFIED is reachable from UNVERIFIED or LAPSED only.")
    elif to_status == "LAPSED":
        if current != "VERIFIED":
            raise ApiError("ERR_INVALID_STATE", "LAPSED is reachable from VERIFIED only.")
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "UNVERIFIED is not a reachable credential status.")

    if reviewer["engagement_status"] == "REMOVED":
        raise ApiError("ERR_REVIEWER_REMOVED", "The reviewer has been removed.")

    reviewer["credential_status"] = to_status
    if bar_admissions is not None:
        reviewer["bar_admissions"] = bar_admissions
    touch(reviewer)
    cascade.sync_staffing_for_reviewer_matters(reviewer["id"])
    return object_response(compute.reviewer_out(reviewer))


@bp.route("/reviewers/<reviewer_id>/scorecard-events", methods=["GET"])
def list_scorecard_events(reviewer_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_REVIEWER)
    reviewer = compute.get_reviewer(reviewer_id)
    rows = compute.events_of_reviewer(reviewer["id"])
    event_type = request.args.get("event_type")
    if event_type:
        rows = [r for r in rows if r["event_type"] == event_type]
    return paginated(rows, compute.scorecard_event_out)


@bp.route("/reviewers/<reviewer_id>/scorecard", methods=["GET"])
def read_scorecard(reviewer_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_REVIEWER)
    reviewer = compute.get_reviewer(reviewer_id)
    weighting = request.args.get("weighting")
    if weighting is None or weighting == "":
        weighting = "SAMPLE_WEIGHTED"
    if weighting not in WEIGHTINGS:
        raise bad("'weighting' must be one of %s." % ", ".join(WEIGHTINGS))
    _samples, sampled, errors = compute.accuracy_totals(reviewer["id"])
    return object_response({
        "reviewer_id": reviewer["id"],
        "weighting_applied": weighting,
        "accuracy_score": compute.num(compute.accuracy_score(reviewer["id"], weighting), 4),
        "sampled_document_count": sampled,
        "total_error_count": errors,
        "scorecard_strikes": compute.scorecard_strikes(reviewer["id"]),
        "pace_dph": compute.num(compute.reviewer_pace_dph(reviewer["id"]), 2),
        "engagement_status": reviewer["engagement_status"],
        "removal_threshold": compute.REMOVAL_STRIKE_THRESHOLD,
        "removal_recommended": compute.removal_grounds_met(reviewer["id"]),
    })
