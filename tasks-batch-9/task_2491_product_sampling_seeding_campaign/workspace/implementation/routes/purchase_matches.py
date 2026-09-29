"""Matched-purchase ingestion from the conversion feed."""

from flask import Blueprint

import clock
import db as store
import serializers
from db import db, new_row, ordered
from errors import ApiError
from middleware import endpoint
from response import collection, single
from services import calculations as calc
from services.gates import must_exist
from validation import field, paginate, parse_body, parse_query

bp = Blueprint("purchase_matches", __name__)

CREATE_FIELDS = [
    field("enrollment_id", "id", required=True),
    field("retailer_channel_code", "string", required=True),
    field("purchase_amount_cents", "integer", required=True, minimum=0),
    field("purchased_at", "datetime", required=True),
    field("match_confidence", "number", required=True, minimum=0, maximum=1,
          max_decimals=4),
]

LIST_FILTERS = [
    field("enrollment_id", "string"),
    field("qualified", "boolean"),
]


def _conversion_window(campaign):
    window_from = clock.sec(clock.parse(campaign["sampling_window_start"]))
    window_to = (clock.sec(clock.parse(campaign["sampling_window_end"]))
                 + clock.days(calc.CONVERSION_TAIL_DAYS))
    return window_from, window_to


@bp.post("/purchase-matches")
@endpoint(["PlatformAdmin"])
def ingest_match():
    body, _ = parse_body(CREATE_FIELDS)
    enrollment = must_exist("enrollments", body["enrollment_id"], "Enrollment")
    campaign = store.campaign_of_enrollment(enrollment)

    window_from, window_to = _conversion_window(campaign)
    purchased_at = clock.sec(clock.parse(body["purchased_at"]))

    # rung 32
    inside = window_from <= purchased_at <= window_to
    if not inside:
        raise ApiError("ERR_PURCHASE_MATCH_OUT_OF_WINDOW",
                       "purchased_at falls outside the campaign conversion window")

    row = new_row(versioned=False)
    row.update({
        "enrollment_id": enrollment["id"],
        "retailer_channel_code": body["retailer_channel_code"],
        "purchase_amount_cents": body["purchase_amount_cents"],
        "purchased_at": body["purchased_at"],
        "match_confidence": body["match_confidence"],
        "qualified": bool(inside
                          and body["match_confidence"] >= calc.MATCH_CONFIDENCE_FLOOR),
    })
    db.purchase_matches[row["id"]] = row
    return single(serializers.purchase_match(row), 201)


@bp.get("/purchase-matches/<purchase_match_id>")
@endpoint(["CampaignManager", "PlatformAdmin"])
def get_match(purchase_match_id):
    parse_body([])
    row = must_exist("purchase_matches", purchase_match_id, "Purchase match")
    return single(serializers.purchase_match(row))


@bp.get("/purchase-matches")
@endpoint(["CampaignManager", "PlatformAdmin"])
def list_matches():
    query = parse_query(LIST_FILTERS)
    rows = ordered(db.purchase_matches.values())
    if query["enrollment_id"] is not None:
        rows = [r for r in rows if r["enrollment_id"] == query["enrollment_id"]]
    if query["qualified"] is not None:
        rows = [r for r in rows if bool(r["qualified"]) == query["qualified"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.purchase_match(r) for r in page], len(rows),
                      query["limit"], query["offset"])
