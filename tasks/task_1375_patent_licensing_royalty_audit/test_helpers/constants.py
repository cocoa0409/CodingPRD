"""Domain thresholds and defaults — numeric constants from the PRD."""

# Fixed basis-point denominator (PRD section 2.5).
BP_DENOMINATOR = 10000

# Logical clock default before any clock-setting call (PRD section 2.6).
DEFAULT_CURRENT_UTC = "2026-08-01T00:00:00Z"

# Server-side defaults applied when optional agreement fields are omitted
# (PRD section 3.2).
AGREEMENT_DEFAULTS = {
    "minimum_period_royalty_cents": 0,
    "sublicense_allowed": False,
    "sublicense_passthrough_rate_bp": 0,
    "mfl_clause": False,
    "mfl_mode": "RETROACTIVE",
    "mfl_lookback_quarters": 4,
    "audit_window_months": 24,
    "underreport_tolerance_bp": 500,
}

# Field bounds (PRD section 2.5).
BASE_RATE_BP_MIN_EXCLUSIVE = 0
BASE_RATE_BP_MAX = 10000
PASSTHROUGH_RATE_BP_MIN = 0
PASSTHROUGH_RATE_BP_MAX = 10000
TOLERANCE_BP_MIN = 0
TOLERANCE_BP_MAX_EXCLUSIVE = 10000
INVENTOR_SHARES_TOTAL_BP = 10000

# Pagination defaults (PRD section 2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

TEST_DEFAULTS = {
    "BASE_RATE_BP": 500,
    "UNDERREPORT_TOLERANCE_BP": 1000,
    "AUDIT_WINDOW_MONTHS": 24,
    "EFFECTIVE_DATE": "2026-01-01T00:00:00Z",
    "EXPIRATION_DATE": "2028-01-01T00:00:00Z",
}
