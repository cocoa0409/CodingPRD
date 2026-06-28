"""Domain thresholds — numeric constants from PRD calculations and §2 principles.

NON_EXISTENT_UUID comes from the framework.
"""

# recommended_weekly_minutes tiers (PRD §3.2): a single banded recommendation
# selects the whole recommendation, not a marginal accumulation.
#   severity_score 0..29  -> 30
#   severity_score 30..59 -> 60
#   severity_score 60..79 -> 90
#   severity_score 80..100 -> 120
RECOMMENDED_WEEKLY_MINUTES_TIERS = [
    (0, 29, 30),
    (30, 59, 60),
    (60, 79, 90),
    (80, 100, 120),
]

THRESHOLDS = {
    # Child double-booking buffer (PRD §3.5 / §2.7): 15-minute gap so two of the
    # same child's sessions cannot be back-to-back.
    "CHILD_BUFFER_MINUTES": 15,
    # IFSP early-intervention age cutoff (PRD §3.7): age_months_at_intake must be
    # below 36 months.
    "IFSP_AGE_MONTHS_CUTOFF": 36,
}

# Pagination defaults (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Logical clock startup default (PRD §2.11).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Shared authorization window used across fixtures (June appointments fall inside
# the window; the week of 2026-06-08 is a Monday).
AUTH_VALID_FROM = "2026-06-01T00:00:00Z"
AUTH_VALID_UNTIL = "2026-09-01T00:00:00Z"
