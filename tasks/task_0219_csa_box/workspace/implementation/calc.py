"""Calculation rules (SCAFFOLD §1.3 / PRD §2.5, §3.3, §3.4, §3.7, §3.9).

All money is integer cents. round_half_up is applied only at the two
fractional-introducing steps: the sliding-scale multiply and the working-share
credit multiply.
"""
from decimal import Decimal, ROUND_HALF_UP

# §1.3 season_share_price constants
SLIDING_SCALE_MULTIPLIER = {
    "SOLIDARITY": Decimal("0.80"),
    "BASELINE": Decimal("1.00"),
    "SUSTAINER": Decimal("1.25"),
}

# §1.3 workshare_credit constants
WORK_CREDIT_RATE_CENTS_PER_HOUR = 1500
WORK_CREDIT_DAILY_HOUR_CAP = 6


def round_half_up(value):
    """Round a Decimal to a whole integer using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def season_share_price(base_price_cents, sliding_scale_tier):
    """§1.3 season_share_price: round_half_up(base * multiplier).

    Pinned at confirm time using the member's tier as-of confirm."""
    multiplier = SLIDING_SCALE_MULTIPLIER[sliding_scale_tier]
    return round_half_up(Decimal(base_price_cents) * multiplier)


def workshare_credit(shift_hours, prior_same_date_hours):
    """§1.3 workshare_credit: daily-capped creditable hours × rate, round_half_up."""
    creditable = max(
        Decimal(0),
        min(Decimal(str(shift_hours)),
            Decimal(WORK_CREDIT_DAILY_HOUR_CAP) - Decimal(str(prior_same_date_hours))),
    )
    return round_half_up(creditable * Decimal(WORK_CREDIT_RATE_CENTS_PER_HOUR))


def hold_refund_value(season_price_cents, week_count, week_index):
    """§1.3 hold_refund_value: one week's pro-rata share value, remainder-last
    so the per-week refunds sum exactly to season_price_cents. Lowest week_index
    weeks carry the +1 remainder cent."""
    if week_count <= 0:
        return 0
    base_per_week = season_price_cents // week_count
    remainder = season_price_cents - base_per_week * week_count
    extra = 1 if week_index <= remainder else 0
    return base_per_week + extra
