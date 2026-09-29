"""Competitive analyses: the six-step concentration screen (PRD 3.5)."""
from flask import Blueprint

import aggregates
from db import db, new_record, serialize
from errors import ApiError
from helpers import fetch, fetch_fk, list_and_respond
from middleware import ALL_ROLES, ROLE_ANALYST, get_body, req_str, require_roles
from response import object_response

analyses_bp = Blueprint("analyses", __name__)


@analyses_bp.post("/competitive-analyses")
@require_roles(ROLE_ANALYST)
def create_analysis():
    body = get_body(required=True)
    application_id = req_str(body, "application_id")
    market_id = req_str(body, "market_id")

    application = fetch_fk("applications", application_id)
    market = fetch_fk("markets", market_id)

    totals = aggregates.deposits_by_institution(market["id"])
    if totals.get(application["acquirer_id"], 0) <= 0 or totals.get(
        application["target_id"], 0
    ) <= 0:
        raise ApiError(
            "ERR_NO_MARKET_OVERLAP",
            "both parties must hold an includable branch in the market",
        )
    for existing in db.analyses.values():
        if (
            existing["application_id"] == application["id"]
            and existing["market_id"] == market["id"]
        ):
            raise ApiError(
                "ERR_DUPLICATE_ANALYSIS", "this application and market are already analyzed"
            )

    fields = {"application_id": application["id"], "market_id": market["id"]}
    fields.update(aggregates.compute_analysis_figures(application, market))
    record = new_record(fields)
    db.analyses[record["id"]] = record
    aggregates.rollup_posture(application)
    return object_response(serialize(record), 201)


@analyses_bp.get("/competitive-analyses/<record_id>")
@require_roles(*ALL_ROLES)
def get_analysis(record_id):
    return object_response(serialize(fetch("analyses", record_id)))


@analyses_bp.get("/competitive-analyses")
@require_roles(*ALL_ROLES)
def list_analyses():
    return list_and_respond("analyses", ("application_id", "market_id", "screen_result"))
