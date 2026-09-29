"""Deterministic calculations (SCAFFOLD calculations / PRD 3.x).

All money is integer cents. Every fractional step uses decimal.Decimal with the
rounding mode the specification names; floor and ceiling are explicit.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

# ---- constants named by the specification --------------------------------
IMPORTANT_SOIL_WEIGHT = Decimal("0.60")
FRONTAGE_POINTS_PER_100_FEET = 3
FRONTAGE_POINTS_MAX = 30
SEWER_POINTS = 25
ZONING_POINTS_UNDER_1_ACRE = 45
ZONING_POINTS_UNDER_3_ACRES = 35
ZONING_POINTS_UNDER_10_ACRES = 20
ZONING_POINTS_10_ACRES_PLUS = 5
SIZE_FULL_CREDIT_ACRES = Decimal("200")

PRELIMINARY_VALUE_FACTOR = Decimal("0.90")
PRELIMINARY_ROUNDING_UNIT_CENTS = 100000
CERTIFIED_ROUNDING_UNIT_CENTS = 10000
MAX_VALUE_PER_ACRE_CENTS = Decimal("1200000")

ADMIN_FEE_TIER_1_LIMIT_CENTS = 25000000
ADMIN_FEE_TIER_2_LIMIT_CENTS = 75000000
ADMIN_FEE_TIER_1_PCT = Decimal("0.030")
ADMIN_FEE_TIER_2_PCT = Decimal("0.020")
ADMIN_FEE_TIER_3_PCT = Decimal("0.015")

INSTALLMENT_ANNUAL_RATE = Decimal("0.0275")
SQFT_PER_ACRE = Decimal("43560")
MAJOR_VIOLATION_EXCESS_SQFT = 2000
CURE_DAYS_MINOR = 180
CURE_DAYS_MAJOR = 90
COMPLIANCE_CLEAR_DAYS = 90
ESCALATION_TERMINATION_DAYS = 730
SURVEY_ACREAGE_TOLERANCE_ACRES = Decimal("0.50")
REQUESTED_PRICE_CEILING_FACTOR = Decimal("1.10")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def round_half_up_int(value):
    return int(round_half_up(value, 0))


# ---- parcel_soil_quality_score -------------------------------------------
def parcel_soil_quality_score(acres, prime_acres, important_acres):
    acres = dec(acres)
    prime_share = dec(prime_acres) / acres
    important_share = dec(important_acres) / acres
    blended = prime_share + IMPORTANT_SOIL_WEIGHT * important_share
    clamped = min(Decimal(1), blended)
    return round_half_up(Decimal(100) * clamped, 2)


# ---- parcel_development_pressure_score -----------------------------------
def parcel_development_pressure_score(road_frontage_feet, sewer_available, zoning_min_lot_acres):
    frontage_points = min(
        FRONTAGE_POINTS_MAX,
        (int(road_frontage_feet) // 100) * FRONTAGE_POINTS_PER_100_FEET,
    )
    sewer_points = SEWER_POINTS if sewer_available else 0
    zoning = dec(zoning_min_lot_acres)
    if zoning < Decimal("1.0"):
        zoning_points = ZONING_POINTS_UNDER_1_ACRE
    elif zoning < Decimal("3.0"):
        zoning_points = ZONING_POINTS_UNDER_3_ACRES
    elif zoning < Decimal("10.0"):
        zoning_points = ZONING_POINTS_UNDER_10_ACRES
    else:
        zoning_points = ZONING_POINTS_10_ACRES_PLUS
    total = frontage_points + sewer_points + zoning_points
    return round_half_up(min(Decimal(100), Decimal(total)), 2)


# ---- application_composite_score ----------------------------------------
def application_composite_score(program, parcel, contiguity_acres):
    acres = dec(parcel["acres"])
    soil_component = dec(parcel["soil_quality_score"])
    size_component = Decimal(100) * min(Decimal(1), acres / SIZE_FULL_CREDIT_ACRES)
    contiguity_component = Decimal(100) * min(Decimal(1), dec(contiguity_acres) / acres)
    pressure_component = dec(parcel["development_pressure_score"])
    weighted = (
        dec(program["soil_weight"]) * soil_component
        + dec(program["size_weight"]) * size_component
        + dec(program["contiguity_weight"]) * contiguity_component
        + dec(program["pressure_weight"]) * pressure_component
    )
    return round_half_up(weighted, 2)


# ---- easement_value -----------------------------------------------------
def preliminary_easement_value_cents(unrestricted_cents, restricted_cents):
    gross = Decimal(int(unrestricted_cents) - int(restricted_cents))
    units = floor_int(PRELIMINARY_VALUE_FACTOR * gross / Decimal(PRELIMINARY_ROUNDING_UNIT_CENTS))
    return units * PRELIMINARY_ROUNDING_UNIT_CENTS


def certified_easement_value_cents(unrestricted_cents, restricted_cents, parcel_acres):
    gross = Decimal(int(unrestricted_cents) - int(restricted_cents))
    ceiling = MAX_VALUE_PER_ACRE_CENTS * dec(parcel_acres)
    capped = min(gross, ceiling)
    units = round_half_up_int(capped / Decimal(CERTIFIED_ROUNDING_UNIT_CENTS))
    return units * CERTIFIED_ROUNDING_UNIT_CENTS


# ---- bargain_sale_and_admin_fee -----------------------------------------
def admin_fee_pct(bargain_sale_price_cents):
    if bargain_sale_price_cents < ADMIN_FEE_TIER_1_LIMIT_CENTS:
        return ADMIN_FEE_TIER_1_PCT
    if bargain_sale_price_cents < ADMIN_FEE_TIER_2_LIMIT_CENTS:
        return ADMIN_FEE_TIER_2_PCT
    return ADMIN_FEE_TIER_3_PCT


def cost_build_up(amount_cents, donation_pct):
    """Returns (donation_cents, bargain_sale_price_cents, admin_fee_cents, total)."""
    amount = int(amount_cents)
    donation_cents = round_half_up_int(Decimal(amount) * dec(donation_pct))
    bargain_sale_price_cents = amount - donation_cents
    fee_pct = admin_fee_pct(bargain_sale_price_cents)
    admin_fee_cents = round_half_up_int(Decimal(bargain_sale_price_cents) * fee_pct)
    total = bargain_sale_price_cents + admin_fee_cents
    return donation_cents, bargain_sale_price_cents, admin_fee_cents, total


# ---- installment_schedule_split -----------------------------------------
def installment_split(total_program_cost_cents, years):
    total = int(total_program_cost_cents)
    n = int(years)
    annual = floor_int(Decimal(total) / Decimal(n))
    first = annual
    final = total - annual * (n - 1)
    interest = round_half_up_int(
        Decimal(total) * INSTALLMENT_ANNUAL_RATE * Decimal(n - 1) / Decimal(2)
    )
    return first, final, interest


# ---- impervious_allowance_and_exceedance --------------------------------
def impervious_allowance_sqft(protected_acres, impervious_allowance_pct):
    return floor_int(dec(protected_acres) * SQFT_PER_ACRE * dec(impervious_allowance_pct))


def impervious_finding(observed_sqft, allowance_sqft):
    observed = int(observed_sqft)
    allowance = int(allowance_sqft)
    excess = max(0, observed - allowance)
    finding = "CONFIRMED_VIOLATION" if observed > allowance else "NO_ISSUE"
    return finding, excess


# ---- violation_severity_and_cure_deadline -------------------------------
def violation_severity(excess_sqft):
    return "MAJOR" if int(excess_sqft) > MAJOR_VIOLATION_EXCESS_SQFT else "MINOR"


def cure_window_days(severity):
    return CURE_DAYS_MAJOR if severity == "MAJOR" else CURE_DAYS_MINOR


# ---- requested-price ceiling --------------------------------------------
def requested_price_ceiling_cents(preliminary_cents):
    return round_half_up_int(Decimal(int(preliminary_cents)) * REQUESTED_PRICE_CEILING_FACTOR)
