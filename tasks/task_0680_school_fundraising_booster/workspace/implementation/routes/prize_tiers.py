"""PrizeTier routes: create (DRAFT building block), get, list.

threshold_cents must be unique within a campaign (ERR_DUPLICATE_KEY).
"""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import get_body, require_str, require_int, paginate_and_respond
from lookups import get_prize_tier
from services import validation

bp = Blueprint("prize_tiers", __name__)


@bp.route("/fundraising/prize-tiers", methods=["POST"])
@require_roles("CampaignAdmin")
def create_prize_tier():
    body = get_body()
    # priority 4: reference existence of campaign_id
    campaign_id = require_str(body, "campaign_id")
    validation.resolve_campaign_ref(campaign_id)
    # priority 5: body shape
    label = require_str(body, "label")
    threshold_cents = require_int(body, "threshold_cents")
    if threshold_cents < 1:
        raise errors.invalid_request("threshold_cents must be at least 1")
    prize_description = require_str(body, "prize_description")
    with lock:
        # priority 12: duplicate threshold within campaign
        for t in db.prize_tiers.values():
            if t["campaign_id"] == campaign_id and t["threshold_cents"] == threshold_cents:
                raise errors.duplicate_key("threshold_cents already used in this campaign")
        tid = new_id()
        ts = now_ts()
        tier = {
            "id": tid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "campaign_id": campaign_id,
            "label": label,
            "threshold_cents": threshold_cents,
            "prize_description": prize_description,
        }
        db.prize_tiers[tid] = tier
    return success(serializers.prize_tier(tier), status=201)


@bp.route("/fundraising/prize-tiers", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def list_prize_tiers():
    items = list(db.prize_tiers.values())
    campaign_id = request.args.get("campaign_id")
    if campaign_id is not None:
        items = [t for t in items if t["campaign_id"] == campaign_id]
    return paginate_and_respond(items, serializers.prize_tier)


@bp.route("/fundraising/prize-tiers/<prize_tier_id>", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def get_prize_tier_route(prize_tier_id):
    t = get_prize_tier(prize_tier_id)
    return success(serializers.prize_tier(t), status=200)
