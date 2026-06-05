"""Campaign + Appeal endpoints (CampaignManager owns mutations; all read)."""

from flask import Blueprint, request

import db
import errors
import lookup
import models
import response
import services
import util
from middleware import authenticate, require_role

bp = Blueprint("campaigns", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}
CHANNELS = {"EMAIL", "DIRECT_MAIL", "EVENT", "PHONE", "WEB"}


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------
@bp.post("/campaigns")
def create_campaign():
    _, role = authenticate()
    require_role(role, {"CampaignManager"})
    with db.LOCK:
        body = util.get_json_body()
        name = util.req_string(body, "name", min_len=1, max_len=120)
        goal_cents = util.req_int(body, "goal_cents", min_val=1)
        starts_dt = util.parse_iso_datetime(body, "starts_on", required=True)
        ends_dt = util.parse_iso_datetime(body, "ends_on", required=True)
        # ends_on must be strictly after starts_on (body range check -> 400).
        if not (ends_dt > starts_dt):
            raise errors.invalid_request("ends_on must be strictly after starts_on.")

        c = models.new_record({
            "name": name,
            "goal_cents": goal_cents,
            "starts_on": util.iso_from_dt(starts_dt),
            "ends_on": util.iso_from_dt(ends_dt),
            "status": "DRAFT",
            "raised_hard_cents": 0,
            "raised_with_match_cents": 0,
        }, common=True)
        db.campaigns[c["id"]] = c
        return response.object_response(models.serialize(c), status=201)


@bp.get("/campaigns/<cid>")
def get_campaign(cid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        c = lookup.campaign(cid)
        services.recompute_campaign_raised(c)
        return response.object_response(models.serialize(c))


@bp.post("/campaigns/<cid>/open")
def open_campaign(cid):
    _, role = authenticate()
    require_role(role, {"CampaignManager"})
    with db.LOCK:
        c = lookup.campaign(cid)
        if c["status"] != "DRAFT":
            raise errors.invalid_state("Campaign must be DRAFT to open.")
        c["status"] = "OPEN"
        models.touch(c)
        return response.object_response(models.serialize(c))


@bp.post("/campaigns/<cid>/close")
def close_campaign(cid):
    _, role = authenticate()
    require_role(role, {"CampaignManager"})
    with db.LOCK:
        c = lookup.campaign(cid)
        if c["status"] != "OPEN":
            raise errors.invalid_state("Campaign must be OPEN to close.")
        c["status"] = "CLOSED"
        models.touch(c)
        return response.object_response(models.serialize(c))


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------
@bp.post("/appeals")
def create_appeal():
    _, role = authenticate()
    require_role(role, {"CampaignManager"})
    with db.LOCK:
        body = util.get_json_body()
        campaign_id = util.req_id(body, "campaign_id")
        channel = util.req_enum(body, "channel", CHANNELS)
        code = util.req_string(body, "code", min_len=1, max_len=40)
        expected_rate = util.opt_number(body, "expected_response_rate",
                                        default=0.05, min_excl=0, max_incl=1)

        # FK existence (campaign) before business constraints.
        lookup.campaign(campaign_id)

        # Appeal code unique (case-insensitive) within its campaign (p9).
        low = code.lower()
        for a in db.appeals.values():
            if a["campaign_id"] == campaign_id and a["code"].lower() == low:
                raise errors.ApiError(errors.ERR_DUPLICATE_APPEAL_CODE, 409,
                                      "Appeal code already exists in this campaign.")

        a = models.new_record({
            "campaign_id": campaign_id,
            "channel": channel,
            "code": code,
            "expected_response_rate": expected_rate,
            "attributed_gift_count": 0,
        }, common=True)
        db.appeals[a["id"]] = a
        return response.object_response(models.serialize(a), status=201)


@bp.get("/appeals/<aid>")
def get_appeal(aid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        a = lookup.appeal(aid)
        services.recompute_appeal_count(a)
        return response.object_response(models.serialize(a))


@bp.get("/appeals")
def list_appeals():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        limit, offset = util.parse_pagination()
        campaign_id = request.args.get("campaign_id")
        rows = list(db.appeals.values())
        if campaign_id is not None:
            rows = [a for a in rows if a["campaign_id"] == campaign_id]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        for a in page:
            services.recompute_appeal_count(a)
        return response.array_response(models.serialize_list(page), limit, offset, total)
