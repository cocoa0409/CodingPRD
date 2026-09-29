"""Calculation rules (scaffold 1.3 / PRD 2.6, 3.3, 3.4, 3.5, 3.7).

Every money quantity is an integer number of cents.  All intermediate factors
are exact rationals (fractions.Fraction) so that "full precision" really is
full precision and round-half-up lands on the pinned cent.
"""
from fractions import Fraction

SECONDS_PER_BILLABLE_UNIT = 30
MONTHS_PER_TERM_YEAR = 12
RENEWAL_WINDOW_DAYS = 60
NEGOTIATION_ROUND_LIMIT = 6
RELEASE_REVISION_LIMIT = 3
DEPICTION_BUFFER_DAYS = 30

# --- E&O premium constants -------------------------------------------------
EO_BASE_RATE = Fraction(125, 10000)          # 0.0125
EO_RETENTION_CREDIT_RATE = Fraction(30, 100)  # 0.30
EO_MIN_PREMIUM_CENTS = 25000
EO_RISK_WEIGHT = {
    "LICENSED": Fraction(10, 1000),        # 0.010
    "FAIR_USE": Fraction(45, 1000),        # 0.045
    "PUBLIC_DOMAIN": Fraction(4, 1000),    # 0.004
}
EO_DEPICTION_SURCHARGE = Fraction(8, 1000)  # 0.008

# --- fair-use weighting vectors -------------------------------------------
FAIR_USE_WEIGHTS = {
    "TRANSFORMATIVE_WEIGHTED": {
        "transformative": Fraction(45, 100),
        "nature": Fraction(10, 100),
        "amount_used": Fraction(15, 100),
        "market_harm": Fraction(30, 100),
    },
    "MARKET_HARM_WEIGHTED": {
        "transformative": Fraction(20, 100),
        "nature": Fraction(10, 100),
        "amount_used": Fraction(20, 100),
        "market_harm": Fraction(50, 100),
    },
}
FAIR_USE_ACCEPT_THRESHOLD_SCALED = 6000  # 0.6000 at 4 decimal places


def frac(value):
    """Exact rational for an int / float / str JSON number."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def round_half_up(value):
    """Round a non-negative rational half up to the nearest integer."""
    f = frac(value)
    if f >= 0:
        return (f.numerator * 2 + f.denominator) // (f.denominator * 2)
    neg = -f
    return -((neg.numerator * 2 + neg.denominator) // (neg.denominator * 2))


def ceil_div(a, b):
    return -(-a // b)


def billable_units_for(duration_seconds):
    return ceil_div(duration_seconds, SECONDS_PER_BILLABLE_UNIT)


MEDIA_FIELD = {
    "THEATRICAL": "media_multiplier_theatrical",
    "BROADCAST": "media_multiplier_broadcast",
    "STREAMING": "media_multiplier_streaming",
    "ALL_MEDIA": "media_multiplier_all_media",
}


def license_rate_card_fee_cents(duration_seconds, media, territory, window_class,
                                term_months, rate_card):
    """Rate-card pricing.  One round_half_up on the final product, then the floor."""
    rc = rate_card
    units = billable_units_for(duration_seconds)

    if duration_seconds <= rc["tier1_max_seconds"]:
        rate_multiplier = Fraction(1)
    elif duration_seconds <= rc["tier2_max_seconds"]:
        rate_multiplier = frac(rc["tier2_rate_multiplier"])
    else:
        rate_multiplier = frac(rc["tier3_rate_multiplier"])

    media_multiplier = frac(rc[MEDIA_FIELD[media]])
    territory_multiplier = frac(
        rc["territory_multiplier_world"] if territory == "WORLD"
        else rc["territory_multiplier_domestic"]
    )

    term_years = ceil_div(term_months, MONTHS_PER_TERM_YEAR)
    term_factor = 1 + frac(rc["term_multiplier_per_year"]) * max(0, term_years - 1)

    if window_class == "FESTIVAL_ONLY":
        window_multiplier = frac(rc["festival_window_multiplier"])
        fee_floor_cents = rc["festival_minimum_fee_cents"]
    else:
        window_multiplier = frac(rc["all_media_window_multiplier"])
        fee_floor_cents = rc["minimum_fee_cents"]

    raw = (
        Fraction(rc["base_rate_per_30s_cents"])
        * units
        * rate_multiplier
        * media_multiplier
        * territory_multiplier
        * term_factor
        * window_multiplier
    )
    return max(round_half_up(raw), fee_floor_cents), units


def fair_use_strength_scaled(weighting_variant, transformative, nature, amount_used,
                            market_harm):
    """Returns the strength score scaled by 10000 (i.e. 4 decimal places)."""
    w = FAIR_USE_WEIGHTS[weighting_variant]
    raw = (
        w["transformative"] * Fraction(transformative, 100)
        + w["nature"] * Fraction(nature, 100)
        + w["amount_used"] * Fraction(amount_used, 100)
        + w["market_harm"] * Fraction(market_harm, 100)
    )
    return round_half_up(raw * 10000)


def scaled_to_score(scaled):
    return float(Fraction(scaled, 10000))
