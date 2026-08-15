"""System clock sweeps: listing expiry, offer expiry, contingency expiry.
Runs whenever the logical clock is advanced via /_clock/set_current_utc."""
from datetime import timedelta
from db import db, clock, parse_iso
from services.common import touch
from services.events import emit

CURE_WINDOW_DAYS = 5


def _expire_offer(offer):
    offer["status"] = "EXPIRED"
    touch(offer)


def _expire_listing_offers(listing_id):
    for o in db.offers.values():
        if o["listing_id"] == listing_id and o["status"] in ("PENDING", "COUNTERED"):
            _expire_offer(o)


def run_sweeps():
    now = clock.now()

    # Listing expiry at end_date (ACTIVE or SUSPENDED -> EXPIRED)
    for l in db.listings.values():
        if l["status"] in ("ACTIVE", "SUSPENDED"):
            if now >= parse_iso(l["end_date"]):
                l["status"] = "EXPIRED"
                l["syndication_status"] = "WITHDRAWN"
                touch(l)
                _expire_listing_offers(l["id"])
                emit("ListingAgreement", l["id"], "LISTING_EXPIRED", "system", "system",
                     {"status": "EXPIRED"})

    # Offer expiry past acceptance_deadline (PENDING or COUNTERED -> EXPIRED)
    for o in db.offers.values():
        if o["status"] in ("PENDING", "COUNTERED"):
            if now > parse_iso(o["acceptance_deadline"]):
                _expire_offer(o)

    # Contingency expiry: OPEN past deadline; OBJECTED past 5-day cure window
    for c in db.contingencies.values():
        if c["status"] == "OPEN":
            if now > parse_iso(c["deadline"]):
                c["status"] = "EXPIRED"
                touch(c)
        elif c["status"] == "OBJECTED":
            objected_at = c.get("objected_at")
            if objected_at is not None:
                if now > parse_iso(objected_at) + timedelta(days=CURE_WINDOW_DAYS):
                    c["status"] = "EXPIRED"
                    touch(c)
