"""Domain thresholds and shared literals from the PRD's calculation rules."""

# Season and default logical clock (PRD "The Logical Clock": startup reads exactly this)
SEASON_START = "2026-08-01T00:00:00Z"
SEASON_END = "2026-09-01T00:00:00Z"
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Standard operating day used across scenarios
DAY_DATE = "2026-08-01"
DAY_OPENS_AT = "2026-08-01T08:00:00Z"
DAY_CLOSES_AT = "2026-08-01T14:00:00Z"

# Standard serial ranges (shared literals used throughout the suite)
BASE500_SERIAL_START = 100001
BASE500_SERIAL_END = 100100
BASE100_SERIAL_START = 200001
BASE100_SERIAL_END = 200200
MATCH_SERIAL_START = 300001
MATCH_SERIAL_END = 300500

# Match economics per benefit type (PRD "Issuing Tokens at the Info Booth")
MATCH_RATIO = {"SNAP": 1.0, "WIC": 0.5, "SENIOR": 1.0}
DAILY_CAP_CENTS = {"SNAP": 2000, "WIC": 1000, "SENIOR": 1500}
SEASON_CAP_CENTS = {"SNAP": 20000, "WIC": 10000, "SENIOR": 15000}
MATCH_TOKEN_DENOM_CENTS = 100
BASE_DENOMINATIONS = (500, 100)

# Program administration withholding: 2.5 percent = 250 basis points
FEE_BPS = 250

# Reconciliation tolerance (five dollars); the boundary is inclusive
RECONCILE_TOLERANCE_CENTS = 500

# Claim temporal limits
SUBMISSION_WINDOW_DAYS = 7
RESUBMIT_GRACE_HOURS = 72
