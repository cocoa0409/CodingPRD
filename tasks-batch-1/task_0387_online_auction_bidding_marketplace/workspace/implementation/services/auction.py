"""Proxy bid resolution, anti-sniping, and auction close. PRD §3.3, §3.4, §3.6."""
import db
import constants as C
from services import core, calc, sales

TERMINAL_LISTING_STATES = {
    "ENDED_MET", "ENDED_RESERVE_NOT_MET", "ENDED_NO_BIDS", "SOLD", "CANCELLED",
}


def active_bids(listing_id):
    """All ACCEPTED bids on a listing, in chronological created order."""
    bs = [b for b in db.bids.values()
          if b["listing_id"] == listing_id and b["status"] == "ACCEPTED"]
    bs.sort(key=lambda b: (b["created_at"], b["id"]))
    return bs


def resolve_proxy(listing, incoming_bid):
    """Apply proxy resolution when `incoming_bid` is accepted onto `listing`.

    Implements PRD §3.3 verbatim. incoming_bid is already in db.bids with status
    ACCEPTED. Returns nothing; mutates bids + listing in place.
    """
    prev_id = listing["highest_bid_id"]
    prev = db.bids.get(prev_id) if prev_id else None

    start_price = listing["start_price_cents"]

    if prev is None:
        # First bid on the listing.
        incoming_bid["current_price_cents"] = start_price
        incoming_bid["is_winning"] = True
        listing["highest_bid_id"] = incoming_bid["id"]
        listing["current_price_cents"] = incoming_bid["current_price_cents"]
        return

    m_new = incoming_bid["max_proxy_cents"]
    m_prev = prev["max_proxy_cents"]

    if m_new > m_prev:
        # Incoming takes the lead.
        incoming_bid["current_price_cents"] = min(m_new, m_prev + calc.bid_increment(m_prev))
        incoming_bid["is_winning"] = True
        prev["status"] = "OUTBID"
        prev["is_winning"] = False
        core.touch(prev)
        listing["highest_bid_id"] = incoming_bid["id"]
        listing["current_price_cents"] = incoming_bid["current_price_cents"]
    else:
        # m_new <= m_prev: incumbent holds (including the exact-equal tie case).
        prev["current_price_cents"] = min(m_prev, m_new + calc.bid_increment(m_new))
        prev["is_winning"] = True
        core.touch(prev)
        incoming_bid["current_price_cents"] = m_new
        incoming_bid["is_winning"] = False
        incoming_bid["status"] = "OUTBID"
        listing["highest_bid_id"] = prev["id"]
        listing["current_price_cents"] = prev["current_price_cents"]


def reresolve_after_retract(listing):
    """Re-run proxy resolution from scratch over the remaining ACCEPTED bids.

    PRD §3.3: only ACCEPTED bids participate; OUTBID/RETRACTED are excluded.
    Used after a retraction (PRD §3.3).
    """
    remaining = active_bids(listing["id"])

    # Reset winner pointer; we will rebuild it by replaying chronologically.
    listing["highest_bid_id"] = None
    if not remaining:
        listing["current_price_cents"] = listing["start_price_cents"]
        for b in db.bids.values():
            if b["listing_id"] == listing["id"] and b["status"] == "ACCEPTED":
                b["is_winning"] = False
        return

    # Clear is_winning on all accepted bids first.
    for b in remaining:
        b["is_winning"] = False

    # Replay: treat the first as the first bid, then fold the rest in.
    first = remaining[0]
    first["current_price_cents"] = listing["start_price_cents"]
    first["is_winning"] = True
    listing["highest_bid_id"] = first["id"]
    listing["current_price_cents"] = first["current_price_cents"]

    for b in remaining[1:]:
        prev = db.bids[listing["highest_bid_id"]]
        m_new = b["max_proxy_cents"]
        m_prev = prev["max_proxy_cents"]
        if m_new > m_prev:
            b["current_price_cents"] = min(m_new, m_prev + calc.bid_increment(m_prev))
            b["is_winning"] = True
            prev["is_winning"] = False
            listing["highest_bid_id"] = b["id"]
            listing["current_price_cents"] = b["current_price_cents"]
        else:
            prev["current_price_cents"] = min(m_prev, m_new + calc.bid_increment(m_new))
            prev["is_winning"] = True
            b["current_price_cents"] = m_new
            b["is_winning"] = False
            listing["current_price_cents"] = prev["current_price_cents"]


def apply_snipe_extension(listing):
    """Anti-sniping window extension. PRD §3.4.

    remaining = effective_end_at - now (seconds).
    if 0 < remaining <= SNIPE_TRIGGER_SECONDS: effective_end_at = now + EXTENSION.
    """
    if listing["effective_end_at"] is None:
        return
    end = db.parse_iso(listing["effective_end_at"])
    now = db.now_dt()
    remaining = (end - now).total_seconds()
    if 0 < remaining <= C.SNIPE_TRIGGER_SECONDS:
        new_end = now.timestamp() + C.SNIPE_EXTENSION_SECONDS
        from datetime import datetime, timezone
        listing["effective_end_at"] = db.iso(datetime.fromtimestamp(new_end, tz=timezone.utc))


def close_auction(listing):
    """Close a single ACTIVE auction whose effective_end_at has been reached.

    PRD §3.6. Routes to ENDED_MET->SOLD (+ Order + Invoice), ENDED_RESERVE_NOT_MET,
    or ENDED_NO_BIDS. Bumps the listing version per terminal close.
    """
    if listing["status"] != "ACTIVE":
        return
    bid_count = listing["bid_count"]
    if bid_count == 0:
        listing["status"] = "ENDED_NO_BIDS"
        core.touch(listing)
        return

    winner = db.bids.get(listing["highest_bid_id"])
    high_price = winner["current_price_cents"] if winner else None
    reserve = listing["reserve_price_cents"]

    if reserve is not None and high_price < reserve:
        # Reserve not met: no winner, no order.
        listing["status"] = "ENDED_RESERVE_NOT_MET"
        core.touch(listing)
        return

    # Reserve met (or no reserve): ENDED_MET transient bridge -> SOLD.
    listing["winner_account_id"] = winner["bidder_account_id"]
    listing["sold_price_cents"] = winner["current_price_cents"]
    listing["status"] = "ENDED_MET"
    core.touch(listing)  # version bump for the ENDED_MET transition

    sales.create_order_and_invoice(
        listing,
        buyer_account_id=winner["bidder_account_id"],
        source="AUCTION_WIN",
        item_price_cents=winner["current_price_cents"],
        shipping_cents=0,
    )

    listing["status"] = "SOLD"
    core.touch(listing)  # version bump for the SOLD continuation
