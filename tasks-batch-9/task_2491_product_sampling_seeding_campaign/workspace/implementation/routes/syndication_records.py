"""Retailer syndication queueing and dispatch."""

from flask import Blueprint

import clock
import db as store
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import endpoint
from response import collection, single
from services import calculations as calc
from services.gates import (must_exist, require_not_banned, require_not_flagged,
                            require_posture_not_frozen)
from validation import field, paginate, parse_body, parse_query

bp = Blueprint("syndication_records", __name__)

SYNDICATION_STATUSES = ("QUEUED", "SYNDICATED", "REJECTED", "TAKEDOWN_REQUESTED")

CREATE_FIELDS = [
    field("review_submission_id", "id", required=True),
    field("retailer_id", "id", required=True),
]

LIST_FILTERS = [
    field("review_submission_id", "string"),
    field("retailer_id", "string"),
    field("status", "enum", values=SYNDICATION_STATUSES),
]


def _require_posture_not_restricted(campaign):
    """Rung 17 — publication requires an OPEN posture."""
    if campaign["compliance_posture"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_POSTURE_RESTRICTED",
                       "The campaign's compliance posture is '%s', not OPEN"
                       % campaign["compliance_posture"])


def _require_feed_accepting(retailer):
    """Rung 21."""
    if retailer["feed_status"] != "ACCEPTING":
        raise ApiError("ERR_RETAILER_FEED_PAUSED",
                       "The retailer's review feed is PAUSED")


@bp.post("/syndication-records")
@endpoint(["CampaignManager", "FulfillmentOps"])
def queue_record():
    body, _ = parse_body(CREATE_FIELDS)
    review = must_exist("review_submissions", body["review_submission_id"], "Review")
    retailer = must_exist("retailers", body["retailer_id"], "Retailer")

    if review["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_REVIEW_STATE",
                       "Review status is '%s', not APPROVED" % review["status"])

    panelist = store.panelist_of_review(review)
    require_not_banned(panelist)
    require_not_flagged(panelist)

    campaign = store.campaign_of_review(review)
    require_posture_not_frozen(campaign)
    _require_posture_not_restricted(campaign)

    # rung 20
    if retailer["id"] not in (campaign["syndication_retailer_ids"] or []):
        raise ApiError("ERR_RETAILER_NOT_IN_CAMPAIGN",
                       "The retailer is not cleared by the owning campaign")

    _require_feed_accepting(retailer)

    # rung 24
    for existing in store.review_syndication_records(review["id"]):
        if existing["retailer_id"] == retailer["id"] and existing["status"] != "REJECTED":
            raise ApiError("ERR_DUPLICATE_SYNDICATION_TARGET",
                           "A non-rejected record already targets this retailer")

    row = new_row()
    row.update({
        "review_submission_id": review["id"],
        "retailer_id": retailer["id"],
        "status": "QUEUED",
        "rejection_reason": None,
        "syndicated_at": None,
        "takedown_requested_at": None,
    })
    db.syndication_records[row["id"]] = row
    return single(serializers.syndication_record(row), 201)


@bp.get("/syndication-records/<syndication_record_id>")
@endpoint(["CampaignManager", "FulfillmentOps", "ComplianceModerator", "PlatformAdmin"])
def get_record(syndication_record_id):
    parse_body([])
    row = must_exist("syndication_records", syndication_record_id, "Syndication record")
    return single(serializers.syndication_record(row))


@bp.get("/syndication-records")
@endpoint(["CampaignManager", "FulfillmentOps", "ComplianceModerator", "PlatformAdmin"])
def list_records():
    query = parse_query(LIST_FILTERS)
    rows = ordered(db.syndication_records.values())
    if query["review_submission_id"] is not None:
        rows = [r for r in rows
                if r["review_submission_id"] == query["review_submission_id"]]
    if query["retailer_id"] is not None:
        rows = [r for r in rows if r["retailer_id"] == query["retailer_id"]]
    if query["status"] is not None:
        rows = [r for r in rows if r["status"] == query["status"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.syndication_record(r) for r in page], len(rows),
                      query["limit"], query["offset"])


@bp.post("/syndication-records/<syndication_record_id>/dispatch")
@endpoint(["FulfillmentOps"])
def dispatch_record(syndication_record_id):
    parse_body([])
    record = must_exist("syndication_records", syndication_record_id,
                        "Syndication record")
    if record["status"] != "QUEUED":
        raise ApiError("ERR_INVALID_SYNDICATION_STATE",
                       "Record status is '%s', not QUEUED" % record["status"])

    review = store.review_of_syndication(record)
    if review is None or review["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_REVIEW_STATE",
                       "The review is no longer APPROVED")

    panelist = store.panelist_of_review(review)
    require_not_flagged(panelist)

    campaign = store.campaign_of_review(review)
    require_posture_not_frozen(campaign)
    _require_posture_not_restricted(campaign)

    retailer = store.retailer_of_syndication(record)
    _require_feed_accepting(retailer)

    accepted, reason = calc.syndication_decision(review, retailer, panelist)
    if accepted:
        record["status"] = "SYNDICATED"
        record["syndicated_at"] = clock.now_iso()
        touch(record)
        campaign["syndicated_review_count"] += 1
        touch(campaign)
    else:
        record["status"] = "REJECTED"
        record["rejection_reason"] = reason
        touch(record)

    return single(serializers.syndication_record(record))
