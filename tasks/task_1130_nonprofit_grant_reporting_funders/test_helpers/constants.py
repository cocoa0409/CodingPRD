"""Domain thresholds — numeric constants named in the PRD (§1, §3)."""

# PRD §1 / §2.11: the logical clock boots at this exact instant.
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# PRD §3.5: standard volunteer rate used to recognize VOLUNTEER_TIME.
STANDARD_VOLUNTEER_RATE_CENTS = 3150

# PRD §3.6: de minimis indirect rate applied for FEDERAL funders with unset rate.
DE_MINIMIS_INDIRECT_PCT = 10

# PRD §3.6: trailing-average burn window length in closed periods.
TRAILING_WINDOW_PERIODS = 1

# PRD §3.8: an auditor_org may hold at most this many mutually-overlapping
# active engagements.
AUDITOR_MAX_CONCURRENT_ENGAGEMENTS = 2

# PRD §3.1: server-side defaults for optional grant fields.
DEFAULT_INTERIM_DUE_DAYS = 30
DEFAULT_FINAL_DUE_DAYS = 90
DEFAULT_RENEWAL_WINDOW_DAYS = 60
DEFAULT_VARIANCE_THRESHOLD_PCT = 10.0

# Frequently reused grant geometry: QUARTERLY 2026-06-01 .. 2027-05-31 gives
# exactly 4 periods (P1 2026-06-01..2026-08-31, ..., P4 2027-03-01..2027-05-31).
DEFAULT_START_DATE = "2026-06-01"
DEFAULT_END_DATE = "2027-05-31"
QUARTERLY_PERIOD_COUNT = 4

TEST_DEFAULTS = {
    "AWARD_AMOUNT_CENTS": 100_000_000,
    "LINE_BUDGET_CENTS": 100_000_000,
    "FUND_ALLOCATED_CENTS": 100_000_000,
    "CONTACT_EMAIL": "contact@example.org",
}
