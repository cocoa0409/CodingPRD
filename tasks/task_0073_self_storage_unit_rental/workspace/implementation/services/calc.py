"""Pure calculation helpers (money, rounding, proration)."""
import calendar
from decimal import Decimal, ROUND_HALF_UP

LIEN_ADMIN_COST_CENTS = 15000

TIER_PREMIUM = {"BASIC": 1000, "STANDARD": 1500, "PREMIUM": 2500}
TIER_LIMIT = {"BASIC": 200000, "STANDARD": 500000, "PREMIUM": 1500000}


def round_half_up(value):
    """Round a numeric value to whole cents, half away from zero."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def climate_component(monthly_rate_cents, climate_controlled, climate_premium_pct):
    if not climate_controlled:
        return 0
    return round_half_up(Decimal(monthly_rate_cents) * Decimal(str(climate_premium_pct)))


def monthly_components(monthly_rate_cents, climate_controlled, climate_premium_pct,
                       insurance_premium_cents):
    """Per-component rounding, then sum (calc: monthly_charge_components)."""
    base = int(monthly_rate_cents)
    climate = climate_component(monthly_rate_cents, climate_controlled, climate_premium_pct)
    insurance = int(insurance_premium_cents or 0)
    total = base + climate + insurance
    return base, climate, insurance, total


def days_in_month(dt):
    return calendar.monthrange(dt.year, dt.month)[1]


def prorate_first(monthly_total, start_dt):
    """Prorated first charge (single round after the day-fraction multiply)."""
    dim = days_in_month(start_dt)
    days_occupied = dim - start_dt.day + 1
    prorated = round_half_up(Decimal(monthly_total) * Decimal(days_occupied) / Decimal(dim))
    return prorated, days_occupied, dim


def whole_days_between(later, earlier):
    """floor of elapsed days from earlier to later (can be negative)."""
    delta = later - earlier
    total_seconds = delta.total_seconds()
    # floor toward negative infinity in days
    import math
    return math.floor(total_seconds / 86400.0)
