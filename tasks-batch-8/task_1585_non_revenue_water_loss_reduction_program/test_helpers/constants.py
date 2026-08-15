"""Domain thresholds — numeric constants stated in the PRD's rules (§3)."""

# Logical clock
CLOCK_INITIAL = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Water balance audited-variant confidence adjustment (PRD §3.2)
    "AUDIT_CONFIDENCE_CREDIT_PCT": 0.50,
    "AUDIT_CREDIT_CAP_FRACTION": 0.10,
    # ILI baseline constants (PRD §3.2)
    "UARL_PER_CONNECTION": 18,
    "UARL_PER_MAINS_KM": 0.8,
    "UARL_PRESSURE_TERM": 25,
    "AVG_PRESSURE_M": 40,
    "ILI_FLOOR": 0.01,
    # Night-flow signal thresholds, inclusive (PRD §3.3)
    "MNF_ELEVATED_LPS": 5.0,
    "MNF_CRITICAL_LPS": 15.0,
    "MNF_ELEVATED_PCT": 8.0,
    "MNF_CRITICAL_PCT": 20.0,
    "MIN_WINDOW_HOURS": 2,
    "MAX_WINDOW_HOURS": 6,
    "WINDOW_BUFFER_HOURS": 1,
    # Leak repair priority (PRD §3.4)
    "WATER_VALUE_PER_M3": 1.20,
    "COST_EPSILON": 1.0,
    "SCORE_SCALE": 2.0,
    "PRESSURE_PROJECT_MULTIPLIER": 1.25,
    "REOPEN_MULTIPLIER": 1.10,
    "P1_THRESHOLD": 50.0,
    "P2_THRESHOLD": 20.0,
    # Meter replacement policy (PRD §3.5)
    "AGE_LIMIT_YEARS": 15,
    "ACCURACY_PASS_THRESHOLD": 98.0,
    "ACCURACY_OVER_CEILING": 102.0,
    # Pressure leak reduction (PRD §3.7)
    "FAVAD_N1": 1.15,
    # Intervention benefit-cost (PRD §3.8)
    "TIER_LOW_MAX": 50000,
    "TIER_MID_MAX": 200000,
    "VALUE_LOW": 1.10,
    "VALUE_MID": 1.30,
    "VALUE_HIGH": 1.55,
    "ANALYSIS_HORIZON_YEARS": 20,
    "R_PROVISIONAL": 0.07,
    "R_BANKABLE": 0.04,
    "COST_FLOOR": 1.0,
    "BCR_APPROVAL_THRESHOLD": 1.00,
}

# Pinned expected values for the standard fixture balance (90-day window
# 2026-01-01..2026-04-01, SIV 1e6, billed 720k, unbilled 40k, unauth 15k,
# metering inaccuracy 25k, on a 5000-connection / 120-km DMA).
PINNED_BALANCE = {
    "NRW_VOLUME_M3": 280000,
    "APPARENT_LOSS_M3": 40000,
    "REAL_LOSS_M3": 200000,
    "NRW_PCT_PROVISIONAL": 28.0,
    "NRW_PCT_AUDITED": 27.5,
    "ILI": 24.39,
}

# Pinned expected leak-score values for a 2.0 lps / 8000-cost leak.
PINNED_LEAK = {
    "ANNUALIZED_LOSS_M3": 63072.0,
    "SCORE_NO_PROJECT": 18.92,
    "SCORE_WITH_PROJECT": 23.65,
    "SCORE_REOPENED_WITH_PROJECT": 26.02,
}

TEST_DEFAULTS = {
    "PROGRAM_DIRECTOR": "pd-1",
    "UTILITY_ANALYST": "ua-1",
    "UTILITY_ANALYST_ALT": "ua-2",
    "FIELD_SUPERVISOR": "fs-1",
    "FIELD_SUPERVISOR_ALT": "fs-2",
    "METER_TECHNICIAN": "mt-1",
    "INVESTIGATOR": "inv-1",
    "REGULATOR_LIAISON": "rl-1",
}
