"""Domain thresholds and reusable values from the PRD (§2.4, §2.7, §3)."""

# Logical clock (PRD §2.4): startup default 2026-08-01T00:00:00Z; most scenarios
# pin the clock to the fiscal-year start so FMV freshness holds throughout.
CLOCK_START = "2026-01-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Fiscal window used by the standard plan fixtures.
FISCAL_YEAR_START = "2026-01-01"
FISCAL_YEAR_END = "2026-12-31"

# Standard rate row: CPT 99213 at 0.97 wRVU over the whole fiscal year
# (half-open window [2026-01-01, 2027-01-01), PRD §3.1).
DEFAULT_CPT_CODE = "99213"
DEFAULT_RATE_WRVU = 0.97
RATE_WINDOW_FROM = "2026-01-01"
RATE_WINDOW_TO = "2027-01-01"

# Tier schedules (PRD §3.1): first threshold 0, strictly increasing.
TIERS_SINGLE = [
    {"tier_code": "T1", "threshold_wrvu": 0, "conversion_factor_cents": 4500,
     "tier_bonus_cents": 0},
]
TIERS_THREE = [
    {"tier_code": "T1", "threshold_wrvu": 0, "conversion_factor_cents": 4500,
     "tier_bonus_cents": 0},
    {"tier_code": "T2", "threshold_wrvu": 5000, "conversion_factor_cents": 5500,
     "tier_bonus_cents": 250000},
    {"tier_code": "T3", "threshold_wrvu": 8000, "conversion_factor_cents": 6500,
     "tier_bonus_cents": 500000},
]

# Money (PRD §2.7: integer cents) and agreement defaults.
QUALITY_POOL_CENTS = 100000
FMV_CAP_CENTS = 90000000
BASE_SALARY_CENTS = 24000000
PERIOD_DRAW_CENTS = 1000000
APP_BASE_SALARY_CENTS = 12000000
APP_PERIOD_DRAW_CENTS = 500000
AGREEMENT_EFFECTIVE_DATE = "2026-01-01"

# FMV rules (PRD §3.3): cooling-off window and freshness horizon.
FMV_COOLING_OFF_DAYS = 30
FMV_FRESHNESS_MONTHS = 12

# Supervision capacity cap (PRD §3.5): a supervisor's supervised_fte sum.
SUPERVISION_FTE_CAP = 4.0
SUPERVISION_PCT_SUM_CAP = 1.0

# Standard measurement period used across scenarios.
PERIOD_FEB = "2026-02"
SERVICE_DATE_FEB = "2026-02-10"
POSTING_DATE_MAR = "2026-03-02"

# Statement period used by most scenarios.
STMT_YEAR = 2026
STMT_MONTH = 2

# Pagination (PRD §2.3).
PAGE_LIMIT_DEFAULT = 10
