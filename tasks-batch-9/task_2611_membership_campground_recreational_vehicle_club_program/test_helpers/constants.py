"""Domain thresholds, rates and date helpers taken from the contract's formulas."""

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

#: Before any client sets it, the logical clock reads exactly this instant.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Entitlement, dues and delinquency
# ---------------------------------------------------------------------------

ENTITLEMENT_YEAR_DAYS = 365
CAPITAL_ASSESSMENT_PCT = Decimal("0.08")
LOYALTY_SUBTOTAL_BAND_CENTS = 60000
LOYALTY_TENURE_YEARS = 5
LOYALTY_PCT_HIGH_LONG = Decimal("0.10")
LOYALTY_PCT_HIGH = Decimal("0.05")
LOYALTY_PCT_LONG = Decimal("0.03")
DUES_NET_DAYS = 30
DUES_CYCLE_DAYS = 365

LATE_FEE_PCT = Decimal("0.015")
DUES_GRACE_START_DAYS = 1
DUES_DELINQUENT_DAYS = 30
DUES_WRITE_OFF_DAYS = 120

# ---------------------------------------------------------------------------
# Capacity, occupancy and seasons
# ---------------------------------------------------------------------------

TRANSIENT_FLOOR_SITES = 1
SEASON_OPEN_LEAD_DAYS = 30
LINK_GAP_NIGHTS = 1
ABSOLUTE_MAX_RUN_NIGHTS = 45

# ---------------------------------------------------------------------------
# Transient nightly pricing
# ---------------------------------------------------------------------------

CLASS_NIGHT_RATE_CENTS: Dict[str, int] = {
    "CLASS_A": 8500,
    "CLASS_B": 6200,
    "CLASS_C": 4100,
}
PEAK_START_MMDD = "07-01"
PEAK_END_MMDD = "09-07"
PEAK_MULTIPLIER = Decimal("1.35")
WEEKEND_MULTIPLIER = Decimal("1.15")
RESORT_FEE_PCT = Decimal("0.09")

# ---------------------------------------------------------------------------
# Surveys, ratings and inspections
# ---------------------------------------------------------------------------

W_OVERALL = Decimal("0.40")
W_CLEANLINESS = Decimal("0.25")
W_STAFF = Decimal("0.20")
W_VALUE = Decimal("0.15")

RECENT_DAYS = 90
MID_DAYS = 365
RECENT_WEIGHT = Decimal("1.0")
MID_WEIGHT = Decimal("0.6")
OLD_WEIGHT = Decimal("0.3")
TRAILING_WINDOW_DAYS = 180
DEFAULT_TRAILING_RATING = Decimal("3.00")
NO_SURVEY_RATING_SCORE = 0.00

W_RESTROOM = Decimal("0.35")
W_HOOKUP = Decimal("0.25")
W_UTILITY = Decimal("0.25")
W_ROAD = Decimal("0.15")
AMENITY_PASS_MIN = Decimal("4.00")
AMENITY_PROBATION_MIN = Decimal("3.00")
FORCED_CANCELLATION_PROBATION_THRESHOLD = 2

# ---------------------------------------------------------------------------
# Capital priority and reinvestment
# ---------------------------------------------------------------------------

CATEGORY_WEIGHTS: Dict[str, Decimal] = {
    "SAFETY": Decimal("1.40"),
    "UTILITY": Decimal("1.20"),
    "AMENITY": Decimal("1.00"),
    "EXPANSION": Decimal("0.80"),
}
COMPLIANCE_FACTORS: Dict[str, Decimal] = {
    "NON_COMPLIANT": Decimal("1.30"),
    "PROBATION": Decimal("1.15"),
    "COMPLIANT": Decimal("1.00"),
}
TARGET_RATING = Decimal("4.50")
USAGE_CAP = Decimal("1.50")
USAGE_DENOM_NIGHTS = 30
COST_BAND_LOW_CENTS = 5000000
COST_BAND_MID_CENTS = 20000000
COST_FACTOR_LOW = Decimal("1.20")
COST_FACTOR_MID = Decimal("1.00")
COST_FACTOR_HIGH = Decimal("0.85")
PRIORITY_SCALE = 1000

# ---------------------------------------------------------------------------
# Transfer, resale and reinstatement
# ---------------------------------------------------------------------------

TRANSFER_TYPE_MULTIPLIERS: Dict[str, Decimal] = {
    "RESALE": Decimal("1.00"),
    "GIFT": Decimal("0.50"),
    "ESTATE": Decimal("0.00"),
}
RESALE_SURCHARGE_PCT = Decimal("0.06")
RESALE_HOLD_DAYS = 730
MAX_TRANSFERS_PER_CHAIN = 2
REINSTATEMENT_FEE_CENTS = 15000

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Small deterministic helpers used to express expected values in tests
# ---------------------------------------------------------------------------


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    """Round half up, the discipline every monetary multiplication obeys."""
    exponent = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def cents_half_up(value: Decimal) -> int:
    """Round a monetary product half up to whole cents."""
    return int(round_half_up(Decimal(value), 0))


def two_dp(value: Decimal) -> float:
    """Round half up to exactly two decimal places, as scores are carried."""
    return float(round_half_up(Decimal(value), 2))


def iso_date(value: date) -> str:
    """Render a calendar date in YYYY-MM-DD form with no time component."""
    return value.isoformat()


def parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def shift_days(value: str, days: int) -> str:
    """Advance (or rewind) an ISO calendar date by whole days."""
    return iso_date(parse_date(value) + timedelta(days=days))


def clock_instant(day: str, time_part: str = "00:00:00") -> str:
    """Build a clock instant from a calendar date and a wall time."""
    return f"{day}T{time_part}Z"


def days_between(start: str, end: str) -> int:
    """Whole days from start to end, the unit every window arithmetic uses."""
    return (parse_date(end) - parse_date(start)).days


def parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def dues_amount_for(annual_dues_cents: int, tenure_years: int = 0) -> Dict[str, int]:
    """Reproduce the five-step dues waterfall, subtotal-keyed loyalty included."""
    base = int(annual_dues_cents)
    capital = cents_half_up(Decimal(base) * CAPITAL_ASSESSMENT_PCT)
    subtotal = base + capital
    if subtotal >= LOYALTY_SUBTOTAL_BAND_CENTS and tenure_years >= LOYALTY_TENURE_YEARS:
        pct = LOYALTY_PCT_HIGH_LONG
    elif subtotal >= LOYALTY_SUBTOTAL_BAND_CENTS:
        pct = LOYALTY_PCT_HIGH
    elif tenure_years >= LOYALTY_TENURE_YEARS:
        pct = LOYALTY_PCT_LONG
    else:
        pct = Decimal("0")
    credit = cents_half_up(Decimal(subtotal) * pct)
    return {
        "base_dues_cents": base,
        "capital_assessment_cents": capital,
        "subtotal_cents": subtotal,
        "loyalty_credit_cents": credit,
        "amount_cents": subtotal - credit,
    }


def late_fee_for(amount_cents: int, days_past_due: int) -> int:
    """One multiplication and exactly one rounding, month count rounded up."""
    if days_past_due < DUES_GRACE_START_DAYS:
        return 0
    months = -(-days_past_due // 30)
    return cents_half_up(Decimal(amount_cents) * LATE_FEE_PCT * Decimal(months))
