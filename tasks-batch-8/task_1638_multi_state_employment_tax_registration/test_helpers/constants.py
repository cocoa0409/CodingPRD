"""Domain thresholds and defaults — numeric constants from PRD calculations."""

# Logical clock default before any set (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Nexus attribution thresholds (PRD §3.3)
    "NEXUS_DAYS_THRESHOLD": 20,
    "NEXUS_WAGE_THRESHOLD_CENTS": 5_000_000,
    "LAPSE_WINDOW_DAYS": 90,
    # Deposit schedule thresholds (PRD §3.4)
    "QUARTERLY_CAP_CENTS": 250_000,
    "SEMIWEEKLY_THRESHOLD_CENTS": 5_000_000,
    "NEXT_DAY_THRESHOLD_CENTS": 1_000_000_000,
    # UI experience rate clamps (PRD §3.7)
    "RATE_FLOOR_BP": 50,
    "RATE_CEILING_BP": 900,
    # Late penalty tiers (PRD §3.8)
    "MIN_PENALTY_CENTS": 2_500,
    "TIER1_MAX_DAYS": 5,
    "TIER2_MAX_DAYS": 15,
    # Abatement (PRD §3.9)
    "ABATEMENT_WINDOW_DAYS": 60,
    "FIRST_TIME_LOOKBACK_YEARS": 3,
    # Compliance posture (PRD §2.7)
    "DELINQUENT_PENALTY_CENTS": 1_000_000,
    "DELINQUENT_LATE_DAYS": 30,
    # Notice severity thresholds (PRD §3.9)
    "SEVERITY_HIGH_PENALTY_CENTS": 500_000,
    "SEVERITY_MEDIUM_PENALTY_CENTS": 50_000,
}

TEST_DEFAULTS = {
    "LEGAL_NAME": "Acme Corp",
    "FEIN": "123456789",
    "HOME_STATE_CODE": "CA",
    "HIRE_DATE": "2026-08-01T00:00:00Z",
    "SETUP_CLOCK": "2026-08-20T00:00:00Z",
    "OR_WITHHOLDING_RATE_BP": 500,
    "PA_NEW_EMPLOYER_RATE_BP": 270,
    "PA_SOLVENCY_SURCHARGE_BP": 30,
    "PA_UI_WAGE_BASE_CENTS": 5_000_000,
}
