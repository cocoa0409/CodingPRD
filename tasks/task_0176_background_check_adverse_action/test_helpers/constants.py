"""Domain thresholds — numeric constants from the PRD.

Values mirror PRD §3.4 (severity scoring), §3.5 (composite decision
thresholds), §3.6 (cooling-off), §3.9 (eligibility posture lock window),
and §2.3 (pagination).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Verification severity score constants — PRD §3.4
# ---------------------------------------------------------------------------
SEVERITY_INFRACTION_SCORE: int = 5
SEVERITY_MISDEMEANOR_SCORE: int = 25
SEVERITY_FELONY_SCORE: int = 70
SEVERITY_MAX: int = 100

MVR_TIER_ZERO: int = 0
MVR_TIER_ONE: int = 10
MVR_TIER_TWO: int = 25
MVR_TIER_THREE_PLUS: int = 50
LICENSE_SUSPENDED_BONUS: int = 20

EDUCATION_UNVERIFIED_PENALTY: int = 40

CRIMINAL_DAYS_PER_YEAR: float = 365.25


# ---------------------------------------------------------------------------
# Composite decision thresholds — PRD §3.5
# ---------------------------------------------------------------------------
FEDERAL_CONSIDER_THRESHOLD: int = 15      # per-item
FEDERAL_INELIGIBLE_FAIL_COUNT: int = 2    # number of failing items

JURISDICTIONAL_AGGREGATE_CONSIDER: int = 30   # > -> CONSIDER

JURISDICTIONAL_INELIGIBLE_CUTS: dict = {
    "CA": 80,
    "NY": 75,
    "IL": 70,
    "TX": 60,
    "FL": 55,
    "MA": 80,
    "WA": 70,
}


# ---------------------------------------------------------------------------
# Cooling-off — PRD §3.6
# ---------------------------------------------------------------------------
FEDERAL_MIN_BUSINESS_DAYS: int = 5
BUSINESS_DAYS_PER_WEEK: int = 5  # Mon-Fri


# ---------------------------------------------------------------------------
# Eligibility posture — PRD §3.9
# ---------------------------------------------------------------------------
ADVERSE_LOCK_WINDOW_DAYS: int = 365


# ---------------------------------------------------------------------------
# Verification item caps — PRD §3.4
# ---------------------------------------------------------------------------
REWORK_CAP: int = 2


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Supported jurisdictions — PRD §3.1
# ---------------------------------------------------------------------------
JURISDICTION_CODES: list = ["CA", "NY", "IL", "TX", "FL", "MA", "WA"]


# ---------------------------------------------------------------------------
# Supported package codes — PRD §3.3
# ---------------------------------------------------------------------------
PACKAGE_CODES: list = ["CRIMINAL", "MVR", "EDUCATION"]


# ---------------------------------------------------------------------------
# Test defaults — used by fixtures / factories.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    # An ISO timestamp chosen well after any leap-year landmines and
    # comfortably before the longest cooling-off scenarios in fixtures.
    "INITIAL_CLOCK_ISO": "2026-01-05T10:00:00.000Z",
    "FALLBACK_CONSENT_HASH":
        "0000000000000000000000000000000000000000000000000000000000000000",
}


__all__ = [
    "SEVERITY_INFRACTION_SCORE",
    "SEVERITY_MISDEMEANOR_SCORE",
    "SEVERITY_FELONY_SCORE",
    "SEVERITY_MAX",
    "MVR_TIER_ZERO",
    "MVR_TIER_ONE",
    "MVR_TIER_TWO",
    "MVR_TIER_THREE_PLUS",
    "LICENSE_SUSPENDED_BONUS",
    "EDUCATION_UNVERIFIED_PENALTY",
    "CRIMINAL_DAYS_PER_YEAR",
    "FEDERAL_CONSIDER_THRESHOLD",
    "FEDERAL_INELIGIBLE_FAIL_COUNT",
    "JURISDICTIONAL_AGGREGATE_CONSIDER",
    "JURISDICTIONAL_INELIGIBLE_CUTS",
    "FEDERAL_MIN_BUSINESS_DAYS",
    "BUSINESS_DAYS_PER_WEEK",
    "ADVERSE_LOCK_WINDOW_DAYS",
    "REWORK_CAP",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "JURISDICTION_CODES",
    "PACKAGE_CODES",
    "TEST_DEFAULTS",
]
