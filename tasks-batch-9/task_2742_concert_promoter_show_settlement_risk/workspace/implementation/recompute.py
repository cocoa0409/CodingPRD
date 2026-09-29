"""Derived-field recomputation: tier -> show -> market cascade (PRD 2.10, 3.3, 3.4)."""

from decimal import Decimal

import calc
import store
from store import db

# The market exposure set and the artist routing set differ by exactly one
# state (POSTPONED) and are deliberately kept as two separate predicates.
EXPOSURE_IN_SCOPE = ("CONFIRMED", "ON_SALE", "PERFORMED")
ROUTING_IN_SCOPE = ("CONFIRMED", "ON_SALE", "PERFORMED", "POSTPONED")
CONFIRMED_COUNT_SCOPE = ("CONFIRMED", "ON_SALE", "PERFORMED")
LIVE_SCOPE = ("ON_SALE", "PERFORMED")


# ---------------------------------------------------------------------------
# ticket tier
# ---------------------------------------------------------------------------

def recompute_tier(tier):
    comp = 0
    held = 0
    for hold in store.holds_of_tier(tier["id"]):
        if hold["status"] == "CONVERTED":
            comp += hold["qty"]
        elif hold["status"] == "HELD":
            if hold["kind"] == "COMP":
                comp += hold["qty"]
            else:
                held += hold["qty"]
    tier["comp_qty"] = comp
    tier["held_qty"] = held
    if tier["status"] == "CLOSED":
        tier["available_qty"] = 0
    else:
        tier["available_qty"] = (tier["allocation_qty"] - tier["sold_qty"]
                                - comp - held)
    return tier


def comp_allowance(show_id):
    """3 percent of total allocation across every tier of the show, half up."""
    total_allocation = sum(t["allocation_qty"] for t in store.tiers_of_show(show_id))
    return calc.rhu(Decimal(total_allocation) * calc.COMP_ALLOWANCE_PCT / Decimal(100))


# ---------------------------------------------------------------------------
# budget line variance recognition
# ---------------------------------------------------------------------------

def _approver_role(variance_pct):
    if variance_pct <= calc.VARIANCE_ESCALATION_PCT:
        return "TOUR_ACCOUNTANT"
    return "RISK_OFFICER"


def refresh_line_variance(line):
    """Hops one and two of the invoice-approval cascade (PRD 3.6)."""
    approved = [i for i in store.invoices_of_line(line["id"])
                if i["status"] == "APPROVED"]
    actual = sum(i["amount_cents"] for i in approved)
    line["actual_cents"] = actual
    line["variance_cents"] = actual - line["budgeted_cents"]
    if line["budgeted_cents"]:
        line["variance_pct"] = calc.rhu2(
            Decimal(line["variance_cents"]) * Decimal(100)
            / Decimal(line["budgeted_cents"]))
    else:
        line["variance_pct"] = Decimal("0.00")

    variance_pct = line["variance_pct"]
    status = line["variance_status"]

    if status == "APPROVED":
        cap = line["approved_cap_cents"]
        if cap is not None and actual > cap:
            line["variance_status"] = "PENDING_APPROVAL"
            line["approved_cap_cents"] = None
            line["variance_decided_by_user_id"] = None
            line["required_approver_role"] = _approver_role(variance_pct)
            line["settlement_expense_cents"] = line["budgeted_cents"]
        else:
            line["settlement_expense_cents"] = (actual if cap is None
                                                else min(actual, cap))
    elif status == "REJECTED":
        marker = line.get("_actual_at_rejection", 0)
        if actual > marker:
            line["variance_status"] = "PENDING_APPROVAL"
            line["variance_decided_by_user_id"] = None
            line["required_approver_role"] = _approver_role(variance_pct)
            line["settlement_expense_cents"] = line["budgeted_cents"]
        else:
            line["settlement_expense_cents"] = line["budgeted_cents"]
    else:
        # WITHIN_TOLERANCE or PENDING_APPROVAL: band from the rounded pct.
        if variance_pct <= calc.VARIANCE_TOLERANCE_PCT:
            line["variance_status"] = "WITHIN_TOLERANCE"
            line["required_approver_role"] = "NONE"
            line["settlement_expense_cents"] = actual
        else:
            line["variance_status"] = "PENDING_APPROVAL"
            line["required_approver_role"] = _approver_role(variance_pct)
            line["settlement_expense_cents"] = line["budgeted_cents"]
    return line


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def _projection_inputs(show):
    """Provisional variant: whole sellable allocation at the current price."""
    gross = 0
    tickets = 0
    for tier in store.tiers_of_show(show["id"]):
        sellable = tier["allocation_qty"] - tier["comp_qty"] - tier["held_qty"]
        if sellable < 0:
            sellable = 0
        gross += sellable * tier["price_cents"]
        tickets += sellable
    return gross, tickets


