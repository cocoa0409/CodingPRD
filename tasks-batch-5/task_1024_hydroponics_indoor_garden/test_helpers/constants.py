"""Domain thresholds and rate tables — numeric constants from the PRD calculations."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

# A non-existent-but-well-formed UUID for 404 tests (alias of the framework constant).
MISSING_UUID = NON_EXISTENT_UUID

# --- Pricing / order_net_total (PRD Section 3.4) ---
VOLUME_THRESHOLD_CENTS = 500_000
VOLUME_BONUS_RATE = 0.05
MAX_DISCOUNT_RATE = 0.12
HAZMAT_BASE_CENTS = 1_500
HAZMAT_PER_KG_CENTS = 200
HAZMAT_CAP_CENTS = 5_000

DISCOUNT_BASE_RATES = {
    "STANDARD": 0.00,
    "SILVER": 0.05,
    "GOLD": 0.10,
}

# --- Loyalty (PRD Sections 3.2 / 3.5) ---
POINTS_DIVISOR_CENTS = 100
LOYALTY_MULTIPLIERS = {
    "BRONZE": 1.0,
    "SILVER": 1.25,
    "GOLD": 1.5,
}
LOYALTY_SILVER_THRESHOLD = 1_000
LOYALTY_GOLD_THRESHOLD = 5_000

# --- RMA refund (PRD Section 3.9) ---
RESTOCK_FEE_RATE = 0.15
WARRANTY_DAYS_PER_MONTH = 30

# --- Consultant / room scheduling (PRD Sections 3.7 / 3.8) ---
DEFAULT_BUFFER_MINUTES = 30
DEFAULT_SEAT_CAPACITY = 20

# --- Logical clock (PRD Section 2.6) ---
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"
