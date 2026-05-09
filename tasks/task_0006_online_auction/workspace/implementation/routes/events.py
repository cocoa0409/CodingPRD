from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BIDDER_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND,
    ERR_INVOICE_NOT_ISSUED,
    ERR_INVALID_REQUEST,
)
from middleware import require_role
from response import success
from routes._helpers import get_json_body, require_int, require_string, require_datetime
from services import calc
from services import risk as risk_svc
from services.lot_service import (
    serialize_bidder,
    serialize_lot,
    serialize_invoice,
    bump,
    refresh_bidder_held,
    recompute_seller_counters,
    evaluate_clock_transitions,
    _release_deposit,
)

bp = Blueprint("events", __name__)


@bp.post("/_clock/advance")
def clock_advance():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    seconds = require_int(body, "seconds", min_val=0)
    new_now = db.advance_seconds(seconds)
    evaluate_clock_transitions()
    return success({"now": db.fmt_dt(new_now)})


@bp.post("/_events/payment-confirmed")
def payment_confirmed():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    invoice_id = require_string(body, "invoice_id", min_len=1, max_len=200)
    paid_at = require_datetime(body, "paid_at")
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise_err(ERR_INVOICE_NOT_FOUND)
    if inv["status"] != "ISSUED":
        raise_err(ERR_INVOICE_NOT_ISSUED)
    lot = db.lots.get(inv["lot_id"])
    if lot is not None and lot.get("payment_deadline_at") and paid_at > lot["payment_deadline_at"]:
        raise_err(ERR_INVOICE_NOT_ISSUED)
    inv["status"] = "PAID"
    inv["paid_at"] = paid_at
    bump(inv)
    # Buyer's deposit on this lot → RELEASED with WINNER_PAID
    buyer_id = inv["buyer_id"]
    for d in db.deposits.values():
        if d["lot_id"] == inv["lot_id"] and d["bidder_id"] == buyer_id and d["status"] == "HELD":
            _release_deposit(d, "WINNER_PAID")
    refresh_bidder_held(buyer_id)
    # Seller proceeds increment
    seller = db.sellers.get(inv["seller_id"])
    if seller:
        recompute_seller_counters(seller)
        bump(seller)
    return success(serialize_invoice(inv))


@bp.post("/_events/identity-verified")
def identity_verified():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    bidder_id = require_string(body, "bidder_id", min_len=1, max_len=200)
    require_datetime(body, "verified_at")
    b = db.bidders.get(bidder_id)
    if b is None:
        raise_err(ERR_BIDDER_NOT_FOUND)
    b["identity_verified"] = True
    bump(b)
    return success(serialize_bidder(b))


@bp.post("/_events/logistics-delivered")
def logistics_delivered():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    lot_id = require_string(body, "lot_id", min_len=1, max_len=200)
    delivered_at = require_datetime(body, "delivered_at")
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    lot["delivered_at"] = delivered_at
    bump(lot)
    return success(serialize_lot(lot))


@bp.post("/_events/account-takeover-alert")
def account_takeover_alert():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    bidder_id = require_string(body, "bidder_id", min_len=1, max_len=200)
    b = db.bidders.get(bidder_id)
    if b is None:
        raise_err(ERR_BIDDER_NOT_FOUND)
    b["account_takeover_alert"] = True
    risk_svc.recompute_risk(b)
    risk_svc.maybe_threshold_transition(b)
    bump(b)
    return success(serialize_bidder(b))


@bp.post("/_sweep/risk-monitor")
def risk_sweep():
    require_role({"PlatformAdmin"})
    from datetime import timedelta
    now = db.now()
    window_start = now - timedelta(seconds=calc.SHILL_DETECTION_VELOCITY_WINDOW_SECONDS)
    # Group by (bidder_id, lot_id) the bids placed in window
    counts = {}
    for bid in db.bids.values():
        if bid["placed_at"] >= window_start and bid["placed_at"] <= now:
            key = (bid["bidder_id"], bid["lot_id"])
            counts[key] = counts.get(key, 0) + 1
    flagged = set()
    for (bidder_id, _lot_id), cnt in counts.items():
        if cnt > calc.SHILL_DETECTION_VELOCITY_THRESHOLD:
            flagged.add(bidder_id)
    for bidder_id in flagged:
        b = db.bidders.get(bidder_id)
        if b is None:
            continue
        b["shill_pattern_detected"] = True
        risk_svc.recompute_risk(b)
        risk_svc.maybe_threshold_transition(b)
        bump(b)
    return success({"flagged_bidder_ids": sorted(flagged)})
