"""PrizeAward endpoints: list / read / fulfill."""

from flask import Blueprint, request

import db
import errors
import helpers
import middleware
from helpers import (
    get_prize_award, paginate, sort_created, serialize_prize_award,
)
from middleware import get_body, parse_pagination
from response import success_object, success_list

bp = Blueprint("prize_awards", __name__)

FULFILL_ALLOWED_CAMPAIGN_STATUSES = ("SORTED", "DISTRIBUTION_COMPLETE", "RECONCILED", "CLOSED")


@bp.get("/fundraiser/prize-awards")
def list_prize_awards():
    middleware.any_role()
    limit, offset = parse_pagination()
    items = list(db.prize_awards.values())
    for param in ("seller_id", "prize_id", "campaign_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_prize_award(a) for a in page], limit, offset, total)


@bp.get("/fundraiser/prize-awards/<aid>")
def read_prize_award(aid):
    middleware.any_role()
    award = get_prize_award(aid)
    return success_object(serialize_prize_award(award))


@bp.post("/fundraiser/prize-awards/<aid>/fulfill")
def fulfill_prize_award(aid):
    middleware.require_role("GroupCoordinator")
    award = get_prize_award(aid)
    get_body()
    if award["status"] != "AWARDED":
        raise errors.err_invalid_state("Prize award is not AWARDED")
    campaign = db.campaigns[award["campaign_id"]]
    if campaign["status"] not in FULFILL_ALLOWED_CAMPAIGN_STATUSES:
        raise errors.err_invalid_state("Campaign state does not permit prize fulfillment")
    award["status"] = "FULFILLED"
    helpers.touch(award)
    return success_object(serialize_prize_award(award))
