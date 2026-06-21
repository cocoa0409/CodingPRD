"""Derived-field recomputation and bubble-up reconciliation.

Each recompute that changes a value mutates its carrying record (updated_at +
version bump) per PRD §2.4 / §2.5. Recomputes are idempotent: when the derived
value is unchanged, no mutation is applied.
"""
from db import db, touch


# ---------------------------------------------------------------------------
# Property.available_sf  (PRD §2.6)
# ---------------------------------------------------------------------------
def recompute_property_available_sf(property_id):
    prop = db.properties.get(property_id)
    if prop is None:
        return
    total = 0
    for sp in db.spaces.values():
        if sp["property_id"] == property_id and sp["status"] == "AVAILABLE":
            total += sp["rentable_sf"]
    if prop["available_sf"] != total:
        prop["available_sf"] = total
        touch(prop)


# ---------------------------------------------------------------------------
# Listing.open_deal_count  (PRD §2.6) and ACTIVE<->UNDER_NEGOTIATION reversion
# ---------------------------------------------------------------------------
def _count_open_deals(listing_id):
    n = 0
    for d in db.deals.values():
        if d["listing_id"] == listing_id and d["stage"] not in ("DEAD", "EXECUTED"):
            n += 1
    return n


def recompute_listing_open_deal_count(listing_id):
    lst = db.listings.get(listing_id)
    if lst is None:
        return
    count = _count_open_deals(listing_id)
    if lst["open_deal_count"] != count:
        lst["open_deal_count"] = count
        touch(lst)


def reconcile_listing_status(listing_id):
    """UNDER_NEGOTIATION -> ACTIVE when open_deal_count returns to 0 and no
    deal executed (PRD §3.2)."""
    lst = db.listings.get(listing_id)
    if lst is None:
        return
    recompute_listing_open_deal_count(listing_id)
    if lst["status"] == "UNDER_NEGOTIATION" and lst["open_deal_count"] == 0:
        any_executed = any(
            d["listing_id"] == listing_id and d["stage"] == "EXECUTED"
            for d in db.deals.values()
        )
        if not any_executed:
            lst["status"] = "ACTIVE"
            touch(lst)


# ---------------------------------------------------------------------------
# Requirement.match_count  (PRD §3.3 matching predicate)
# ---------------------------------------------------------------------------
def listing_matches_requirement(lst, req):
    if lst["status"] not in ("ACTIVE", "UNDER_NEGOTIATION"):
        return False
    sp = db.spaces.get(lst["space_id"])
    if sp is None:
        return False
    prop = db.properties.get(sp["property_id"])
    if prop is None:
        return False
    if prop["market"] != req["market"]:
        return False
    if prop["asset_class"] != req["asset_class"]:
        return False
    if not (req["min_sf"] <= sp["rentable_sf"] <= req["max_sf"]):
        return False
    if not (sp["asking_rent_psf_yr"] <= req["max_rent_psf_yr"]):
        return False
    return True


def matching_listings_for_requirement(req):
    matches = []
    for lst in db.listings.values():
        if listing_matches_requirement(lst, req):
            matches.append(lst)
    return matches


def recompute_requirement_match_count(requirement_id):
    req = db.requirements.get(requirement_id)
    if req is None:
        return
    count = len(matching_listings_for_requirement(req))
    if req["match_count"] != count:
        req["match_count"] = count
        touch(req)


def recompute_all_requirement_match_counts():
    """Recompute match_count for every requirement (used on space/listing change)."""
    for rid in list(db.requirements.keys()):
        recompute_requirement_match_count(rid)


# ---------------------------------------------------------------------------
# Deal.round_count  (PRD §2.6)
# ---------------------------------------------------------------------------
def recompute_deal_round_count(deal_id):
    deal = db.deals.get(deal_id)
    if deal is None:
        return
    count = sum(1 for p in db.proposals.values() if p["deal_id"] == deal_id)
    deal["round_count"] = count
