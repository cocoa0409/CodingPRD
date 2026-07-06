"""Domain thresholds — numeric constants from PRD calculations."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Order line pricing (PRD 3.5)
SIZE_MULT = {"SMALL": 1.0, "MEDIUM": 1.25, "LARGE": 1.5}

# Order totals (PRD 3.5)
FEE_WAIVE_SUBTOTAL_CENTS = 2000
SMALL_ORDER_FEE_CENTS = 50
CENTS_PER_POINT = 5
TIER_DISCOUNT_RATE = {"BRONZE": 0.0, "SILVER": 0.05, "GOLD": 0.10}

# Loyalty points (PRD 3.7)
EARN_DIVISOR_CENTS = 100

# Loyalty tier thresholds (PRD 3.4)
SILVER_MIN = 500
GOLD_MIN = 1000

# Equipment calibration (PRD 2.10 / 3.6)
CALIBRATION_SHOT_LIMIT = 4
DRIFT_PER_SHOT_PCT = 0.1

# Catering quote (PRD 3.9)
PER_HEAD_CENTS = 1500
DEPOSIT_RATE = 0.25
