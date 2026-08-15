"""Domain thresholds and numeric constants from PRD calculation rules."""

# PRD §3.3: composite index scales the rubric maximum of 4 to 100.
RUBRIC_MAX = 4

# PRD §3.7: interim report due date is moved earlier by 60 days of advance notice.
ADVANCE_NOTICE_DAYS = 60

# PRD §3.7: flat late-report penalty debited when a LATE report is accepted.
LATE_REPORT_PENALTY_CENTS = 25000

# PRD §2.8 / §3.2: renewal window opens 180 days before term_end.
RENEWAL_WINDOW_DAYS = 180

# PRD §3.6: allowed follow_up_months values for REQUIRED_ACTION findings.
ALLOWED_FOLLOW_UP_MONTHS = (6, 12, 18)

# Default logical-clock instant at server startup (PRD §2.8).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Default fee schedule figures shared by fee/invoice tests (PRD §3.8).
TEST_DEFAULTS = {
    "BASE_SYSTEM_FEE_CENTS": 500000,
    "PER_CAMPUS_FEE_CENTS": 120000,
    "LARGE_CAMPUS_FEE_CENTS": 200000,
    "LARGE_CAMPUS_THRESHOLD": 1000,
    "VISIT_DAY_RATE_CENTS": 75000,
    "FEE_SCHEDULE_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "TERM_START": "2026-09-01T00:00:00Z",
    "TERM_LENGTH_YEARS": 5,
}

# Comparison tolerance for 2-decimal-place half-up-rounded percentages
# (composite_index_pct, attainment_pct — PRD §2.7).
PCT_ABS_TOL = 0.001
