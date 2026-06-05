"""Shared mutation/cascade helpers: version bumps, cascades, bubbling."""
from db import db, now_iso
from services.money import commission_split, financing_passes
from services.negotiation import offer_projection


def touch(rec):
    """Bump updated_at + version on a versioned resource (a mutation)."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] += 1


def listing_offers(listing_id):
    return [o for o in db.offers.values() if o["listing_id"] == listing_id]


def listing_lockboxes(listing_id):
    return [lb for lb in db.lockboxes.values() if lb["listing_id"] == listing_id]


def lockbox_showings(lockbox_id):
    return [s for s in db.showings.values() if s["lockbox_id"] == lockbox_id]


def listing_showings(listing_id):
    lb_ids = {lb["id"] for lb in listing_lockboxes(listing_id)}
    return [s for s in db.showings.values() if s["lockbox_id"] in lb_ids]


def offer_contingencies(offer_id):
    return [c for c in db.contingencies.values() if c["offer_id"] == offer_id]


# ---------------------------------------------------------------------------
# Listing transitions driven by offer/contingency side effects
# ---------------------------------------------------------------------------

def accept_offer_cascade(listing, accepted_offer):
    """ACTIVE -> UNDER_CONTRACT on acceptance.

    Freeze price, reject siblings, set accepted_offer_id, materialize
    contingencies, bubble to PENDING if no contingencies requested.
    """
    proj = offer_projection(accepted_offer)
    accepted_offer["effective_price_cents"] = proj["current_price_cents"]
    accepted_offer["status"] = "ACCEPTED"
    touch(accepted_offer)

    # Reject sibling live offers
    for o in listing_offers(listing["id"]):
        if o["id"] == accepted_offer["id"]:
            continue
        if o["status"] in ("OPEN", "SELLER_COUNTERED", "BUYER_COUNTERED"):
            o["status"] = "REJECTED"
            touch(o)

    listing["status"] = "UNDER_CONTRACT"
    listing["accepted_offer_id"] = accepted_offer["id"]
    touch(listing)

    # Materialize contingencies
    from services.entities import make_contingency
    for kind in accepted_offer["requested_contingencies"]:
        make_contingency(accepted_offer["id"], kind)

    # If none requested, immediately bubble UNDER_CONTRACT -> PENDING
    if not accepted_offer["requested_contingencies"]:
        bubble_to_pending_if_ready(listing, accepted_offer)


def bubble_to_pending_if_ready(listing, offer):
    """If every contingency on the offer is WAIVED/SATISFIED (none PENDING/FAILED),
    move listing UNDER_CONTRACT -> PENDING."""
    if listing["status"] != "UNDER_CONTRACT":
        return
    conts = offer_contingencies(offer["id"])
    if any(c["status"] == "PENDING" for c in conts):
        return
    if any(c["status"] == "FAILED" for c in conts):
        return
    listing["status"] = "PENDING"
    touch(listing)


def fail_contingency_cascade(listing, offer):
    """A contingency on the accepted offer FAILED: unwind the deal.

    Offer -> WITHDRAWN, remaining PENDING contingencies -> WAIVED,
    listing UNDER_CONTRACT -> ACTIVE, accepted_offer_id cleared.
    """
    offer["status"] = "WITHDRAWN"
    touch(offer)
    for c in offer_contingencies(offer["id"]):
        if c["status"] == "PENDING":
            c["status"] = "WAIVED"
            touch(c)
    listing["status"] = "ACTIVE"
    listing["accepted_offer_id"] = None
    touch(listing)


def make_commission_ledger(listing):
    from services.entities import make_ledger_record
    split = commission_split(
        listing["final_sale_price_cents"],
        listing["total_commission_pct"],
        listing["coop_split_pct"],
    )
    return make_ledger_record(listing["id"], listing["final_sale_price_cents"], split)
