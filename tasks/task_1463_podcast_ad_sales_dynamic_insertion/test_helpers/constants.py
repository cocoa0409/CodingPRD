"""Domain thresholds and shared instants — numeric constants from PRD §2 and §3."""

# Logical clock (PRD §2.4)
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Inventory forecast (PRD §3.1)
FORECAST_HORIZON_DAYS = 30
CAP_CLEAR = 0.95
CAP_FLAGGED = 0.70
CAP_SUSPENDED = 0.00

# Position multipliers, per mille of base CPM (PRD §2.6 / §3.7)
POSITION_MULT_PER_MILLE = {
    "PRE_ROLL": 800,
    "MID_ROLL": 1000,
    "POST_ROLL": 600,
}

# Attribution window (PRD §3.6)
ATTRIBUTION_WINDOW_DAYS = 30

# Episode defaults (PRD §3.1)
DEFAULT_MEASUREMENT_WINDOW_DAYS = 30
DEFAULT_SLOT_CAPACITY = 2

# Shared instants used across scenarios
FLIGHT_START = "2026-08-01T00:00:00Z"
FLIGHT_END = "2026-09-01T00:00:00Z"
DELIVERY_INSTANT = "2026-08-05T00:00:00Z"
POST_WINDOW_CLOCK = "2026-09-01T00:00:01Z"

TEST_DEFAULTS = {
    "AVG_DOWNLOADS_30D": 10000,
    "BOOKED_IMPRESSIONS": 1000,
    "CPM_CENTS": 1000,
    "RESERVED_IMPRESSIONS": 100,
    "PRIORITY": 10,
    "COMMISSION_BPS": 1500,
}
