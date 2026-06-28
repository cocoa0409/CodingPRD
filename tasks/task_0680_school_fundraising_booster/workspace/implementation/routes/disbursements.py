"""Disbursement read-back routes: get, list (0 or 1 per campaign)."""

from flask import Blueprint, request

import serializers
from db import db
from middleware import require_roles
from response import success
from helpers import paginate_and_respond
from lookups import get_disbursement

bp = Blueprint("disbursements", __name__)


@bp.route("/fundraising/disbursements", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def list_disbursements():
    items = list(db.disbursements.values())
    campaign_id = request.args.get("campaign_id")
    if campaign_id is not None:
        items = [d for d in items if d["campaign_id"] == campaign_id]
    return paginate_and_respond(items, serializers.disbursement)


@bp.route("/fundraising/disbursements/<disbursement_id>", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def get_disbursement_route(disbursement_id):
    d = get_disbursement(disbursement_id)
    return success(serializers.disbursement(d), status=200)
