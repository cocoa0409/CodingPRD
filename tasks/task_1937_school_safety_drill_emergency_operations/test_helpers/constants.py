"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Evacuation timing assessment: unannounced drills get a 25% ceiling-rounded
# allowance on the target (PRD section on drill completion and timing).
UNANNOUNCED_ALLOWANCE_PCT = 0.25

# EOP submit gate: trailing walkthrough-currency window in days (inclusive).
WALKTHROUGH_WINDOW_DAYS = 365

# Compliance posture: overdue-action count at or above which a site is
# NON_COMPLIANT.
OVERDUE_NONCOMPLIANT_THRESHOLD = 3

# Logical clock value at server startup, before any clock-advance call.
DEFAULT_CLOCK_START = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "YEAR_START": "2026-08-01",
    "YEAR_END": "2027-06-30",
    "REQUIRED_PER_YEAR": 2,
    "MIN_SPACING_DAYS": 20,
    "TARGET_EVAC_SECONDS": 300,
    "DRILL_DATE": "2026-09-15",
    "DRILL_START": "09:00",
    "DRILL_DURATION_MINUTES": 30,
    "WALKTHROUGH_DATE": "2026-07-20",
    "SITE_PLAN_REVIEW_BY": "2027-01-15",
    "EOP_REVIEW_DUE": "2027-08-01",
    "CA_DUE_DATE": "2026-10-15",
}

__all__ = [
    "UNANNOUNCED_ALLOWANCE_PCT", "WALKTHROUGH_WINDOW_DAYS",
    "OVERDUE_NONCOMPLIANT_THRESHOLD", "DEFAULT_CLOCK_START", "TEST_DEFAULTS",
]
