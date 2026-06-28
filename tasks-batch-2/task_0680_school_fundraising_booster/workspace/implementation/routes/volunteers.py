"""Volunteer routes: create (posture-gated), get, list."""

from flask import Blueprint, request

import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import get_body, require_str, paginate_and_respond
from lookups import get_volunteer
from services import validation

bp = Blueprint("volunteers", __name__)


@bp.route("/fundraising/volunteers", methods=["POST"])
@require_roles("CampaignAdmin")
def create_volunteer():
    body = get_body()
    # priority 4: reference existence of campaign_id.
    campaign_id = require_str(body, "campaign_id")
    campaign = validation.resolve_campaign_ref(campaign_id)
    # priority 5: body shape.
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    with lock:
        # priority 8: posture gate — volunteer create requires ACTIVE.
        validation.require_campaign_active_for_create(campaign)
        vid = new_id()
        ts = now_ts()
        volunteer = {
            "id": vid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "campaign_id": campaign_id,
            "full_name": full_name,
            "email": email,
        }
        db.volunteers[vid] = volunteer
    return success(serializers.volunteer(volunteer), status=201)


@bp.route("/fundraising/volunteers", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def list_volunteers():
    items = list(db.volunteers.values())
    campaign_id = request.args.get("campaign_id")
    if campaign_id is not None:
        items = [v for v in items if v["campaign_id"] == campaign_id]
    return paginate_and_respond(items, serializers.volunteer)


@bp.route("/fundraising/volunteers/<volunteer_id>", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def get_volunteer_route(volunteer_id):
    v = get_volunteer(volunteer_id)
    return success(serializers.volunteer(v), status=200)
