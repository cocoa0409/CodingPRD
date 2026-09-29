"""Domain constants for the job classification exemption audit API.

Every value here is pinned by the product requirements document; tests import
these names instead of repeating magic numbers.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_STAMP = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Federal baseline constants
# ---------------------------------------------------------------------------
FEDERAL_MIN_WEEKLY_SALARY_CENTS = 84400
FEDERAL_HCE_ANNUAL_CENTS = 13200000
FEDERAL_PRIMARY_DUTY_MIN_PCT = 50.0
STRICT_ENUM_PRIMARY_DUTY_MIN_PCT = 60.0
HCE_MIN_DUTY_PCT = 20.0
COMPUTER_HOURLY_MIN_CENTS = 2763
EXECUTIVE_MIN_SUPERVISED = 2
ANNUAL_HOURS_DIVISOR = 2080
STANDARD_WORKWEEK_HOURS = 40

# ---------------------------------------------------------------------------
# Duties corroboration
# ---------------------------------------------------------------------------
CORROBORATION_SPREAD_MAX_PCT = 15.0
MANAGER_WEIGHT_PCT = 40
INCUMBENT_WEIGHT_PCT = 60

# ---------------------------------------------------------------------------
# Back-wage lookback
# ---------------------------------------------------------------------------
LOOKBACK_WEEKS_STANDARD = 104
LOOKBACK_WEEKS_WILLFUL = 156

# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------
MISCLASSIFICATION_STATUS_RISK = 25
SCREENING_UNCERTAINTY_PREMIUM = 12
RISK_TIER_CRITICAL_MIN = 75
RISK_TIER_HIGH_MIN = 55
RISK_TIER_MEDIUM_MIN = 30

# ---------------------------------------------------------------------------
# Remediation money guards
# ---------------------------------------------------------------------------
VOLUNTARY_CORRECTION_MANDATORY_CENTS = 5000000
LEGAL_COUNSEL_AUTHORITY_CAP_CENTS = 25000000

# ---------------------------------------------------------------------------
# Reclassification scheduling
# ---------------------------------------------------------------------------
RECLASS_WINDOW_BUFFER_DAYS = 7
MAX_CONCURRENT_RECLASS_PER_FAMILY = 3

# ---------------------------------------------------------------------------
# Independent-contractor tests
# ---------------------------------------------------------------------------
ABC_PRONGS_REQUIRED = 3
ECONOMIC_REALITY_CONTRACTOR_MIN = 5
ECONOMIC_REALITY_EMPLOYEE_MAX = 2
COMMON_LAW_CONTRACTOR_MIN = 20
COMMON_LAW_EMPLOYEE_MAX = 11
COMMON_LAW_BEHAVIORAL_WEIGHT = 3
COMMON_LAW_FINANCIAL_WEIGHT = 2
COMMON_LAW_RELATIONSHIP_WEIGHT = 1

# ---------------------------------------------------------------------------
# Re-analysis trigger
# ---------------------------------------------------------------------------
REANALYSIS_DUTY_DELTA_PCT = 10.0

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ---------------------------------------------------------------------------
# Jurisdiction fixtures used throughout the suite
# ---------------------------------------------------------------------------
CA_MIN_WEEKLY_SALARY_CENTS = 132000
CA_RECLASS_NOTICE_DAYS = 7
TX_MIN_WEEKLY_SALARY_CENTS = 60000
TX_RECLASS_NOTICE_DAYS = 14

# Placeholder identifiers that are syntactically valid but never persisted.
UNKNOWN_UUID_A = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
UNKNOWN_UUID_B = "11111111-1111-4111-8111-111111111111"
UNKNOWN_UUID_C = "22222222-2222-4222-8222-222222222222"
UNKNOWN_UUID_D = "33333333-3333-4333-8333-333333333333"
UNKNOWN_UUID_E = "00000000-0000-4000-8000-000000000abc"
UNKNOWN_UUID_F = "00000000-0000-4000-8000-0000000000ff"
