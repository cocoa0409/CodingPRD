"""Domain thresholds and rate tables — numeric constants from the PRD."""

# Canonical season windows used by the test suite (all instants on the
# server-maintained logical clock; startup default is 2026-05-01T00:00:00Z).
SEASON_DEFAULTS = {
    "year": 2026,
    "booking_open_at": "2026-06-01T00:00:00Z",
    "booking_close_at": "2026-08-31T23:59:59Z",
    "harvest_window_start": "2026-11-01",
    "harvest_window_end": "2026-11-25",
    "shipping_window_start": "2026-11-15T00:00:00Z",
    "shipping_window_end": "2026-12-10T23:59:59Z",
}

# Logical-clock waypoints used across fixtures.
CLOCK = {
    "STARTUP_DEFAULT": "2026-05-01T00:00:00Z",
    "BOOKING_OPEN": "2026-06-01T00:00:00Z",
    "PAST_BOOKING_CLOSE": "2026-09-01T00:00:00Z",
    "HARVEST_DAY": "2026-11-05T08:00:00Z",
    "HARVEST_DAY_ALT": "2026-11-10T08:00:00Z",
    "SHIPPING_WINDOW_END": "2026-12-10T23:59:59Z",
    "ONE_SECOND_PAST_SHIPPING_END": "2026-12-11T00:00:00Z",
}

# Wholesale order volume tiers (inclusive lower bounds) from the PRD invoice rule.
ORDER_TIERS = {
    "TIER_1_QTY": 100,
    "TIER_1_PCT": 0.03,
    "TIER_2_QTY": 200,
    "TIER_2_PCT": 0.05,
    "TIER_3_QTY": 500,
    "TIER_3_PCT": 0.08,
}

# Harvest piece rates in cents per tree, keyed by height class.
PIECE_RATE_CENTS = {
    "H_4_5": 180,
    "H_5_6": 220,
    "H_6_7": 260,
    "H_7_8": 310,
    "H_8_9": 380,
    "H_9_PLUS": 460,
}

# Statutory minimum pay: cents per worker-hour.
MIN_HOURLY_CENTS_PER_WORKER = 1500

# Load tree-unit weight per height class.
LOAD_UNIT_WEIGHT = {
    "H_4_5": 1,
    "H_5_6": 2,
    "H_6_7": 3,
    "H_7_8": 5,
    "H_8_9": 7,
    "H_9_PLUS": 9,
}

# Choose-and-cut tag time-to-live in hours (logical clock).
TAG_TTL_HOURS = 48

# Dock pickup windows of the same season require a 30-minute buffer.
DOCK_BUFFER_MINUTES = 30

# A generous credit limit for fixtures that do not exercise the credit check.
AMPLE_CREDIT_LIMIT_CENTS = 100_000_000
