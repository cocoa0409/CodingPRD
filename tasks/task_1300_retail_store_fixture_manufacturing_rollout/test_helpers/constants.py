"""Domain thresholds and rates — numeric constants stated in the PRD."""

# PRD section 3.3: six percent handling uplift on kit configuration lines.
HANDLING_PCT = 0.06

# PRD section 3.4: release surcharge pricing inputs.
BASE_RATE_CENTS = 150
RUSH_MULTIPLIER = 1.25
TIER_MULTIPLIER_LOW = 1.0        # utilization after release below 70%
TIER_MULTIPLIER_MID = 1.15       # 70% <= utilization after release < 90%
TIER_MULTIPLIER_HIGH = 1.35      # utilization after release >= 90%

# PRD section 3.4: posture flips at exactly 90.0 percent (inclusive).
AT_RISK_THRESHOLD_PCT = 90.0

# PRD section 3.5: standard crew day.
DAILY_CAPACITY_HOURS = 8

# PRD section 3.7/3.8: attic stock seeding and disposition.
ATTIC_STOCK_PCT = 0.05
REORDER_POINT_DEFAULT = 2
LIQUIDATION_UNIT_CENTS = 2500
RECOVERY_RATES = {
    "RETURN_VENDOR": 0.80,
    "SCRAP": 0.05,
    "DONATE": 0.00,
}

# PRD section 2.8: logical clock startup value.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
