"""Pure calculation rules (scaffold 1.3 / PRD 3.4, 3.6, 3.8, 3.9).

All money is integer cents; rates are integer basis points. Rounding is
half-up, applied exactly where the business rule pins it.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from util import dec_quantize, parse_dt, round_half_up_int

# lot_current_price volume tiers
VOLUME_TIER_1_MIN_CLOSED = 5
VOLUME_TIER_1_DISCOUNT_BP = 250
VOLUME_TIER_2_MIN_CLOSED = 10
VOLUME_TIER_2_DISCOUNT_BP = 500

# draw_disbursement
RETAINAGE_BP = 500
DRAW_FEE_BP = 50

# bond_requirement
BOND_MULTIPLIER_BP = 11000

# absorption_pace
PHASE_LEAD_MONTHS = 6
W1 = Decimal("0.5")
W2 = Decimal("0.3")
W3 = Decimal("0.2")

# impact_fee_amount
ORDINANCE_EPOCH = date(2024, 1, 1)
INDEX_BP = 300
BASE_FEE_CENTS = {"WATER": 250000, "SEWER": 300000, "ELECTRIC": 175000}


def quarters_elapsed(eff, now) -> int:
    """Whole completed quarters between effective date and the logical clock.

    months = (now.year - eff.year) * 12 + (now.month - eff.month)
             - (1 if now.day < eff.day else 0)
    quarters = floor(months / 3), clamped below at 0. Integer arithmetic only.
    """
    months = (now.year - eff.year) * 12 + (now.month - eff.month) - (1 if now.day < eff.day else 0)
    if months <= 0:
        return 0
    return months // 3


def lot_current_price(agreement, now) -> int:
    """Escalator + cap + volume-tier pricing; one rounding step at the end.

    1. q = quarters_elapsed(effective_date, now)
    2. escalated = base * (1 + rate_bp/10000) ^ q        (compounds quarterly)
    3. cap = base * price_cap_bp / 10000
    4. capped = min(escalated, cap)
    5. discount_bp from closed_lot_count tiers
    6. price = capped * (1 - discount_bp/10000)
    7. round_half_up to integer cents -- the ONLY rounding step
    """
    q = quarters_elapsed(parse_dt(agreement["effective_date"]), now)
    base = Decimal(agreement["base_lot_price_cents"])
    factor = Decimal(10000 + agreement["escalator_rate_bp_per_quarter"]) / Decimal(10000)
    escalated = base * (factor ** q)
    cap = base * Decimal(agreement["price_cap_bp"]) / Decimal(10000)
    capped = min(escalated, cap)
    n = agreement["closed_lot_count"]
    if n >= VOLUME_TIER_2_MIN_CLOSED:
        discount_bp = VOLUME_TIER_2_DISCOUNT_BP
    elif n >= VOLUME_TIER_1_MIN_CLOSED:
        discount_bp = VOLUME_TIER_1_DISCOUNT_BP
    else:
        discount_bp = 0
    price = capped * Decimal(10000 - discount_bp) / Decimal(10000)
    return int(price.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def draw_disbursement(line_items):
    """Pinned rounding order: retainage from gross FIRST, fee from the
    post-retainage base SECOND, net = gross - retainage - fee."""
    gross = sum(item["amount_cents"] for item in line_items)
    retainage = round_half_up_int(gross * RETAINAGE_BP, 10000)
    fee = round_half_up_int((gross - retainage) * DRAW_FEE_BP, 10000)
    net = gross - retainage - fee
    return gross, retainage, fee, net


def required_bond_cents(basis_cents) -> int:
    """110% of the basis (engineer estimate while ESTIMATED, awarded bid from
    BID_FINAL onward), rounded half-up to whole cents."""
    return round_half_up_int(basis_cents * BOND_MULTIPLIER_BP, 10000)


def half_of_required_bond(required_cents) -> int:
    """round_half_up(required * 5000 / 10000) — the reduce floor."""
    return round_half_up_int(required_cents * 5000, 10000)


def lien_release_price(contract_price_cents, floor_bp) -> int:
    return round_half_up_int(contract_price_cents * floor_bp, 10000)


def impact_fee_cents(utility_type, now_date) -> int:
    """Base fee indexed by whole years since the 2024-01-01 ordinance epoch,
    compounded at 300 bp/year; one half-up rounding step at the end."""
    days = (now_date - ORDINANCE_EPOCH).days
    years = max(0, days // 365)
    base = Decimal(BASE_FEE_CENTS[utility_type])
    factor = Decimal(10000 + INDEX_BP) / Decimal(10000)
    fee = base * (factor ** years)
    return int(fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def straight_line_pace(total_lots, months) -> Decimal:
    if months == 0:
        return Decimal(0)
    return dec_quantize(Decimal(total_lots) / Decimal(months), 4)


def trailing_weighted_pace(c1, c2, c3) -> Decimal:
    return dec_quantize(W1 * c1 + W2 * c2 + W3 * c3, 4)


def closed_pct_calc(closed, total) -> Decimal:
    if total == 0:
        return Decimal(0)
    return dec_quantize(Decimal(100 * closed) / Decimal(total), 2)


def projection_calc(remaining, selected_pace: Decimal):
    """round(remaining / selected_pace, 1) when pace > 0; null otherwise."""
    if selected_pace <= 0:
        return None
    return dec_quantize(Decimal(remaining) / selected_pace, 1)
