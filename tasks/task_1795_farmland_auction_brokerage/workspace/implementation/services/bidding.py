"""Bid economics: tiered increments, combination premium, winner selection."""

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_err, ERR_INVALID_AUCTION_STATE

Q2 = Decimal("0.01")

# bid_increment_schedule constants
TIER1_MAX = Decimal("100000")
TIER2_MAX = Decimal("500000")
TIER3_MAX = Decimal("1000000")
INC1 = Decimal("1000")
INC2 = Decimal("2500")
INC3 = Decimal("5000")
INC4 = Decimal("10000")
COMBO_PREMIUM_PCT = Decimal("0.05")


def increment(high: Decimal) -> Decimal:
    if high < TIER1_MAX:
        return INC1
    if high < TIER2_MAX:
        return INC2
    if high < TIER3_MAX:
        return INC3
    return INC4


def scope_key(bid):
    return frozenset(bid["tract_ids"])


def placed_high_for_scope(auction_id, scope):
    """Max amount among PLACED bids of the auction with an identical tract set."""
    best = None
    for b in db.bids.values():
        if b["auction_id"] != auction_id or b["status"] != "PLACED":
            continue
        if scope_key(b) == scope:
            if best is None or b["amount"] > best:
                best = b["amount"]
    return best if best is not None else Decimal("0")


def per_tract_high(auction_id, tract_id, statuses=("PLACED",)):
    """Highest-amount eligible bid whose scope is exactly [tract_id]; tie -> earliest
    created order. Returns bid or None."""
    best = None
    for b in db.bids.values():
        if b["auction_id"] != auction_id or b["status"] not in statuses:
            continue
        if len(b["tract_ids"]) == 1 and b["tract_ids"][0] == tract_id:
            if best is None or b["amount"] > best["amount"] or (
                b["amount"] == best["amount"] and b["_seq"] < best["_seq"]
            ):
                best = b
    return best


def combo_threshold(auction_id, scope_tract_ids, eligible_statuses):
    """round_half_up(1.05 * sum of per-tract individual highs over the scope, 2)."""
    total = Decimal("0")
    for tid in scope_tract_ids:
        hb = per_tract_high(auction_id, tid, eligible_statuses)
        if hb is not None:
            total += hb["amount"]
    return (Decimal("1") + COMBO_PREMIUM_PCT) * total


def select_winners(auction):
    """winning_bid_selection. Returns (winning_bids, losing_bids, awarded_total).

    Raises ERR_INVALID_AUCTION_STATE when the eligible pool is empty.
    Eligibility: PLACED for LIVE/ONLINE, REVEALED for SEALED_BID.
    """
    if auction["method"] == "SEALED_BID":
        eligible_status = "REVEALED"
    else:
        eligible_status = "PLACED"

    eligible = [
        b for b in db.bids.values()
        if b["auction_id"] == auction["id"] and b["status"] == eligible_status
    ]
    if not eligible:
        raise_err(ERR_INVALID_AUCTION_STATE, "no eligible bids to award")

    listing = db.listings[auction["listing_id"]]
    listing_tracts = [t for t in db.tracts.values() if t["listing_id"] == listing["id"]]

    # Per-tract individual highs: tract_id -> bid (max amount, earliest created).
    ind_high = {}
    for t in listing_tracts:
        hb = per_tract_high(auction["id"], t["id"], (eligible_status,))
        if hb is not None:
            ind_high[t["id"]] = hb

    combos = [b for b in eligible if len(set(b["tract_ids"])) > 1]
    combos.sort(key=lambda b: (-b["amount"], b["_seq"]))

    assigned = set()
    winners = []
    winner_ids = set()

    for combo in combos:
        scope = list(dict.fromkeys(combo["tract_ids"]))
        tracts = [db.tracts[tid] for tid in scope]
        if not all(t["status"] == "OFFERED" and t["id"] not in assigned for t in tracts):
            continue
        threshold = (Decimal("1") + COMBO_PREMIUM_PCT) * sum(
            (ind_high[tid]["amount"] if tid in ind_high else Decimal("0")) for tid in scope
        )
        threshold = threshold.quantize(Q2, rounding=ROUND_HALF_UP)
        min_sum = sum((t["min_price"] for t in tracts), Decimal("0"))
        if combo["amount"] >= max(threshold, min_sum):
            winners.append(combo)
            winner_ids.add(combo["id"])
            assigned.update(scope)

    # Remaining OFFERED tracts with an individual high are won by that bid.
    for t in listing_tracts:
        if t["id"] in assigned or t["status"] != "OFFERED":
            continue
        hb = ind_high.get(t["id"])
        if hb is not None and hb["id"] not in winner_ids:
            winners.append(hb)
            winner_ids.add(hb["id"])
            assigned.add(t["id"])

    awarded_total = sum((b["amount"] for b in winners), Decimal("0"))
    losers = [b for b in eligible if b["id"] not in winner_ids]
    return winners, losers, awarded_total, assigned
