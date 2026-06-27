"""Calculation rules (PRD §2.8, §3, SCAFFOLD §1.3).

All odds products are carried at 4 decimal places (round half-up) and monetary
results are integer cents computed via floor (never rounding up in the bettor's
favor). Decimal is used throughout to avoid IEEE-754 drift.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

FOUR_DP = Decimal("0.0001")
CASHOUT_RETENTION = Decimal("0.92")

DAILY_SECONDS = 86400
WEEKLY_SECONDS = 604800

GEO_TTL_SECONDS = 900
MAX_ACCURACY_M = 100
MIN_AGE_YEARS = 21
PERMITTED_BET_STATES = {"NJ", "NY", "PA", "CO", "AZ", "NV"}


def round_half_up_4(value):
    """Round a Decimal/number half-up to 4 decimal places, returning Decimal."""
    return Decimal(value).quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def american_to_decimal(american_odds):
    """American odds -> decimal odds, 4dp round-half-up (PRD §2.8).

    Positive: 1 + odds/100.  Non-positive (|odds| >= 100): 1 + 100/|odds|.
    """
    a = Decimal(int(american_odds))
    if a > 0:
        dec = Decimal(1) + a / Decimal(100)
    else:
        dec = Decimal(1) + Decimal(100) / abs(a)
    return round_half_up_4(dec)


def decimal_to_float(d):
    """Render a 4dp Decimal as a JSON number (float), trimming trailing zeros."""
    return float(d)


def combined_decimal_odds(leg_decimals):
    """Product of per-leg decimal odds, rounded ONCE at the end (PRD §3.7).

    leg_decimals: list of Decimal (each already pre-rounded to 4dp at snapshot).
    Intermediate partial products are NOT re-rounded.
    """
    product = Decimal(1)
    for d in leg_decimals:
        product = product * Decimal(d)
    return round_half_up_4(product)


def floor_cents(stake_cents, decimal_odds):
    """floor(stake_cents * decimal_odds) as integer cents (PRD §2.8)."""
    gross = Decimal(int(stake_cents)) * Decimal(decimal_odds)
    return int(gross.quantize(Decimal(1), rounding=ROUND_FLOOR))


def potential_payout(stake_cents, combined_dec):
    return floor_cents(stake_cents, combined_dec)


def settlement_effective_odds(legs):
    """Compute effective odds over graded legs (PRD §3.10).

    legs: ordered list of dicts with leg_result and decimal_odds_at_placement.
    Returns (effective_decimal, all_push_or_void, any_lost).
    WON legs keep their decimal; PUSH/VOID legs drop to 1.0; any LOST -> 0.
    """
    any_lost = False
    any_won = False
    effective = Decimal(1)
    for leg in legs:
        res = leg["leg_result"]
        if res == "WON":
            any_won = True
            effective = effective * Decimal(leg["decimal_odds_at_placement"])
        elif res in ("PUSH", "VOID"):
            effective = effective * Decimal(1)
        elif res == "LOST":
            any_lost = True
            effective = Decimal(0)
            break
    effective = round_half_up_4(effective)
    return effective, any_won, any_lost


def cash_out_value(stake_cents, current_leg_decimals):
    """Cash-out value: floor(stake * current_product * 0.92) (PRD §3.9).

    current_leg_decimals: list of Decimal from each leg's CURRENT selection odds.
    """
    product = Decimal(1)
    for d in current_leg_decimals:
        product = product * Decimal(d)
    product = round_half_up_4(product)
    gross = Decimal(int(stake_cents)) * product
    discounted = gross * CASHOUT_RETENTION
    return int(discounted.quantize(Decimal(1), rounding=ROUND_FLOOR))


def period_seconds(period):
    return WEEKLY_SECONDS if period == "WEEKLY" else DAILY_SECONDS
