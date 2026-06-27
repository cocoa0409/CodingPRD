"""Domain thresholds — numeric constants from PRD calculations (Sections 2.7, 3.4, 3.7, 3.8)."""

# Interest-match proration (Section 3.7):
#   raw_interest = round_half_up(base * annual_rate_bps * period_days / (BPS_DENOM * DAYS_PER_YEAR))
DAYS_PER_YEAR = 365
BPS_DENOM = 10000

# Schedule spacing buffer (Section 3.4): new schedule must be >= 7 days from an
# existing ACTIVE schedule on the same child + payout_jar_type (closed buffer).
MIN_SCHEDULE_GAP_DAYS = 7

# Share accounting (Section 2.7 / 3.8): 1000 milli-shares == 1 whole share.
MILLI_PER_SHARE = 1000

# Teen-investing eligibility (Section 3.8): child must be at least 13 years old.
TEEN_AGE_YEARS = 13

THRESHOLDS = {
    "DAYS_PER_YEAR": DAYS_PER_YEAR,
    "BPS_DENOM": BPS_DENOM,
    "MIN_SCHEDULE_GAP_DAYS": MIN_SCHEDULE_GAP_DAYS,
    "MILLI_PER_SHARE": MILLI_PER_SHARE,
    "TEEN_AGE_YEARS": TEEN_AGE_YEARS,
}

# Default clock instant used by fixtures that need a deterministic "now".
DEFAULT_CLOCK_ISO = "2026-06-26T00:00:00Z"
