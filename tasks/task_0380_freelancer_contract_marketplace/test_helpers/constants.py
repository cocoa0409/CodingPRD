"""Domain thresholds — numeric constants drawn from the PRD's calculations (§3)."""

# Platform fee tiering (PRD §3.6)
PLATFORM_FEE = {
    "TIER_A_CEIL": 5_000_000,     # < 5,000,000 cents -> TIER_A (20%)
    "TIER_B_CEIL": 100_000_000,   # < 100,000,000 cents -> TIER_B (10%); else TIER_C (5%)
    "TIER_A_RATE": 0.20,
    "TIER_B_RATE": 0.10,
    "TIER_C_RATE": 0.05,
    "RISK_LOSS_THRESHOLD": 3,     # dispute_loss_count >= 3 adds surcharge
    "RISK_SURCHARGE": 0.05,
    "MAX_RATE": 0.25,
    "MIN_FEE_CENTS": 100,
}

# Hourly milestone cap (PRD §3.4)
MINUTES_PER_HOUR = 60

# Daily hours overlap / aggregate cap (PRD §3.4)
GLOBAL_DAILY_MINUTE_CAP = 720      # 12 hours

# Reputation score (PRD §3.1)
REPUTATION = {
    "COMPLETION_WEIGHT": 0.6,
    "RATING_WEIGHT": 0.4,
    "LOSS_PENALTY": 4,
    "MAX_PENALTY": 40,
}

# 1099 reporting (PRD §3.9)
REPORTING_THRESHOLD_CENTS = 60_000   # $600.00

# Proposal negotiation (PRD §3.2)
MAX_COUNTER_ROUNDS = 5

# Job match score weights (PRD §3.2)
JOB_MATCH = {
    "SKILL_W": 0.5,
    "REP_W": 0.3,
    "PRICE_W": 0.2,
}

# Validation minimums (PRD §3.2, §3.3)
MIN_BUDGET_CENTS = 100
MIN_MILESTONE_AMOUNT_CENTS = 100
