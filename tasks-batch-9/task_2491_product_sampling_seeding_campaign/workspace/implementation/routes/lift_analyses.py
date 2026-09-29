"""Campaign lift measurement and the diversion-penalty cost figures."""

from flask import Blueprint

import clock
import serializers
from db import db, new_row, ordered, touch
from middleware import endpoint
from response import collection, single
from services import calculations as calc
from services.gates import check_campaign_version, must_exist, require_campaign_status
from validation import field, paginate, parse_body, parse_query

bp = Blueprint("lift_analyses", __name__)

VARIANTS = ("ITT", "PER_PROTOCOL")
MEASURABLE_CAMPAIGN_STATUSES = ("REVIEW_WINDOW", "CLOSED")

CREATE_FIELDS = [
    field("campaign_id", "id", required=True),
    field("variant", "enum", required=True, values=VARIANTS),
    field("expected_campaign_version", "integer", required=True),
]

LIST_FILTERS = [
    field("campaign_id", "string"),
    field("variant", "enum", values=VARIANTS),
]


@bp.post("/lift-analyses")
@endpoint(["CampaignManager"])
def create_analysis():
    body, _ = parse_body(CREATE_FIELDS)
    campaign = must_exist("campaigns", body["campaign_id"], "Campaign")
    require_campaign_status(campaign, MEASURABLE_CAMPAIGN_STATUSES)
    check_campaign_version(campaign, body["expected_campaign_version"])

    metrics = calc.compute_lift(campaign, body["variant"])

    for existing in ordered(db.lift_analyses.values()):
        if existing["campaign_id"] == campaign["id"] and not existing["superseded"]:
            existing["superseded"] = True
            touch(existing)

    row = new_row()
    row.update({
        "campaign_id": campaign["id"],
        "variant": body["variant"],
        "superseded": False,
        "computed_at": clock.now_iso(),
    })
    row.update(metrics)
    db.lift_analyses[row["id"]] = row

    touch(campaign)
    return single(serializers.lift_analysis(row), 201)


@bp.get("/lift-analyses/<lift_analysis_id>")
@endpoint(["CampaignManager", "PlatformAdmin"])
def get_analysis(lift_analysis_id):
    parse_body([])
    row = must_exist("lift_analyses", lift_analysis_id, "Lift analysis")
    return single(serializers.lift_analysis(row))


@bp.get("/lift-analyses")
@endpoint(["CampaignManager", "PlatformAdmin"])
def list_analyses():
    query = parse_query(LIST_FILTERS)
    rows = ordered(db.lift_analyses.values())
    if query["campaign_id"] is not None:
        rows = [r for r in rows if r["campaign_id"] == query["campaign_id"]]
    if query["variant"] is not None:
        rows = [r for r in rows if r["variant"] == query["variant"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.lift_analysis(r) for r in page], len(rows),
                      query["limit"], query["offset"])
