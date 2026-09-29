"""Domain thresholds, rate tables and date arithmetic used by the tests.

Every figure below is stated in the PRD: rates per $1,000 of insured value,
catastrophe load percentages, risk-score point tables, thresholds and the
logical clock's pre-set value.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# The logical clock reads exactly this instant before it has ever been set.
INITIAL_CLOCK = "2026-08-01T00:00:00Z"

CONSTRUCTION_RATE_PER_1000_CENTS = {
    "FRAME": 210, "JOISTED_MASONRY": 150, "NON_COMBUSTIBLE": 110, "FIRE_RESISTIVE": 80,
}
CAT_LOAD_PCT = {
    "INLAND": Decimal("0.00"), "WIND_TIER_2": Decimal("0.18"), "SEISMIC": Decimal("0.25"),
    "WIND_TIER_1": Decimal("0.35"), "FLOOD_A": Decimal("0.40"),
}
DURATION_LOAD_PCT_PER_MONTH = Decimal("0.02")
SOFT_COST_RATE_PER_1000_CENTS = 60
RENOVATION_LOAD_PCT = Decimal("0.12")
DEDUCTIBLE_CREDIT_PCT = {
    "STANDARD_25K": Decimal("0.00"), "ELEVATED_100K": Decimal("0.06"),
    "HIGH_250K": Decimal("0.11"),
}
MIN_PREMIUM_CENTS = 250000

OCCURRENCE_DEDUCTIBLE_CENTS = {
    "STANDARD_25K": 2500000, "ELEVATED_100K": 10000000, "HIGH_250K": 25000000,
}

CONSTRUCTION_PTS = {
    "FRAME": 30, "JOISTED_MASONRY": 20, "NON_COMBUSTIBLE": 12, "FIRE_RESISTIVE": 6,
}
CAT_PTS = {
    "INLAND": 0, "WIND_TIER_2": 12, "SEISMIC": 18, "WIND_TIER_1": 25, "FLOOD_A": 30,
}
VALUE_PTS_STEP_CENTS = 500000000
RENOVATION_PTS = 10
REFERRAL_THRESHOLD = 75
INELIGIBLE_THRESHOLD = 90

RECONSTRUCTION_UPLIFT = Decimal("1.08")
PM_WEEKLY_PCT = Decimal("0.0015")
PM_MAX_WEEKS = 12

WAITING_PERIOD_DAYS = 5

SLIP_TIER_1_RATIO = Decimal("0.10")
SLIP_TIER_2_RATIO = Decimal("0.25")
MAX_CUMULATIVE_EXTENSION_RATIO = Decimal("0.50")
MANAGER_APPROVAL_AP_THRESHOLD_CENTS = 500000
CAT_RESLIP_SCORE_THRESHOLD = 85
CAT_RESLIP_LOAD = Decimal("1.25")

SHORT_RATE_RETENTION_PCT = Decimal("0.90")
SHORT_RATE_FEE_CENTS = 25000

MAX_STORAGE_DISTANCE_MILES = 100
HOT_WORK_BUFFER_HOURS = 24

MAX_RESUBMISSIONS = 3
MAX_REOPENS = 2

DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100


def round_half_up(value) -> int:
    """Round a numeric value half up to a whole number of cents."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant as used throughout the API."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def iso(dt: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with second precision."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(value: str, days: int) -> str:
    """Advance an ISO 8601 instant by a whole number of days."""
    return iso(parse_iso(value) + timedelta(days=days))


def add_hours(value: str, hours: float) -> str:
    """Advance an ISO 8601 instant by a number of hours."""
    return iso(parse_iso(value) + timedelta(hours=hours))


def add_seconds(value: str, seconds: int) -> str:
    """Advance an ISO 8601 instant by a number of seconds."""
    return iso(parse_iso(value) + timedelta(seconds=seconds))


def whole_days_between(start: str, end: str) -> int:
    """Whole number of days between two ISO 8601 instants."""
    return (parse_iso(end) - parse_iso(start)).days


def same_instant(a: str, b: str) -> bool:
    """Compare two ISO 8601 instants to whole-second precision."""
    return parse_iso(a).replace(microsecond=0) == parse_iso(b).replace(microsecond=0)
