"""
Domain thresholds and numeric constants taken directly from PRD §2 / §3.

Tests reference these by name to keep boundary assertions readable and
self-documenting.
"""

# ---------------------------------------------------------------------------
# Cabinet connectivity (PRD §2.5)
# ---------------------------------------------------------------------------

HEARTBEAT_TIMEOUT_SECONDS = 300

# ---------------------------------------------------------------------------
# Wallet / deposit (PRD §3.3 / §2.7)
# ---------------------------------------------------------------------------

MIN_DEPOSIT = 99.00
MAX_DEPOSIT = 99.00

# ---------------------------------------------------------------------------
# Risk control (PRD §2.7 / §3.7)
# ---------------------------------------------------------------------------

REFUND_LIMIT_30D = 5
BORROW_LIMIT_24H = 10

# ---------------------------------------------------------------------------
# Overdue / lost (PRD §3.6)
# ---------------------------------------------------------------------------

OVERDUE_THRESHOLD_HOURS = 24       # exclusive: > 24
LOST_THRESHOLD_HOURS = 168         # inclusive: >= 168
LOST_DEVICE_FEE = 99.00

# Tiered overdue penalty rates (PRD §3.6).
# Tier A covers overdue_hours 1..48 (i.e. elapsed 25..72 inclusive).
# Tier B covers overdue_hours 49..144 (i.e. elapsed 73..168 inclusive).
# After overdue_hours > 144, penalty is capped at 1200.00 CNY.
OVERDUE_TIER_A_HOURLY = 5.00
OVERDUE_TIER_B_HOURLY = 10.00
OVERDUE_TIER_A_HOURS = 48
OVERDUE_TIER_B_HOURS = 96
OVERDUE_PENALTY_CAP = 1200.00      # 48*5 + 96*10

# ---------------------------------------------------------------------------
# Borrow eligibility (PRD §3.4)
# ---------------------------------------------------------------------------

MIN_BORROW_BATTERY = 50            # device.battery_level >= 50

# ---------------------------------------------------------------------------
# Anomaly sweep (PRD §3.6)
# ---------------------------------------------------------------------------

ANOMALY_BATTERY_THRESHOLD = 5      # strict: battery_level < 5

# ---------------------------------------------------------------------------
# Operator-task priority weights (PRD §3.8)
# ---------------------------------------------------------------------------

LOW_BATTERY_THRESHOLD = 30         # strict: battery_level < 30
LOW_BATTERY_WEIGHT = 10
FAULTY_SLOT_WEIGHT = 5
OFFLINE_BONUS = 50

# ---------------------------------------------------------------------------
# Cabinet model -> total_slots (PRD §3.1)
# ---------------------------------------------------------------------------

MODEL_TOTAL_SLOTS = {
    "SLOT_8": 8,
    "SLOT_16": 16,
    "SLOT_24": 24,
}

# ---------------------------------------------------------------------------
# Default pricing-plan values used by setup helpers
# ---------------------------------------------------------------------------

DEFAULT_PRICING = {
    "BJ": {
        "city_code": "BJ",
        "hourly_rate": 3.00,
        "daily_cap": 30.00,
        "free_minutes": 5,
        "cross_city_surcharge": 10.00,
    },
    "SH": {
        "city_code": "SH",
        "hourly_rate": 4.00,
        "daily_cap": 40.00,
        "free_minutes": 5,
        "cross_city_surcharge": 10.00,
    },
}
