"""Domain thresholds — numeric constants from the PRD's eligibility calculations.

Generic NON_EXISTENT_UUID comes from the framework. The literal reference data
below matches the canonical fixtures the test scenarios build (CA expansion / TX
non-expansion state rules and the 2026 FPL schedule).
"""

# Calculation constants (PRD §2.7 / §3.4 / §3.6).
FPL_DISREGARD_PCT = 0.05
MONTHS_PER_YEAR = 12
ADULT_AGE_FLOOR = 19
EXEMPT_BURIAL_CAP_CENTS = 150000

# 2026 FPL schedule reference data used by the test scenarios.
FPL_YEAR = 2026
FPL_BASE_ANNUAL_CENTS = 1500000          # 100% FPL annual income, household of one
FPL_PER_MEMBER_INCREMENT_CENTS = 520000  # added per additional member

# Precomputed FPL bases for common household sizes (base + (size-1)*increment).
FPL_BASE_SIZE_1 = 1500000
FPL_BASE_SIZE_2 = 2020000
FPL_BASE_SIZE_3 = 2540000

# Canonical state-rule reference data.
STATE_RULE_CA = {
    "state_code": "CA",
    "is_expansion_state": True,
    "magi_adult_threshold_pct": 138,
    "magi_child_threshold_pct": 200,
    "abd_asset_limit_cents": 200000,
    "standard_asset_limit_cents": 300000,
}

STATE_RULE_TX = {
    "state_code": "TX",
    "is_expansion_state": False,
    "magi_adult_threshold_pct": 100,
    "magi_child_threshold_pct": 200,
    "abd_asset_limit_cents": 200000,
    "standard_asset_limit_cents": 300000,
}

# A non-resolving but well-formed UUID for not-found / segregation fixtures.
SAMPLE_MISSING_UUID = "00000000-0000-4000-8000-000000000000"
