"""Domain thresholds — numeric constants from PRD rules (§2.5, §3.2-§3.8)."""

THRESHOLDS = {
    # Logical clock (PRD §2.5)
    "DEFAULT_CLOCK_UTC": "2026-08-01T00:00:00Z",
    # Service credit (PRD §3.2)
    "MONTHS_PER_YEAR": 12,
    # Benefit estimate (PRD §3.5)
    "FAS_YEARS": 3,
    "TIER_25_MULT": 0.025,
    "TIER_20_MULT": 0.022,
    "TIER_10_MULT": 0.020,
    "BASE_MULT": 0.017,
    "OPTION_JOINT_50_NEAR": 0.95,
    "OPTION_JOINT_50_FAR": 0.90,
    "OPTION_JOINT_100_NEAR": 0.90,
    "OPTION_JOINT_100_FAR": 0.82,
    "OPTION_AGE_DIFF_MAX_NEAR": 10,
    # Service purchase pricing (PRD §3.4)
    "FLAT_RATE_PCT": 0.10,
    "FLAT_WINDOW_YEARS": 5,
    "RETIREMENT_AGE": 60,
    "AGE_FACTOR_HI": 0.35,
    "AGE_FACTOR_MID": 0.28,
    "AGE_FACTOR_LO": 0.22,
    "QUOTE_TTL_DAYS": 90,
    "INSTALLMENT_COUNT_MIN": 1,
    "INSTALLMENT_COUNT_MAX": 60,
    # Disability benefit (PRD §3.6)
    "DISABILITY_FAS_PCT": 0.60,
    "APPEAL_WINDOW_DAYS": 60,
    # Vesting / age gates (PRD §3.5, §3.6)
    "VESTING_YEARS": 5,
    # COLA (PRD §3.7)
    "COLA_MIN_MONTHS_ACTIVE": 12,
    # Survivor claims (PRD §3.8)
    "CLAIM_WINDOW_DAYS": 365,
    "SURVIVOR_PCT_JOINT_50": 0.50,
    "SURVIVOR_PCT_JOINT_100": 1.00,
}

TEST_DEFAULTS = {
    "COLA_RATE_PCT": 0.025,
    "EARNINGS_LIMIT_ANNUAL_CENTS": 3_000_000,
    # Standard six-year salary history: FY2018..FY2023 (FAS 5,500,000; 6.0 years)
    "SIX_YEAR_SALARIES": [3_500_000, 4_000_000, 4_500_000, 5_000_000,
                        5_500_000, 6_000_000],
    "SIX_YEAR_FIRST_FY": 2018,
    # Flat-window single-line salary used by installment/conservation setups
    "ODD_SALARY_CENTS": 5_000_005,
}
