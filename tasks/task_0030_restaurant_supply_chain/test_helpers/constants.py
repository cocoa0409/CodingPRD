"""Domain thresholds — numeric constants from PRD prose.

All literals correspond to numeric thresholds, defaults, or magic constants
named in PRD §2 / §3 prose. The reference implementation is expected to use
these same literal values.
"""

# Pagination — PRD §2.3
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Order quantity range — PRD §3.2 ("at least 1 and at most 10,000")
MIN_ORDER_UNITS = 1
MAX_ORDER_UNITS = 10000

# Cutoff default — PRD §3.1 ("cutoff_minutes_before_close (default 60)")
DEFAULT_CUTOFF_MINUTES_BEFORE_CLOSE = 60

# Low-amount auto-submit threshold default — PRD §3.1
# ("Submission of replenishment orders below low_amount_bypass_cents
#  (default 50000) auto-approve without manager intervention.")
DEFAULT_LOW_AMOUNT_BYPASS_CENTS = 50000

# Equipment-class capacity — PRD §3.3
# ("Equipment-class capacity per day is 8 hours (480 minutes) per equipment_class")
EQUIPMENT_MINUTES_PER_CLASS_PER_DAY = 480

# Provisional cost — PRD §3.7 ("a fixed batch setup fee of 100 cents")
BATCH_SETUP_FEE_CENTS = 100

# Final cost allocation — PRD §3.7
# ("Indirect overhead is 15% of the direct production cost")
INDIRECT_OVERHEAD_PCT = 0.15
# ("a transfer overhead rate of 0.10")
TRANSFER_OVERHEAD_RATE = 0.10

# Forecast horizon — PRD §3.3 ("a forecast horizon of one day")
FORECAST_HORIZON_DAYS = 1

# Near-expiry alert tier thresholds — PRD §3.5
# ("if the distance is at most 24 hours, alert_tier becomes TIER1")
# ("if the distance is at most 8 hours, alert_tier becomes TIER2")
# ("If that distance is at most zero hours, alert_tier becomes TIER3")
TIER1_HOURS = 24
TIER2_HOURS = 8

# Replenishment minimum — PRD §3.5 ("a minimum replenishment of 1 unit")
MIN_REPLENISHMENT_UNITS = 1

# Abnormal-loss detection — PRD §3.6
# ("over a rolling window of 168 hours (one week)")
LOSS_WINDOW_HOURS = 168
# ("strictly greater than 0.05 (5%) — the comparison is strict")
ABNORMAL_LOSS_THRESHOLD = 0.05


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "MIN_ORDER_UNITS",
    "MAX_ORDER_UNITS",
    "DEFAULT_CUTOFF_MINUTES_BEFORE_CLOSE",
    "DEFAULT_LOW_AMOUNT_BYPASS_CENTS",
    "EQUIPMENT_MINUTES_PER_CLASS_PER_DAY",
    "BATCH_SETUP_FEE_CENTS",
    "INDIRECT_OVERHEAD_PCT",
    "TRANSFER_OVERHEAD_RATE",
    "FORECAST_HORIZON_DAYS",
    "TIER1_HOURS",
    "TIER2_HOURS",
    "MIN_REPLENISHMENT_UNITS",
    "LOSS_WINDOW_HOURS",
    "ABNORMAL_LOSS_THRESHOLD",
]
