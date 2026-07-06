"""Precision-sensitive calculations. All money in integer cents."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- occupancy ---
def occupancy_max(bedroom_count):
    return 2 * bedroom_count + 1


# --- TOT tax ---
TOT_BASE_RATE_BP = 800      # 8.00%
TOT_SURGE_RATE_BP = 1200    # 12.00%
TOT_TIER_NIGHTS = 14
TOT_FLAT_PER_NIGHT_CENTS = 300


def tot_due(gross_revenue_cents, nights_booked):
    base_pct = Decimal(TOT_BASE_RATE_BP) / Decimal(10000)
    surge_pct = Decimal(TOT_SURGE_RATE_BP) / Decimal(10000)
    gross = Decimal(gross_revenue_cents)
    if nights_booked <= TOT_TIER_NIGHTS:
        pct_component = round_half_up(gross * base_pct)
    else:
        per_night_rev = gross / Decimal(nights_booked)  # exact rational
        base_share = round_half_up(per_night_rev * Decimal(TOT_TIER_NIGHTS) * base_pct)
        surge_share = round_half_up(
            per_night_rev * Decimal(nights_booked - TOT_TIER_NIGHTS) * surge_pct
        )
        pct_component = base_share + surge_share
    flat_component = nights_booked * TOT_FLAT_PER_NIGHT_CENTS
    return pct_component + flat_component


# --- penalty ---
PENALTY_FLAT_CENTS = 2500
PENALTY_DAILY_BP = 50       # 0.50% per day
PENALTY_CAP_BP = 2500       # 25% cap


def tax_penalty(tot_due_cents, amount_remitted_cents, days_late):
    unpaid = tot_due_cents - amount_remitted_cents
    interest = round_half_up(
        Decimal(unpaid) * Decimal(PENALTY_DAILY_BP) / Decimal(10000) * Decimal(days_late)
    )
    raw_penalty = PENALTY_FLAT_CENTS + interest
    cap = round_half_up(Decimal(unpaid) * Decimal(PENALTY_CAP_BP) / Decimal(10000))
    return min(raw_penalty, cap)
