"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Sibling discount tiers (PRD Section 3.9).
DISCOUNT_2_PCT = 0.10
DISCOUNT_3_PLUS_PCT = 0.15

# Readiness scoring (PRD Section 3.7).
MASTERY_SCORE = 0.80
DEFAULT_READINESS_THRESHOLD = 0.80

# Makeup credit validity window in days (PRD Section 3.8).
MAKEUP_CREDIT_VALIDITY_DAYS = 60

# Instructor weekly-calendar transition buffer in minutes (PRD Section 3.4).
TRANSITION_BUFFER_MINUTES = 15

# Pagination defaults (PRD Section 2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Server-startup logical clock default (PRD Section 2.4).
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"

TEST_DEFAULTS = {
    "MONTHLY_TUITION_CENTS": 12000,
    "RATIO": 4,
    "MIN_AGE_MONTHS": 36,
    "MAX_AGE_MONTHS": 72,
}
