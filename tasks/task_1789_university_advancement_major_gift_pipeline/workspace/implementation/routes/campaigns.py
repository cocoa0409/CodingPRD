"""Campaigns and recognition societies."""

from flask import Blueprint, request

from core import (
    authenticate, authorize, body_json, check_unknown_fields, req_str, opt_str,
    req_money, req_enum, parse_dt, new_entity, touch,
    success_object, success_list, paginate, ALL_ROLES,
)
from db import store
from errors import (
    fail, ERR_INVALID_REQUEST, ERR_CAMPAIGN_NOT_FOUND, ERR_CAMPAIGN_INVALID_STATE,
    ERR_DUPLICATE_SOCIETY_LEVEL,
)
from services import ser_campaign, ser_credit_split, ser_society

bp = Blueprint("campaigns", __name__)


def _get_campaign(cid):
    campaign = store["campaigns"].get(cid)
    if campaign is None:
        fail(ERR_CAMPAIGN_NOT_FOUND, "Campaign not found")
    return campaign


@bp.post("/advancement/campaigns")
def create_campaign():
    user_id, role = authenticate()
    authorize(role, ["VPAdvancement"])
    body = body_json()
    check_unknown_fields(body, {"name", "goal_cents", "counting_start", "counting_end"})
    name = req_str(body, "name")
    goal_cents = req_money(body, "goal_cents")
    counting_start = parse_dt(body.get("counting_start"), "counting_start")
    counting_end = parse_dt(body.get("counting_end"), "counting_end")
    if counting_end <= counting_start:
        fail(ERR_INVALID_REQUEST, "counting_end must be later than counting_start")
    entity = new_entity()
    entity.update({
        "name": name,
        "goal_cents": goal_cents,
        "counting_start": counting_start,
        "counting_end": counting_end,
        "face_value_counted_cents": 0,
        "cash_counted_cents": 0,
        "status": "DRAFT",
    })
    store["campaigns"][entity["id"]] = entity
    return success_object(ser_campaign(entity), 201)


@bp.get("/advancement/campaigns/<cid>")
def get_campaign(cid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(ser_campaign(_get_campaign(cid)))


def _campaign_transition(cid, required, target):
    user_id, role = authenticate()
    authorize(role, ["VPAdvancement"])
    body_json()  # no documented inputs
    campaign = _get_campaign(cid)
    if campaign["status"] != required:
        fail(ERR_CAMPAIGN_INVALID_STATE,
             f"Campaign must be {required} for this action (current: {campaign['status']})")
    campaign["status"] = target
    touch(campaign)
    return success_object(ser_campaign(campaign))


@bp.post("/advancement/campaigns/<cid>/activate")
def activate_campaign(cid):
    return _campaign_transition(cid, "DRAFT", "ACTIVE")


@bp.post("/advancement/campaigns/<cid>/close")
def close_campaign(cid):
    return _campaign_transition(cid, "ACTIVE", "CLOSED")


@bp.post("/advancement/campaigns/<cid>/report")
def report_campaign(cid):
    return _campaign_transition(cid, "CLOSED", "REPORTED")


@bp.get("/advancement/campaigns/<cid>/totals")
def campaign_totals(cid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    campaign = _get_campaign(cid)
    return success_object({
        "face_value_counted_cents": campaign["face_value_counted_cents"],
        "cash_counted_cents": campaign["cash_counted_cents"],
        "goal_cents": campaign["goal_cents"],
        "status": campaign["status"],
    })


@bp.get("/advancement/campaigns/<cid>/credit-splits")
def list_campaign_credit_splits(cid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    _get_campaign(cid)
    items = [s for s in store["credit_splits"].values() if s["campaign_id"] == cid]
    credit_type = request.args.get("credit_type")
    if credit_type is not None:
        items = [s for s in items if s["credit_type"] == credit_type]
    page, limit, offset, total = paginate(items)
    return success_list([ser_credit_split(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Recognition societies
# ---------------------------------------------------------------------------

@bp.post("/advancement/recognition-societies")
def create_society():
    user_id, role = authenticate()
    authorize(role, ["DonorRelationsOfficer"])
    body = body_json()
    check_unknown_fields(body, {"name", "level", "threshold_cash_cents", "benefits_text"})
    name = req_str(body, "name")
    level = req_enum(body, "level", {"BRONZE", "SILVER", "GOLD", "PLATINUM"})
    threshold_cash_cents = req_money(body, "threshold_cash_cents")
    benefits_text = opt_str(body, "benefits_text")
    if any(s["level"] == level for s in store["societies"].values()):
        fail(ERR_DUPLICATE_SOCIETY_LEVEL, "A recognition society with this level already exists")
    entity = new_entity()
    entity.update({
        "name": name,
        "level": level,
        "threshold_cash_cents": threshold_cash_cents,
        "benefits_text": benefits_text,
    })
    store["societies"][entity["id"]] = entity
    # prospect recognition membership is recomputed lazily on the next
    # recognition read; no eager directory-wide update here
    return success_object(ser_society(entity), 201)


@bp.get("/advancement/recognition-societies")
def list_societies():
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store["societies"].values())
    page, limit, offset, total = paginate(items)
    return success_list([ser_society(s) for s in page], limit, offset, total)
