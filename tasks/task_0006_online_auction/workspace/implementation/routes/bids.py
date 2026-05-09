from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_LOT_NOT_FOUND,
    ERR_LOT_NOT_LIVE,
    ERR_BIDDER_RESTRICTED,
    ERR_SHILL_AFFILIATION,
    ERR_IDENTITY_MISMATCH,
    ERR_BID_BELOW_MIN_INCREMENT,
    ERR_BID_NOT_HIGHER,
    ERR_INSUFFICIENT_DEPOSIT_FUNDS,
)
from middleware import require_role
from response import success
from routes._helpers import get_json_body, require_int, parse_pagination, paginate
from services import calc
from services.lot_service import (
    serialize_bid,
    bump,
    recompute_lot_state,
    maybe_soft_close,
    get_or_create_deposit,
    refresh_bidder_held,
    held_deposit_total,
    emit_proxy_bids,
)

bp = Blueprint("bids", __name__)


@bp.post("/lots/<lot_id>/bids")
def place_bid(lot_id):
    user_id, _ = require_role({"Bidder"})
    body = get_json_body()
    amount = require_int(body, "amount_cents", min_val=1)
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    if lot["status"] != "LIVE":
        raise_err(ERR_LOT_NOT_LIVE)
    bidder = db.bidders.get(user_id)
    if bidder is None:
        raise_err(ERR_IDENTITY_MISMATCH)
    if bidder["status"] in ("RESTRICTED", "SUSPENDED"):
        raise_err(ERR_BIDDER_RESTRICTED)
    if bidder.get("affiliated_seller_id") and bidder["affiliated_seller_id"] == lot["seller_id"]:
        raise_err(ERR_SHILL_AFFILIATION)
    # Priority 8: increment ladder
    min_required = calc.min_required_bid_cents(lot)
    if amount < min_required:
        raise_err(ERR_BID_BELOW_MIN_INCREMENT)
    # Priority 9: strict-greater
    if lot["bid_count"] > 0 and amount <= lot["current_price_cents"]:
        raise_err(ERR_BID_NOT_HIGHER)
    # Priority 13: deposit funds
    existing = next((d for d in db.deposits.values() if d["lot_id"] == lot_id and d["bidder_id"] == user_id and d["status"] == "HELD"), None)
    if existing is None:
        required_dep = calc.deposit_required_cents(lot["reserve_price_cents"])
        held = held_deposit_total(user_id)
        if bidder["wallet_balance_cents"] - held < required_dep:
            raise_err(ERR_INSUFFICIENT_DEPOSIT_FUNDS)
        deposit, _ = get_or_create_deposit(user_id, lot_id, required_dep)
    else:
        deposit = existing
    # Create bid
    bid_id = db.gen_id()
    placed_at = db.now()
    bid = {
        "id": bid_id,
        "lot_id": lot_id,
        "bidder_id": user_id,
        "amount_cents": amount,
        "source": "MANUAL",
        "proxy_id": None,
        "status": "ACTIVE",
        "deposit_id": deposit["id"],
        "placed_at": placed_at,
        "triggered_extension": False,
        "created_at": placed_at,
    }
    db.bids[bid_id] = bid
    refresh_bidder_held(user_id)
    recompute_lot_state(lot)
    maybe_soft_close(lot, bid)
    bump(lot)
    # Proxy emissions for OTHER bidders' proxies
    emit_proxy_bids(lot)
    return success(serialize_bid(bid), http_status=201)


@bp.get("/lots/<lot_id>/bids")
def list_bids(lot_id):
    require_role({"PlatformAdmin", "Seller", "Bidder", "ArbitratorOps", "Anonymous"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    limit, offset = parse_pagination()
    items = [b for b in db.bids.values() if b["lot_id"] == lot_id]
    items.sort(key=lambda b: b["placed_at"], reverse=True)
    page, pag = paginate(items, limit, offset)
    return success([serialize_bid(b) for b in page], pagination=pag)
