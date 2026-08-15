"""Order pricing, invoice line rounding, and freight schedule (PRD §3.2/§3.3, scaffold §1.3).

All money is integer cents via Decimal with ROUND_HALF_UP. The CONTRACT variant
rounds each opening line to whole cents FIRST, then sums (pinned rounding order).
"""

from decimal import Decimal, ROUND_HALF_UP

import db

BASE_LEAF_PRICE = {
    "OAK": 42000,
    "MAPLE": 38000,
    "CHERRY": 51000,
    "WALNUT": 56000,
    "PAINT_GRADE": 29000,
}

BUDGET_WASTE = Decimal("1.12")
BUDGET_FINISH_PCT = Decimal("1.08")
BUDGET_HARDWARE_PER_OPENING = 5500
BUDGET_FREIGHT_FLAT = 25000

WASTE = {
    "OAK": Decimal("0.14"),
    "MAPLE": Decimal("0.10"),
    "CHERRY": Decimal("0.18"),
    "WALNUT": Decimal("0.20"),
    "PAINT_GRADE": Decimal("0.08"),
}

HARDWARE_TEMPLATE_CHARGE_PER_OPENING = 8500
HARDWARE_INSTALLER_CREDIT_PER_OPENING = -4000

FIRE_PER_LEAF = {
    "MIN_20": 6000,
    "MIN_45": 9500,
    "MIN_90": 14000,
}

FREIGHT_FLAT = 25000
FREIGHT_TIER1_MAX = 500000
FREIGHT_TIER2_MAX = 2000000

# Tiered finish percentage keyed on the total leaf count across the order's
# priced openings. The PRD references this tier but does not publish concrete
# thresholds; the mid/large bands discount the finishing upcharge on volume.
FINISH_TIERS = [
    (10, Decimal("1.08")),    # up to and including 10 leaves
    (50, Decimal("1.06")),    # 11..50 leaves
    (None, Decimal("1.05")),  # 51+ leaves
]


def _round_cents(value):
    """Round a Decimal to whole cents, half-up, returning int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def finish_pct(total_leaves):
    for bound, pct in FINISH_TIERS:
        if bound is None or total_leaves <= bound:
            return pct
    return FINISH_TIERS[-1][1]


def priced_openings(order):
    """All non-CANCELLED openings of the order, in creation order."""
    return sorted(
        [o for o in db.openings.values()
         if o["order_id"] == order["id"] and o["fab_status"] != "CANCELLED"],
        key=lambda o: o["created_at"],
    )


def compute_budget_quote(order):
    """BUDGET variant at DRAFT->CONFIGURED: flat 12% waste, flat 8% finish,
    flat 5500 hardware per opening, no fire surcharge, flat 25000 freight."""
    base = BASE_LEAF_PRICE[order["species"]]
    total = 0
    for opening in priced_openings(order):
        raw = Decimal(opening["leaf_count"]) * Decimal(base) * BUDGET_WASTE * BUDGET_FINISH_PCT
        total += _round_cents(raw) + BUDGET_HARDWARE_PER_OPENING
    return total + BUDGET_FREIGHT_FLAT


def contract_lines(order):
    """CONTRACT variant per-opening rounded line totals.

    line = round_half_up(leaf_count * base * (1 + waste[species]) * finish_pct(total_leaves))
           + hardware_delta + fire_rate[opening.fire_rating] * leaf_count
    """
    openings = priced_openings(order)
    base = BASE_LEAF_PRICE[order["species"]]
    waste = WASTE[order["species"]]
    total_leaves = sum(o["leaf_count"] for o in openings)
    pct = finish_pct(total_leaves)
    hardware_delta = (HARDWARE_TEMPLATE_CHARGE_PER_OPENING
                      if order["hardware_prep_mode"] == "TEMPLATE_PREP"
                      else HARDWARE_INSTALLER_CREDIT_PER_OPENING)
    lines = []
    for opening in openings:
        raw = (Decimal(opening["leaf_count"]) * Decimal(base)
               * (Decimal(1) + waste) * pct)
        line = _round_cents(raw) + hardware_delta
        fire_rate = FIRE_PER_LEAF.get(opening["fire_rating"], 0)
        line += fire_rate * opening["leaf_count"]
        lines.append(line)
    return lines


def freight_fee(merchandise_total_cents):
    """Freight keyed on merchandise_total_cents ONLY (never contract price)."""
    merch = Decimal(merchandise_total_cents)
    if merchandise_total_cents < FREIGHT_TIER1_MAX:
        return FREIGHT_FLAT
    if merchandise_total_cents <= FREIGHT_TIER2_MAX:
        return _round_cents(Decimal("0.04") * merch)
    return _round_cents(Decimal("0.03") * merch)


def compute_contract_pricing(order):
    """Full CONTRACT variant: returns (merchandise_total, freight_fee, contract_price)."""
    lines = contract_lines(order)
    merchandise_total = sum(lines)
    freight = freight_fee(merchandise_total)
    return merchandise_total, freight, merchandise_total + freight
