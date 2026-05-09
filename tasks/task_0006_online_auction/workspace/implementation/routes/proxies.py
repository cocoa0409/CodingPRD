from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_LOT_NOT_FOUND,
    ERR_PROXY_NOT_FOUND,
    ERR_LOT_NOT_LIVE,
    ERR_BIDDER_RESTRICTED,
    ERR_SHILL_AFFILIATION,
    ERR_IDENTITY_MISMATCH,
    ERR_PROXY_MAX_TOO_LOW,
    ERR_PROXY_ALREADY_ACTIVE,
    ERR_PROXY_INVALID_STATE,
    ERR_INSUFFICIENT_DEPOSIT_FUNDS,
)
from middleware import require_role
from response import success
from routes._helpers import get_json_body, require_int
from services import calc
from services.lot_service import (
    serialize_proxy,
    bump,
    get_or_create_deposit,
    held_deposit_total,
    refresh_bidder_held,
    recompute_lot_state,
    maybe_soft_close,
    emit_proxy_bids,
)

bp = Blueprint("proxies", __name__)


@bp.post("/lots/<lot_id>/auto-bid-proxies")
def create_proxy(lot_id):
    user_id, _ = require_role({"Bidder"})
    body = get_json_body()
    max_amount = require_int(body, "max_amount_cents", min_val=1)
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
    # Priority 10: PROXY validations
    min_required = calc.min_required_bid_cents(lot)
    if max_amount < lot["starting_bid_cents"] or max_amount < min_required:
        raise_err(ERR_PROXY_MAX_TOO_LOW)
    if any(p for p in db.proxies.values() if p["lot_id"] == lot_id and p["bidder_id"] == user_id and p["status"] == "ACTIVE"):
        raise_err(ERR_PROXY_ALREADY_ACTIVE)
    # Deposit
    existing = next((d for d in db.deposits.values() if d["lot_id"] == lot_id and d["bidder_id"] == user_id and d["status"] == "HELD"), None)
    if existing is None:
        required_dep = calc.deposit_required_cents(lot["reserve_price_cents"])
        held = held_deposit_total(user_id)
        if bidder["wallet_balance_cents"] - held < required_dep:
            raise_err(ERR_INSUFFICIENT_DEPOSIT_FUNDS)
        deposit, _ = get_or_create_deposit(user_id, lot_id, required_dep)
    else:
        deposit = existing
    refresh_bidder_held(user_id)
    pid = db.gen_id()
    now = db.now()
    proxy = {
        "id": pid,
        "lot_id": lot_id,
        "bidder_id": user_id,
        "max_amount_cents": max_amount,
        "status": "ACTIVE",
        "last_executed_amount_cents": None,
        "bids_emitted_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.proxies[pid] = proxy
    # Immediate resolution: emit a bid if (a) no current winner OR (b) this bidder is not currently winning.
    if lot["current_winner_bidder_id"] != user_id:
        # Emit at min_required (which is starting_bid_cents if no bids, else current_price + increment)
        bid_id = db.gen_id()
        placed_at = db.now()
        emit_amount = min_required
        bid = {
            "id": bid_id,
            "lot_id": lot_id,
            "bidder_id": user_id,
            "amount_cents": emit_amount,
            "source": "PROXY",
            "proxy_id": pid,
            "status": "ACTIVE",
            "deposit_id": deposit["id"],
            "placed_at": placed_at,
            "triggered_extension": False,
            "created_at": placed_at,
        }
        db.bids[bid_id] = bid
        proxy["last_executed_amount_cents"] = emit_amount
        proxy["bids_emitted_count"] += 1
        bump(proxy)
        recompute_lot_state(lot)
        maybe_soft_close(lot, bid)
        bump(lot)
        # Now let other proxies counter-bid
        emit_proxy_bids(lot)
    return success(serialize_proxy(proxy, mask_max=False), http_status=201)


@bp.get("/lots/<lot_id>/auto-bid-proxies/<proxy_id>")
def get_proxy(lot_id, proxy_id):
    user_id, role = require_role({"PlatformAdmin", "Bidder", "ArbitratorOps"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    proxy = db.proxies.get(proxy_id)
    if proxy is None or proxy["lot_id"] != lot_id:
        raise_err(ERR_PROXY_NOT_FOUND)
    is_owner = (role == "Bidder" and proxy["bidder_id"] == user_id)
    return success(serialize_proxy(proxy, mask_max=not is_owner))


@bp.post("/lots/<lot_id>/auto-bid-proxies/<proxy_id>/cancel")
def cancel_proxy(lot_id, proxy_id):
    user_id, _ = require_role({"Bidder"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    proxy = db.proxies.get(proxy_id)
    if proxy is None or proxy["lot_id"] != lot_id:
        raise_err(ERR_PROXY_NOT_FOUND)
    if proxy["status"] != "ACTIVE":
        raise_err(ERR_PROXY_INVALID_STATE)
    if proxy["bidder_id"] != user_id:
        raise_err(ERR_IDENTITY_MISMATCH)
    proxy["status"] = "CANCELLED"
    bump(proxy)
    return success(serialize_proxy(proxy, mask_max=False))
