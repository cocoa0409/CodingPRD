"""Deal negotiation state machine, bubble-up, and cascades (PRD §3.5, §3.6)."""
from db import db, touch
from services.calc import (net_effective_rent, lease_consideration,
                           effective_commission_pct, total_commission,
                           commission_split)
from services.recompute import (recompute_deal_round_count,
                                recompute_listing_open_deal_count,
                                reconcile_listing_status,
                                recompute_property_available_sf,
                                recompute_all_requirement_match_counts)


# ---------------------------------------------------------------------------
# Proposal helpers
# ---------------------------------------------------------------------------
def latest_pending_proposal(deal_id):
    candidates = [p for p in db.proposals.values()
                  if p["deal_id"] == deal_id and p["outcome"] == "PENDING"]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return candidates[-1]


# ---------------------------------------------------------------------------
# Bubble-up: Requirement status on first LOI_DRAFT and reversion to OPEN
# ---------------------------------------------------------------------------
def bubble_requirement_to_negotiating(requirement_id):
    req = db.requirements.get(requirement_id)
    if req is None:
        return
    if req["status"] in ("OPEN", "TOURING"):
        req["status"] = "NEGOTIATING"
        touch(req)


def reconcile_requirement_after_kill(requirement_id):
    """NEGOTIATING -> OPEN when this was the requirement's only open deal (PRD §3.6)."""
    req = db.requirements.get(requirement_id)
    if req is None or req["status"] != "NEGOTIATING":
        return
    any_open = any(
        d["requirement_id"] == requirement_id and d["stage"] not in ("DEAD", "EXECUTED")
        for d in db.deals.values()
    )
    if not any_open:
        req["status"] = "OPEN"
        touch(req)


def bubble_listing_to_under_negotiation(listing_id):
    lst = db.listings.get(listing_id)
    if lst is None:
        return
    if lst["status"] == "ACTIVE":
        lst["status"] = "UNDER_NEGOTIATION"
        touch(lst)


# ---------------------------------------------------------------------------
# Acceptance financial computation (PRD §3.7, §3.8)
# ---------------------------------------------------------------------------
def compute_deal_financials(deal, proposal):
    sp = _deal_space(deal)
    rentable_sf = sp["rentable_sf"]
    consideration = lease_consideration(
        proposal["base_rent_psf_yr"], proposal["term_months"],
        proposal["annual_escalation_pct"], rentable_sf)
    listing_broker = db.brokers.get(deal["listing_broker_id"])
    brokerage = db.brokerages.get(listing_broker["brokerage_id"])
    eff_pct = effective_commission_pct(
        brokerage["default_commission_pct"], proposal["term_months"])
    commission = total_commission(consideration, eff_pct)
    deal["total_consideration"] = consideration
    deal["total_commission"] = commission


def _deal_space(deal):
    lst = db.listings.get(deal["listing_id"])
    return db.spaces.get(lst["space_id"])


# ---------------------------------------------------------------------------
# Space cascades driven by deal transitions
# ---------------------------------------------------------------------------
def space_to_under_loi(deal):
    """On LOI_ACCEPTED: Space AVAILABLE/ON_HOLD -> UNDER_LOI; complete holding tour."""
    sp = _deal_space(deal)
    if sp is None:
        return
    holding_tour_id = sp.get("held_by_tour_id")
    if sp["status"] in ("AVAILABLE", "ON_HOLD"):
        sp["status"] = "UNDER_LOI"
        sp["held_by_tour_id"] = None
        touch(sp)
        recompute_property_available_sf(sp["property_id"])
    # complete the holding tour if one exists
    if holding_tour_id:
        tour = db.tours.get(holding_tour_id)
        if tour is not None and tour["status"] == "CONFIRMED":
            tour["holds_space"] = False
            tour["status"] = "COMPLETED"
            touch(tour)


def space_under_loi_to_available(deal):
    """Compensation on kill from LOI_ACCEPTED: UNDER_LOI -> AVAILABLE."""
    sp = _deal_space(deal)
    if sp is None:
        return
    if sp["status"] == "UNDER_LOI":
        sp["status"] = "AVAILABLE"
        touch(sp)
        recompute_property_available_sf(sp["property_id"])


def space_under_loi_to_leased(deal):
    sp = _deal_space(deal)
    if sp is None:
        return
    if sp["status"] == "UNDER_LOI":
        sp["status"] = "LEASED"
        touch(sp)
        recompute_property_available_sf(sp["property_id"])


