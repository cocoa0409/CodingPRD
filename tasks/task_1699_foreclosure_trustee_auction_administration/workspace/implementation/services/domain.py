"""Domain finders, derived statuses, hold-posture recompute, and views.

Path identifiers resolve left to right; the first unresolvable id aborts
with ERR_RESOURCE_NOT_FOUND (PRD §2.9).
"""
from datetime import timedelta

import db
from db import pub
from errors import err_not_found, err_beneficiary_ownership, err_bidder_ownership
from util import (parse_date_strict, format_date, add_days, business_days_before)
from services import calc

TERMINAL_CASE_STATES = ("CLOSED", "REINSTATED", "PAID_OFF", "CANCELLED")
BANKRUPTCY_STAY_TYPES = ("BANKRUPTCY_CHAPTER_7", "BANKRUPTCY_CHAPTER_11",
                         "BANKRUPTCY_CHAPTER_13")

# ---------------------------------------------------------------------------
# Finders (left-to-right path resolution)
# ---------------------------------------------------------------------------

def _get(store, entity_id, what):
    rec = store.get(entity_id)
    if rec is None:
        raise err_not_found(what + " not found: " + str(entity_id))
    return rec


def get_beneficiary(bid):
    return _get(db.beneficiaries, bid, "Beneficiary")


def get_case(cid):
    return _get(db.foreclosure_cases, cid, "ForeclosureCase")


def get_nod(nid):
    return _get(db.notices_of_default, nid, "NoticeOfDefault")


def get_nots(nid):
    return _get(db.notices_of_trustee_sale, nid, "NoticeOfTrusteeSale")


def get_publication(pid):
    return _get(db.publications, pid, "Publication")


def get_sale(sid):
    return _get(db.auction_sales, sid, "AuctionSale")


def get_registration(rid):
    return _get(db.bidder_registrations, rid, "BidderRegistration")


def get_instruction(iid):
    return _get(db.bidding_instructions, iid, "BiddingInstruction")


def get_quote(qid):
    return _get(db.quotes, qid, "Quote")


def get_advance(aid):
    return _get(db.cost_advances, aid, "CostAdvance")


def get_stay(sid):
    return _get(db.stay_orders, sid, "StayOrder")


def get_deed(did):
    return _get(db.trustees_deeds, did, "TrusteesDeed")


def get_claim(cid):
    return _get(db.surplus_claims, cid, "SurplusClaim")


def get_disbursement(did):
    return _get(db.disbursements, did, "Disbursement")


# ---------------------------------------------------------------------------
# Ownership checks (PRD §2.1, validation priority 3-4)
# ---------------------------------------------------------------------------

def check_beneficiary_owns_case(case, user_id, role):
    """Beneficiary-role calls touching a case (GET case, bidding-instructions,
    cost-advances) require case.beneficiary_id == X-User-ID."""
    if role == "Beneficiary" and case["beneficiary_id"] != user_id:
        raise err_beneficiary_ownership()


def check_bidder_owns_registration(registration_id, user_id, role):
    if role == "ThirdPartyBidder" and registration_id != user_id:
        raise err_bidder_ownership()


# ---------------------------------------------------------------------------
# Relationship selectors (creation order = created_at ASC, _seq tie-break)
# ---------------------------------------------------------------------------

def _children(store, fk_field, fk_value):
    items = [r for r in store.values() if r.get(fk_field) == fk_value]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return items


def case_nods(case_id):
    return _children(db.notices_of_default, "foreclosure_case_id", case_id)


def case_nots_list(case_id):
    return _children(db.notices_of_trustee_sale, "foreclosure_case_id", case_id)


def nots_publications(nots_id):
    return _children(db.publications, "notice_of_trustee_sale_id", nots_id)


def case_sales(case_id):
    return _children(db.auction_sales, "foreclosure_case_id", case_id)


def sale_postponements(sale_id):
    return _children(db.postponements, "auction_sale_id", sale_id)


def sale_registrations(sale_id):
    return _children(db.bidder_registrations, "auction_sale_id", sale_id)


def sale_bids(sale_id):
    items = _children(db.bids, "auction_sale_id", sale_id)
    items.sort(key=lambda r: (r["placed_at"], r["_seq"]))
    return items


def registration_bids(reg_id):
    return _children(db.bids, "bidder_registration_id", reg_id)


def case_instructions(case_id):
    return _children(db.bidding_instructions, "foreclosure_case_id", case_id)


def case_quotes(case_id):
    return _children(db.quotes, "foreclosure_case_id", case_id)


def case_advances(case_id):
    return _children(db.cost_advances, "foreclosure_case_id", case_id)


def case_stays(case_id):
    return _children(db.stay_orders, "foreclosure_case_id", case_id)


def sale_deeds(sale_id):
    return _children(db.trustees_deeds, "auction_sale_id", sale_id)


def case_claims(case_id):
    return _children(db.surplus_claims, "foreclosure_case_id", case_id)


def case_disbursements(case_id):
    return _children(db.disbursements, "foreclosure_case_id", case_id)


# ---------------------------------------------------------------------------
# Derived / computed lookups
# ---------------------------------------------------------------------------

def recorded_nod(case_id):
    """The case's RECORDED NoticeOfDefault, if any."""
    for n in case_nods(case_id):
        if n["status"] == "RECORDED":
            return n
    return None


