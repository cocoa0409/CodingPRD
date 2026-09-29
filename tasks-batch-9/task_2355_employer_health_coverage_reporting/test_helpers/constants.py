"""Domain constants and shared test literals (PRD §2.9, §3.1-§3.9)."""

# ---------------------------------------------------------------------------
# ALE determination arithmetic
# ---------------------------------------------------------------------------
ALE_THRESHOLD = 50
FTE_HOURS_DIVISOR = 120
SEASONAL_EXCEPTION_MAX_MONTHS = 4
MONTHLY_FT_HOURS_THRESHOLD = 130
WAITING_PERIOD_MONTHS = 2

# ---------------------------------------------------------------------------
# Penalty arithmetic
# ---------------------------------------------------------------------------
EXCLUSION_EMPLOYEES = 30
TRANSMITTAL_SELF_COUNT = 1

# ---------------------------------------------------------------------------
# Late-furnishing penalty tiers
# ---------------------------------------------------------------------------
TIER1_MAX_DAYS = 30
TIER1_CENTS = 6000
TIER2_CENTS = 12000
TIER3_CENTS = 31000
TIER4_CENTS = 63000

# ---------------------------------------------------------------------------
# Employment / transmittal limits
# ---------------------------------------------------------------------------
REHIRE_BREAK_DAYS = 91
CORRECTION_CYCLE_LIMIT = 3

# ---------------------------------------------------------------------------
# FilingSeason optional-field defaults (PRD §3.1)
# ---------------------------------------------------------------------------
DEFAULT_AFFORDABILITY_PCT = 0.0902
DEFAULT_MAINLAND_FPL_ANNUAL_CENTS = 1560000
DEFAULT_PENALTY_A_ANNUAL_CENTS = 296400
DEFAULT_PENALTY_B_ANNUAL_CENTS = 444000
DEFAULT_ELECTRONIC_FILING_THRESHOLD = 10

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Shared test-scenario literals
# ---------------------------------------------------------------------------
TAX_YEAR = 2026
FURNISHING_DEADLINE_DATE = "2027-03-02"
FILING_DEADLINE_DATE = "2027-03-31"
TIER2_CUTOFF_DATE = "2027-08-01"
MONTHS = list(range(1, 13))
