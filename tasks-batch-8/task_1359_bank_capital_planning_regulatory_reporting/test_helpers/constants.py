"""Domain thresholds — numeric constants from the PRD's computation rules."""

THRESHOLDS = {
    # Basis-point denominator (PRD §2.6: 10000 bps = 100 percent)
    "BPS_DENOMINATOR": 10000,
    # Advanced-approaches multiplier 1.06 (PRD §3.2)
    "ADVANCED_MULTIPLIER_BPS": 10600,
    # Capital-stack caps (PRD §3.3): AT1 capped at 1.5% of RWA; T2 at 2% of RWA
    "AT1_CAP_BPS_OF_RWA": 150,
    "T2_CAP_BPS_OF_RWA": 200,
    # PCA bucket floors in bps, inclusive lower bound (PRD §2.7)
    "PCA_WELL_CET1_BPS": 650,
    "PCA_ADEQUATE_CET1_BPS": 450,
    "PCA_UNDER_CET1_BPS": 400,
    "PCA_SIGNIFICANT_CET1_BPS": 300,
    "PCA_WELL_TIER1_BPS": 800,
    "PCA_ADEQUATE_TIER1_BPS": 600,
    "PCA_UNDER_TIER1_BPS": 500,
    "PCA_SIGNIFICANT_TIER1_BPS": 400,
    "PCA_WELL_TOTAL_BPS": 1000,
    "PCA_ADEQUATE_TOTAL_BPS": 800,
    "PCA_UNDER_TOTAL_BPS": 700,
    "PCA_SIGNIFICANT_TOTAL_BPS": 600,
    "PCA_WELL_LEVERAGE_BPS": 500,
    "PCA_ADEQUATE_LEVERAGE_BPS": 400,
    "PCA_UNDER_LEVERAGE_BPS": 350,
    "PCA_SIGNIFICANT_LEVERAGE_BPS": 300,
    # Stress projection constants (PRD §3.5)
    "TAX_RATE_BPS": 2100,
    "STRESS_RWA_GROWTH_BPS_PER_QUARTER": 50,
    "SCB_FLOOR_BPS": 250,
    # Filing calendar (PRD §3.2)
    "FILING_LAG_Q1_Q2_Q3_DAYS": 35,
    "FILING_LAG_Q4_DAYS": 40,
    # Distribution payment window (PRD §3.6)
    "DISTRIBUTION_WINDOW_DAYS": 10,
    # Stress scenario activation cap (PRD §3.5)
    "MAX_ACTIVE_SCENARIOS": 2,
    # Sub-debt T2 eligibility term (PRD §3.7)
    "MIN_T2_MATURITY_YEARS": 5,
}

TEST_DEFAULTS = {
    "RWA_CENTS": 100_000_000_000,
    "CET1_CENTS": 10_000_000_000,
    "PAYMENT_DATE": "2027-03-15",
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
}
