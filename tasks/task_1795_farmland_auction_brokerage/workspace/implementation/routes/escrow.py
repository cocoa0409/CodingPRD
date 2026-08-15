"""Earnest-money deposits: record-payment, verify, reads."""

from flask import Blueprint, request

import db
import serializers
from errors import raise_err, ERR_INVALID_DEPOSIT_STATE
from middleware import auth, require_roles, forbid
from response import (
    success_object, success_list, get_body, as_decimal, touch, paginate,
)
from .clock import get_or_404

bp = Blueprint("escrow", __name__)


def _deposit_listing(dep):
    bid = db.bids.get(dep["bid_id"])
    auction = db.auctions.get(bid["auction_id"]) if bid else None
    return db.listings.get(auction["listing_id"]) if auction else None


@bp.post("/api/deposits/<did>/record-payment")
def record_payment(did):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    dep = get_or_404(db.deposits, did, "deposit")
    listing = _deposit_listing(dep)
    if listing is None or listing["agent_id"] != user_id:
        forbid("caller is not the agent of the listing behind this deposit")
    body = get_body()
    amount = as_decimal(body, "amount", gt=0)
    if dep["status"] not in ("PENDING", "LATE"):
        raise_err(ERR_INVALID_DEPOSIT_STATE,
                  "payments may be recorded only while PENDING or LATE")

    dep["amount_received"] += amount
    if dep["status"] == "PENDING" and dep["amount_received"] >= dep["amount_due"]:
        # Timing decides: on or before due_at -> RECEIVED; after due_at -> LATE.
        if db.clock_now() <= dep["_due_at_dt"]:
            dep["status"] = "RECEIVED"
        else:
            dep["status"] = "LATE"
    # A LATE deposit never returns to RECEIVED; payments keep accumulating.
    touch(dep)
    return success_object(serializers.deposit(dep))


@bp.post("/api/deposits/<did>/verify")
def verify_deposit(did):
    _, role = auth()
    # Segregation of duties: verification is PlatformAdmin-only.
    require_roles(role, {"PlatformAdmin"})
    dep = get_or_404(db.deposits, did, "deposit")
    if dep["status"] not in ("RECEIVED", "LATE"):
        raise_err(ERR_INVALID_DEPOSIT_STATE,
                  "only a RECEIVED or LATE deposit can be verified")
    dep["status"] = "VERIFIED"
    touch(dep)
    return success_object(serializers.deposit(dep))


@bp.get("/api/deposits/<did>")
def get_deposit(did):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent", "PlatformAdmin", "Buyer"})
    dep = get_or_404(db.deposits, did, "deposit")
    if role == "Buyer" and dep["buyer_id"] != user_id:
        forbid("a Buyer may read only deposits of its own bids")
    return success_object(serializers.deposit(dep))


@bp.get("/api/bids/<bid>/deposits")
def list_bid_deposits(bid):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent", "PlatformAdmin", "Buyer"})
    b = get_or_404(db.bids, bid, "bid")
    if role == "Buyer" and b["buyer_id"] != user_id:
        forbid("a Buyer may read only deposits of its own bids")
    items = [d for d in db.deposits.values() if d["bid_id"] == b["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serializers.deposit(d) for d in page], limit, offset, total)
