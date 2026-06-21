"""Domain thresholds — numeric constants from the PRD pricing and settlement narratives."""

# Shipping tiers (PRD §3.2): discounted_subtotal < 5000 → 999; [5000, 10000) → 499; >= 10000 → 0.
FREE_SHIP_LOW = 5000
FREE_SHIP_HIGH = 10000
SHIP_STANDARD = 999
SHIP_REDUCED = 499
SHIP_FREE = 0

# Store-credit bonus (PRD §3.8): base refund * 10500 / 10000 (5% bonus) on STORE_CREDIT.
STORE_CREDIT_BONUS_BPS = 500

# Return-risk high-risk threshold (PRD §3.9): score >= 0.5 → high-risk.
HIGH_RISK_THRESHOLD = 0.5
