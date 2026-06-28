"""Seller routes: create (DRAFT building block), get, list, credit-forecast,
block (cascade), unblock.
"""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import get_body, require_str, paginate_and_respond
from lookups import get_seller
from services import validation
from services.mutations import touch, cascade_block_seller

bp = Blueprint("sellers", __name__)


@bp.route("/fundraising/sellers", methods=["POST"])
@require_roles("CampaignAdmin")
def create_seller():
    body = get_body()
    # priority 4: reference existence of campaign_id
    campaign_id = require_str(body, "campaign_id")
    validation.resolve_campaign_ref(campaign_id)
    # priority 5: body shape
    display_name = require_str(body, "display_name")
    guardian_email = require_str(body, "guardian_email")
    with lock:
        sid = new_id()
        ts = now_ts()
        seller = {
            "id": sid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "campaign_id": campaign_id,
            "display_name": display_name,
            "guardian_email": guardian_email,
            "share_slug": db.next_share_slug(),
            "status": "ACTIVE",
        }
        db.sellers[sid] = seller
    return success(serializers.seller(seller), status=201)


@bp.route("/fundraising/sellers", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def list_sellers():
    items = list(db.sellers.values())
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    if campaign_id is not None:
        items = [s for s in items if s["campaign_id"] == campaign_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate_and_respond(items, serializers.seller)


@bp.route("/fundraising/sellers/<seller_id>", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def get_seller_route(seller_id):
    s = get_seller(seller_id)
    return success(serializers.seller(s), status=200)


@bp.route("/fundraising/sellers/<seller_id>/credit-forecast", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def credit_forecast(seller_id):
    s = get_seller(seller_id)
    return success(serializers.seller_forecast(s), status=200)


@bp.route("/fundraising/sellers/<seller_id>/block", methods=["POST"])
@require_roles("CampaignAdmin")
def block(seller_id):
    s = get_seller(seller_id)
    with lock:
        if s["status"] != "ACTIVE":
            raise errors.invalid_state("Seller must be ACTIVE to block")
        s["status"] = "BLOCKED"
        touch(s)
        cascade_block_seller(s)
    return success(serializers.seller(s), status=200)


@bp.route("/fundraising/sellers/<seller_id>/unblock", methods=["POST"])
@require_roles("CampaignAdmin")
def unblock(seller_id):
    s = get_seller(seller_id)
    with lock:
        if s["status"] != "BLOCKED":
            raise errors.invalid_state("Seller must be BLOCKED to unblock")
        s["status"] = "ACTIVE"
        touch(s)
    return success(serializers.seller(s), status=200)
