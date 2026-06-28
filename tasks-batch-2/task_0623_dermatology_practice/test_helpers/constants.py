"""Domain thresholds — numeric constants from PRD calculations."""

# Charge split (PRD §3.7, §2.9)
CASH_PROMPT_PAY_DISCOUNT = 0.10  # 10% self-pay discount on the billed amount

# Membership redemption tier discounts (PRD §3.6)
TIER_DISCOUNT_SILVER = 0.05
TIER_DISCOUNT_GOLD = 0.15

# Membership activation tier bonuses (PRD §3.6)
TIER_BONUS_SILVER = 0.00
TIER_BONUS_GOLD = 0.10

# Biologic charge pricing (PRD §3.7)
STEP_DOWN_PER_ROUND = 0.05
MIN_ROUND_FACTOR = 0.80
ADMIN_UPLIFT_RATE = 0.04
ADMIN_UPLIFT_CAP_CENTS = 25000

# Biopsy recall horizon months (PRD §3.5)
BENIGN_MONTHS = 12
INDETERMINATE_MONTHS = 6
MALIGNANT_MONTHS = 3

# Routine skin-check recall horizon months (PRD §3.2)
ROUTINE_RECALL_MONTHS = 12

# Default patient billing attributes (PRD §3.2)
DEFAULT_COINSURANCE_RATE = 0.2

# Logical clock startup default (PRD §2.4)
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"
