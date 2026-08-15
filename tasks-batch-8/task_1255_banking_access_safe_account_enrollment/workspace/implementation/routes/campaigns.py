"""OutreachCampaign endpoints."""

import db
from errors import (
    err_not_found, err_invalid_state, err_validation, raise_err,
    ERR_CAMPAIGN_OVERLAP, ERR_CAMPAIGN_BUDGET_EXCEEDED,
)
from middleware import require_roles, get_json_body, require_fields, check_string, check_int
from response import success_object
from services.common import new_entity, touch

REGIONAL_CAP_CENTS = 500000


def _serialize(c):
    return dict(c)


def register(bp):
    @bp.route("/outreach-campaigns", methods=["POST"])
    def create_campaign():
        require_roles("CoalitionAdmin")
        body = get_json_body()
        require_fields(body, ["name", "zip_cluster", "window_start", "window_end", "budget_cents", "per_conversion_cents"])
        check_string(body["name"], "name")
        check_string(body["zip_cluster"], "zip_cluster")
        check_string(body["window_start"], "window_start")
        check_string(body["window_end"], "window_end")
        check_int(body["budget_cents"], "budget_cents")
        check_int(body["per_conversion_cents"], "per_conversion_cents")
        if db.parse_date(body["window_start"]) > db.parse_date(body["window_end"]):
            err_validation("window_start must not fall after window_end")

        # temporal: overlap check against ACTIVE campaigns in same zip_cluster (half-open)
        ns = db.parse_date(body["window_start"])
        ne = db.parse_date(body["window_end"])
        for other in db.outreach_campaigns.values():
            if other["status"] != "ACTIVE" or other["zip_cluster"] != body["zip_cluster"]:
                continue
            os_ = db.parse_date(other["window_start"])
            oe = db.parse_date(other["window_end"])
            if ns < oe and os_ < ne:
                raise_err(ERR_CAMPAIGN_OVERLAP, "An ACTIVE campaign with an overlapping window exists in this zip_cluster")

        # fiscal: aggregate budget cap
        total_budget = sum(
            c["budget_cents"] for c in db.outreach_campaigns.values()
            if c["status"] == "ACTIVE" and c["zip_cluster"] == body["zip_cluster"]
        )
        if total_budget + body["budget_cents"] > REGIONAL_CAP_CENTS:
            raise_err(ERR_CAMPAIGN_BUDGET_EXCEEDED, "Zip-cluster budget cap exceeded")

        c = new_entity()
        c.update({
            "name": body["name"],
            "zip_cluster": body["zip_cluster"],
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "budget_cents": body["budget_cents"],
            "per_conversion_cents": body["per_conversion_cents"],
            "spent_cents": 0,
            "status": "ACTIVE",
        })
        db.outreach_campaigns[c["id"]] = c
        return success_object(_serialize(c), status=201)

    @bp.route("/outreach-campaigns/<cid>", methods=["GET"])
    def get_campaign(cid):
        require_roles("CoalitionAdmin", "AgencyNavigator")
        c = db.outreach_campaigns.get(cid)
        if c is None:
            err_not_found("OutreachCampaign not found")
        return success_object(_serialize(c))

    @bp.route("/outreach-campaigns/<cid>/close", methods=["POST"])
    def close_campaign(cid):
        require_roles("CoalitionAdmin")
        c = db.outreach_campaigns.get(cid)
        if c is None:
            err_not_found("OutreachCampaign not found")
        if c["status"] != "ACTIVE":
            err_invalid_state("Campaign must be ACTIVE to close")
        c["status"] = "CLOSED"
        touch(c)
        return success_object(_serialize(c))
