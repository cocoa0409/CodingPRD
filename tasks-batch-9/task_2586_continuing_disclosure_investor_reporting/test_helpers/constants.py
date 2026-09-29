"""Domain thresholds and derived-value helpers taken from the PRD's calculations."""

from datetime import date, timedelta

# --------------------------------------------------------------------------- #
# The logical clock (PRD §2.5)
# --------------------------------------------------------------------------- #

CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DATE = "2026-08-01"

# --------------------------------------------------------------------------- #
# The business-day calendar (PRD §2.6)
# --------------------------------------------------------------------------- #

MARKET_HOLIDAYS = [
    "2026-07-03",
    "2026-09-07",
    "2026-10-12",
    "2026-11-11",
    "2026-11-26",
    "2026-12-25",
    "2027-01-01",
    "2027-01-18",
    "2027-02-15",
    "2027-05-31",
    "2027-07-05",
    "2027-09-06",
    "2027-11-25",
    "2027-12-24",
]

THRESHOLDS = {
    # PRD §3.2 — undertaking defaults
    "DEFAULT_FILING_WINDOW_DAYS": 210,
    # PRD §3.5 — the ten-business-day listed-event window
    "MATERIAL_EVENT_WINDOW_BUSINESS_DAYS": 10,
    # PRD §3.3 — completeness scoring rounding
    "SCORE_ITEM_DECIMALS": 4,
    "SCORE_PCT_DECIMALS": 2,
    # PRD §3.6 — the 500 basis point materiality boundary
    "MATERIAL_OBLIGATION_THRESHOLD_BP": 500,
    "PLACEMENT_REVIEW_CAPACITY": 2,
    # PRD §3.7 — at most three submissions and resubmissions in total
    "MAX_SUBMISSION_ATTEMPTS": 3,
    # PRD §3.8 — risk score weights and bands
    "LATE_WEIGHT": 12,
    "MISSED_WEIGHT": 20,
    "DELINQUENT_WEIGHT": 15,
    "SCORE_CEILING": 100.00,
    "MAJOR_DAYS_LATE": 30,
    # PRD §3.9 — five-year lookback
    "LOOKBACK_YEARS": 5,
    # PRD §3.10 — monitoring lapse and invoicing
    "MONITORING_ACK_MAX_GAP_DAYS": 45,
    "TIER1_RATE_CENTS": 45000,
    "TIER2_RATE_CENTS": 32500,
    "TIER3_RATE_CENTS": 25000,
    "SURCHARGE_RATE": 0.15,
    "MAX_SURCHARGE_CENTS": 150000,
    "ANNUAL_FEE_CAP_CENTS": 1200000,
    "MIN_ANNUAL_FEE_CENTS": 300000,
}

TIER_MULTIPLIER = {
    "TIER_0": 1.00,
    "TIER_1": 1.10,
    "TIER_2": 1.25,
    "TIER_3": 1.40,
}

TEST_DEFAULTS = {
    "ISSUER_PROGRAM_CODE": "CIVICCENTER",
    "SERIES_DESIGNATION": "2026A",
    "ORIGINAL_PAR_AMOUNT_CENTS": 75000000,
    "FISCAL_YEAR_END_MONTH_DAY": "06-30",
    "FILING_WINDOW_DAYS": 210,
    "RETAINER_CENTS": 250000,
}


# --------------------------------------------------------------------------- #
# Business-day arithmetic (PRD §2.6).  Pure date helpers, used by fixtures that
# need to place a clock instant relative to a derived deadline.
# --------------------------------------------------------------------------- #

def _parse(d):
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def is_business_day(d) -> bool:
    """A business day is neither Saturday nor Sunday and not a market holiday."""
    parsed = _parse(d)
    if parsed.weekday() >= 5:
        return False
    return parsed.isoformat() not in MARKET_HOLIDAYS


def add_business_days(base_date, n: int) -> str:
    """The n-th business day strictly after base_date; base_date is never counted."""
    cursor = _parse(base_date)
    counted = 0
    while counted < n:
        cursor = cursor + timedelta(days=1)
        if is_business_day(cursor):
            counted += 1
    return cursor.isoformat()


def roll_forward_to_business_day(d) -> str:
    """Walk forward one calendar day at a time until the date is a business day."""
    cursor = _parse(d)
    while not is_business_day(cursor):
        cursor = cursor + timedelta(days=1)
    return cursor.isoformat()


def add_calendar_days(base_date, n: int) -> str:
    return (_parse(base_date) + timedelta(days=n)).isoformat()


def days_between(start_date, end_date) -> int:
    """Whole calendar days from start_date to end_date, floored at zero."""
    return max(0, (_parse(end_date) - _parse(start_date)).days)


def clock_instant(day, time_part: str = "T00:00:00Z") -> str:
    """Build a logical-clock instant string from a calendar date."""
    return f"{_parse(day).isoformat()}{time_part}"
