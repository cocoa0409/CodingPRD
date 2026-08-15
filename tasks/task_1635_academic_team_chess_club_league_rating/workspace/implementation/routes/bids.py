from flask import Blueprint, g, request

from db import store
from errors import state_error, integrity_error, forbidden_ownership
from middleware import require_roles, ALL_ROLES, acting_coach
from response import success_object, success_array, paginate
from services.common import get_or_404, touch, club_balance
from services.bids import create_bid, promote_next_individual
from services.serializers import bid_json
from validate import get_body

bp = Blueprint("bids", __name__)

READ = ALL_ROLES


@bp.route("/api/qualification-bids", methods=["GET"])
@require_roles(*READ)
def list_bids():
    items = list(store.bids.values())
    for param, field in (("season_id", "season_id"), ("club_id", "club_id"),
                         ("player_id", "player_id"), ("status", "status"),
                         ("bid_type", "bid_type")):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b.get(field) == v]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([bid_json(b) for b in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/qualification-bids/<bidId>", methods=["GET"])
@require_roles(*READ)
def get_bid(bidId):
    b = get_or_404(store.bids, bidId, "qualification bid")
    return success_object(bid_json(b), 200)


def _ownership_and_suspension(b):
    coach = acting_coach()
    if coach is None or coach["club_id"] != b["club_id"]:
        raise forbidden_ownership()
    if store.clubs[b["club_id"]]["status"] == "SUSPENDED":
        raise integrity_error("ERR_CLUB_SUSPENDED", "Club is SUSPENDED")


@bp.route("/api/qualification-bids/<bidId>/accept", methods=["POST"])
@require_roles("ClubCoach")
def accept_bid(bidId):
    get_body()
    b = get_or_404(store.bids, bidId, "qualification bid")
    # bid state checked first (pinned), then season state, then ownership
    if b["status"] != "OFFERED":
        raise state_error("ERR_BID_INVALID_STATE", "Bid is not OFFERED")
    season = store.seasons[b["season_id"]]
    if season["status"] not in ("ACTIVE", "FINALIZING"):
        raise state_error("ERR_SEASON_INVALID_STATE",
                          "Season is not ACTIVE or FINALIZING")
    _ownership_and_suspension(b)
    b["status"] = "ACCEPTED"
    touch(b)
    if b["bid_type"] == "TEAM_STATE" and club_balance(b["club_id"]) >= 0:
        create_bid(b["season_id"], b["club_id"], None, "NATIONAL")
    return success_object(bid_json(b), 200)


@bp.route("/api/qualification-bids/<bidId>/decline", methods=["POST"])
@require_roles("ClubCoach")
def decline_bid(bidId):
    get_body()
    b = get_or_404(store.bids, bidId, "qualification bid")
    if b["status"] != "OFFERED":
        raise state_error("ERR_BID_INVALID_STATE", "Bid is not OFFERED")
    _ownership_and_suspension(b)
    b["status"] = "DECLINED"
    touch(b)
    if b["bid_type"] == "INDIVIDUAL_STATE":
        promote_next_individual(b)
    return success_object(bid_json(b), 200)
