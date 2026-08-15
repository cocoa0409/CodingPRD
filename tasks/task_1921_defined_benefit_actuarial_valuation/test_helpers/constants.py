"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # benefit_restriction_posture tiers (percent)
    "TIER_FULL": 80.00,
    "TIER_PARTIAL": 60.00,
    # presumed AFTAP reduction (percentage points)
    "PRESUMED_REDUCTION_PP": 10.00,
    # asset smoothing corridor
    "EXPECTED_RETURN_RATE": 0.05,
    "CORRIDOR_LOW": 0.80,
    "CORRIDOR_HIGH": 1.20,
    # minimum required contribution amortization
    "AMORTIZATION_YEARS": 7,
    # maximum deductible cushion
    "CUSHION_FACTOR": 1.5,
    # PBGC premium
    "FLAT_RATE_PER_PARTICIPANT": 100,
    "VARIABLE_RATE_PER_1000": 50,
    "PER_PARTICIPANT_CAP": 600,
    "ALTERNATIVE_TARGET_FACTOR": 1.05,
    # excise tax
    "EXCISE_RATE": 0.10,
    # election revocation window (days)
    "REVOKE_WINDOW_DAYS": 21,
}

# Mortality table TEST_TABLE_4AGE pinned decrement rates
MORTALITY = {
    "Q60": 0.20,
    "Q61": 0.25,
    "Q62": 0.50,
    "Q63": 1.00,
    "OMEGA_AGE": 63,
    "FACTOR_DECIMALS": 4,
}

TEST_DEFAULTS = {
    "PLAN_YEAR": 2028,
    "ACCRUAL_RATE": 0.01,
    "NORMAL_RETIREMENT_AGE": 62,
    "PRIOR_AFTAP_PCT": 90.00,
    "FUNDING_DISCOUNT_RATE": 0.05,
    "DISCLOSURE_DISCOUNT_RATE": 0.04,
    "MORTALITY_TABLE": "TEST_TABLE_4AGE",
}

# Logical clock anchors
CLOCK = {
    "STARTUP_DEFAULT": "2026-08-01T00:00:00Z",
    "APRIL_FIRST_2028": "2028-04-01T00:00:00Z",
    "OCTOBER_FIRST_2028": "2028-10-01T00:00:00Z",
    "DUE_DATE_2028": "2028-09-15T00:00:00Z",
    "FILING_DEADLINE_2028": "2028-10-15T00:00:00Z",
}
