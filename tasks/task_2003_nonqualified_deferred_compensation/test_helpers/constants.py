"""Domain thresholds and clock constants from the PRD (§2.6, §3)."""

THRESHOLDS = {
    # Vesting (PRD §3.3)
    "THOUSAND": 1000,
    "DAYS_PER_YEAR": 365,
    "DEFAULT_VESTING_CLIFF_YEARS": 3,
    # Deferral caps (PRD §3.2)
    "MIN_DEFERRAL_BP": 1,
    "MAX_DEFERRAL_BP": 7500,
    "BP_DENOMINATOR": 10000,
    # Separation presumption tests (PRD §3.4)
    "DEFAULT_50_THRESHOLD_BP": 5000,
    "LIBERAL_20_THRESHOLD_BP": 2000,
    "MIN_SERVICE_RECORD_DAYS": 1095,
    "REOPEN_WINDOW_DAYS": 30,
    "REOPEN_HARD_CAP": 1,
    # Specified employees (PRD §3.5)
    "OFFICER_CAP_MAX": 50,
    "EFFECTIVE_DATE_MAX_LAG_DAYS": 120,
    # Six-month delay (PRD §3.5)
    "DELAY_MONTHS": 6,
    # CIC adjudication thresholds (PRD §3.7)
    "CIC_OWNERSHIP_CHANGE_BP": 5000,
    "CIC_EFFECTIVE_CONTROL_CHANGE_BP": 3500,
    "CIC_ASSET_CHANGE_BP": 4000,
    # Rabbi trust CIC escalation (PRD §3.7)
    "CIC_TARGET_BP": 12500,
    # Income inclusion (PRD §3.8)
    "UNDERPAYMENT_PLUS_PREMIUM_BP": 800,
    "EXCISE_TAX_BP": 2000,
    # Findings / failures correction (PRD §3.8, §3.9)
    "CORRECTION_WINDOW_YEARS": 2,
}

TEST_DEFAULTS = {
    "ANNUAL_COMP_CENTS": 30000000,
    "OFFICER_COMP_THRESHOLD_CENTS": 20000000,
    "FIXED_RATE_BP": 500,
    "PROCESSING_LAG_DAYS": 30,
    "DEFERRAL_PCT_BP": 5000,
}

# PRD §2.6: "At server startup the logical clock reads exactly 2026-08-01T00:00:00Z"
CLOCK_START = "2026-08-01T00:00:00Z"
