"""Domain thresholds — numeric constants from PRD calculations (§3.2, §3.5, §3.8, §3.9)."""

# Check-cash hold thresholds (PRD §3.5)
HOLD_THRESHOLD_CENTS = 300000      # face >= this -> RISK_HELD (hold_reason AMOUNT_THRESHOLD)
VELOCITY_HOLD_COUNT = 8            # daily_transaction_count >= this at posting -> VELOCITY hold

# Non-check-cash service-fee constants (PRD §3.2)
MO_FLAT_CENTS = 99
MO_BPS = 50
MO_MAX_CENTS = 500
WIRE_FLAT_CENTS = 1500
WIRE_BPS = 100
BILLPAY_FLAT_CENTS = 195
PREPAID_FLAT_CENTS = 395
PREPAID_BPS = 30

# Risk-score deltas (PRD §3.8)
HIGH_MAKER_PTS = 120
AMOUNT_HOLD_PTS = 60
VELOCITY_HOLD_PTS = 90
RETURN_RISK_DELTA = 250
WRITE_OFF_RISK_DELTA = 200

# Risk-tier per-transaction ceilings (PRD §3.8)
STANDARD_CEILING_CENTS = 500000
ELEVATED_CEILING_CENTS = 200000
HIGH_CEILING_CENTS = 50000

# Risk-tier score boundaries (PRD §3.8)
ELEVATED_SCORE_MIN = 350
HIGH_SCORE_MIN = 700

# Rolling velocity window (PRD §3.8)
DAILY_TXN_LIMIT = 12
DAILY_CASH_LIMIT_CENTS = 1000000

# Recovery (PRD §3.9)
RETURN_FEE_CENTS = 2500

# Embargoed wire destinations (PRD §3.6)
EMBARGOED_COUNTRIES = ["CU", "IR", "KP", "SY"]

# Clock startup default (PRD §3.8)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
