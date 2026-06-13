"""Calculation rules (SCAFFOLD §1.3, PRD §2.8 / §3.2-§3.11).

All money is integer cents. Rounding is round-half-up, applied PER LINE ITEM
first, and only then are whole-cent line totals summed (PRD §2.8).
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# labor_estimate constants (SCAFFOLD §1.3)
PREP_FACTOR = {
    "LIGHT": Decimal("1.0"),
    "STANDARD": Decimal("1.25"),
    "HEAVY": Decimal("1.6"),
    "RESTORATION": Decimal("2.0"),
}
SQFT_PER_HOUR = Decimal(160)
LABOR_RATE_CENTS_PER_HOUR = Decimal(6550)

# weather_suitability constants
MIN_EXTERIOR_TEMP_F = 50
MAX_EXTERIOR_PRECIP_PCT = 30

# warranty_payout constant
TOUCHUP_LABOR_FRACTION = Decimal("0.20")

# crew skill ordering (higher index = higher skill)
SKILL_RANK = {"APPRENTICE": 0, "JOURNEYMAN": 1, "MASTER": 2}
# minimum skill rank demanded by a prep level
PREP_MIN_SKILL = {
    "LIGHT": 0,        # any
    "STANDARD": 0,     # any
    "HEAVY": 1,        # JOURNEYMAN+
    "RESTORATION": 2,  # MASTER
}
PREP_HEAVINESS = {"LIGHT": 0, "STANDARD": 1, "HEAVY": 2, "RESTORATION": 3}


def round_half_up(value):
    """Round a Decimal to a whole integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def material_estimate(area_sqft, coats, coverage_sqft_per_gallon_per_coat, price_per_gallon_cents):
    """gallons = ceil(area*coats / coverage); material = gallons * price."""
    gallons_required = math.ceil((area_sqft * coats) / coverage_sqft_per_gallon_per_coat)
    material_cost_cents = gallons_required * price_per_gallon_cents
    return gallons_required, material_cost_cents


def labor_estimate(area_sqft, coats, prep_level):
    """labor_hours = area*coats*PREP_FACTOR / SQFT_PER_HOUR (exact rational);
    labor_cost_cents = round_half_up(labor_hours * LABOR_RATE)."""
    labor_hours = (Decimal(area_sqft) * Decimal(coats) * PREP_FACTOR[prep_level]) / SQFT_PER_HOUR
    labor_cost_cents = round_half_up(labor_hours * LABOR_RATE_CENTS_PER_HOUR)
    return labor_hours, labor_cost_cents


def labor_hours_float(labor_hours):
    """Expose labor_hours as a JSON number; keep exact value where it is integral."""
    if labor_hours == labor_hours.to_integral_value():
        return int(labor_hours)
    return float(labor_hours)


def weather_suitable(forecast_temp_f, precipitation_pct):
    return forecast_temp_f >= MIN_EXTERIOR_TEMP_F and precipitation_pct <= MAX_EXTERIOR_PRECIP_PCT


def deposit_due(estimate_total_cents, deposit_pct):
    return round_half_up(Decimal(estimate_total_cents) * Decimal(deposit_pct) / Decimal(100))


def provisional_payout(labor_cost_cents):
    return round_half_up(Decimal(labor_cost_cents) * TOUCHUP_LABOR_FRACTION)


def final_payout(logged_touchup_hours):
    return round_half_up(Decimal(str(logged_touchup_hours)) * LABOR_RATE_CENTS_PER_HOUR)
