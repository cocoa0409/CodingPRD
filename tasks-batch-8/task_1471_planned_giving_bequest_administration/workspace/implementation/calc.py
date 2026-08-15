"""Actuarial + monetary calculations (scaffold §1.3, PRD 2.6/3.3/3.9).

Round-half-up to integer cents at each pinned step; actuarial factors are
carried in full float precision with no intermediate rounding. The single
exception is reserve coverage, which is floored (PRD 2.6/2.8).
"""
from decimal import ROUND_HALF_UP, Decimal

FREQ_DIVISOR = {"ANNUAL": 1, "SEMIANNUAL": 2, "QUARTERLY": 4, "MONTHLY": 12}
MORTALITY_TERMINAL_AGE = 100
EXHAUSTION_LIMIT_BPS = 8500
RESERVE_DISCOUNT_RATE_BPS = 600
RESERVE_MULTIPLIER_BPS = 11000
LEGACY_THRESHOLD_CENTS = 10000000
COVERAGE_SOLVENT_BPS = 10000
DEFAULT_MIN_ENDOWMENT_CENTS = 2500000


def div_rhu(num, den):
    """round_half_up(num/den) for non-negative integers, exact."""
    return (2 * num + den) // (2 * den)


def rhu_float(x):
    """round_half_up to integer cents of a float (shortest-repr faithful)."""
    return int(Decimal(repr(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def annuity_factor(age, rate_bps):
    """Whole-life annuity-immediate factor a(n), n = max(1, 100 - age),
    full float precision: a(n) = (1 - v^n) / r, v = 1/(1+r)."""
    r = rate_bps / 10000.0
    v = 1.0 / (1.0 + r)
    n = max(1, MORTALITY_TERMINAL_AGE - age)
    return (1.0 - v ** n) / r


def lives_factor(age1, age2, lives, rate_bps):
    if lives == 2 and age2 is not None:
        return (
            annuity_factor(age1, rate_bps)
            + annuity_factor(age2, rate_bps)
            - annuity_factor(max(age1, age2), rate_bps)
        )
    return annuity_factor(age1, rate_bps)


def oldest_age(age1, age2, lives):
    if lives == 2 and age2 is not None:
        return max(age1, age2)
    return age1


def annual_annuity(amount_cents, payout_bps):
    """round_half_up(amount * payout_bps / 10000) — exact integer step."""
    return div_rhu(amount_cents * payout_bps, 10000)


def pv_of_annuity(annual_cents, factor):
    """round_half_up(annual * factor); factor in full float precision."""
    return rhu_float(annual_cents * factor)


def reserve_requirement(annual_cents, age1, age2, lives):
    """CGA statutory reserve: round_half_up(annual * a(n_oldest)@600bps * 11000/10000)."""
    f = annuity_factor(oldest_age(age1, age2, lives), RESERVE_DISCOUNT_RATE_BPS)
    return rhu_float(annual_cents * f * RESERVE_MULTIPLIER_BPS / 10000)


def whole_years_between(funding_month, valuation_dt):
    """Whole years from funding month (YYYY-MM, day = 1) to valuation_date."""
    y, m = int(funding_month[:4]), int(funding_month[5:7])
    years = valuation_dt.year - y
    if (valuation_dt.month, valuation_dt.day) < (m, 1):
        years -= 1
    return years


def exhaustion_limit_cents(gift_amount_cents):
    """round_half_up(gift * 8500 / 10000) — exact integer step."""
    return div_rhu(gift_amount_cents * EXHAUSTION_LIMIT_BPS, 10000)
