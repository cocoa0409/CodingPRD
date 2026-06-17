"""Logical clock advance: fire due timers. PRD §3.12."""
from datetime import timedelta

import db
import constants as C
from services import core, auction


def fire_due_timers():
    """Close every auction whose effective_end_at has been reached and expire
    every offer whose TTL has elapsed, evaluated against the current clock.

    PRD §3.12: advancing closes due auctions (cascade orders + invoices) and
    expires due offers.
    """
    now = db.now_dt()

    # Close due auctions. Sort by effective_end_at for determinism.
    due_listings = []
    for l in db.listings.values():
        if l["status"] == "ACTIVE" and l["effective_end_at"] is not None:
            end = db.parse_iso(l["effective_end_at"])
            if now >= end:
                due_listings.append(l)
    due_listings.sort(key=lambda l: (l["effective_end_at"], l["created_at"], l["id"]))
    for l in due_listings:
        auction.close_auction(l)

    # Expire due offers.
    ttl = timedelta(seconds=C.OFFER_TTL_SECONDS)
    due_offers = []
    for o in db.offers.values():
        if o["status"] == "PENDING":
            if now >= db.parse_iso(o["created_at"]) + ttl:
                due_offers.append(o)
        elif o["status"] == "COUNTERED":
            if now >= db.parse_iso(o["updated_at"]) + ttl:
                due_offers.append(o)
    due_offers.sort(key=lambda o: (o["created_at"], o["id"]))
    for o in due_offers:
        o["status"] = "EXPIRED"
        core.touch(o)
