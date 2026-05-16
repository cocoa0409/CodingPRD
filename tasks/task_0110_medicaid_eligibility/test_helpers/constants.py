"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Premium estimate constants — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "a base premium of 30.00 dollars per FPL unit".
BASE_PREMIUM_PER_FPL_UNIT: float = 30.00

# PRD §3.7: "when the applicant's age is less than the floor of 18 years,
# the age factor is 1.0 exactly".
AGE_FACTOR_FLOOR_AGE: int = 18

# PRD §3.7: "the factor caps at 1.92 once the applicant has reached 64 years".
AGE_FACTOR_CEIL_AGE: int = 64

# PRD §3.7: "an 18-year-old contributes a factor of 1.0, a 19-year-old
# contributes 1.02". 0.02 per year.
AGE_FACTOR_PER_YEAR: float = 0.02


# ---------------------------------------------------------------------------
# Date / window constants — PRD §2.6
# ---------------------------------------------------------------------------
# PRD §2.6: "the '90 days' used to derive an appeal deadline_at ... are
# interpreted as exactly 90 * 86400 seconds".
APPEAL_WINDOW_DAYS: int = 90

# PRD §2.6: "the '365 days' used to derive coverage_end and
# redetermination_due_at are interpreted as exactly 365 * 86400 seconds".
COVERAGE_PERIOD_DAYS: int = 365

# PRD §3.6: "a 30-minute buffer applied to the new hearing's interval".
HEARING_BUFFER_MINUTES: int = 30

# PRD §3.4: redetermination 90-day grace period.
REDETERMINATION_GRACE_DAYS: int = 90

SECONDS_PER_DAY: int = 86_400
SECONDS_PER_MINUTE: int = 60


# ---------------------------------------------------------------------------
# Federal exempt asset set — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "Under the federal exempt set, only PRIMARY_RESIDENCE,
# RETIREMENT, and LIFE_INSURANCE are exempt".
FEDERAL_EXEMPT_ASSET_TYPES = frozenset({
    "PRIMARY_RESIDENCE", "RETIREMENT", "LIFE_INSURANCE",
})


# ---------------------------------------------------------------------------
# MAGI countable / excluded source types — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "the countable set for MAGI is WAGES, SELF_EMPLOYMENT,
# INTEREST, DIVIDENDS, CAPITAL_GAINS, UNEMPLOYMENT, and OTHER".
MAGI_COUNTABLE_BASE = frozenset({
    "WAGES", "SELF_EMPLOYMENT", "INTEREST", "DIVIDENDS",
    "CAPITAL_GAINS", "UNEMPLOYMENT", "OTHER",
})

# PRD §3.2: "SOCIAL_SECURITY is countable only when the owning applicant's
# dependent_status is PRIMARY".
SOCIAL_SECURITY_CONDITIONAL_DEPENDENT_STATUS = "PRIMARY"

# PRD §3.2: "CHILD_SUPPORT, TANF, and SSI are never countable for MAGI".
MAGI_EXCLUDED = frozenset({"CHILD_SUPPORT", "TANF", "SSI"})


# ---------------------------------------------------------------------------
# Income frequency annualization multipliers — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "when the frequency is ANNUAL the annualized amount is the
# gross_amount itself; when it is MONTHLY the gross amount is multiplied
# by twelve; when it is BIWEEKLY the gross amount is multiplied by
# twenty-six; when it is WEEKLY the gross amount is multiplied by
# fifty-two".
FREQUENCY_MULTIPLIERS = {
    "ANNUAL": 1,
    "MONTHLY": 12,
    "BIWEEKLY": 26,
    "WEEKLY": 52,
}


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — generous values so most tests do not trip thresholds
# ---------------------------------------------------------------------------
# PRD §3.4: redetermination_count_this_year counts redeterminations
# whose due_date falls in the calendar year equal to the household's
# StatePolicy.fpl_year. The fixtures approve applications against the
# server clock, then advance the clock by 365 days to trigger a
# redetermination_due. The created redetermination's due_date is in
# (server_now + 365d). Picking FPL_YEAR to match that year keeps the
# count-this-year invariant satisfied across all tests.
_redet_year = (datetime.now(timezone.utc) + timedelta(days=365)).year

TEST_DEFAULTS = {
    "FPL_YEAR": _redet_year,
    "FPL_BASE_AMOUNT": 15_000.00,
    "FPL_PER_MEMBER_AMOUNT": 5_000.00,
    "MAGI_INCOME_LIMIT_PCT": 138.0,
    "ASSET_LIMIT_PER_MEMBER": 10_000.00,
    "STATE_DISREGARD_AMOUNT": 0.00,
    "DEFAULT_ADDRESS_LINE": "123 Main St",
    "DEFAULT_FILING_STATUS": "SINGLE",
    "DEFAULT_DEPENDENT_STATUS": "PRIMARY",
    # An adult applicant born in 1990 — adult ages reach 18+ for premium
    # calc but stay well under 64; use specific DOBs in age-targeted tests.
    "DEFAULT_DATE_OF_BIRTH": "1990-06-15",
}


__all__ = [
    "BASE_PREMIUM_PER_FPL_UNIT",
    "AGE_FACTOR_FLOOR_AGE",
    "AGE_FACTOR_CEIL_AGE",
    "AGE_FACTOR_PER_YEAR",
    "APPEAL_WINDOW_DAYS",
    "COVERAGE_PERIOD_DAYS",
    "HEARING_BUFFER_MINUTES",
    "REDETERMINATION_GRACE_DAYS",
    "SECONDS_PER_DAY",
    "SECONDS_PER_MINUTE",
    "FEDERAL_EXEMPT_ASSET_TYPES",
    "MAGI_COUNTABLE_BASE",
    "SOCIAL_SECURITY_CONDITIONAL_DEPENDENT_STATUS",
    "MAGI_EXCLUDED",
    "FREQUENCY_MULTIPLIERS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
