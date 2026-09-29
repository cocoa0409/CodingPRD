"""Numeric constants and unit-arithmetic helpers taken from the PRD.

Every value here is quoted from the PRD narrative, not invented: the sections
that state each one are named in the comments.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

# ─── Unit scales (PRD §2.5) ───────────────────────────────────────────
SHARE_UNIT_SCALE = 10000          # one whole share is 10,000 ``_e4`` units
BPS_SCALE = 10000                 # 10,000 basis points is one hundred percent

# ─── Logical clock (PRD §2.6) ─────────────────────────────────────────
CLOCK_BOOT_INSTANT = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Concentration basis (PRD §3.2) ───────────────────────────────────
CONCENTRATION_LIMIT_BPS = 1000
STRICT_CONCENTRATION_STATES = ("OH", "MA", "NM", "IA", "AL")

# ─── Subscription floors (PRD §3.4) ───────────────────────────────────
MINIMUM_INITIAL_INVESTMENT_CENTS = 250000
MINIMUM_ADDITIONAL_INVESTMENT_CENTS = 50000

# ─── Fee-schedule ranges (PRD §3.1) ───────────────────────────────────
MAX_UPFRONT_SELLING_COMMISSION_BPS = 1000
MAX_DEALER_MANAGER_FEE_BPS = 300
MAX_ANNUAL_DISTRIBUTION_FEE_BPS = 1500
MAX_DISTRIBUTION_FEE_CAP_BPS = 2000
MAX_COMMISSION_BPS_CEILING = 1300
VALID_CLASS_CODES = ("T", "S", "D", "I")

# ─── Valuation (PRD §3.6) ─────────────────────────────────────────────
NAV_VARIANCE_ESCALATION_BPS = 500

# ─── Distribution coverage and trail fees (PRD §3.7) ──────────────────
FULL_COVERAGE_BPS = 10000
MONTHS_PER_YEAR = 12

# ─── Repurchase caps and deductions (PRD §3.8) ────────────────────────
MONTHLY_REPURCHASE_CAP_BPS = 200
QUARTERLY_REPURCHASE_CAP_BPS = 500
EARLY_REPURCHASE_DEDUCTION_BPS = 200
EARLY_REPURCHASE_MIN_HOLDING_DAYS = 365
REPURCHASE_PERIOD_BLACKOUT_DAYS = 5

# ─── Vote tally (PRD §3.9) ────────────────────────────────────────────
QUORUM_DIVISOR = 2

# ─── Offering defaults (PRD §3.1) ─────────────────────────────────────
DEFAULT_RESCISSION_WINDOW_DAYS = 5


# ─── Rounding helpers (PRD §2.5) ──────────────────────────────────────

def round_half_up(numerator: int, denominator: int) -> int:
    """Nearest integer, resolving an exact tie away from zero."""
    if denominator == 0:
        raise ZeroDivisionError("round_half_up denominator must be non-zero")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * -numerator + denominator) // (2 * denominator))


def floor_div(numerator: int, denominator: int) -> int:
    """Truncate downward, toward negative infinity."""
    if denominator == 0:
        raise ZeroDivisionError("floor_div denominator must be non-zero")
    return numerator // denominator if denominator > 0 else (-numerator) // (-denominator)


def bps_of(amount_cents: int, bps: int) -> int:
    """A basis-point slice of a money amount, rounded half up (PRD §2.5)."""
    return round_half_up(amount_cents * bps, BPS_SCALE)


def bps_of_floor(amount_cents: int, bps: int) -> int:
    """A basis-point slice of a money amount, floored."""
    return floor_div(amount_cents * bps, BPS_SCALE)


def share_value_cents(shares_e4: int, price_cents: int) -> int:
    """Value of a share quantity at a price, rounded half up (PRD §2.5)."""
    return round_half_up(shares_e4 * price_cents, SHARE_UNIT_SCALE)


def shares_for_value_e4(value_cents: int, price_cents: int) -> int:
    """Share units a money amount buys at a price, floored (PRD §3.4)."""
    return floor_div(value_cents * SHARE_UNIT_SCALE, price_cents)


def quarter_key_for(period_month: str) -> str:
    """``<YYYY>-Q<n>`` derived as PRD §3.8 specifies."""
    year, month = period_month.split("-")
    quarter = (int(month) - 1) // 3 + 1
    return f"{year}-Q{quarter}"


def holding_period_days(issued_instant: str, settlement_date: str) -> int:
    """Whole days from a lot's issued calendar date to a settlement date."""
    issued = datetime.strptime(issued_instant[:10], "%Y-%m-%d").date()
    settled = datetime.strptime(settlement_date, "%Y-%m-%d").date()
    return (settled - issued).days


def instant(text: str) -> datetime:
    """Parse an ISO 8601 UTC instant used by the logical clock."""
    return datetime.strptime(text.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z").astimezone(
        timezone.utc
    )


def add_days(day: str, days: int) -> str:
    """Advance a ``YYYY-MM-DD`` calendar date by whole days."""
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()
