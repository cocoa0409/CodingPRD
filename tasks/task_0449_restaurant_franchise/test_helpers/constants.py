"""Domain thresholds — numeric constants from the PRD calculation and pricing rules.

These mirror the literal figures stated in PRD §2.6, §3.1, §3.7, and §3.9. Generic
NON_EXISTENT_UUID comes from the framework (re-exported from the barrel __init__).
"""

# Brand default economic parameters (§3.1)
DEFAULT_ROYALTY_TIER_1_RATE = 0.06
DEFAULT_ROYALTY_TIER_2_RATE = 0.05
DEFAULT_ROYALTY_TIER_3_RATE = 0.04
DEFAULT_AD_FUND_RATE = 0.02
DEFAULT_LATE_FEE_MONTHLY_RATE = 0.015

# Royalty marginal-tier ceilings, in cents (§3.9)
TIER1_CEILING_CENTS = 5_000_000   # first $50,000
TIER2_CEILING_CENTS = 10_000_000  # up to $100,000

# Audit weighted-scoring weights and bands (§3.7)
W_FOOD = 0.40
W_CLEAN = 0.25
W_SERVICE = 0.20
W_BRAND = 0.15
CRITICAL_FOOD_SAFETY_FLOOR = 70    # food_safety_score < 70 → critical-fail cap
CRITICAL_FAIL_CAP = 59.0
PASS_FLOOR = 90.0                  # overall_score >= 90.0 → PASS
CONDITIONAL_FLOOR = 70.0           # 70.0 <= overall_score < 90.0 → CONDITIONAL

# Transfer-fee constants, in cents (§3.9)
TRANSFER_FLAT_MIN_CENTS = 1_000_000   # $10,000 floor
TRANSFER_TRAINING_FEE_CENTS = 500_000  # $5,000 added for a brand-new operator
DEFAULT_TRANSFER_FEE_RATE = 0.02

# National-account rebate defaults (§3.9)
DEFAULT_MIN_QUALIFYING_CENTS = 1_000_000

# Brand logical-clock default (§2.5, §3.1)
DEFAULT_CURRENT_UTC = "2026-01-01T00:00:00Z"

# Compliance-strike default threshold (§3.5) — a franchisee defaults when
# open_compliance_strikes reaches this count.
STRIKE_DEFAULT_THRESHOLD = 2
