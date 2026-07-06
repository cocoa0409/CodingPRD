"""Pure calculation rules from SCAFFOLD §1.3 and PRD §3.

All monetary math is done in cents with round-half-up. No floats propagate
into totals.
"""
from datetime import timedelta
from decimal import Decimal
from util import round_half_up_cents, floor_hours, parse_iso

# --- Constants ---
SIZE_UPCHARGE_CENTS = {
    "PETITE": 0,
    "ORIGINAL": 0,
    "DELUXE": 1500,
    "GRAND": 3000,
}
VASE_UPCHARGE_CENTS = 1200
MAX_DISCOUNT_CENTS = 1000
MIN_PRICE_CENTS = 2000

DELIVERIES_PER_CYCLE = {
    "WEEKLY": 4,
    "BIWEEKLY": 2,
    "MONTHLY": 1,
}
CADENCE_SPACING_DAYS = {
    "WEEKLY": 7,
    "BIWEEKLY": 14,
    "MONTHLY": 30,
}
FIRST_LEAD_DAYS = 2
CYCLE_DAYS = 30

FRESH_HOURS = 24
SHRINKAGE_PCT = Decimal("0.15")

STEM_MARKUP = Decimal("1.375")

SKIP_CUTOFF_HOURS = 48
WINBACK_WINDOW_DAYS = 30
WINBACK_DISCOUNT_PCT = Decimal("0.20")

CLEAN_BUFFER_MINUTES = 30

SILVER_MIN = 2
GOLD_MIN = 5


# --- renewal_price ---
def renewal_price_cents(plan, size, vase_addon, discount_pct):
    """gross = base + size_upcharge + vase_upcharge
       raw_discount = round_half_up(gross * discount_pct)
       applied = min(raw_discount, MAX_DISCOUNT_CENTS)
       net = max(gross - applied, MIN_PRICE_CENTS)
    """
    gross = int(plan["base_fee_cents"]) \
        + int(SIZE_UPCHARGE_CENTS[size]) \
        + (VASE_UPCHARGE_CENTS if vase_addon else 0)
    dp = Decimal(str(discount_pct or 0))
    raw_discount = round_half_up_cents(Decimal(gross) * dp)
    applied = min(raw_discount, MAX_DISCOUNT_CENTS)
    net = max(gross - applied, MIN_PRICE_CENTS)
    return int(net)


# --- per_shipment_value ---
def per_shipment_value_cents(renewal_price, cadence):
    n = DELIVERIES_PER_CYCLE[cadence]
    return round_half_up_cents(Decimal(renewal_price) / Decimal(n))


# --- loyalty_tier ---
def loyalty_tier(lifetime_cycles):
    if lifetime_cycles < SILVER_MIN:
        return "BRONZE"
    if lifetime_cycles < GOLD_MIN:
        return "SILVER"
    return "GOLD"


# --- stem_valuation (reserved / committed variants) ---
def _shrinkage_at(lot, at_time):
    """Return the shrinkage fraction for `lot` evaluated at `at_time`.

    While the lot is FRESH:
      0.0 if age_hours < FRESH_HOURS
      SHRINKAGE_PCT if age_hours >= FRESH_HOURS

    (The formula in the scaffold defines shrinkage only while FRESH; commits
    against EXPIRED lots are rejected at the validation layer with ERR_LOT_EXPIRED
    before this function is called.)
    """
    sourced = parse_iso(lot["sourced_at"])
    age_h = floor_hours(at_time - sourced)
    if age_h < FRESH_HOURS:
        return Decimal("0.0")
    return SHRINKAGE_PCT


def stem_value_cents(lot, quantity_reserved, at_time):
    """Return round_half_up(base * (1 - shrinkage(at_time)))."""
    base = Decimal(quantity_reserved) * Decimal(lot["unit_cost_cents"])
    shrink = _shrinkage_at(lot, at_time)
    return round_half_up_cents(base * (Decimal(1) - shrink))


# --- shipment_stem_cost ---
# ROUNDING ORDER: round each committed allocation line, THEN sum.
def shipment_stem_cost_cents(committed_allocations):
    """Sum over committed allocations, ordered by created_at asc.

    stem_cost_cents = sum( round_half_up(a.committed_value_cents * STEM_MARKUP) )
    """
    total = 0
    ordered = sorted(committed_allocations, key=lambda a: a["created_at"])
    for a in ordered:
        line = round_half_up_cents(Decimal(a["committed_value_cents"]) * STEM_MARKUP)
        total += int(line)
    return int(total)


# --- cold_chain_deadline ---
def cold_chain_state(lot, clock_dt):
    usable_until = parse_iso(lot["sourced_at"]) + timedelta(hours=int(lot["shelf_life_hours"]))
    if clock_dt < usable_until:
        return "FRESH", usable_until
    return "EXPIRED", usable_until
