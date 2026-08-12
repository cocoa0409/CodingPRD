"""Referral campaign and campaign event endpoints (PRD 3.7)."""

from flask import Blueprint, request

import domain as D
from db import store, new_record, bump
from errors import (
    ApiError, ERR_CASE_NOT_FOUND, ERR_CAMPAIGN_NOT_FOUND,
    ERR_CAMPAIGN_EVENT_NOT_FOUND, ERR_INVALID_STATE, ERR_CAMPAIGN_NOT_ACTIVE,
    ERR_CAMPAIGN_BUDGET_EXCEEDED, ERR_EVENT_WINDOW_OVERLAP,
    ERR_EVENT_NOT_PLANNED, ERR_PANEL_CAPACITY_EXCEEDED,
)
from middleware import get_context, require_role
from response import success_object, paginate

bp = Blueprint("campaigns", __name__)


def _get_campaign(cid):
    campaign = store.campaigns.get(cid)
    if campaign is None:
        raise ApiError(ERR_CAMPAIGN_NOT_FOUND, 404, "ReferralCampaign not found")
    return campaign


def _get_event(eid):
    event = store.events.get(eid)
    if event is None:
        raise ApiError(ERR_CAMPAIGN_EVENT_NOT_FOUND, 404, "CampaignEvent not found")
    return event


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


@bp.route("/onboarding/referral-campaigns", methods=["POST"])
def create_campaign():
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    body = D.get_body()
    case_id = D.req_str(body, "onboarding_case_id")
    name = D.req_str(body, "name")
    budget = D.non_negative(D.req_int(body, "budget_cents"), "budget_cents")
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "OnboardingCase not found")
    rec = new_record()
    rec.update({
        "onboarding_case_id": case_id,
        "name": name,
        "budget_cents": budget,
        "spent_cents": 0,
        "referrals_attributed": 0,
        "status": "DRAFT",
    })
    store.campaigns[rec["id"]] = rec
    bump(case)
    return success_object(D.serialize_campaign(rec), status=201)


