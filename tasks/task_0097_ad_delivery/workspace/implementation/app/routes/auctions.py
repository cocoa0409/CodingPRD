"""Auction endpoints."""
from flask import Blueprint

from ..auth import require_auth
from ..errors import ApiError
from ..response import success
from ..validators import get_json_body, require_fields, require_enum
from ..services.auction import run_auction
from ..services.paths import resolve_auction


bp = Blueprint("auctions", __name__)


@bp.post("/auctions")
@require_auth(["ExchangeService", "PlatformAdmin"])
def create_auction():
    body = get_json_body()
    require_fields(body, ["exchange", "pricing_rule", "floor_price_cents", "user_id", "device", "geo", "candidate_ad_group_ids"])
    require_enum(body, "exchange", ["INTERNAL", "EXTERNAL_RTB"])
    require_enum(body, "pricing_rule", ["GSP", "VCG"])
    require_enum(body, "device", ["DESKTOP", "MOBILE", "TABLET", "CTV"])

    cands = body.get("candidate_ad_group_ids")
    if not isinstance(cands, list) or len(cands) == 0:
        raise ApiError("ERR_EMPTY_AUCTION_POOL")

    rec = run_auction(body)
    return success(rec, status=201)


@bp.get("/auctions/<auction_id>")
@require_auth(["PlatformAdmin", "ExchangeService"])
def get_auction(auction_id):
    rec = resolve_auction(auction_id)
    return success(rec)