def live_nots(case_id):
    """The case's NOTS in a live status (RECORDED / PUBLICATION_COMPLETE /
    SALE_SCHEDULED), if any — a case carries at most one live NOTS."""
    for n in case_nots_list(case_id):
        if n["status"] in ("RECORDED", "PUBLICATION_COMPLETE", "SALE_SCHEDULED"):
            return n
    return None


def active_instruction(case_id):
    for ins in case_instructions(case_id):
        if ins["status"] == "ACTIVE":
            return ins
    return None


def pending_sale(case_id):
    """The case's AuctionSale in SCHEDULED or CONDUCTED status, if any."""
    for s in case_sales(case_id):
        if s["status"] in ("SCHEDULED", "CONDUCTED"):
            return s
    return None


def closed_sale(case_id):
    """The case's most recent CLOSED sale (the one that produced the SOLD
    state / surplus), if any."""
    closed = [s for s in case_sales(case_id) if s["status"] == "CLOSED"]
    return closed[-1] if closed else None


def approved_advances(case_id):
    return [a for a in case_advances(case_id) if a["status"] == "APPROVED"]


def total_approved_costs_cents(case_id):
    return sum(a["amount_cents"] for a in approved_advances(case_id))


# ---------------------------------------------------------------------------
# Hold posture (PRD §2.10)
# ---------------------------------------------------------------------------

def compute_hold_status(case_id):
    stays = case_stays(case_id)
    if any(s["status"] == "ACTIVE" and s["stay_type"] in BANKRUPTCY_STAY_TYPES for s in stays):
        return "BANKRUPTCY_STAY"
    if any(s["status"] == "ACTIVE" and s["stay_type"] == "LITIGATION_HOLD" for s in stays):
        return "LITIGATION_HOLD"
    return "CLEAR"


def recompute_hold(case):
    new_hold = compute_hold_status(case["id"])
    if case["hold_status"] != new_hold:
        case["hold_status"] = new_hold
    return case["hold_status"]


# ---------------------------------------------------------------------------
# Lazy-derived EXPIRED statuses (never stored)
# ---------------------------------------------------------------------------

def quote_derived_status(quote):
    """EXPIRED is derived, not stored: a stored-ISSUED quote past its
    good_through_date surfaces EXPIRED on reads and acceptance."""
    if quote["status"] == "ISSUED":
        gtd = parse_date_strict(quote["good_through_date"])
        if gtd is not None and db.CLOCK.now_date() > gtd:
            return "EXPIRED"
    return quote["status"]


def claim_derived_status(claim):
    """A stored-FILED claim past the claims deadline (closing sale's
    closed_at + 180 days) surfaces EXPIRED on reads; EXPIRED claims drop out
    of the distribution input set."""
    if claim["status"] == "FILED":
        sale = closed_sale(claim["foreclosure_case_id"])
        if sale is not None and sale.get("closed_at"):
            close_date = db._parse_iso(sale["closed_at"]).date()
            deadline = add_days(close_date, calc.CLAIMS_WINDOW_DAYS)
            if db.CLOCK.now_date() > deadline:
                return "EXPIRED"
    return claim["status"]


# ---------------------------------------------------------------------------
# Views (serialize public fields; derive lazy statuses)
# ---------------------------------------------------------------------------

def view(rec):
    return pub(rec)


def quote_view(quote):
    v = pub(quote)
    v["status"] = quote_derived_status(quote)
    return v


def claim_view(claim):
    v = pub(claim)
    v["status"] = claim_derived_status(claim)
    return v


# ---------------------------------------------------------------------------
# Computed dates for the summary read / reinstatement cutoff
# ---------------------------------------------------------------------------

def reinstatement_deadline(case):
    """recording_date of the currently RECORDED NOD + 90 days; None when no
    RECORDED NOD."""
    nod = recorded_nod(case["id"])
    if nod is None:
        return None
    return add_days(parse_date_strict(nod["recording_date"]), calc.REINSTATEMENT_PERIOD_DAYS)


def reinstatement_cutoff(case):
    """Scheduled sale date minus 5 business days (weekend skip); None when no
    SCHEDULED/CONDUCTED sale exists."""
    sale = pending_sale(case["id"])
    if sale is None:
        return None
    sale_date = db._parse_iso(sale["scheduled_sale_start_at"]).date()
    return business_days_before(sale_date, calc.REINSTATEMENT_CUTOFF_BUSINESS_DAYS)


def claims_deadline(case):
    """Closing sale's closed_at date + 180 days; None when no CLOSED sale."""
    sale = closed_sale(case["id"])
    if sale is None or not sale.get("closed_at"):
        return None
    close_date = db._parse_iso(sale["closed_at"]).date()
    return add_days(close_date, calc.CLAIMS_WINDOW_DAYS)


def case_summary(case):
    return {
        "lifecycle_status": case["lifecycle_status"],
        "hold_status": case["hold_status"],
        "active_stay_count": sum(1 for s in case_stays(case["id"]) if s["status"] == "ACTIVE"),
        "reinstatement_deadline_date": format_date(reinstatement_deadline(case)),
        "reinstatement_cutoff_date": format_date(reinstatement_cutoff(case)),
        "claims_deadline_date": format_date(claims_deadline(case)),
        "undistributed_surplus_cents": case["undistributed_surplus_cents"],
        "total_approved_costs_cents": total_approved_costs_cents(case["id"]),
    }
