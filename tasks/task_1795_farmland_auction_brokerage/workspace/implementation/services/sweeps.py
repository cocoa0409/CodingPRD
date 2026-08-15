"""Logical-clock sweeps and shared cascade helpers (PRD 2.5, 2.9, 3.7)."""

from datetime import timedelta

import db
from response import touch

ACTIVE_AUCTION_STATES = ("SCHEDULED", "OPEN", "EXTENDED", "CLOSED_PENDING_AWARD")


def listing_of_auction(auction):
    return db.listings[auction["listing_id"]]


def listing_tracts(listing_id):
    return [t for t in db.tracts.values() if t["listing_id"] == listing_id]


def has_active_auction(listing_id):
    return any(
        a["listing_id"] == listing_id and a["status"] in ACTIVE_AUCTION_STATES
        for a in db.auctions.values()
    )


def unlock_rights_if_idle(listing):
    """Rights LOCKED -> DECLARED when no active auction of the listing remains."""
    if has_active_auction(listing["id"]):
        return
    for t in listing_tracts(listing["id"]):
        for r in db.rights.values():
            if r["tract_id"] == t["id"] and r["status"] == "LOCKED":
                r["status"] = "DECLARED"
                touch(r)


def listing_fallback_if_idle(listing):
    """Listing AUCTION_SCHEDULED -> MARKETED when no active auction remains."""
    if listing["status"] == "AUCTION_SCHEDULED" and not has_active_auction(listing["id"]):
        listing["status"] = "MARKETED"
        touch(listing)


def no_sale_fallout(auction):
    """Shared tail of every auction NO_SALE transition: listing fallback + rights unlock."""
    listing = listing_of_auction(auction)
    listing_fallback_if_idle(listing)
    unlock_rights_if_idle(listing)


def void_bids(auction, from_statuses):
    for b in db.bids.values():
        if b["auction_id"] == auction["id"] and b["status"] in from_statuses:
            b["status"] = "VOIDED"
            touch(b)


def forfeiture_cascade(deposit):
    """The five-hop unwind of PRD 3.7. Each hop applies only from its source state."""
    deposit["status"] = "FORFEITED"
    deposit["amount_forfeited"] = deposit["amount_received"]
    touch(deposit)

    buyer = db.buyers.get(deposit["buyer_id"])
    bid = db.bids.get(deposit["bid_id"])
    auction = db.auctions.get(bid["auction_id"]) if bid else None
    listing = listing_of_auction(auction) if auction else None

    # Hop 1: buyer -> DISQUALIFIED (from QUALIFIED or EXPIRED).
    if buyer is not None and buyer["qualification_status"] in ("QUALIFIED", "EXPIRED"):
        buyer["qualification_status"] = "DISQUALIFIED"
        touch(buyer)

    # Hop 2: this buyer's CONFIRMED_WINNER bid -> VOIDED.
    if bid is not None and bid["status"] == "CONFIRMED_WINNER":
        bid["status"] = "VOIDED"
        touch(bid)

    # Hop 3: auction AWARDED -> NO_SALE (voids any remaining confirmed winners).
    if auction is not None and auction["status"] == "AWARDED":
        void_bids(auction, ("CONFIRMED_WINNER",))
        auction["status"] = "NO_SALE"
        touch(auction)

    # Hop 4: listing UNDER_CONTRACT -> MARKETED.
    if listing is not None and listing["status"] == "UNDER_CONTRACT":
        listing["status"] = "MARKETED"
        touch(listing)

    # Hop 5: tracts SOLD -> OFFERED.
    if listing is not None:
        for t in listing_tracts(listing["id"]):
            if t["status"] == "SOLD":
                t["status"] = "OFFERED"
                touch(t)
        # Disclosures acknowledged by the disqualified buyer revert to DISCLOSED.
        for d in db.disclosures.values():
            if d["acknowledged_by_buyer_id"] == deposit["buyer_id"] and d["status"] == "ACKNOWLEDGED":
                d["status"] = "DISCLOSED"
                d["acknowledged_by_buyer_id"] = None
                touch(d)
        unlock_rights_if_idle(listing)


# ---------------------------------------------------------------------------
# Clock sweeps (run by POST /api/_clock/set_current_utc)
# ---------------------------------------------------------------------------

def sweep_auction_closes(now):
    for auction in sorted(db.auctions.values(), key=lambda a: a["_seq"]):
        if auction["status"] not in ("OPEN", "EXTENDED"):
            continue
        if now < auction["_effective_end_dt"]:
            continue
        standing = [
            b for b in db.bids.values()
            if b["auction_id"] == auction["id"] and b["status"] in ("PLACED", "SEALED")
        ]
        if standing:
            if auction["method"] == "SEALED_BID":
                for b in standing:
                    if b["status"] == "SEALED":
                        b["status"] = "REVEALED"
                        b["_amount_hidden"] = False
                        touch(b)
            auction["status"] = "CLOSED_PENDING_AWARD"
            touch(auction)
        else:
            auction["status"] = "NO_SALE"
            touch(auction)
            no_sale_fallout(auction)


def sweep_qualification_expiry(now):
    for buyer in db.buyers.values():
        if buyer["qualification_status"] != "QUALIFIED":
            continue
        exp = buyer.get("_qualification_expires_dt")
        if exp is not None and now >= exp:
            buyer["qualification_status"] = "EXPIRED"
            touch(buyer)


def sweep_deposit_late(now):
    for dep in db.deposits.values():
        if dep["status"] == "PENDING" and now > dep["_due_at_dt"]:
            if dep["amount_received"] < dep["amount_due"]:
                dep["status"] = "LATE"
                touch(dep)


def sweep_deposit_forfeit(now):
    for dep in sorted(db.deposits.values(), key=lambda d: d["_seq"]):
        if dep["status"] in ("PENDING", "LATE"):
            if now > dep["_due_at_dt"] + timedelta(hours=24):
                forfeiture_cascade(dep)


def run_all_sweeps(now):
    sweep_auction_closes(now)
    sweep_qualification_expiry(now)
    sweep_deposit_late(now)
    sweep_deposit_forfeit(now)
