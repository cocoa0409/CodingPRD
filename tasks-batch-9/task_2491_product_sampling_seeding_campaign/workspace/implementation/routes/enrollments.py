"""Enrollment creation, eligibility screening and screener resubmission."""

from flask import Blueprint

import clock
import db as store
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import endpoint
from response import collection, single
from services import calculations as calc
from services.gates import (must_exist, require_campaign_status, require_not_banned,
                            require_owner, require_posture_not_frozen)
from validation import field, paginate, parse_body, parse_query

bp = Blueprint("enrollments", __name__)

SCREENING_STATUSES = ("PENDING_SCREEN", "SCREEN_PASSED", "SCREEN_FAILED", "SCREEN_REVOKED")
OBLIGATION_STATUSES = ("NONE", "SAMPLE_SENT", "REVIEW_DUE", "REVIEW_FULFILLED", "FORFEITED")
MAX_SCREEN_ATTEMPTS = 3

CREATE_FIELDS = [
    field("campaign_id", "id", required=True),
    field("panelist_id", "id", required=True),
    field("screening_answers", "object", required=True),
]

RESUBMIT_FIELDS = [
    field("screening_answers", "object", required=True),
]

LIST_FILTERS = [
    field("campaign_id", "string"),
    field("panelist_id", "string"),
    field("screening_status", "enum", values=SCREENING_STATUSES),
    field("obligation_status", "enum", values=OBLIGATION_STATUSES),
    field("holdout_flag", "boolean"),
]


@bp.post("/enrollments")
@endpoint(["Panelist", "CampaignManager"])
def create_enrollment():
    body, _ = parse_body(CREATE_FIELDS)
    campaign = must_exist("campaigns", body["campaign_id"], "Campaign")
    panelist = must_exist("panelists", body["panelist_id"], "Panelist")

    require_owner(panelist["id"])
    require_campaign_status(campaign, ("SCREENING_OPEN", "SAMPLING_ACTIVE"))
    require_not_banned(panelist)

    # rung 23 — one live enrollment per campaign-and-panelist pair
    for existing in store.campaign_enrollments(campaign["id"]):
        if (existing["panelist_id"] == panelist["id"]
                and existing["screening_status"] != "SCREEN_REVOKED"):
            raise ApiError("ERR_DUPLICATE_ENROLLMENT",
                           "The panelist already holds an enrollment on this campaign")

    row = new_row()
    row.update({
        "campaign_id": campaign["id"],
        "panelist_id": panelist["id"],
        "screening_answers": body["screening_answers"],
        "enrollment_seq": campaign["enrollment_count"] + 1,
        "holdout_flag": False,
        "screening_status": "PENDING_SCREEN",
        "obligation_status": "NONE",
        "screening_failure_reason": None,
        "screen_attempt_count": 0,
        "review_due_at": None,
        "fraud_score_at_screening": None,
    })
    db.enrollments[row["id"]] = row

    campaign["enrollment_count"] += 1
    touch(campaign)
    return single(serializers.enrollment(row), 201)


@bp.get("/enrollments/<enrollment_id>")
@endpoint(["CampaignManager", "ComplianceModerator", "FulfillmentOps", "Panelist",
           "PlatformAdmin"])
def get_enrollment(enrollment_id):
    parse_body([])
    row = must_exist("enrollments", enrollment_id, "Enrollment")
    require_owner(row["panelist_id"])
    return single(serializers.enrollment(row))


@bp.get("/enrollments")
@endpoint(["CampaignManager", "ComplianceModerator", "FulfillmentOps", "PlatformAdmin"])
def list_enrollments():
    query = parse_query(LIST_FILTERS)
    rows = ordered(db.enrollments.values())
    if query["campaign_id"] is not None:
        rows = [r for r in rows if r["campaign_id"] == query["campaign_id"]]
    if query["panelist_id"] is not None:
        rows = [r for r in rows if r["panelist_id"] == query["panelist_id"]]
    if query["screening_status"] is not None:
        rows = [r for r in rows if r["screening_status"] == query["screening_status"]]
    if query["obligation_status"] is not None:
        rows = [r for r in rows if r["obligation_status"] == query["obligation_status"]]
    if query["holdout_flag"] is not None:
        rows = [r for r in rows if bool(r["holdout_flag"]) == query["holdout_flag"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.enrollment(r) for r in page], len(rows),
                      query["limit"], query["offset"])


@bp.post("/enrollments/<enrollment_id>/screen")
@endpoint(["CampaignManager"])
def screen_enrollment(enrollment_id):
    parse_body([])
    enrollment = must_exist("enrollments", enrollment_id, "Enrollment")
    if enrollment["screening_status"] != "PENDING_SCREEN":
        raise ApiError("ERR_ENROLLMENT_NOT_SCREENABLE",
                       "Screening status is '%s', not PENDING_SCREEN"
                       % enrollment["screening_status"])
    campaign = store.campaign_of_enrollment(enrollment)
    require_campaign_status(campaign, ("SCREENING_OPEN", "SAMPLING_ACTIVE"))
    panelist = store.panelist_of_enrollment(enrollment)
    require_not_banned(panelist)
    require_posture_not_frozen(campaign)

    enrollment["screen_attempt_count"] += 1
    score = calc.rescore_panelist(panelist, "SCREENING")
    enrollment["fraud_score_at_screening"] = score

    passed, reason = calc.eligibility_screening_decision(enrollment, panelist, campaign)
    if passed:
        enrollment["screening_status"] = "SCREEN_PASSED"
        enrollment["screening_failure_reason"] = None
        if calc.holdout_flag_for(campaign, enrollment["enrollment_seq"]):
            enrollment["holdout_flag"] = True
            campaign["holdout_enrollment_count"] += 1
            touch(campaign)
    else:
        enrollment["screening_status"] = "SCREEN_FAILED"
        enrollment["screening_failure_reason"] = reason
    touch(enrollment)
    return single(serializers.enrollment(enrollment))


@bp.post("/enrollments/<enrollment_id>/resubmit-screening")
@endpoint(["Panelist"])
def resubmit_screening(enrollment_id):
    body, _ = parse_body(RESUBMIT_FIELDS)
    enrollment = must_exist("enrollments", enrollment_id, "Enrollment")
    require_owner(enrollment["panelist_id"])
    if enrollment["screening_status"] != "SCREEN_FAILED":
        raise ApiError("ERR_ENROLLMENT_NOT_SCREENABLE",
                       "Screening status is '%s', not SCREEN_FAILED"
                       % enrollment["screening_status"])
    panelist = store.panelist_of_enrollment(enrollment)
    require_not_banned(panelist)
    if enrollment["screen_attempt_count"] >= MAX_SCREEN_ATTEMPTS:
        raise ApiError("ERR_ENROLLMENT_NOT_SCREENABLE",
                       "The three evaluated screening attempts are exhausted")

    enrollment["screening_answers"] = body["screening_answers"]
    enrollment["screening_status"] = "PENDING_SCREEN"
    enrollment["screening_failure_reason"] = None
    touch(enrollment)
    return single(serializers.enrollment(enrollment))


@bp.get("/enrollments/<enrollment_id>/purchase-matches")
@endpoint(["CampaignManager", "PlatformAdmin"])
def list_enrollment_purchase_matches(enrollment_id):
    query = parse_query([])
    enrollment = must_exist("enrollments", enrollment_id, "Enrollment")
    rows = [m for m in ordered(db.purchase_matches.values())
            if m["enrollment_id"] == enrollment["id"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.purchase_match(r) for r in page], len(rows),
                      query["limit"], query["offset"])
