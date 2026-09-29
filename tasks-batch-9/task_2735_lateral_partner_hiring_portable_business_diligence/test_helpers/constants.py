"""Domain thresholds and canonical fixture literals for the Lateral Partner
Hiring API.

Every numeric constant here is stated in the PRD narrative; the ``EXPECTED_*``
blocks are the pre-computed outcomes of the canonical fixture book variants so
that tests assert literals rather than re-deriving formulas.
"""

# ----------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"

# ----------------------------------------------------------------------
# Portable-business validation
# ----------------------------------------------------------------------

LOOKBACK_YEARS = 3
MIN_VERIFIED_RECORDS = 3
REALIZATION_CEILING = 0.95
PORTABILITY_CEILING = 0.90

ROLE_FACTORS = {
    "BILLING_ATTORNEY": 1.00,
    "RELATIONSHIP_PARTNER": 0.85,
    "SERVICE_PARTNER": 0.55,
}

CONSENT_FACTORS = {
    "CONSENT_CONFIRMED": 1.00,
    "CONSENT_PENDING": 0.60,
}

# Concentration grading is on inclusive boundaries.
CONCENTRATION_HIGH_THRESHOLD = 0.30
CONCENTRATION_MEDIUM_THRESHOLD = 0.20
CONCENTRATION_HAIRCUTS = {"HIGH": 0.15, "MEDIUM": 0.07, "LOW": 0.00}

# ----------------------------------------------------------------------
# Offer economics
# ----------------------------------------------------------------------

RAMP_FACTOR_LONG_NOTICE = 0.70          # notice_period_days strictly greater than 60
RAMP_FACTOR_SHORT_NOTICE = 0.85         # 60 days or fewer
RAMP_NOTICE_BOUNDARY_DAYS = 60
PRACTICE_UPLIFT = 0.05
PRACTICE_UPLIFT_LEVERAGE_THRESHOLD = 3.00
EFFECTIVE_MULTIPLIER_CAP = 0.92

RATE_ALIGNMENT_FLOOR = 0.80
RATE_ALIGNMENT_CEILING = 1.10

OFFICE_BUILD_OUT_USD = 50000.00
PARALEGAL_SUPPORT_USD = 35000.00
ONBOARDING_OVERHEAD_PCT = 0.04

TRUE_UP_HIGH_NET_THRESHOLD_USD = 500000.00
TRUE_UP_HIGH_PCT = 0.10
TRUE_UP_LOW_PCT = 0.05

# ----------------------------------------------------------------------
# Search-firm fees
# ----------------------------------------------------------------------

FIRM_MAX_FEE_PCT_CEILING = 0.40
TAIL_OFF_DISCOUNT = 0.50
MAX_TAIL_OFF_DAYS = 365

# ----------------------------------------------------------------------
# Committee
# ----------------------------------------------------------------------

MIN_ELIGIBLE_VOTER_COUNT = 3
QUORUM_PCT = 0.60
NEGOTIATION_ROUND_CAP = 3
REVISION_ROUND_CAP = 3

# ----------------------------------------------------------------------
# Performance tracking
# ----------------------------------------------------------------------

PLAN_TARGET_DAYS_IN_YEAR = 365
PERFORMANCE_ON_PLAN_THRESHOLD = 0.90
PERFORMANCE_WATCH_THRESHOLD = 0.70

# ----------------------------------------------------------------------
# Input range bounds
# ----------------------------------------------------------------------

MAX_NOTICE_PERIOD_DAYS = 365
MAX_NON_SOLICIT_DAYS = 730
MAX_CROSS_SELL_TARGET_COUNT = 50
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ----------------------------------------------------------------------
# Probe identifiers
# ----------------------------------------------------------------------

PROBE_UUID = "00000000-0000-4000-8000-000000000000"

# ----------------------------------------------------------------------
# Canonical fixture book variants — pre-computed expected values
# ----------------------------------------------------------------------

# SLIM BOOK: entry A only (Northwind Holdings).
EXPECTED_SLIM_BOOK = {
    "entry_a_baseline": 1269000.00,
    "gross_baseline_total_usd": 1269000.00,
    "validated_portable_total_usd": 1269000.00,
    "declined_portable_total_usd": 0.00,
    "self_reported_total_usd": 1280000.00,
    "variance_pct": 0.0086,
    "top_client_share": 1.0000,
    "top3_client_share": 1.0000,
    "concentration_grade": "HIGH",
    "concentration_haircut_pct": 0.15,
    "adjusted_portable_total_usd": 1078650.00,
    "entry_count_in_scope": 1,
}

# AB BOOK: entries A and B (Northwind Holdings, Calder Manufacturing).
EXPECTED_AB_BOOK = {
    "entry_a_baseline": 1269000.00,
    "entry_b_baseline": 332112.15,
    "gross_baseline_total_usd": 1601112.15,
    "validated_portable_total_usd": 1601112.15,
    "declined_portable_total_usd": 0.00,
    "self_reported_total_usd": 1910000.00,
    "variance_pct": 0.1617,
    "top_client_share": 0.7926,
    "concentration_grade": "HIGH",
    "concentration_haircut_pct": 0.15,
    "adjusted_portable_total_usd": 1360945.33,
    "entry_count_in_scope": 2,
}

# FULL BOOK: entries A, B and C (adds Ridgeline Foods).
EXPECTED_FULL_BOOK = {
    "entry_a_baseline": 1269000.00,
    "entry_b_baseline": 332112.15,
    "entry_c_baseline": 219450.00,
    "gross_baseline_total_usd": 1820562.15,
    "validated_portable_total_usd": 1820562.15,
    "declined_portable_total_usd": 0.00,
    "self_reported_total_usd": 2320000.00,
    "variance_pct": 0.2153,
    "top_client_share": 0.6970,
    "concentration_grade": "HIGH",
    "concentration_haircut_pct": 0.15,
    "adjusted_portable_total_usd": 1547477.83,
    "self_reported_adjusted_portable_total_usd": 1972000.00,
    "entry_count_in_scope": 3,
}

# Offer economics against the SLIM BOOK snapshot 1078650.00 with
# guaranteed_comp_usd 500000.00 and signing_bonus_usd 50000.00.
EXPECTED_SLIM_OFFER = {
    "adjusted_portable_total_snapshot_usd": 1078650.00,
    "expected_contribution_usd": 1053981.27,
    "total_first_year_comp_usd": 550000.00,
    "search_fee_amount_usd": 137500.00,
    "integration_cost_total_usd": 244500.00,
    "net_first_year_economics_usd": 259481.27,
    "guarantee_true_up_amount_usd": 25000.00,
}

# Offer economics against the FULL/AB snapshot with guaranteed_comp_usd
# 850000.00 and signing_bonus_usd 100000.00.
EXPECTED_LARGE_OFFER = {
    "expected_contribution_usd": 1512087.01,
    "total_first_year_comp_usd": 950000.00,
    "search_fee_amount_usd": 237500.00,
    "integration_cost_total_usd": 360500.00,
    "net_first_year_economics_usd": 201587.01,
    "guarantee_true_up_amount_usd": 42500.00,
}

# Declination waterfall for entry B (baseline 332112.15, two matter types
# [LITIGATION, EMPLOYMENT]); the first array element absorbs the remainder.
EXPECTED_ENTRY_B_DECLINATION = {
    "LITIGATION": 166056.08,
    "EMPLOYMENT": 166056.07,
}
