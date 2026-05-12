"""Domain thresholds — numeric constants from PRD §2.8, §3.4, §3.6, §3.7, §3.8.

Field names mirror PRD prose exactly. Generic NON_EXISTENT_UUID comes from
the framework.
"""
from __future__ import annotations
import math


# ---------------------------------------------------------------------------
# Move-out lead time (PRD §3.8: 'at least 30 days after the current server
# date — the lead-time check is strict at the day granularity, so 29 days
# from today is rejected while 30 days from today is accepted')
# ---------------------------------------------------------------------------
MOVE_OUT_LEAD_DAYS = 30


# ---------------------------------------------------------------------------
# Renewal window (PRD §3.5: 'the renewal window opens exactly 60 days before
# the lease's nominal end')
# ---------------------------------------------------------------------------
RENEWAL_WINDOW_DAYS = 60


# ---------------------------------------------------------------------------
# Property-fee cap (PRD §3.7: 'capped at the round-half-up of 5000 cents
# (50.00 currency units) per square metre per month')
# ---------------------------------------------------------------------------
PROPERTY_FEE_CAP_CENTS_PER_SQM_PER_MONTH = 5000


# ---------------------------------------------------------------------------
# Deposit-month bounds (PRD §3.3: 'a deposit_months integer between 1 and 6
# inclusive')
# ---------------------------------------------------------------------------
DEPOSIT_MONTHS_MIN = 1
DEPOSIT_MONTHS_MAX = 6


# ---------------------------------------------------------------------------
# Days-per-year (PRD §3.4 step 1: 'divided by 365.25 (the system's
# DAYS_PER_YEAR constant)')
# ---------------------------------------------------------------------------
DAYS_PER_YEAR = 365.25


# ---------------------------------------------------------------------------
# Renovation buffer day (PRD §3.1 / §3.3: 'closed-with-buffer renovation
# window [renovation_start_date, renovation_end_date + 1 day]')
# ---------------------------------------------------------------------------
RENOVATION_BUFFER_DAYS = 1


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Rounding utility (PRD §2.8: 'the round-half-up convention')
# ---------------------------------------------------------------------------
def round_half_up(value: float) -> int:
    """Half-up rounding to integer cents.

    PRD §2.8: 'Wherever a fractional cent arises during a calculation, the
    system applies the round-half-up convention.'
    """
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


def months_between(period_start_iso: str, period_end_iso: str) -> int:
    """Count whole calendar months in [period_start, period_end).

    PRD §3.7: 'months_in_period is the count of whole calendar months in
    [period_start, period_end) (the period must align to month boundaries,
    so this count is always an integer)'.
    """
    from datetime import datetime
    a = datetime.fromisoformat(period_start_iso.replace("Z", "+00:00"))
    b = datetime.fromisoformat(period_end_iso.replace("Z", "+00:00"))
    return (b.year - a.year) * 12 + (b.month - a.month)


__all__ = [
    "MOVE_OUT_LEAD_DAYS",
    "RENEWAL_WINDOW_DAYS",
    "PROPERTY_FEE_CAP_CENTS_PER_SQM_PER_MONTH",
    "DEPOSIT_MONTHS_MIN",
    "DEPOSIT_MONTHS_MAX",
    "DAYS_PER_YEAR",
    "RENOVATION_BUFFER_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "round_half_up",
    "months_between",
]
