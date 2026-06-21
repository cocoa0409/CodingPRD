"""Calculation rules per PRD section 3.7 - 3.11. All money is integer cents."""
from decimal import Decimal, ROUND_HALF_UP

# Constants (from SCAFFOLD §1.3).
MIN_PARTIAL_FLOOR_CENTS = 100000
LOYALTY_BPS = {"BRONZE": 0, "SILVER": 500, "GOLD": 1000}

SEAT_POINT_VALUE = 100
TENURE_POINT_VALUE = 50
PLAYOFF_BONUS_PER_SEAT = 200

MARKETPLACE_FEE_BPS = 750
PROCESSING_FEE_BPS = 290

DOWN_PAYMENT_BPS = 2500
CANCELLATION_FEE_BPS = 1000


def round_half_up(numerator, denominator):
    """Round numerator/denominator to nearest integer, ties away from zero."""
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def floor_div_bps(value, bps):
    """floor(value * bps / 10000) with exact integer arithmetic."""
    return (value * bps) // 10000


# ---------------------------------------------------------------------------
# renewal_price (§3.7)
# ---------------------------------------------------------------------------
def seat_price(base_price_cents, price_multiplier_bps, loyalty_tier):
    plan_adjusted = floor_div_bps(base_price_cents, price_multiplier_bps)
    loyalty_disc = floor_div_bps(plan_adjusted, LOYALTY_BPS[loyalty_tier])
    discounted = plan_adjusted - loyalty_disc
    return max(discounted, MIN_PARTIAL_FLOOR_CENTS)


# ---------------------------------------------------------------------------
# priority_points_accrual (§3.8)
# ---------------------------------------------------------------------------
def points_accrual(seat_count, consecutive_seasons, includes_playoffs):
    base_points = seat_count * SEAT_POINT_VALUE
    tenure_bonus = consecutive_seasons * TENURE_POINT_VALUE
    raw = base_points + tenure_bonus
    if includes_playoffs:
        raw += PLAYOFF_BONUS_PER_SEAT * seat_count
    return raw


# ---------------------------------------------------------------------------
# resale_payout (§3.9)
# ---------------------------------------------------------------------------
def resale_payout(gross):
    mkt_fee = round_half_up(gross * MARKETPLACE_FEE_BPS, 10000)
    proc_fee = round_half_up(gross * PROCESSING_FEE_BPS, 10000)
    return gross - mkt_fee - proc_fee


# ---------------------------------------------------------------------------
# payment_plan_installments (§3.10)
# ---------------------------------------------------------------------------
def installment_allocation(total, installment_count):
    """Return a list of amounts indexed by sequence (1-based positions)."""
    down_payment = round_half_up(total * DOWN_PAYMENT_BPS, 10000)
    remaining = total - down_payment
    n_rest = installment_count - 1
    per_rest = remaining // n_rest
    remainder = remaining - per_rest * n_rest

    amounts = [down_payment]  # sequence 1
    for seq in range(2, installment_count + 1):
        if seq == installment_count:
            amounts.append(per_rest + remainder)
        else:
            amounts.append(per_rest)
    return amounts


# ---------------------------------------------------------------------------
# cancellation_refund (§3.11)
# ---------------------------------------------------------------------------
def cancellation_refund(amount_paid_cents, locked_price_cents):
    fee = round_half_up(locked_price_cents * CANCELLATION_FEE_BPS, 10000)
    return max(amount_paid_cents - fee, 0)
