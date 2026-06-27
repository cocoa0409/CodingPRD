"""State-machine cascades and cross-aggregate side effects.

These are the operations where a single request mutates several resources, each
of which independently records its own updated_at + version bump (PRD §2.8).
"""
import calculations as calc
import clock
import db
from helpers import new_record, touch


# ---------------------------------------------------------------------------
# Escrow ledger (PRD §3.2). escrow_balance_cents is a running ledger maintained
# incrementally; deposit_total_cents is the cumulative deposit sum.
# ---------------------------------------------------------------------------
def escrow_credit(investor, amount):
    investor["escrow_balance_cents"] += amount
    touch(investor)


def escrow_debit(investor, amount):
    investor["escrow_balance_cents"] -= amount
    touch(investor)


# ---------------------------------------------------------------------------
# Sub-tax helpers
# ---------------------------------------------------------------------------
def posted_sub_taxes_for(certificate_id):
    """POSTED sub-taxes on a certificate, in posting order (creation order)."""
    rows = [s for s in db.sub_taxes.values()
            if s["certificate_id"] == certificate_id and s["status"] == "POSTED"]
    return sorted(rows, key=lambda s: s["_seq"])


def recompute_sub_tax_total(certificate):
    total = sum(s["principal_cents"] for s in posted_sub_taxes_for(certificate["id"]))
    certificate["sub_tax_total_cents"] = total


# ---------------------------------------------------------------------------
# Certificate issuance (close cascade, PRD §3.5/§3.6)
# ---------------------------------------------------------------------------
def issue_certificate(county, parcel, listing, winning_bid):
    """Create an ACTIVE certificate and lien the parcel."""
    now = clock.now()
    redeem_deadline = now + _days(county["redemption_period_days"])
    cert = new_record({
        "county_id": county["id"],
        "parcel_id": parcel["id"],
        "listing_id": listing["id"],
        "holder_investor_id": winning_bid["investor_id"],
        "face_amount_cents": parcel["base_tax_due_cents"],
        "rate_bps": winning_bid["_award_rate_bps"],
        "premium_cents": winning_bid["_award_premium_cents"],
        "issued_at": clock.format_iso(now),
        "issued_at_dt": now,
        "redeem_deadline_at": clock.format_iso(redeem_deadline),
        "redeem_deadline_at_dt": redeem_deadline,
        "sub_tax_total_cents": 0,
        "assignment_seq": 0,
        "status": "ACTIVE",
    })
    db.certificates[cert["id"]] = cert

    listing["winning_bid_id"] = winning_bid["id"]
    listing["certificate_id"] = cert["id"]

    parcel["status"] = "LIENED"
    parcel["active_certificate_id"] = cert["id"]
    touch(parcel)
    return cert


def _days(n):
    from datetime import timedelta
    return timedelta(days=n)


# ---------------------------------------------------------------------------
# Award winner selection (PRD §3.5, scaffold award_winner)
# ---------------------------------------------------------------------------
def select_winner(placed_bids, sale, county):
    """Pick the winning bid and annotate the awarded rate/premium on it."""
    if sale["sale_type"] == "RATE_BID_DOWN":
        # Lowest rate_bps wins; ties -> earliest created (lowest _seq).
        winner = min(placed_bids, key=lambda b: (b["rate_bps"], b["_seq"]))
        winner["_award_rate_bps"] = winner["rate_bps"]
        winner["_award_premium_cents"] = 0
    else:  # PREMIUM
        # Highest premium_cents wins; ties -> earliest created (lowest _seq).
        winner = max(placed_bids, key=lambda b: (b["premium_cents"], -b["_seq"]))
        winner["_award_rate_bps"] = county["max_interest_rate_bps"]
        winner["_award_premium_cents"] = winner["premium_cents"]
    return winner


def hold_amount(bid, sale, parcel):
    """Escrow hold for a PLACED bid (PRD §3.4): face(+premium for PREMIUM)."""
    if sale["sale_type"] == "PREMIUM":
        return parcel["base_tax_due_cents"] + (bid.get("premium_cents") or 0)
    return parcel["base_tax_due_cents"]


# ---------------------------------------------------------------------------
# Close cascade (PRD §3.5)
# ---------------------------------------------------------------------------
def run_close_cascade(county, sale):
    """Award every LISTED listing, releasing/committing escrow holds."""
    listings = [l for l in db.listings.values()
                if l["sale_id"] == sale["id"] and l["status"] == "LISTED"]
    listings.sort(key=lambda l: l["_seq"])

    for listing in listings:
        placed = [b for b in db.bids.values()
                  if b["listing_id"] == listing["id"] and b["status"] == "PLACED"]
        parcel = db.parcels[listing["parcel_id"]]

        if not placed:
            # No bids -> struck off, no certificate. Parcel reverts unless
            # already liened by another path.
            listing["status"] = "STRUCK_OFF"
            touch(listing)
            _maybe_revert_parcel(parcel)
            continue

        winner = select_winner(placed, sale, county)

        for bid in placed:
            investor = db.investors[bid["investor_id"]]
            if bid["id"] == winner["id"]:
                bid["status"] = "WON"
                # The hold placed at bid time becomes a permanent commitment with
                # "no further escrow change" (PRD §3.5): the already-held amount is
                # simply not released, so we touch the bid but do not re-debit.
                touch(bid)
            else:
                bid["status"] = "LOST"
                # Release the hold back to the loser.
                escrow_credit(investor, hold_amount(bid, sale, parcel))
                touch(bid)

        listing["status"] = "SOLD"
        issue_certificate(county, parcel, listing, winner)
        touch(listing)