def recompute_show(show):
    venue = db.venues.get(show["venue_id"])
    tiers = store.tiers_of_show(show["id"])
    lines = store.live_lines_of_show(show["id"])

    show["paid_tickets_sold"] = sum(t["sold_qty"] for t in tiers)
    show["comp_tickets_issued"] = sum(t["comp_qty"] for t in tiers)
    show["held_tickets"] = sum(t["held_qty"] for t in tiers)

    refunded = bool(show.get("_refunds_processed"))
    show["gross_sold_cents"] = 0 if refunded else sum(
        t["gross_sold_cents"] for t in tiers)

    offer = store.accepted_offer(show["id"])
    show["committed_guarantee_cents"] = offer["guarantee_cents"] if offer else 0

    gross = show["gross_sold_cents"] + show["transferred_in_gross_cents"]
    tickets = show["paid_tickets_sold"] + show["transferred_in_paid_tickets"]
    if refunded:
        show["adjusted_gross_cents"] = 0
    elif venue is not None:
        show["adjusted_gross_cents"] = calc.waterfall(
            gross, tickets, venue)["adjusted_gross_cents"]
    else:
        show["adjusted_gross_cents"] = 0

    show["total_budgeted_expense_cents"] = sum(l["budgeted_cents"] for l in lines)
    show["total_actual_expense_cents"] = sum(l["actual_cents"] for l in lines)

    if offer is not None:
        deductible = sum(l["settlement_expense_cents"] for l in lines
                         if l["is_artist_deductible"])
        cap = offer["expense_cap_cents"]
        allowed = deductible if cap is None else min(deductible, cap)
        show["breakeven_cents"] = show["committed_guarantee_cents"] + allowed
    else:
        show["breakeven_cents"] = 0

    projected_gross, projected_tickets = _projection_inputs(show)
    if venue is not None:
        show["projected_adjusted_gross_cents"] = calc.waterfall(
            projected_gross, projected_tickets, venue)["adjusted_gross_cents"]
    else:
        show["projected_adjusted_gross_cents"] = 0
    show["projected_promoter_net_cents"] = (
        show["projected_adjusted_gross_cents"]
        - show["committed_guarantee_cents"]
        - show["total_budgeted_expense_cents"])

    statuses = [l["variance_status"] for l in lines]
    if "PENDING_APPROVAL" in statuses:
        show["budget_posture"] = "VARIANCE_PENDING"
    elif all(s == "WITHIN_TOLERANCE" for s in statuses):
        show["budget_posture"] = "ON_BUDGET"
    else:
        show["budget_posture"] = "OVER_BUDGET"
    return show


def recompute_artist(artist):
    artist["confirmed_show_count"] = len([
        s for s in store.shows_of_artist(artist["id"])
        if s["show_status"] in CONFIRMED_COUNT_SCOPE])
    return artist


# ---------------------------------------------------------------------------
# market
# ---------------------------------------------------------------------------

def _settlement_of(show):
    paid = store.paid_settlement(show["id"])
    if paid is not None:
        return paid
    rows = store.settlements_of_show(show["id"])
    return rows[-1] if rows else None


def performance_index(market, valuation="TRAILING_SETTLED"):
    shows = store.shows_of_market(market["id"])
    numerator = 0
    denominator = 0
    for show in shows:
        if show["show_status"] != "SETTLED":
            continue
        settlement = _settlement_of(show)
        if settlement is not None:
            numerator += settlement["promoter_net_cents"]
        denominator += show["projected_promoter_net_cents"]
    if valuation == "MARK_TO_MARKET":
        for show in shows:
            if show["show_status"] not in LIVE_SCOPE:
                continue
            if store.paid_settlement(show["id"]) is not None:
                continue
            allocation = sum(t["allocation_qty"]
                             for t in store.tiers_of_show(show["id"]))
            if allocation > 0:
                numerator += calc.rhu(
                    Decimal(show["projected_promoter_net_cents"])
                    * Decimal(show["paid_tickets_sold"]) / Decimal(allocation))
            denominator += show["projected_promoter_net_cents"]
    if denominator <= 0:
        return 0
    return calc.rhu(Decimal(numerator) * Decimal(100) / Decimal(denominator))


def market_figures(market):
    shows = store.shows_of_market(market["id"])
    in_scope = [s for s in shows if s["show_status"] in EXPOSURE_IN_SCOPE]
    committed = sum(s["committed_guarantee_cents"] for s in in_scope)
    shortfall = sum(max(0, s["breakeven_cents"] - s["adjusted_gross_cents"])
                    for s in in_scope)
    recovered = 0
    for show in shows:
        for event in store.events_of_show(show["id"]):
            if event["status"] == "CLAIM_SETTLED":
                recovered += event["insurance_recovery_cents"]
    at_risk = max(0, shortfall - recovered)
    utilization = calc.utilization_pct(
        committed, market["guarantee_exposure_limit_cents"])
    settled_count = len([s for s in shows
                         if store.paid_settlement(s["id"]) is not None])
    return {
        "committed_guarantee_cents": committed,
        "at_risk_guarantee_cents": at_risk,
        "exposure_utilization_pct": utilization,
        "risk_posture": calc.risk_posture(utilization),
        "settled_show_count": settled_count,
    }


def recompute_market(market):
    if market is None:
        return None
    market.update(market_figures(market))
    market["performance_index"] = performance_index(market, "TRAILING_SETTLED")
    return market


# ---------------------------------------------------------------------------
# cascade helper
# ---------------------------------------------------------------------------

def cascade(show, bump_show=False, bump_market=False):
    """Recompute show then market; bump only the versions the PRD names."""
    recompute_show(show)
    if bump_show:
        store.touch(show)
    market = db.markets.get(show["market_id"])
    if market is not None:
        recompute_market(market)
        if bump_market:
            store.touch(market)
    return show
