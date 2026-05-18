"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Capped-value computation — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "the server first computes a ceiling equal to prior_capped_value
# multiplied by 1.02 (one plus the system growth-cap constant GROWTH_CAP,
# which is 2 percent — the Prop-13-style annual growth cap)"
GROWTH_CAP: float = 0.02


# ---------------------------------------------------------------------------
# Exemption stack — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "HOMESTEAD: the smaller of 20 percent of the residual base (the
# system constant HOMESTEAD_PCT is 0.20) and the absolute dollar cap of
# 75,000 (the system constant HOMESTEAD_CAP_DOLLARS)"
HOMESTEAD_PCT: float = 0.20
HOMESTEAD_CAP_DOLLARS: float = 75_000.00

# PRD §3.3: "SENIOR: a flat 25,000 (the system constant SENIOR_FLAT)"
SENIOR_FLAT: float = 25_000.00

# PRD §3.3: "VETERAN: a flat 15,000 (the system constant VETERAN_FLAT)"
VETERAN_FLAT: float = 15_000.00

# PRD §3.3: "DISABILITY: if Owner.disability_rating is at least 70, the full
# 30,000 (the system constant DISABILITY_FULL); otherwise half of
# DISABILITY_FULL, i.e. 15,000"
DISABILITY_FULL: float = 30_000.00
DISABILITY_HALF: float = 15_000.00

# PRD §3.3: "DISABILITY requires Owner.disability_rating to be at least 50
# percent (the system constant DISABILITY_MIN_PCT)"
DISABILITY_MIN_PCT: int = 50

# PRD §3.3: "DISABILITY: if Owner.disability_rating is at least 70"
DISABILITY_FULL_THRESHOLD: int = 70

# PRD §3.3: "SENIOR requires that the Owner's age, computed from
# date_of_birth, is at least 65 (the system constant SENIOR_AGE)"
SENIOR_AGE: int = 65


# ---------------------------------------------------------------------------
# Tax bill computation — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "if mill_rate is omitted, the system constant DEFAULT_MILL_RATE
# (12.5 per $1000 of taxable value) is captured on the bill"
DEFAULT_MILL_RATE: float = 12.5

# PRD §3.4: "due_date is set to issued_at plus the system constant
# DUE_WINDOW_DAYS (30 days)"
DUE_WINDOW_DAYS: int = 30


# ---------------------------------------------------------------------------
# Appeal window — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "computes appeal_window_closes_at as issued_at plus 30 days
# (the system constant APPEAL_WINDOW_DAYS)"
APPEAL_WINDOW_DAYS: int = 30


# ---------------------------------------------------------------------------
# Hearing — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "The interval (scheduled_end − scheduled_start) must not exceed
# the system constant HEARING_MAX_DURATION_MIN (120 minutes)"
HEARING_MAX_DURATION_MIN: int = 120

# PRD §3.5: "No other Hearing in SCHEDULED for the same officer_id may sit
# within the system constant OFFICER_BUFFER_MIN minutes (15 minutes)"
OFFICER_BUFFER_MIN: int = 15

# PRD §3.5: "The current time must be at or after Hearing.scheduled_start
# and strictly less than Hearing.scheduled_end plus a system grace period
# of 30 minutes (the system constant GRACE_MIN)"
GRACE_MIN: int = 30


# ---------------------------------------------------------------------------
# Deferral — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "annual_interest_rate is captured from the system constant
# DEFERRAL_INTEREST_RATE (5 percent annually)"
DEFERRAL_INTEREST_RATE: float = 0.05

# PRD §2.11: "DeferralPlans whose elapsed term has exceeded
# DEFERRAL_MAX_TERM_DAYS (365 days) auto-default"
DEFERRAL_MAX_TERM_DAYS: int = 365

# PRD §3.6: "Owner.disability_rating at least 50 percent (the system
# constant DEFERRAL_DISABILITY_MIN_PCT)"
DEFERRAL_DISABILITY_MIN_PCT: int = 50


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "limit defaults to 10, with a minimum of 1 and a maximum of 100"
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Aggregated defaults — anchored to PRD-named values
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "GROWTH_CAP": GROWTH_CAP,
    "HOMESTEAD_PCT": HOMESTEAD_PCT,
    "HOMESTEAD_CAP_DOLLARS": HOMESTEAD_CAP_DOLLARS,
    "SENIOR_FLAT": SENIOR_FLAT,
    "VETERAN_FLAT": VETERAN_FLAT,
    "DISABILITY_FULL": DISABILITY_FULL,
    "DISABILITY_HALF": DISABILITY_HALF,
    "DEFAULT_MILL_RATE": DEFAULT_MILL_RATE,
    "APPEAL_WINDOW_DAYS": APPEAL_WINDOW_DAYS,
    "DUE_WINDOW_DAYS": DUE_WINDOW_DAYS,
    "HEARING_MAX_DURATION_MIN": HEARING_MAX_DURATION_MIN,
    "OFFICER_BUFFER_MIN": OFFICER_BUFFER_MIN,
    "GRACE_MIN": GRACE_MIN,
    "DEFERRAL_INTEREST_RATE": DEFERRAL_INTEREST_RATE,
    "DEFERRAL_MAX_TERM_DAYS": DEFERRAL_MAX_TERM_DAYS,
}


__all__ = [
    "GROWTH_CAP",
    "HOMESTEAD_PCT",
    "HOMESTEAD_CAP_DOLLARS",
    "SENIOR_FLAT",
    "VETERAN_FLAT",
    "DISABILITY_FULL",
    "DISABILITY_HALF",
    "DISABILITY_MIN_PCT",
    "DISABILITY_FULL_THRESHOLD",
    "SENIOR_AGE",
    "DEFAULT_MILL_RATE",
    "DUE_WINDOW_DAYS",
    "APPEAL_WINDOW_DAYS",
    "HEARING_MAX_DURATION_MIN",
    "OFFICER_BUFFER_MIN",
    "GRACE_MIN",
    "DEFERRAL_INTEREST_RATE",
    "DEFERRAL_MAX_TERM_DAYS",
    "DEFERRAL_DISABILITY_MIN_PCT",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
