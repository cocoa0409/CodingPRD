"""Domain constants and pure date helpers drawn from the PRD's fiscal rules."""

from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

#: Mandatory default value of the clock when it has never been set.
DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"
#: The quarter that contains the default clock instant.
DEFAULT_CLOCK_QUARTER = "2026Q3"

# ---------------------------------------------------------------------------
# Category policy defaults
# ---------------------------------------------------------------------------

DEFAULT_CLOSEOUT_CAP_PCT_BPS = 1500
DEFAULT_CLOSEOUT_HARD_LIMIT_BPS = 4000
DEFAULT_DEDUCTION_CAP_PCT_BPS = 500
DEFAULT_DEDUCTION_HARD_LIMIT_BPS = 2000
DEFAULT_ADVANCE_FLOOR_BPS_OF_MG = 2500
DEFAULT_CENTRAL_LICENSING = True

BPS_DENOMINATOR = 10000

# ---------------------------------------------------------------------------
# Recoupment
# ---------------------------------------------------------------------------

#: Normal recoupment cap: the whole cash royalty may be applied to the advance.
RECOUPMENT_CAP_BPS_NORMAL = 10000
#: Under PROBATION or FROZEN the cap halves.
RECOUPMENT_CAP_BPS_RESTRICTED = 5000

# ---------------------------------------------------------------------------
# Late filing and administration fee
# ---------------------------------------------------------------------------

LATE_INTEREST_BPS_PER_DAY = 5
FILING_DEADLINE_DAYS_AFTER_QUARTER_END = 45
ADMIN_FEE_WAIVER_THRESHOLD_CENTS = 100000
ADMIN_FEE_BPS = 150

# ---------------------------------------------------------------------------
# Compliance risk index
# ---------------------------------------------------------------------------

#: A failed sample inspection.
RISK_WEIGHT_SAMPLE_FAILURE = 8
#: A rejected design, unless it was rejected because the agreement expired.
RISK_WEIGHT_REJECTED_DESIGN = 5
#: A returned royalty report, counted as many times as its `return_count`.
RISK_WEIGHT_RETURNED_REPORT = 6
#: A confirmed audit underreporting.
RISK_WEIGHT_AUDIT_UNDERREPORT = 20
#: A counterfeit seizure.
RISK_WEIGHT_SEIZURE = 15

#: Only rows whose elapsed-quarter count is between 0 and 7 inclusive are kept.
RISK_WINDOW_QUARTERS = 8
RISK_WINDOW_MAX_ELAPSED = 7
RISK_INDEX_MAX = 100

POSTURE_BAND_FROZEN_MIN = 60
POSTURE_BAND_PROBATION_MIN = 35
POSTURE_BAND_WATCH_MIN = 15

# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

AUDIT_LOOKBACK_QUARTERS = 8
AUDIT_COST_SHIFT_THRESHOLD_BPS = 500
AUDIT_COST_RECOVERY_CENTS = 750000
AUDIT_INTEREST_BPS_PER_QUARTER = 150

# ---------------------------------------------------------------------------
# Retailer authorizations
# ---------------------------------------------------------------------------

RETAILER_WINDOW_BUFFER_DAYS = 30
OFF_PRICE_MAX_CONCURRENT_ACCOUNTS = 2

# ---------------------------------------------------------------------------
# Central pool distribution
# ---------------------------------------------------------------------------

PLAYER_POOL_BPS = 2500
CLUB_EQUAL_SHARE_BPS = 7500

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ---------------------------------------------------------------------------
# Immutable record types: only `id` and `created_at`
# ---------------------------------------------------------------------------

IMMUTABLE_RECORD_TYPES = ("SampleReview", "ClubDistribution")


# ---------------------------------------------------------------------------
# Pure quarter arithmetic (mirrors the PRD's fiscal calendar)
# ---------------------------------------------------------------------------

_QUARTER_END_MONTH_DAY = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def quarter_label(year: int, quarter: int) -> str:
    """Four-digit year, the letter Q, then the quarter number, with no separator."""
    return f"{year}Q{quarter}"


def parse_quarter(label: str) -> tuple:
    """Split a `YYYYQn` label into its (year, quarter) integers."""
    year, quarter = label.split("Q")
    return int(year), int(quarter)


def quarter_of_date(iso_date: str) -> str:
    """The quarter label that contains the given calendar date."""
    parsed = date.fromisoformat(iso_date)
    return quarter_label(parsed.year, (parsed.month - 1) // 3 + 1)


def quarter_end_date(label: str) -> str:
    """The last calendar day of the quarter."""
    year, quarter = parse_quarter(label)
    month, day = _QUARTER_END_MONTH_DAY[quarter]
    return date(year, month, day).isoformat()


def filing_deadline_date(label: str) -> str:
    """The quarter's quarter-end date plus 45 calendar days."""
    end = date.fromisoformat(quarter_end_date(label))
    return (end + timedelta(days=FILING_DEADLINE_DAYS_AFTER_QUARTER_END)).isoformat()


def quarter_index(label: str) -> int:
    """A monotonically increasing index over quarters, for elapsed-quarter arithmetic."""
    year, quarter = parse_quarter(label)
    return year * 4 + (quarter - 1)


def elapsed_quarters(earlier: str, later: str) -> int:
    """How many quarters have elapsed between two quarter labels."""
    return quarter_index(later) - quarter_index(earlier)


def add_quarters(label: str, count: int) -> str:
    """Shift a quarter label forward (or backward) by whole quarters."""
    index = quarter_index(label) + count
    return quarter_label(index // 4, index % 4 + 1)
