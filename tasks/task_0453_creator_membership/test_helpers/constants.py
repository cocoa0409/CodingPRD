"""Domain thresholds — numeric constants from the Creator Membership PRD calculations (§3)."""

# Platform commission rate by creator platform_plan (PRD §3.7).
FEE_RATE = {
    "STARTER": 0.10,
    "PRO": 0.08,
    "PREMIUM": 0.05,
}

# Processing fee (PRD §3.7): net * PCT_RATE rounded half up + FLAT_CENTS, per line.
PROCESSING_PCT_RATE = 0.029
PROCESSING_FLAT_CENTS = 30

# Grace window (PRD §3.3): one week.
GRACE_PERIOD_DAYS = 7

# Win-back redemption window (PRD §3.6): 60 days from lapsed_at.
WIN_BACK_WINDOW_DAYS = 60

# Default win-back discount fraction (PRD §3.6).
DEFAULT_WIN_BACK_DISCOUNT_PCT = 0.30

# Logical clock default at server startup (PRD §3.3).
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# Tier pricing floors (PRD §3.1).
MIN_MONTHLY_FEE_CENTS = 100
MIN_PER_CREATION_FEE_CENTS = 50

# A clearly-non-existent UUID for not-found checks (matches the design indices).
BOGUS_UUID = "00000000-0000-4000-8000-000000000000"