@bp.route("/onboarding/referral-campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    get_context()
    return success_object(D.serialize_campaign(_get_campaign(cid)))


@bp.route("/onboarding/referral-campaigns", methods=["GET"])
def list_campaigns():
    get_context()
    case_id = request.args.get("onboarding_case_id")
    status = request.args.get("status")
    records = sorted(store.campaigns.values(), key=lambda r: r["_seq"])
    if case_id is not None:
        records = [r for r in records if r["onboarding_case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate([D.serialize_campaign(r) for r in records], request.args)


@bp.route("/onboarding/referral-campaigns/<cid>/activate", methods=["POST"])
def activate_campaign(cid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    campaign = _get_campaign(cid)
    if campaign["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT campaign can be activated")
    campaign["status"] = "ACTIVE"
    bump(campaign)
    return success_object(D.serialize_campaign(campaign))


@bp.route("/onboarding/referral-campaigns/<cid>/complete", methods=["POST"])
def complete_campaign(cid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    campaign = _get_campaign(cid)
    if campaign["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE campaign can be completed")
    campaign["status"] = "COMPLETED"
    bump(campaign)
    return success_object(D.serialize_campaign(campaign))


# ---------------------------------------------------------------------------
# Campaign events
# ---------------------------------------------------------------------------


@bp.route("/onboarding/campaign-events", methods=["POST"])
def create_event():
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    body = D.get_body()
    campaign_id = D.req_str(body, "campaign_id")
    event_type = D.req_enum(body, "event_type", D.EVENT_TYPES)
    start_date_raw = D.req_str(body, "start_date")
    end_date_raw = D.req_str(body, "end_date")
    cost = D.non_negative(D.req_int(body, "cost_cents"), "cost_cents")
    venue = D.req_str(body, "venue")
    start_date = D.parse_date(start_date_raw, "start_date")
    end_date = D.parse_date(end_date_raw, "end_date")
    if start_date > end_date:
        raise ApiError("ERR_VALIDATION", 400, "start_date must not be after end_date")

    campaign = store.campaigns.get(campaign_id)
    if campaign is None:
        raise ApiError(ERR_CAMPAIGN_NOT_FOUND, 404, "ReferralCampaign not found")
    if campaign["status"] != "ACTIVE":
        raise ApiError(ERR_CAMPAIGN_NOT_ACTIVE, 409,
                       "Events can be planned only inside an ACTIVE campaign")

    # Closed-interval overlap against non-CANCELLED siblings; adjacency conflicts.
    for other in store.events.values():
        if other["campaign_id"] != campaign_id or other["status"] == "CANCELLED":
            continue
        o_start = D.parse_date(other["start_date"], "start_date")
        o_end = D.parse_date(other["end_date"], "end_date")
        if start_date <= o_end and o_start <= end_date:
            raise ApiError(ERR_EVENT_WINDOW_OVERLAP, 422,
                           "Event window overlaps a sibling event")

    if campaign["spent_cents"] + cost > campaign["budget_cents"]:
        raise ApiError(ERR_CAMPAIGN_BUDGET_EXCEEDED, 422,
                       "Event cost would exceed the campaign budget")

    rec = new_record()
    rec.update({
        "campaign_id": campaign_id,
        "event_type": event_type,
        "start_date": start_date_raw,
        "end_date": end_date_raw,
        "cost_cents": cost,
        "venue": venue,
        "referrals_generated": 0,
        "status": "PLANNED",
    })
    store.events[rec["id"]] = rec
    campaign["spent_cents"] += cost
    bump(campaign)
    return success_object(D.serialize_event(rec), status=201)


@bp.route("/onboarding/campaign-events/<eid>", methods=["GET"])
def get_event(eid):
    get_context()
    return success_object(D.serialize_event(_get_event(eid)))


@bp.route("/onboarding/campaign-events", methods=["GET"])
def list_events():
    get_context()
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    event_type = request.args.get("event_type")
    records = sorted(store.events.values(), key=lambda r: r["_seq"])
    if campaign_id is not None:
        records = [r for r in records if r["campaign_id"] == campaign_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if event_type is not None:
        records = [r for r in records if r["event_type"] == event_type]
    return paginate([D.serialize_event(r) for r in records], request.args)


@bp.route("/onboarding/campaign-events/<eid>/hold", methods=["POST"])
def hold_event(eid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    event = _get_event(eid)
    body = D.get_body()
    referrals = D.non_negative(D.req_int(body, "referrals_generated"),
                               "referrals_generated")
    if event["status"] != "PLANNED":
        raise ApiError(ERR_EVENT_NOT_PLANNED, 409, "Only a PLANNED event can be held")
    campaign = store.campaigns.get(event["campaign_id"])
    panel = D.panel_of_case(campaign["onboarding_case_id"]) if campaign else None
    if panel is not None and panel["status"] == "OPEN":
        if panel["current_size"] + referrals > panel["capacity"]:
            raise ApiError(ERR_PANEL_CAPACITY_EXCEEDED, 422,
                           "Referrals would push the panel census beyond capacity")
    event["referrals_generated"] = referrals
    event["status"] = "HELD"
    bump(event)
    if campaign is not None:
        campaign["referrals_attributed"] += referrals
        bump(campaign)
    if panel is not None and panel["status"] == "OPEN":
        panel["current_size"] += referrals
        bump(panel)
    return success_object(D.serialize_event(event))


@bp.route("/onboarding/campaign-events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    event = _get_event(eid)
    if event["status"] != "PLANNED":
        raise ApiError(ERR_EVENT_NOT_PLANNED, 409, "Only a PLANNED event can be cancelled")
    event["status"] = "CANCELLED"
    bump(event)
    campaign = store.campaigns.get(event["campaign_id"])
    if campaign is not None:
        campaign["spent_cents"] -= event["cost_cents"]
        bump(campaign)
    return success_object(D.serialize_event(event))
