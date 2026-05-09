from flask import Blueprint

import db
from errors import raise_err, ERR_BIDDER_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_role
from response import success
from routes._helpers import get_json_body, require_string, require_int
from services import risk as risk_svc
from services.lot_service import serialize_bidder, bump

bp = Blueprint("bidders", __name__)


@bp.post("/bidders")
def create_bidder():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    display_name = require_string(body, "display_name", min_len=1, max_len=80)
    affiliated_seller_id = body.get("affiliated_seller_id")
    if affiliated_seller_id is not None and not isinstance(affiliated_seller_id, str):
        raise_err(ERR_INVALID_REQUEST, "affiliated_seller_id must be a string or null")
    bid_id = db.gen_id()
    now = db.now()
    b = {
        "id": bid_id,
        "display_name": display_name,
        "affiliated_seller_id": affiliated_seller_id,
        "identity_verified": False,
        "wallet_balance_cents": 0,
        "held_deposit_cents": 0,
        "status": "ACTIVE",
        "risk_score": 0.0,
        "chronic_score": 0.0,
        "acute_score": 0.0,
        "shill_pattern_detected": False,
        "account_takeover_alert": False,
        "withdrawal_count": 0,
        "dispute_loss_count": 0,
        "default_count_since_reinstate": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.bidders[bid_id] = b
    return success(serialize_bidder(b), http_status=201)


@bp.get("/bidders/<bidder_id>")
def get_bidder(bidder_id):
    require_role({"PlatformAdmin", "Bidder", "ArbitratorOps"})
    b = db.bidders.get(bidder_id)
    if b is None:
        raise_err(ERR_BIDDER_NOT_FOUND)
    return success(serialize_bidder(b))


@bp.post("/bidders/<bidder_id>/wallet/credit")
def credit_wallet(bidder_id):
    require_role({"PlatformAdmin"})
    b = db.bidders.get(bidder_id)
    if b is None:
        raise_err(ERR_BIDDER_NOT_FOUND)
    body = get_json_body()
    amount = require_int(body, "amount_cents", min_val=1)
    b["wallet_balance_cents"] += amount
    bump(b)
    return success(serialize_bidder(b))


@bp.post("/bidders/<bidder_id>/restrict")
def restrict_bidder(bidder_id):
    require_role({"PlatformAdmin"})
    b = db.bidders.get(bidder_id)
    if b is None:
        raise_err(ERR_BIDDER_NOT_FOUND)
    b["status"] = "RESTRICTED"
    bump(b)
    return success(serialize_bidder(b))


@bp.post("/bidders/<bidder_id>/suspend")
def suspend_bidder(bidder_id):
    require_role({"PlatformAdmin"})
    b = db.bidders.get(bidder_id)
    if b is None:
        raise_err(ERR_BIDDER_NOT_FOUND)
    from services.lot_service import bidder_suspend_cascade
    b["status"] = "SUSPENDED"
    bidder_suspend_cascade(b)
    bump(b)
    return success(serialize_bidder(b))


@bp.post("/bidders/<bidder_id>/reinstate")
def reinstate_bidder(bidder_id):
    require_role({"PlatformAdmin"})
    b = db.bidders.get(bidder_id)
    if b is None:
        raise_err(ERR_BIDDER_NOT_FOUND)
    b["status"] = "ACTIVE"
    b["account_takeover_alert"] = False
    b["shill_pattern_detected"] = False
    b["default_count_since_reinstate"] = 0
    risk_svc.recompute_risk(b)
    # PRD §3.6: chronic-only score after reinstate may still cross 70 → re-restrict.
    risk_svc.maybe_threshold_transition(b)
    bump(b)
    return success(serialize_bidder(b))
