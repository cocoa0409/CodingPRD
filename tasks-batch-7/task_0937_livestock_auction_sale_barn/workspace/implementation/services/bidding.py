"""Bid increments and bid restoration (PRD 3.8)."""
import config
from money import D, q2
from store import db, touch


def lot_bids(lot_id):
    return sorted([b for b in db["bids"].values() if b["lot_id"] == lot_id],
                  key=lambda b: b["_seq"])


def current_winning(lot_id):
    for bid in lot_bids(lot_id):
        if bid["status"] == "WINNING":
            return bid
    return None


def increment_for(current_high):
    high = D(current_high)
    if high < config.BID_INCREMENT_TIER1_MAX:
        return config.BID_INCREMENT_TIER1
    if high < config.BID_INCREMENT_TIER2_MAX:
        return config.BID_INCREMENT_TIER2
    return config.BID_INCREMENT_TIER3


def minimum_acceptable(lot, winner):
    """Opening bid on a virgin lot, else current high plus the tiered
    increment, rounded half up to two places; the comparison is inclusive."""
    if winner is None:
        return D(lot["opening_bid"])
    high = D(winner["unit_price"])
    return q2(high + increment_for(high))


def restore_highest_outbid(lot_id):
    """OUTBID -> WINNING when the bid that outbid it is voided.

    Adjudication of friction 10: restoration fires on exactly the two named
    triggers - a revoked registration and a voided purchase - and nowhere else.
    A no-sale and the close cascade void a lot's WINNING bids deliberately, so
    restoring one there would resurrect a bid the PRD just killed and would
    make the no-sale exposure recomputation unobservable.
    """
    bids = lot_bids(lot_id)
    if any(b["status"] == "WINNING" for b in bids):
        return None
    candidates = [b for b in bids if b["status"] == "OUTBID"]
    if not candidates:
        return None
    # Highest unit_price among the lot's non-VOIDED, non-HAMMERED bids; ties
    # break on the earlier created_at.
    best = None
    for bid in candidates:
        if best is None:
            best = bid
            continue
        if D(bid["unit_price"]) > D(best["unit_price"]):
            best = bid
    if best is None:
        return None
    best["status"] = "WINNING"
    touch(best)
    return best
