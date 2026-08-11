"""GiftCampaign endpoints."""

from flask import Blueprint

import db
from errors import (
    err_duplicate_child, err_invalid_request, err_invalid_state, err_not_found,
    err_not_milestone, err_pledges_outstanding,
)
from middleware import require_roles
from response import success_list, success_object
from services.common import (
    json_body, new_entity, req_int, req_str, touch,
)
from services.serializers import CAMPAIGN_FIELDS, serialize
from routes.events import get_event_or_404

bp = Blueprint("campaigns", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
CAMPAIGN_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "ReunionChair")


def get_campaign_or_404(cid):
    c = db.campaigns.get(cid)
    if c is None:
        raise err_not_found("GiftCampaign not found")
    return c


@bp.route("/alumni/events/<eid>/campaigns", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def create_campaign(eid, _role, _user_id):
    get_event_or_404(eid)
    existing = next((c for c in db.campaigns.values() if c["event_id"] == eid), None)
    if existing is not None:
        raise err_duplicate_child("A campaign already exists for this event")
    body = json_body(required=["name", "goal_cents"])
    name = req_str(body["name"], "name")
    goal = req_int(body["goal_cents"], "goal_cents")
    mult = body.get("matching_multiplier_bps", 0)
    if mult is None:
        mult = 0
    mult = req_int(mult, "matching_multiplier_bps")
    if mult < 0:
        raise err_invalid_request("matching_multiplier_bps must be >= 0")

    campaign = new_entity({
        "event_id": eid,
        "name": name,
        "goal_cents": goal,
        "matching_multiplier_bps": mult,
        "pledged_total_cents": 0,
        "fulfilled_total_cents": 0,
        "matched_credit_cents": 0,
        "status": "DRAFT",
    })
    db.campaigns[campaign["id"]] = campaign
    return success_object(serialize(campaign, CAMPAIGN_FIELDS), status=201)


@bp.route("/alumni/events/<eid>/campaigns", methods=["GET"])
@require_roles(*CAMPAIGN_READ)
def get_event_campaign(eid, _role, _user_id):
    get_event_or_404(eid)
    rows = [c for c in db.campaigns.values() if c["event_id"] == eid]
    rows.sort(key=lambda c: (c["created_at"], c["id"]))
    return success_list([serialize(c, CAMPAIGN_FIELDS) for c in rows],
                        limit=len(rows) if rows else 10, offset=0,
                        total_count=len(rows))


@bp.route("/alumni/campaigns/<cid>", methods=["GET"])
@require_roles(*CAMPAIGN_READ)
def get_campaign(cid, _role, _user_id):
    return success_object(serialize(get_campaign_or_404(cid), CAMPAIGN_FIELDS))


@bp.route("/alumni/campaigns/<cid>/activate", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def activate(cid, _role, _user_id):
    campaign = get_campaign_or_404(cid)
    if campaign["status"] != "DRAFT":
        raise err_invalid_state("Campaign must be DRAFT to activate")
    event = db.events.get(campaign["event_id"])
    if event is None:
        raise err_not_found("ReunionEvent not found")
    milestone = event["milestone_year"]
    if not (milestone > 0 and milestone % 5 == 0):
        raise err_not_milestone()
    if campaign["goal_cents"] <= 0:
        raise err_invalid_request("goal_cents must be > 0 to activate")
    campaign["status"] = "ACTIVE"
    touch(campaign)
    return success_object(serialize(campaign, CAMPAIGN_FIELDS))


@bp.route("/alumni/campaigns/<cid>/close", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def close(cid, _role, _user_id):
    campaign = get_campaign_or_404(cid)
    if campaign["status"] != "ACTIVE":
        raise err_invalid_state("Campaign must be ACTIVE to close")
    for p in db.pledges.values():
        if p["campaign_id"] == cid and p["status"] == "PLEDGED":
            raise err_pledges_outstanding()
    campaign["status"] = "CLOSED"
    touch(campaign)
    return success_object(serialize(campaign, CAMPAIGN_FIELDS))
