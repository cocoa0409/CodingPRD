"""Statutory notice length and relocation assistance (PRD 3.6).

A "month" here is always exactly 2592000 seconds -- thirty 86400-second days.
No calendar, month-length or business-day adjustment is ever applied.
"""

from fractions import Fraction

from rounding import half_up_frac

SECONDS_PER_DAY = 86400
SECONDS_PER_MONTH = 2592000
ROFR_WINDOW_DAYS = 90

RELOCATION_CAP_CENTS = 1500000
RELOCATION_FLOOR_CENTS = 250000
BASE_MONTHS_MULTIPLE = 3
UPLIFT_NUMERATOR = 3
UPLIFT_DENOMINATOR = 2

PROTECTED_CLASS_EXTENSION_DAYS = {
    "NONE": 0,
    "HOUSEHOLD_WITH_MINOR": 45,
    "ELDERLY": 90,
    "DISABLED": 90,
}

UPLIFT_CLASSES = ("ELDERLY", "DISABLED")


def completed_months(tenancy_start_date, now):
    elapsed_seconds = int((now - tenancy_start_date).total_seconds())
    return elapsed_seconds // SECONDS_PER_MONTH


def base_notice_days(months):
    if months < 12:
        return 120
    if months < 60:
        return 180
    return 270


def notice_period_days(household, now):
    """Base tier plus the single largest applicable extension, never a sum."""
    months = completed_months(household["tenancy_start_date"], now)
    extension = PROTECTED_CLASS_EXTENSION_DAYS[household["protected_class"]]
    return base_notice_days(months) + extension


def relocation_assistance_cents(household):
    """Five pinned steps: base, cap, uplift, cap again, floor last."""
    amount = half_up_frac(
        Fraction(household["monthly_rent_cents"] * BASE_MONTHS_MULTIPLE, 1))
    amount = min(amount, RELOCATION_CAP_CENTS)
    if household["protected_class"] in UPLIFT_CLASSES:
        amount = half_up_frac(
            Fraction(amount * UPLIFT_NUMERATOR, UPLIFT_DENOMINATOR))
    amount = min(amount, RELOCATION_CAP_CENTS)
    amount = max(amount, RELOCATION_FLOOR_CENTS)
    return amount
