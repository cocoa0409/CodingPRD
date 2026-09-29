"""Numeric constants and repeated literals of the scheduling domain."""

from __future__ import annotations

from typing import Any, Dict

API_PREFIX = "/scheduling"

# The logical clock's mandatory startup instant.
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DATE = "2026-08-01"
CLOCK_STARTUP_ISO_WEEK_START = "2026-07-27"

THRESHOLDS: Dict[str, Any] = {
    # Daily capacity
    "STANDARD_WORK_DAYS_PER_WEEK": 5,
    # Prior-week utilisation tiers and their weekly-cap multipliers
    "TIER_GREEN_MAX_UTILISATION": 1.0000,
    "TIER_AMBER_MAX_UTILISATION": 1.2500,
    "TIER_MULTIPLIER_GREEN": 1.25,
    "TIER_MULTIPLIER_AMBER": 1.15,
    "TIER_MULTIPLIER_RED": 1.00,
    "ABSOLUTE_CEILING_MULTIPLIER": 1.40,
    # Offshore review charging
    "OFFSHORE_REVIEW_RATIO": 0.20,
    "MIN_REVIEW_BLOCK_HOURS": 2.00,
    "REWORK_REVIEW_HOURS": 1.00,
    "MAX_REWORK_CYCLES": 2,
    # Automated selection scoring
    "LEVEL_MATCH_WEIGHT": 40,
    "INDUSTRY_WEIGHT": 30,
    "SLACK_WEIGHT": 30,
    # Effective bill-rate factors
    "RATE_MODEL_FACTOR_ONSHORE": 1.00,
    "RATE_MODEL_FACTOR_OFFSHORE": 0.55,
    # Decay-weighted burnout
    "DECAY_WEIGHTS": [1.00, 0.75, 0.50, 0.25],
    "DECAY_WEIGHT_SUM": 2.50,
    "BURNOUT_WEEK_WINDOW": 4,
    # Partner rotation
    "ROTATION_LIMIT_PIE": 5,
    "ROTATION_LIMIT_STANDARD": 7,
    # Execution
    "TIME_ENTRY_OVERRUN_TOLERANCE": 1.25,
    # Fieldwork gate
    "START_FIELDWORK_MIN_COMPLETION_PCT": 50.00,
}

PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
    "MIN_OFFSET": 0,
}

TEST_DEFAULTS: Dict[str, Any] = {
    "CLIENT_NAME": "Meridian Manufacturing",
    "CLIENT_INDUSTRY": "MANUFACTURING",
    "CLIENT_FISCAL_YEAR_END": "2026-12-31",
    "PARTNER_NAME": "Pat Rowe",
    "SENIOR_NAME": "Sam Oyelaran",
    "BUSY_SEASON_YEAR": 2026,
    "DEADLINE_DATE": "2026-10-15",
    "SERVICE_LINE": "AUDIT",
    "PHASE_WINDOW_START": "2026-08-03",
    "PHASE_WINDOW_END": "2026-08-31",
}

# Mondays used repeatedly by the week-keyed reads and records.
MONDAY_JUL_27 = "2026-07-27"
MONDAY_AUG_03 = "2026-08-03"
MONDAY_AUG_10 = "2026-08-10"
MONDAY_AUG_17 = "2026-08-17"
MONDAY_AUG_24 = "2026-08-24"
MONDAY_AUG_31 = "2026-08-31"

__all__ = [
    "API_PREFIX",
    "CLOCK_STARTUP_UTC",
    "CLOCK_STARTUP_DATE",
    "CLOCK_STARTUP_ISO_WEEK_START",
    "THRESHOLDS",
    "PAGINATION",
    "TEST_DEFAULTS",
    "MONDAY_JUL_27",
    "MONDAY_AUG_03",
    "MONDAY_AUG_10",
    "MONDAY_AUG_17",
    "MONDAY_AUG_24",
    "MONDAY_AUG_31",
]
