"""Settlement math: commission_calc, closing_cost_allocation, possession_proration,
seller_net_sheet."""

from decimal import Decimal, ROUND_HALF_UP

import db
from services.valuation import compute_valuation

Q2 = Decimal("0.01")

# commission_calc constants
COMMISSION_FLOOR = Decimal("7500")
KICKER_THRESHOLD = Decimal("1.10")
KICKER_PCT = Decimal("0.005")

# closing_cost_allocation constants
TITLE_FLAT = Decimal("1500")
TITLE_PCT = Decimal("0.002")
SURVEY_PER_TRACT = Decimal("1200")
ESCROW_PCT = Decimal("0.001")
ESCROW_SELLER_SHARE = Decimal("0.5")
EST_COST_PCT = Decimal("0.005")


def money(d: Decimal) -> Decimal:
    return d.quantize(Q2, rounding=ROUND_HALF_UP)


def winning_scope_tracts(auction):
    """Tracts covered by CONFIRMED_WINNER bids of the auction, in listing order."""
    scope_ids = []
    winners = sorted(
        (b for b in db.bids.values()
         if b["auction_id"] == auction["id"] and b["status"] == "CONFIRMED_WINNER"),
        key=lambda b: b["_seq"],
    )
    for b in winners:
        for tid in dict.fromkeys(b["tract_ids"]):
            if tid not in scope_ids:
                scope_ids.append(tid)
    return [db.tracts[tid] for tid in scope_ids]


def appraisal_map(tracts):
    """tract_id -> APPRAISAL estimated_value (whole dollars)."""
    out = {}
    for t in tracts:
        _, _, est = compute_valuation(t, "APPRAISAL")
        out[t["id"]] = est
    return out


def commission_calc(gross: Decimal, appraisal_total: Decimal) -> Decimal:
    """Marginal tiers, then over-appraisal kicker, then floor; round only the final."""
    g = gross
    base = Decimal("0")
    base += Decimal("0.06") * min(g, Decimal("250000"))
    if g > Decimal("250000"):
        base += Decimal("0.045") * (min(g, Decimal("750000")) - Decimal("250000"))
    if g > Decimal("750000"):
        base += Decimal("0.03") * (min(g, Decimal("2000000")) - Decimal("750000"))
    if g > Decimal("2000000"):
        base += Decimal("0.015") * (g - Decimal("2000000"))
    kicker = KICKER_PCT * g if g >= KICKER_THRESHOLD * appraisal_total else Decimal("0")
    return money(max(COMMISSION_FLOOR, base + kicker))


def closing_costs_final(gross: Decimal, scope_tracts, appraisals):
    """Returns (allocated_total, tract_allocations list). Per-tract rounding first,
    residual (signed cents) to the tract with the highest tract_number."""
    n = Decimal(len(scope_tracts))
    total_cost = TITLE_FLAT + TITLE_PCT * gross + SURVEY_PER_TRACT * n \
        + ESCROW_PCT * gross * ESCROW_SELLER_SHARE
    total_cost = money(total_cost)

    appr_sum = sum(appraisals.values())
    allocations = []
    running = Decimal("0")
    for t in scope_tracts:
        w = appraisals[t["id"]] / appr_sum
        share = money(total_cost * w)
        allocations.append({"tract_id": t["id"], "share": share,
                            "_tract_number": t["tract_number"]})
        running += share
    residual = total_cost - running
    if allocations:
        top = max(allocations, key=lambda a: a["_tract_number"])
        top["share"] = top["share"] + residual
    for a in allocations:
        a.pop("_tract_number", None)
    return total_cost, allocations


def closing_costs_provisional(gross: Decimal) -> Decimal:
    return money(EST_COST_PCT * gross)


def possession_proration(closing, scope_tracts) -> Decimal:
    """FINAL rent credit: per in-scope tract with a lease disclosure (any status)."""
    from datetime import timedelta
    target = closing["_target_dt"]
    total = Decimal("0")
    for t in scope_tracts:
        disc = next((d for d in db.disclosures.values() if d["tract_id"] == t["id"]), None)
        if disc is None:
            continue
        possession = max(target, disc["_lease_end_dt"] + timedelta(days=1))
        if possession > target:
            days = Decimal((possession.date() - target.date()).days)
            daily = (disc["annual_rent"] / Decimal("365")).quantize(Q2, rounding=ROUND_HALF_UP)
            total += money(daily * days)
    return total