def _maybe_revert_parcel(parcel):
    """Revert ON_SALE -> DELINQUENT if no still-LISTED listing references it."""
    if parcel["status"] != "ON_SALE":
        return
    other = any(l for l in db.listings.values()
                if l["parcel_id"] == parcel["id"] and l["status"] == "LISTED")
    if not other:
        parcel["status"] = "DELINQUENT"
        touch(parcel)


# ---------------------------------------------------------------------------
# Listing withdrawal (PRD §3.3)
# ---------------------------------------------------------------------------
def withdraw_listing(listing):
    """LISTED -> WITHDRAWN: refund PLACED bids, revert parcel, bump version."""
    for bid in db.bids.values():
        if bid["listing_id"] == listing["id"] and bid["status"] == "PLACED":
            investor = db.investors[bid["investor_id"]]
            sale = db.sales[listing["sale_id"]]
            parcel = db.parcels[listing["parcel_id"]]
            escrow_credit(investor, hold_amount(bid, sale, parcel))
            bid["status"] = "REFUNDED"
            touch(bid)
    listing["status"] = "WITHDRAWN"
    touch(listing)
    parcel = db.parcels[listing["parcel_id"]]
    _maybe_revert_parcel(parcel)


# ---------------------------------------------------------------------------
# Redemption (PRD §3.9)
# ---------------------------------------------------------------------------
def process_redemption(county, certificate, filed_deed=None):
    """Create a Redemption, settle the lien, transition certificate -> REDEEMED."""
    now = clock.now()
    posted = posted_sub_taxes_for(certificate["id"])
    filed_cost = filed_deed["deed_cost_cents"] if filed_deed else 0
    payoff = calc.compute_payoff(county, certificate, posted, now, filed_cost)

    redemption = new_record({
        "certificate_id": certificate["id"],
        "redeemed_at": clock.format_iso(now),
        "face_payoff_cents": payoff["face_payoff_cents"],
        "face_interest_cents": payoff["face_interest_cents"],
        "penalty_cents": payoff["penalty_cents"],
        "sub_tax_payoff_cents": payoff["sub_tax_payoff_cents"],
        "sub_tax_interest_cents": payoff["sub_tax_interest_cents"],
        "premium_refund_cents": payoff["premium_refund_cents"],
        "total_payoff_cents": payoff["total_payoff_cents"],
    })
    db.redemptions[redemption["id"]] = redemption

    # Credit holder the lien payoff. The filed-deed-cost passthrough reimburses
    # the applicant outside the holder's lien credit (PRD §3.9), so exclude it.
    holder = db.investors[certificate["holder_investor_id"]]
    escrow_credit(holder, payoff["total_payoff_cents"] - filed_cost)

    for st in posted:
        st["status"] = "REDEEMED"
        touch(st)

    parcel = db.parcels[certificate["parcel_id"]]
    parcel["status"] = "REDEEMED"
    parcel["active_certificate_id"] = None
    touch(parcel)

    if filed_deed is not None:
        filed_deed["status"] = "CANCELLED"
        touch(filed_deed)

    certificate["status"] = "REDEEMED"
    touch(certificate)
    return redemption


# ---------------------------------------------------------------------------
# Deed application filing (PRD §3.10)
# ---------------------------------------------------------------------------
def file_deed_application(county, certificate, applicant_id, deed_cost_cents):
    now = clock.now()
    posted = posted_sub_taxes_for(certificate["id"])
    minimum_bid = calc.compute_position(county, certificate, posted, now, deed_cost_cents)

    deed = new_record({
        "certificate_id": certificate["id"],
        "applicant_investor_id": applicant_id,
        "deed_cost_cents": deed_cost_cents,
        "minimum_bid_cents": minimum_bid,
        "sale_price_cents": None,
        "status": "FILED",
    })
    db.deed_applications[deed["id"]] = deed

    holder = db.investors[certificate["holder_investor_id"]]
    escrow_debit(holder, deed_cost_cents)

    certificate["status"] = "FORECLOSURE_PENDING"
    touch(certificate)
    return deed


# ---------------------------------------------------------------------------
# Deed award (PRD §3.10/§3.11)
# ---------------------------------------------------------------------------
def award_deed(county, certificate, deed, sale_price_cents):
    lien_satisfied, surplus = calc.compute_surplus(
        sale_price_cents, deed["minimum_bid_cents"]
    )

    deed["sale_price_cents"] = sale_price_cents
    deed["status"] = "AWARDED"

    surplus_rec = new_record({
        "deed_application_id": deed["id"],
        "certificate_id": certificate["id"],
        "gross_proceeds_cents": sale_price_cents,
        "lien_satisfied_cents": lien_satisfied,
        "surplus_cents": surplus,
        "claimed": False,
    })
    db.surplus_distributions[surplus_rec["id"]] = surplus_rec

    holder = db.investors[certificate["holder_investor_id"]]
    escrow_credit(holder, lien_satisfied)

    for st in posted_sub_taxes_for(certificate["id"]):
        st["status"] = "REDEEMED"
        touch(st)

    parcel = db.parcels[certificate["parcel_id"]]
    parcel["status"] = "DEEDED"
    parcel["active_certificate_id"] = None
    touch(parcel)

    touch(deed)
    certificate["status"] = "DEEDED"
    touch(certificate)
    return deed


def cancel_deed(certificate, deed):
    deed["status"] = "CANCELLED"
    touch(deed)
    certificate["status"] = "ACTIVE"
    touch(certificate)
    return deed
