"""Domain thresholds — numeric constants from the PRD §3 calculation narratives."""

# PRD §2.5: logical clock startup default before any set call.
LOGICAL_CLOCK_START = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD §3.4 / §3.6: leak annualization kilowatt load per CFM.
    "KW_PER_CFM": 0.20,
    # PRD §3.6: sequencing component percentage parameters.
    "SEQ_BASE_PCT": 0.07,
    "PRESSURE_SAVINGS_PCT_PER_PSI": 0.005,
    "PRESSURE_REDUCTION_CAP_PSI": 20,
    # PRD §3.6: utility rebate tiers and caps.
    "REBATE_TIER1_KWH": 100000,
    "REBATE_TIER1_RATE_CENTS": 7,
    "REBATE_TIER2_RATE_CENTS": 3,
    "REBATE_COST_CAP_PCT": 0.50,
    "REBATE_PROGRAM_CAP_CENTS": 20_000_000,
    # PRD §3.7: SLA base hours per contract tier.
    "SLA_BASE_HOURS": {"BASIC": 48, "STANDARD": 24, "PREMIUM": 8},
    # PRD §3.7: severity multipliers applied to the tier base hours.
    "SEVERITY_MULTIPLIER": {"EMERGENCY": 1, "URGENT": 2, "ROUTINE": 4},
    # PRD §3.7: SLA credit parameters.
    "SLA_CREDIT_PCT": 0.05,
    "SLA_BREACH_SUSPEND_THRESHOLD": 3,
    "CREDIT_TTL_DAYS": 90,
    # PRD §3.8: rental billing actual-variant parameters.
    "MIN_BILL_DAYS": 3,
    "LONG_TERM_DAY": 28,
    "LONG_TERM_RATE_FACTOR": 0.85,
    # PRD §3.9: guarantee settlement parameters.
    "DEADBAND_PCT": 0.02,
    "PAYOUT_CAP_MONTHS": 12,
}

TEST_DEFAULTS = {
    "UTILITY_RATE_CENTS_PER_KWH": 12,
    "OPERATING_HOURS_PER_YEAR": 6000,
    "REPAIR_BUDGET_CENTS": 5_000_000,
    "MONTHLY_FEE_CENTS": 400000,
    "DAILY_RATE_CENTS": 35000,
    "DEPOSIT_CENTS": 100000,
}
