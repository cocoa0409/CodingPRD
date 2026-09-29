"""Retailer feed registration."""

from flask import Blueprint

import serializers
from db import db, new_row
from middleware import endpoint
from response import single
from services.gates import must_exist
from validation import field, parse_body

bp = Blueprint("retailers", __name__)

FEED_STATUSES = ("ACCEPTING", "PAUSED")

CREATE_FIELDS = [
    field("name", "string", required=True),
    field("feed_status", "enum", default="ACCEPTING", values=FEED_STATUSES),
    field("requires_disclosure_badge", "boolean", default=True),
    field("min_star_rating_accepted", "integer", default=1, minimum=1, maximum=5),
    field("max_reviews_per_panelist_per_month", "integer", default=1, minimum=1),
]


@bp.post("/retailers")
@endpoint(["PlatformAdmin", "CampaignManager"])
def create_retailer():
    body, _ = parse_body(CREATE_FIELDS)
    row = new_row()
    row.update({
        "name": body["name"],
        "feed_status": body["feed_status"],
        "requires_disclosure_badge": bool(body["requires_disclosure_badge"]),
        "min_star_rating_accepted": body["min_star_rating_accepted"],
        "max_reviews_per_panelist_per_month": body["max_reviews_per_panelist_per_month"],
    })
    db.retailers[row["id"]] = row
    return single(serializers.retailer(row), 201)


@bp.get("/retailers/<retailer_id>")
@endpoint(["PlatformAdmin", "CampaignManager", "FulfillmentOps", "ComplianceModerator"])
def get_retailer(retailer_id):
    parse_body([])
    row = must_exist("retailers", retailer_id, "Retailer")
    return single(serializers.retailer(row))
