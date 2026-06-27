"""Calculation rules (SCAFFOLD.yaml section 1.3 / PRD section 3).

All monetary values are integer cents. Percentage-derived values use
round-half-up (away from zero on a .5 tie) per PRD 2.6. We use Decimal with
ROUND_HALF_UP for those.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# --- loyalty tiers (calc loyalty_discount) ---
TIER1_MIN_CENTS = 50000
TIER2_MIN_CENTS = 100000
TIER1_RATE = Decimal("0.02")
TIER2_RATE = Decimal("0.05")

# --- service base fees (calc service_fee) ---
SERVICE_BASE_CENTS = {
    "KEY_CUT": 300,
    "PAINT_MIX": 800,
    "PROPANE_EXCHANGE": 2499,
}

# --- special order drop-ship (calc special_order_total) ---
DROP_SHIP_SURCHARGE_CENTS = 1500
DROP_SHIP_FREE_THRESHOLD_CENTS = 50000

# --- co-op rebate (calc coop_rebate) ---
COOP_MIN_GROSS_CENTS = 200000

# --- rental ---
MIN_BILLED_DAYS = 1

# --- loyalty accrual ---
POINTS_PER_DOLLAR = 1


def round_half_up(value):
    """Round a numeric value to a whole integer using round-half-up (away from
    zero on a .5 tie)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_total(product, qty, cut_count):
    """calc line_total — per-line charge, rounded to the cent at the line level.

    EACH:    raw = list_price_cents * qty   (qty whole units)
    BY_FOOT: raw = price_per_foot_cents * qty + cut_fee_cents * cut_count
    line_total_cents = round_half_up(raw)
    """
    if product["sell_mode"] == "EACH":
        raw = Decimal(str(product["list_price_cents"])) * Decimal(str(qty))
    else:  # BY_FOOT
        lumber = Decimal(str(product["price_per_foot_cents"])) * Decimal(str(qty))
        cut = Decimal(str(product["cut_fee_cents"])) * Decimal(str(cut_count))
        raw = lumber + cut
    return round_half_up(raw)


def reorder_needed(on_hand, reorder_point):
    """calc reorder_flag — inclusive boundary."""
    return on_hand <= reorder_point


def loyalty_discount(subtotal_cents, has_account):
    """calc loyalty_discount.

    Tier is keyed on the PRE-discount subtotal; the rate is then multiplied by
    that subtotal and rounded half-up. Cash sale (no account) -> 0.
    """
    if not has_account:
        return 0
    if subtotal_cents >= TIER2_MIN_CENTS:
        rate = TIER2_RATE
    elif subtotal_cents >= TIER1_MIN_CENTS:
        rate = TIER1_RATE
    else:
        return 0
    return round_half_up(Decimal(subtotal_cents) * rate)


def order_total(line_totals, has_account):
    """Shared aggregation for provisional and final order totals.

    line_totals: the already-rounded per-line totals of the included lines.
    Returns (subtotal_cents, loyalty_discount_cents, total_cents).
    """
    subtotal = sum(line_totals)
    discount = loyalty_discount(subtotal, has_account)
    total = max(0, subtotal - discount)
    return subtotal, discount, total


def loyalty_accrual(total_cents):
    """calc loyalty_accrual — 1 point per whole dollar (floor)."""
    return math.floor(total_cents / 100) * POINTS_PER_DOLLAR


def rental_charge(daily_rate_cents, start_at, returned_at):
    """calc rental_charge.

    billed_days = number of distinct started UTC calendar days, counting from
    the start date through the return date inclusive, never fewer than 1.
    """
    start_date = start_at.date()
    end_date = returned_at.date()
    billed_days = max(MIN_BILLED_DAYS, (end_date - start_date).days + 1)
    return daily_rate_cents * billed_days


def service_fee(service_type):
    """calc service_fee — flat base fee keyed on service_type."""
    return SERVICE_BASE_CENTS[service_type]


def special_order_total(quoted_unit_cents, qty):
    """calc special_order_total.

    goods = quoted_unit_cents * qty
    surcharge = 0 when goods >= 50000 (free shipping), else 1500.
    """
    goods = quoted_unit_cents * qty
    if goods >= DROP_SHIP_FREE_THRESHOLD_CENTS:
        surcharge = 0
    else:
        surcharge = DROP_SHIP_SURCHARGE_CENTS
    return goods + surcharge


def coop_rebate(po_lines, coop_rebate_pct):
    """calc coop_rebate.

    gross = sum(qty * unit_cost_cents)
    rebate = round_half_up(gross * coop_rebate_pct) when gross >= 200000, else 0
    net = gross - rebate
    Returns (gross_cents, coop_rebate_cents, net_cost_cents).
    """
    gross = sum(l["qty"] * l["unit_cost_cents"] for l in po_lines)
    if gross >= COOP_MIN_GROSS_CENTS:
        rebate = round_half_up(Decimal(gross) * Decimal(str(coop_rebate_pct)))
    else:
        rebate = 0
    net = gross - rebate
    return gross, rebate, net