# ---------------------------------------------------------------------------
# Kill cascade (used by /kill and by listing-withdraw)
# ---------------------------------------------------------------------------
def kill_deal_cascade(deal, reconcile_parents=True):
    """Drive a deal to DEAD with the appropriate compensating side effects.

    Used internally (no OCC, no version bump beyond the standard touch) for
    sibling/cascade kills. Does NOT itself bump deal.version unless via touch.
    """
    prior_stage = deal["stage"]
    if prior_stage in ("EXECUTED", "DEAD"):
        return
    # reject all PENDING proposals
    for p in db.proposals.values():
        if p["deal_id"] == deal["id"] and p["outcome"] == "PENDING":
            p["outcome"] = "REJECTED"
            touch(p)
    if prior_stage == "LOI_ACCEPTED":
        # compensating cascade: undo acceptance
        ap_id = deal.get("accepted_proposal_id")
        if ap_id:
            ap = db.proposals.get(ap_id)
            if ap is not None and ap["outcome"] == "ACCEPTED":
                ap["outcome"] = "REJECTED"
                touch(ap)
        deal["accepted_proposal_id"] = None
        deal["total_consideration"] = 0
        deal["total_commission"] = 0
        space_under_loi_to_available(deal)
    deal["stage"] = "DEAD"
    touch(deal)
    if reconcile_parents:
        reconcile_listing_status(deal["listing_id"])
        reconcile_requirement_after_kill(deal["requirement_id"])


# ---------------------------------------------------------------------------
# Execute cascade (PRD §3.6)
# ---------------------------------------------------------------------------
def execute_deal_cascade(deal):
    from db import new_lean_record
    # commission split rows
    lst = db.listings.get(deal["listing_id"])
    listing_amount, procuring_amount = commission_split(
        deal["total_commission"], deal["is_co_broke"], lst["co_broke_offered_pct"])
    listing_row = new_lean_record({
        "deal_id": deal["id"],
        "broker_id": deal["listing_broker_id"],
        "side": "LISTING",
        "amount": listing_amount,
    })
    db.commission_splits[listing_row["id"]] = listing_row
    procuring_row = new_lean_record({
        "deal_id": deal["id"],
        "broker_id": deal["procuring_broker_id"],
        "side": "PROCURING",
        "amount": procuring_amount,
    })
    db.commission_splits[procuring_row["id"]] = procuring_row

    # Space UNDER_LOI -> LEASED
    space_under_loi_to_leased(deal)
    # Listing UNDER_NEGOTIATION -> EXECUTED
    if lst is not None and lst["status"] == "UNDER_NEGOTIATION":
        lst["status"] = "EXECUTED"
        touch(lst)
    # sibling deals on this listing NOT IN {EXECUTED, DEAD} -> DEAD
    for sib in list(db.deals.values()):
        if sib["id"] == deal["id"]:
            continue
        if sib["listing_id"] == deal["listing_id"] and \
                sib["stage"] not in ("EXECUTED", "DEAD"):
            kill_deal_cascade(sib, reconcile_parents=False)
    # Requirement NEGOTIATING -> PLACED
    req = db.requirements.get(deal["requirement_id"])
    if req is not None and req["status"] == "NEGOTIATING":
        req["status"] = "PLACED"
        touch(req)
    # cancel other tours of that requirement in REQUESTED/CONFIRMED
    from services.tour_engine import release_tour_hold
    for t in db.tours.values():
        if t["requirement_id"] == deal["requirement_id"] and \
                t["status"] in ("REQUESTED", "CONFIRMED"):
            release_tour_hold(t)
            t["status"] = "CANCELLED"
            touch(t)
    # append Comp
    sp = _deal_space(deal)
    prop = db.properties.get(sp["property_id"]) if sp else None
    accepted = db.proposals.get(deal.get("accepted_proposal_id"))
    comp = new_lean_record({
        "space_id": sp["id"] if sp else None,
        "deal_id": deal["id"],
        "market": prop["market"] if prop else None,
        "effective_rent_psf_yr": accepted["net_effective_rent_psf_yr"] if accepted else None,
        "term_months": accepted["term_months"] if accepted else None,
        "executed_at": db.current_clock_iso(),
    })
    db.comps[comp["id"]] = comp
    # recompute match counts (listing now EXECUTED, no longer matches)
    recompute_all_requirement_match_counts()
