"""Domain thresholds — numeric constants named in PRD §2.6, §3.2, §3.3, §3.4, §3.8."""

# Money / labor billing (PRD §3.2, §3.4)
SHOP_RATE_CENTS_PER_HOUR = 14500
REGULAR_HOUR_CAP = 8.0
OVERTIME_MULTIPLIER = 1.5
TASK_KIND_MULTIPLIER = {
    "HARNESS_FABRICATION": 1.0,
    "PANEL_ASSEMBLY": 1.1,
    "INSTALLATION": 1.25,
}

# Quote discount tiers keyed by customer_kind (PRD §3.2)
DISCOUNT_RATE = {
    "FLEET_OPERATOR": 0.10,
    "FLIGHT_SCHOOL": 0.05,
    "INDIVIDUAL": 0.00,
}

# Change-order budget (PRD §3.3): 110% of the approved design's equipment
# subtotal, or a floor of 250,000 cents, whichever is greater.
CHANGE_ORDER_CAP_RATIO = 1.10
CHANGE_ORDER_FLOOR_CENTS = 250000

# Completion overage acknowledgement threshold in whole days (PRD §3.8)
OVERAGE_ACK_THRESHOLD_DAYS = 5

# Flight-test separation buffer in minutes (PRD §2.6)
FLIGHT_BUFFER_MINUTES = 60

# Test-attempt ceiling: initial run plus two reschedules (PRD §3.5)
MAX_TEST_ATTEMPTS = 3

# Logical clock (PRD §2.5): startup default and the pinned instant most
# fixtures park the clock at for deterministic derived timestamps.
STARTUP_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK = "2026-08-01T09:00:00Z"

# Default aircraft datum shared by most scenarios (PRD §3.1 baseline fields)
DEFAULT_BASELINE_WEIGHT_LB = 1800.0
DEFAULT_BASELINE_ARM_IN = 40.0
DEFAULT_BASELINE_MOMENT_LB_IN = 72000.0
DEFAULT_CG_MIN_IN = 35.0
DEFAULT_CG_MAX_IN = 41.5

TEST_DEFAULTS = {
    "QUOTED_LABOR_HOURS": 5,
    "ESTIMATED_DOWNTIME_DAYS": 10,
    "WARRANTY_TERM_MONTHS": 12,
    "SUBSCRIPTION_MONTHS": 12,
}
