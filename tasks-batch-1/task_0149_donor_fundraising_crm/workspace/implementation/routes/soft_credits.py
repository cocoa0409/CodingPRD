"""SoftCredit read endpoints (all roles)."""

from flask import Blueprint, request

import db
import lookup
import models
import response
import util
from middleware import authenticate, require_role

bp = Blueprint("soft_credits", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}


@bp.get("/soft-credits/<scid>")
def get_soft_credit(scid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        sc = lookup.soft_credit(scid)
        return response.object_response(models.serialize(sc))


@bp.get("/soft-credits")
def list_soft_credits():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        limit, offset = util.parse_pagination()
        beneficiary_donor_id = request.args.get("beneficiary_donor_id")
        household_id = request.args.get("household_id")
        gift_id = request.args.get("gift_id")
        rows = list(db.soft_credits.values())
        if beneficiary_donor_id is not None:
            rows = [s for s in rows if s["beneficiary_donor_id"] == beneficiary_donor_id]
        if household_id is not None:
            rows = [s for s in rows if s["household_id"] == household_id]
        if gift_id is not None:
            rows = [s for s in rows if s["gift_id"] == gift_id]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)
