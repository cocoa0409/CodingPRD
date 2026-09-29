"""Proxy-bid resolution, reserve, minimum next bid and anti-sniping (PRD 3.4)."""

import db
from util import clock, plus_seconds, whole_seconds_between
from services import aggregates, calc, lookups


def qualifying_bids(listing_id):
    return [
        bid for bid in lookups.bids_of_listing(listing_id)
        if bid["bid_status"] in aggregates.ACTIVE_BID_STATUSES
    ]


def supersede_previous(listing_id, buyer_id):
    """A buyer's own earlier live bid on the listing steps aside."""
    for bid in qualifying_bids(listing_id):
        if bid["buyer_id"] == buyer_id:
            bid["bid_status"] = "SUPERSEDED"
            db.touch(bid)


def recount(listing):
    listing["bid_count"] = len([
        bid for bid in lookups.bids_of_listing(listing["id"])
        if bid["bid_status"] in aggregates.COUNTED_BID_STATUSES
    ])


def _rank(bids):
    """Ceiling descending, then created_at ascending — never by id."""
    return sorted(
        bids,
        key=lambda bid: (-int(bid["ceiling_cents"]), bid["created_at"], bid["_seq"]),
    )


def resolve(listing, fresh_bid_id=None):
    """Recompute the public price, the leader, reserve_met and min_next_bid.

    `fresh_bid_id` names a bid created by this very request: its status is
    assigned as part of creation, so it keeps version 1.
    """
    opening = listing.get("opening_bid_cents")
    increment = int(listing.get("bid_increment_cents") or calc.DEFAULT_BID_INCREMENT_CENTS)
    candidates = qualifying_bids(listing["id"])

    leader = None
    price = None
    if len(candidates) == 1:
        leader = candidates[0]
        if leader["bid_type"] == "LIVE":
            price = max(int(opening or 0), int(leader["amount_cents"]))
        else:
            price = int(opening or 0)
    elif len(candidates) >= 2:
        ranked = _rank(candidates)
        leader = ranked[0]
        runner_up = ranked[1]
        price = min(
            int(leader["ceiling_cents"]),
            int(runner_up["ceiling_cents"]) + increment,
        )

    listing["current_high_bid_cents"] = price
    listing["current_high_bidder_id"] = leader["buyer_id"] if leader else None

    reserve = listing.get("reserve_price_cents")
    if reserve is None:
        listing["reserve_met"] = True
    else:
        listing["reserve_met"] = price is not None and price >= int(reserve)

    for bid in candidates:
        fresh = bid["id"] == fresh_bid_id
        if leader is not None and bid["id"] == leader["id"]:
            changed = bid["bid_status"] != "WINNING"
            if bid["meets_reserve"] != listing["reserve_met"]:
                bid["meets_reserve"] = listing["reserve_met"]
                changed = True
            bid["bid_status"] = "WINNING"
            if changed and not fresh:
                db.touch(bid)
        elif bid["bid_status"] != "STANDING":
            bid["bid_status"] = "STANDING"
            if not fresh:
                db.touch(bid)

    if price is None:
        listing["min_next_bid_cents"] = int(opening) if opening is not None else None
    else:
        listing["min_next_bid_cents"] = price + increment

    recount(listing)


def apply_anti_sniping(listing):
    """Extend the soft close when a bid lands inside the trigger window."""
    if listing["listing_format"] != "AUCTION":
        return False
    if listing.get("effective_close_at") is None:
        return False
    remaining = whole_seconds_between(clock.now(), listing["effective_close_at"])
    if remaining < 0 or remaining > calc.ANTI_SNIPE_TRIGGER_SECONDS:
        return False
    if int(listing["extension_count"]) >= calc.MAX_EXTENSIONS:
        return False
    listing["effective_close_at"] = plus_seconds(
        listing["effective_close_at"], calc.ANTI_SNIPE_EXTENSION_SECONDS
    )
    listing["extension_count"] = int(listing["extension_count"]) + 1
    return True


def bidders_of(listing_id):
    """Distinct buyer ids that have ever bid on the listing."""
    seen = []
    for bid in lookups.bids_of_listing(listing_id):
        if bid["buyer_id"] not in seen:
            seen.append(bid["buyer_id"])
    return seen
