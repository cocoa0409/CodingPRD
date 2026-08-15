"""Domain thresholds and numeric constants from the PRD."""

# Logical clock default at server startup (PRD: the clock reads exactly
# 2026-08-01T00:00:00Z before any clock-setting call).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Booking constraints
MAX_BOOKING_NIGHTS = 21
HOLD_TTL_HOURS = 48

# Deposit base per size class (integer cents)
BASE_DEPOSIT = {
    "COMPACT_36": 150000,
    "STANDARD_44": 200000,
    "LUXE_56": 250000,
}

# Deposit multiplier tiers on risk_score_rolling_24m
TIER_MED_MIN = 20
TIER_HIGH_MIN = 50
MULTIPLIER_LOW = 1.0
MULTIPLIER_MED = 1.5
MULTIPLIER_HIGH = 2.0

# Renter risk severity weights
SEVERITY_WEIGHT = {
    "MINOR": 10,
    "MAJOR": 25,
    "TOTAL_LOSS": 60,
}
RISK_WINDOW_MONTHS = 24

# Settlement constants (integer cents)
FUEL_PRICE_CENTS_PER_GALLON = 700
PUMP_OUT_FEE_CENTS = 15000
CLEANING_FEE_CENTS = 25000
LATE_HOURLY_CENTS = 5000
RETURN_DEADLINE_LOCAL = "10:00:00Z"  # on end_date
ESTIMATED_BURN_PCT = 50

# Grounding liability base per severity (integer cents)
GROUNDING_BASE = {
    "MINOR": 50000,
    "MAJOR": 250000,
    "TOTAL_LOSS": 900000,
}

# Cancellation refund tiers (whole days before start_date -> percent)
TIER_FULL_DAYS = 30
TIER_HALF_DAYS = 14
TIER_QUARTER_DAYS = 8
PCT_FULL = 90
PCT_HALF = 50
PCT_QUARTER = 25

# Orientation item sets pinned by size class at confirm time
BASE_ORIENTATION_ITEMS = ["SAFETY_BRIEF", "DOCKING", "ANCHORING", "GENERATOR_OPS"]
LUXE_EXTRA_ORIENTATION_ITEMS = ["THRUSTER_OPS", "SEWAGE_PUMPOUT"]


def orientation_items_for(size_class: str) -> list:
    """Item set a vessel's size class pins on the booking at confirm time."""
    items = list(BASE_ORIENTATION_ITEMS)
    if size_class == "LUXE_56":
        items += LUXE_EXTRA_ORIENTATION_ITEMS
    return items


# Common test defaults
TEST_DEFAULTS = {
    "VESSEL_NAME": "Test Vessel",
    "HOME_MARINA": "Wahweap",
    "TANK_COMPACT": 150,
    "TANK_STANDARD": 200,
    "TANK_LUXE": 300,
    "BERTH_COMPACT": 6,
    "BERTH_STANDARD": 6,
    "BERTH_LUXE": 8,
    "RATE_COMPACT_PEAK": 45000,
    "RATE_STANDARD_PEAK": 65000,
    "RATE_LUXE_PEAK": 90000,
    "WEEKLY_DISCOUNT_PCT": 10,
}
