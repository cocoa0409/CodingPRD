"""OutreachCampaign endpoints (PRD §3.9)."""

from flask import Blueprint, request

from db import STORE
from errors import (ApiError, ERR_CAMPAIGN_BUDGET_EXCEEDED, ERR_ZONE_NOT_FOUND,
                    err_invalid_request, err_invalid_state, err_not_found)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import base_record, touch, campaign_out
from services.validate import (require_body, check_unknown_fields, req_str, req_int,
                               req_date, req_enum, opt_int, opt_date)

bp = Blueprint("campaigns", __name__)

ROLES = ("OutreachCoordinator", "ProgramAdmin")
CHANNELS = {"MAIL", "DOOR_TAG", "EMAIL", "SOCIAL"}
TOPICS = {"ACCEPTABLE_MATERIALS", "SEASON_START", "CONTAMINATION_PREVENTION", "COMPOST_GIVEBACK"}


@bp.post("/outreach-campaigns")
def create_campaign():
    require_roles("OutreachCoordinator")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"zone_id", "channel", "topic", "budget_cents",
                                "audience_size", "cost_per_impression_cents", "end_date"})
    zone_id = data.get("zone_id")
    if zone_id is not None:
        if not isinstance(zone_id, str):
            raise err_invalid_request("zone_id must be a string or null")
        if zone_id not in STORE.zones:
            raise err_not_found(ERR_ZONE_NOT_FOUND, "Zone not found")
    channel = req_enum(data, "channel", CHANNELS)
    topic = req_enum(data, "topic", TOPICS)
    budget = req_int(data, "budget_cents")
    audience = req_int(data, "audience_size")
    cpi = req_int(data, "cost_per_impression_cents")
    end_date = req_date(data, "end_date")

    c = base_record()
    c.update({
        "zone_id": zone_id, "channel": channel, "topic": topic,
        "budget_cents": budget, "audience_size": audience,
        "cost_per_impression_cents": cpi, "end_date": end_date,
        "spent_cents": 0, "status": "DRAFT",
    })
    STORE.campaigns[c["id"]] = c
    return success_object(campaign_out(c), 201)


@bp.get("/outreach-campaigns")
def list_campaigns():
    require_roles(*ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.campaigns.values())
    zid = request.args.get("zone_id")
    st = request.args.get("status")
    if zid is not None:
        items = [c for c in items if c["zone_id"] == zid]
    if st is not None:
        items = [c for c in items if c["status"] == st]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([campaign_out(c) for c in page], limit, offset, total)


@bp.get("/outreach-campaigns/<cid>")
def get_campaign(cid):
    require_roles(*ROLES)
    c = STORE.campaigns.get(cid)
    if not c:
        raise err_not_found()
    return success_object(campaign_out(c))


@bp.post("/outreach-campaigns/<cid>/launch")
def launch_campaign(cid):
    require_roles("OutreachCoordinator")
    c = STORE.campaigns.get(cid)
    if not c:
        raise err_not_found()
    if c["status"] != "DRAFT":
        raise err_invalid_state("Campaign is not DRAFT")
    spend = c["audience_size"] * c["cost_per_impression_cents"]
    if spend > c["budget_cents"]:
        raise ApiError(ERR_CAMPAIGN_BUDGET_EXCEEDED,
                       "Campaign spend exceeds budget", 402)
    c["spent_cents"] = spend
    c["status"] = "ACTIVE"
    touch(c)
    return success_object(campaign_out(c))


@bp.patch("/outreach-campaigns/<cid>")
def patch_campaign(cid):
    require_roles("OutreachCoordinator")
    c = STORE.campaigns.get(cid)
    if not c:
        raise err_not_found()
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"status", "budget_cents", "audience_size",
                                "cost_per_impression_cents", "end_date"})

    non_status_fields = {"budget_cents", "audience_size", "cost_per_impression_cents", "end_date"}
    touches_non_status = any(k in data and data[k] is not None for k in non_status_fields)
    if touches_non_status and c["status"] != "DRAFT":
        raise err_invalid_state("Non-status fields are editable only in DRAFT")

    if "status" in data and data["status"] is not None:
        new_status = req_enum(data, "status", {"ACTIVE", "PAUSED", "CANCELLED"})
        cur = c["status"]
        ok = ((cur == "ACTIVE" and new_status == "PAUSED") or
              (cur == "PAUSED" and new_status == "ACTIVE") or
              (cur in ("DRAFT", "ACTIVE", "PAUSED") and new_status == "CANCELLED"))
        if not ok:
            raise err_invalid_state(f"Cannot transition campaign {cur} -> {new_status}")
        c["status"] = new_status

    if "budget_cents" in data and data["budget_cents"] is not None:
        c["budget_cents"] = req_int(data, "budget_cents")
    if "audience_size" in data and data["audience_size"] is not None:
        c["audience_size"] = req_int(data, "audience_size")
    if "cost_per_impression_cents" in data and data["cost_per_impression_cents"] is not None:
        c["cost_per_impression_cents"] = req_int(data, "cost_per_impression_cents")
    if "end_date" in data and data["end_date"] is not None:
        c["end_date"] = req_date(data, "end_date")

    touch(c)
    return success_object(campaign_out(c))
