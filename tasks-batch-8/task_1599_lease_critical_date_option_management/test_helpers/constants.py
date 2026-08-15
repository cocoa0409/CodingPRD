"""Domain thresholds and test defaults — numeric constants from the PRD."""

# Holdover accrual
DAYS_PER_YEAR_DIVISOR = 365

# Negotiation timeline compliance
LEAD_DAYS_REQUIRED = 270

# Assessment dispute window
DISPUTE_WINDOW_DAYS = 15

# Arbitration submission window
ARBITRATION_SUBMISSION_DAYS = 30

# Reminder cascade tiers (days before notice_window_close_date)
TIER_OFFSETS_DAYS = [90, 60, 30, 7, 0]

# Reminder fire time (UTC)
REMINDER_FIRE_TIME = "09:00:00"

# Expiring-threshold: a lease enters EXPIRING when clock >= expiration - 180 days
EXPIRING_LOOKAHEAD_DAYS = 180

TEST_DEFAULTS = {
    "RSF": 5000,
    "BASE_RENT_CENTS_PER_RSF_YEAR": 4000,
    "HOLDOVER_TIER1_PCT": 150,
    "HOLDOVER_TIER2_PCT": 200,
    "HOLDOVER_TIER1_DAYS": 90,
    "LADDER_MAX_PCT": 40,
    "EXERCISE_FEE_CENTS": 0,
    "MISSED_OPTION_PENALTY_CENTS": 0,
}
