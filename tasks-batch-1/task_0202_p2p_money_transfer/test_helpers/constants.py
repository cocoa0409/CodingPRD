"""Domain thresholds — numeric constants from the PRD's calculations."""

# Withdrawal fee (PRD §3.9): INSTANT charges 1.75% with a 25c floor and 1500c cap.
WITHDRAWAL_FEE = {
    "INSTANT_FEE_RATE_BPS": 175,        # 1.75%
    "INSTANT_FEE_FLOOR_CENTS": 25,      # minimum 25c on any INSTANT
    "INSTANT_FEE_CAP_CENTS": 1500,      # cap 15.00 USD
}

# Risk score deltas (PRD §3.5).
RISK_SCORE = {
    "RISK_BLOCK_DELTA": 20,             # +20 to sender when a hold is BLOCKED
    "RISK_CHARGEBACK_DELTA": 35,        # +35 to recipient when a dispute is UPHELD
    "RISK_DENIED_DELTA": -10,           # -10 to opener when their dispute is DENIED (floored at 0)
}

# Risk tier bands (PRD §2.7): LOW if <30, ELEVATED if 30..69, HIGH if >=70.
RISK_TIER_BANDS = {
    "ELEVATED_MIN": 30,
    "HIGH_MIN": 70,
}

# Risk gate thresholds (PRD §3.3).
RISK_GATE = {
    "LARGE_AMOUNT_THRESHOLD_CENTS": 100000,   # >= triggers HOLD (1000.00 USD)
    "UNVERIFIED_RECIPIENT_CAP_CENTS": 5000,   # > cap to unverified recipient triggers HOLD (50.00 USD)
}

# Rolling send-limit windows (PRD §3.3).
SEND_LIMITS = {
    "DAILY_WINDOW_HOURS": 24,
    "WEEKLY_WINDOW_DAYS": 7,
    "DEFAULT_DAILY_SEND_LIMIT_CENTS": 250000,
    "DEFAULT_WEEKLY_SEND_LIMIT_CENTS": 1000000,
}

# Dispute eligibility window (PRD §3.8).
DISPUTE_WINDOW_DAYS = 60

# Recipient verification token lifetime (PRD §3.2).
VERIFICATION_TTL_HOURS = 24

TEST_DEFAULTS = {
    "SEED_CREDIT_CENTS": 500000,
}
