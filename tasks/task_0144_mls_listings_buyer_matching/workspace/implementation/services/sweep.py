"""Deferred-action sweep (scaffold §1.5 + PRD §3.9).

Traverses time-gated rows in deterministic order:
  Contingency  → Offer → Counter → ShowingAppointment → Listing
within each, (created_at, id) ascending.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from config import LISTING_LIFETIME_DAYS
from db import store
from services.state_machine import (
    bump_version,
    fail_contingency_cascade,
    expire_listing_cascade,
    withdraw_open_counters_of_offer,
)


def _sorted_by_created_id(items):
    return sorted(items, key=lambda x: (x["created_at"], x["id"]))


def run_sweep() -> dict:
    now = store.now()

    expired_offers = 0
    expired_counters = 0
    failed_contingencies = 0
    expired_listings = 0
    no_show_showings = 0

    # 1. Contingencies — PENDING & deadline_at <= now() → FAILED + cascade.
    for c in _sorted_by_created_id(list(store.contingencies.values())):
        if c["status"] != "PENDING":
            continue
        if c["deadline_at"] > now:
            continue
        # Check accepted_offer / listing — only cascade if still UNDER_CONTRACT
        # on the listing whose accepted_offer_id matches this contingency's offer_id.
        offer = store.offers.get(c["offer_id"])
        if offer is None:
            # Just FAIL it without cascade.
            c["status"] = "FAILED"
            bump_version(c, now)
            failed_contingencies += 1
            continue
        listing = store.listings.get(offer["listing_id"])
        # Mark this contingency FAILED first.
        c["status"] = "FAILED"
        bump_version(c, now)
        failed_contingencies += 1
        # Cascade only if the listing is still UNDER_CONTRACT and this is
        # the accepted offer.
        if (
            listing is not None
            and listing["status"] == "UNDER_CONTRACT"
            and listing.get("accepted_offer_id") == offer["id"]
        ):
            fail_contingency_cascade(c, listing, offer, now)

    # 2. Offers — SUBMITTED & expires_at <= now() → EXPIRED (counters withdrawn).
    for o in _sorted_by_created_id(list(store.offers.values())):
        if o["status"] != "SUBMITTED":
            continue
        if o["expires_at"] > now:
            continue
        o["status"] = "EXPIRED"
        bump_version(o, now)
        withdraw_open_counters_of_offer(o["id"], now)
        expired_offers += 1

    # 3. Counters — OPEN & counter_expires_at <= now() → EXPIRED.
    for c in _sorted_by_created_id(list(store.counters.values())):
        if c["status"] != "OPEN":
            continue
        if c["counter_expires_at"] > now:
            continue
        c["status"] = "EXPIRED"
        expired_counters += 1

    # 4. ShowingAppointments — SCHEDULED & end_at <= now() & access never granted
    #    → NO_SHOW. Listing.showing_count decremented (recompute via state_machine).
    listings_touched_for_showcount = set()
    for s in _sorted_by_created_id(list(store.showings.values())):
        if s["status"] != "SCHEDULED":
            continue
        if s["end_at"] > now:
            continue
        if s.get("lockbox_access_granted_at") is not None:
            continue
        s["status"] = "NO_SHOW"
        bump_version(s, now)
        listings_touched_for_showcount.add(s["listing_id"])
        no_show_showings += 1

    from services.state_machine import recompute_showing_count
    for lid in listings_touched_for_showcount:
        listing = store.listings.get(lid)
        if listing is not None:
            recompute_showing_count(listing, now)

    # 5. Listings — ACTIVE & now() - created_at >= 180 days → EXPIRED cascade.
    threshold = timedelta(days=LISTING_LIFETIME_DAYS)
    for l in _sorted_by_created_id(list(store.listings.values())):
        if l["status"] != "ACTIVE":
            continue
        if (now - l["created_at"]) < threshold:
            continue
        expire_listing_cascade(l, now)
        expired_listings += 1

    return {
        "expired_offers": expired_offers,
        "expired_counters": expired_counters,
        "failed_contingencies": failed_contingencies,
        "expired_listings": expired_listings,
        "no_show_showings": no_show_showings,
    }
