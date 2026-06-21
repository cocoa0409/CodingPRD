"""Calculation rules — SCAFFOLD §1.3 / PRD §2.7, §3.2, §3.5, §3.7, §3.8.

All money is integer cents (PRD §2.7). Non-integer intermediates are rounded
HALF UP on the single raw product. fill_rate is the lone non-money ratio,
carried to four decimals, also rounded half up.
"""

from decimal import Decimal, ROUND_HALF_UP

import db


def _round_half_up_int(value):
    """Round a Decimal to the nearest integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4(value):
    """Round a Decimal/float ratio to 4 decimals, half up, return float."""
    q = Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# fill_rate / fill metrics — calc: episode_fill_rate (PRD §3.2)
# ---------------------------------------------------------------------------

def fill_metrics(episode):
    """Return (filled_slots, available_slots, fill_rate) for an episode.

    filled_slots = count of placements on the episode in {INSERTED, DELIVERED}.
    available_slots = total_ad_slots - filled_slots.
    fill_rate = filled/total to 4 decimals (half up), or 0.0 when total == 0.
    """
    total = episode["total_ad_slots"]
    filled = 0
    for p in db.db.ad_placements.values():
        if p["episode_id"] == episode["id"] and p["status"] in ("INSERTED", "DELIVERED"):
            filled += 1
    available = total - filled
    if total == 0:
        rate = 0.0
    else:
        rate = round_half_up_4(Decimal(filled) / Decimal(total))
    return filled, available, rate


# ---------------------------------------------------------------------------
# estimated_placement_cost — at AdPlacement create (PRD §3.5)
# Returns (estimated_cost_cents, fill_tier_multiplier).
# fill_rate band is evaluated BEFORE this placement is counted (PROPOSED does
# not count toward filled_slots).
# ---------------------------------------------------------------------------

def tier_multiplier_for_fill_rate(fill_rate):
    fr = Decimal(str(fill_rate))
    if fr >= Decimal("0.80"):
        return Decimal(db.HIGH_FILL_MULT)
    elif fr >= Decimal("0.50"):
        return Decimal(db.MID_FILL_MULT)
    else:
        return Decimal(db.LOW_FILL_MULT)


def estimated_placement_cost(bid_cpm_cents, forecast_impressions, premium_targeting, fill_rate):
    base = Decimal(bid_cpm_cents) * Decimal(forecast_impressions) / Decimal(1000)
    premium = Decimal(db.PREMIUM_MULTIPLIER) if premium_targeting else Decimal("1.0")
    tier = tier_multiplier_for_fill_rate(fill_rate)
    raw = base * premium * tier
    estimated = max(db.MIN_PLACEMENT_CENTS, _round_half_up_int(raw))
    return estimated, tier


# ---------------------------------------------------------------------------
# final_placement_cost — at AdPlacement reconcile (PRD §3.7)
# Same shape but driven by delivered_impressions; tier multiplier reused
# (no re-banding); capped at estimated_cost_cents.
# ---------------------------------------------------------------------------

def final_placement_cost(bid_cpm_cents, delivered_impressions, premium_targeting,
                         fill_tier_multiplier, estimated_cost_cents):
    base = Decimal(bid_cpm_cents) * Decimal(delivered_impressions) / Decimal(1000)
    premium = Decimal(db.PREMIUM_MULTIPLIER) if premium_targeting else Decimal("1.0")
    tier = Decimal(str(fill_tier_multiplier))
    raw = base * premium * tier
    uncapped = max(db.MIN_PLACEMENT_CENTS, _round_half_up_int(raw))
    return min(uncapped, estimated_cost_cents)


# ---------------------------------------------------------------------------
# campaign_budget_ledger — recomputed on every placement mutation (PRD §3.4)
# reserved = sum(estimated_cost_cents for {PROPOSED, INSERTED})
# spent    = sum(final_cost_cents     for {DELIVERED})
# available = budget - reserved - spent
# ---------------------------------------------------------------------------

def campaign_ledger(campaign):
    reserved = 0
    spent = 0
    for p in db.db.ad_placements.values():
        if p["campaign_id"] != campaign["id"]:
            continue
        if p["status"] in ("PROPOSED", "INSERTED"):
            reserved += p["estimated_cost_cents"]
        elif p["status"] == "DELIVERED":
            spent += p["final_cost_cents"]
    available = campaign["budget_cents"] - reserved - spent
    return reserved, spent, available


# ---------------------------------------------------------------------------
# payout calculations — PRD §3.8 / SCAFFOLD payout_gross_revenue, payout_net_payable
# ---------------------------------------------------------------------------

def payout_net_from_gross(gross_cents, revenue_share_pct):
    """net = round_half_up(gross * share) once, after the product (PRD §3.8)."""
    return _round_half_up_int(Decimal(gross_cents) * Decimal(str(revenue_share_pct)))
