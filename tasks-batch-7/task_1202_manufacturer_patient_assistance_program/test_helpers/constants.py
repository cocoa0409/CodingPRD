"""Domain thresholds and numeric constants from the PRD (§2.5, §2.11, §3.2)."""

# Logical clock startup default (PRD §2.5).
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

# Federal Poverty Level figures (PRD §3.2), integer cents.
FPL_BASE_CENTS = 1_565_000
FPL_ADDITIONAL_CENTS = 550_000
FPL_THRESHOLD_UNINSURED_PCT = "400.00"
FPL_THRESHOLD_UNDERINSURED_PCT = "500.00"

# Posture thresholds on the committed basis (PRD §2.11), inclusive.
RESTRICTED_THRESHOLD_PCT = "90.00"
EXHAUSTED_THRESHOLD_PCT = "100.00"

# Canonical budget period window used by most scenarios.
DEFAULT_PERIOD_START = "2026-01-01"
DEFAULT_PERIOD_END = "2026-12-31"
DEFAULT_ALLOCATED_CENTS = 1_000_000

# Canonical screening that always computes ELIGIBLE for an UNINSURED
# household of one (fpl 191.69 <= 400.00).
DEFAULT_PRIOR_YEAR_INCOME_CENTS = 3_000_000

# Canonical lot expiry comfortably beyond the 30-day buffer from 2026-05-01.
DEFAULT_LOT_EXPIRY = "2027-01-01"
