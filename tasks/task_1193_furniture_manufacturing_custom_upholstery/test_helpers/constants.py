"""Domain thresholds and shared values from PRD calculations."""

# Clock
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"
CLOCK_TEST_ISO = "2026-05-10T00:00:00Z"

# Fabric requirement calculation constants
NOMINAL_WIDTH_IN = 54
SELVAGE_TRIM_IN = 2

# Waste tiers
WASTE_TIER_LOW_MAX_QTY = 5
WASTE_TIER_MID_MAX_QTY = 20
WASTE_LOW = 0.15
WASTE_MID = 0.10
WASTE_HIGH = 0.07

# Freight value-per-pound override threshold (cents per pound)
VALUE_PER_LB_THRESHOLD_CENTS = 3000

# Freight charge constants
FUEL_PCT = 0.18
WG_MIN_CENTS = 15000
WG_PER_PIECE_CENTS = 8500
WG_INSIDE_SURCHARGE_CENTS = 4500

# Supply requisition
CONTAINER_MOQ = 50
CONTAINER_UNIT_COST_CENTS = 1200
CONTAINER_LEAD_DAYS = 45
DOMESTIC_UNIT_COST_CENTS = 2000
DOMESTIC_LEAD_DAYS = 7

# Sample refurb gap (days)
SAMPLE_REFURB_GAP_DAYS = 5

# Test default timestamps used by booking scenarios
BOOKING_WINDOW_A_START = "2026-06-01T08:00:00Z"
BOOKING_WINDOW_A_END = "2026-06-01T09:00:00Z"
