"""Calculation engine. Every formula, rounding point, and constant is pinned by
the specification (Section 3 workflows / calculations table).

Money is integer cents; Decimal is used for every non-integer intermediate.
round_half_up is applied exactly at the pinned steps.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# --- constants -------------------------------------------------------------
TIER_DISCOUNT = {
    "STANDARD": Decimal("0.00"),
    "SILVER": Decimal("0.05"),
    "GOLD": Decimal("0.10"),
    "PLATINUM": Decimal("0.15"),
}
QTY_BREAK_MIN = 10
QTY_BREAK_PCT = Decimal("0.03")
TAX_RATE_BPS = 825

SILVER_MIN_CENTS = 5_000_000
GOLD_MIN_CENTS = 15_000_000
PLATINUM_MIN_CENTS = 40_000_000

BAND1_LIMIT_CENTS = 10_000_000
BAND1_RATE = Decimal("0.02")
BAND2_LIMIT_CENTS = 30_000_000
BAND2_RATE = Decimal("0.04")
BAND3_RATE = Decimal("0.06")
REBATE_CAP_PCT = Decimal("0.05")

TIER_POINT_MULT = {"STANDARD": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 5}

MISTINT_INITIAL_PCT = Decimal("0.50")
MISTINT_WEEKLY_DECAY = Decimal("0.90")
MISTINT_FLOOR_PCT = Decimal("0.25")

MATCH_MAX_ITERATIONS = 3


def _rhup_int(d):
    """Round a Decimal half-up to a whole cent -> int."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- line pricing ------------------------------------------------------------
def price_line(tier, unit_list_price_cents, quantity):
    """unit_price = round_half_up(list * (1 - tier_pct) * (1 - qty_pct)) -- the
    per-unit price is rounded FIRST, then multiplied by quantity.
    line_total = unit_price * quantity."""
    tier_pct = TIER_DISCOUNT[tier]
    qty_pct = QTY_BREAK_PCT if quantity >= QTY_BREAK_MIN else Decimal("0")
    unit_price = _rhup_int(
        Decimal(unit_list_price_cents) * (Decimal("1") - tier_pct) * (Decimal("1") - qty_pct)
    )
    return unit_price, unit_price * quantity


def tax_of(subtotal_cents):
    """round_half_up(subtotal * 825 / 10000); exact integer arithmetic (subtotal >= 0)."""
    return (subtotal_cents * TAX_RATE_BPS + 5000) // 10000


def refund_amounts(unit_price_cents, quantity):
    """Per return event: merchandise refund, tax refund (rounded per event), credit."""
    merch = unit_price_cents * quantity
    tax = (merch * TAX_RATE_BPS + 5000) // 10000
    return merch, tax, merch + tax


# --- tier evaluation -----------------------------------------------------------
def tier_for_volume(ytd_net_volume_cents):
    """Inclusive thresholds: V exactly equal to a threshold earns that tier."""
    v = ytd_net_volume_cents
    if v >= PLATINUM_MIN_CENTS:
        return "PLATINUM"
    if v >= GOLD_MIN_CENTS:
        return "GOLD"
    if v >= SILVER_MIN_CENTS:
        return "SILVER"
    return "STANDARD"


# --- rebates -------------------------------------------------------------------
def banded(volume_cents):
    """2% up to band1, 4% of band1..band2, 6% above band2. Exact Decimal cents."""
    v = Decimal(volume_cents)
    b1 = Decimal(BAND1_LIMIT_CENTS)
    b2 = Decimal(BAND2_LIMIT_CENTS)
    return (
        BAND1_RATE * min(v, b1)
        + BAND2_RATE * max(Decimal("0"), min(v, b2) - b1)
        + BAND3_RATE * max(Decimal("0"), v - b2)
    )


def rebate_provisional_amount(net_so_far, days_total, days_elapsed):
    """Forward-looking variant: annualize, band, prorate back.
    Two pinned truncations (floor at projected, floor at provisional)."""
    if days_total <= 0 or days_elapsed <= 0:
        return 0
    projected = (net_so_far * days_total) // days_elapsed  # floor division
    b = banded(projected)
    prov = (b * days_elapsed) / Decimal(days_total)
    return int(prov.to_integral_value(rounding=ROUND_FLOOR))


def rebate_final_amount(events):
    """Chronological variant: running-accumulator marginal allocation.
    events: iterable of signed amounts (+payment subtotal, -refund merchandise)
    already sorted by (event ts asc, payments before refunds, row created_at asc).
    R accumulated in exact decimal cents; single round_half_up at the end."""
    volume = 0
    rebate = Decimal("0")
    for amount in events:
        if amount >= 0:
            a = amount
            while a > 0:
                if volume >= BAND2_LIMIT_CENTS:
                    rate, headroom = BAND3_RATE, a
                elif volume >= BAND1_LIMIT_CENTS:
                    rate, headroom = BAND2_RATE, BAND2_LIMIT_CENTS - volume
                else:
                    rate, headroom = BAND1_RATE, BAND1_LIMIT_CENTS - volume
                chunk = min(a, headroom)
                if chunk <= 0:
                    break
                rebate += Decimal(chunk) * rate
                volume += chunk
                a -= chunk
        else:
            f = -amount
            while f > 0:
                if volume > BAND2_LIMIT_CENTS:
                    rate, band_floor = BAND3_RATE, BAND2_LIMIT_CENTS
                elif volume > BAND1_LIMIT_CENTS:
                    rate, band_floor = BAND2_RATE, BAND1_LIMIT_CENTS
                else:
                    rate, band_floor = BAND1_RATE, 0
                chunk = min(f, volume - band_floor)
                if chunk <= 0:
                    break
                rebate -= Decimal(chunk) * rate
                volume -= chunk
                f -= chunk
    return _rhup_int(rebate)


def rebate_payable_amount(final_amount_cents, adjustment_cents, period_net_cents):
    """payable = max(0, min(final + adjustment, round_half_up(0.05 * period_net)))."""
    cap = _rhup_int(REBATE_CAP_PCT * Decimal(period_net_cents))
    return max(0, min(final_amount_cents + adjustment_cents, cap))


# --- loyalty -------------------------------------------------------------------
def earn_points(tier_snapshot, subtotal_cents):
    """floor(subtotal / 100) * multiplier; floor before multiplying."""
    return (subtotal_cents // 100) * TIER_POINT_MULT[tier_snapshot]


def clawback_points(tier_snapshot, refund_merchandise_cents):
    return (refund_merchandise_cents // 100) * TIER_POINT_MULT[tier_snapshot]


# --- mistint pricing -------------------------------------------------------------
def mistint_initial_list_price(cost_basis_cents):
    """floor(cost_basis * 0.50)."""
    return (cost_basis_cents * 50) // 100


def mistint_current_price(list_price_cents, cost_basis_cents, weeks):
    """current = max(round_half_up(cost_basis * 0.25),
                     round_half_up(list_price * 0.90 ** weeks))."""
    decayed = _rhup_int(Decimal(list_price_cents) * (MISTINT_WEEKLY_DECAY ** weeks))
    floor_price = _rhup_int(Decimal(cost_basis_cents) * MISTINT_FLOOR_PCT)
    return max(floor_price, decayed)


# --- spec pull-through -----------------------------------------------------------
def pct_2dp(numerator, denominator):
    """100 * num / den rounded half-up to 2 decimals, returned as a JSON number."""
    if denominator == 0:
        return 0
    value = (Decimal(100) * Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(value)
