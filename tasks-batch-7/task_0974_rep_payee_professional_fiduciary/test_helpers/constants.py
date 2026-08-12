"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Fiduciary fee tiers (PRD §3.6)
    "FEE_TIER1_LIMIT": 100000,
    "FEE_TIER2_LIMIT": 300000,
    "FEE_TIER2_SPAN": 200000,
    "FEE_MONTHLY_CAP": 20000,
    # Medicaid default countable-resource ceiling (PRD §3.1)
    "MEDICAID_DEFAULT_LIMIT": 200000,
    # Conservator SHARED-scope co-approval threshold (PRD §3.5)
    "SHARED_CO_APPROVAL_THRESHOLD": 50000,
    # Report statutory due window in days (PRD §3.8)
    "REPORT_DUE_DAYS": 30,
}

TEST_DEFAULTS = {
    "BOND_COVERAGE": 5000000,
    "SOURCE_BENEFIT": 100000,
    "MONTHLY_BENEFIT": 80000,
}

CLOCK_START = "2026-05-01T00:00:00Z"
