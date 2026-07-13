"""Domain thresholds and numeric constants stated in the PRD."""

# --- Flat-earth geodesy (PRD §2.7) ---
KM_PER_DEG_LAT = 111.0
KM_PER_DEG_LON = 85.0

# --- Delivery fee tiers (PRD §3.3) ---
TIER1_MAX_KM = 5.0
TIER1_BASE = 4.00
TIER2_MAX_KM = 12.0
TIER2_BASE = 6.50
TIER3_BASE = 9.00
PAYLOAD_RATE_PER_KG = 0.90
PRIORITY_MULT = {"STANDARD": 1.0, "URGENT": 1.35, "MEDICAL": 1.60}

# --- Airspace surcharge tiers, keyed on delivery_fee (PRD §3.3) ---
SURCHARGE_TIER1_MAX = 8.00
SURCHARGE_TIER2_MAX = 15.00
SURCHARGE_PCT_LOW = 0.05
SURCHARGE_PCT_MID = 0.08
SURCHARGE_PCT_HIGH = 0.12

# --- Flight energy (PRD §3.4 provisional variant / §3.7 actual variant) ---
ENERGY_PCT_PER_KM = 1.6
PAYLOAD_ENERGY_FACTOR = 0.08
WIND_FREE_KPH = 10.0
WIND_PENALTY_PER_KPH = 0.02
HOVER_PCT = 3.0
RESERVE_PCT = 15.0

# --- Airworthiness risk (PRD §3.2) ---
SERVICE_WEIGHT = 40.0
SERVICE_INTERVAL_H = 50.0
CYCLE_WEIGHT = 30.0
RETIRE_CYCLES = 300
SEVERITY_POINTS = {"MINOR": 5, "MAJOR": 15, "CRITICAL": 30}
SEVERITY_CAP = 30
RISK_BLOCK_THRESHOLD = 70.0

# --- Weather flyability (PRD §3.1) ---
MAX_WIND_KPH = 35.0
MAX_GUST_KPH = 45.0
MIN_VISIBILITY_KM = 1.5

# --- Pad holds (PRD §3.4) ---
PAD_BUFFER_MIN = 5
PAD_HOLD_MIN = 10
HOVER_MIN = 3

# --- Maintenance work-order windows (PRD §3.7 / §3.8) ---
BATTERY_SWAP_WINDOW_MIN = 60
REPAIR_WINDOW_MIN = 120

# --- Pagination (PRD §2.3) ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- The logical mission clock (PRD §2.4) ---
CLOCK_STARTUP_UTC = "2026-05-01T00:00:00Z"

# --- Values shared by the generated fixtures/tests ---
TEST_CLOCK = "2026-06-01T09:00:00Z"

TEST_DEFAULTS = {
    # Bay service area, centred at 37.0 / -122.0.
    "SA_NAME": "Bay",
    "SA_CENTER_LAT": 37.0,
    "SA_CENTER_LON": -122.0,
    "SA_MAX_RANGE_KM": 12.0,
    "SA_MAX_PAYLOAD_G": 2500,
    # Nest N1 at the centroid.
    "NEST_NAME": "N1",
    "NEST_LAT": 37.0,
    "NEST_LON": -122.0,
    "NEST_PAD_COUNT": 2,
    # Airframe N101.
    "TAIL_NUMBER": "N101",
    "AIRFRAME_CLASS": "HEAVY",
    "DRONE_MAX_PAYLOAD_G": 2500,
    "CRUISE_SPEED_KMH": 60,
    "HOURS_SINCE_SERVICE": 0,
    # Pack B-1.
    "BATTERY_SERIAL": "B-1",
    "BATTERY_CHARGE_PCT": 100,
    "BATTERY_CYCLE_COUNT": 0,
    # Customer Ann at 37.05 / -122.0 => 5.550 km from the Bay centroid.
    "CUSTOMER_NAME": "Ann",
    "CUSTOMER_EMAIL": "ann@x.com",
    "DROPOFF_LAT": 37.05,
    "DROPOFF_LON": -122.0,
    # Order.
    "PAYLOAD_WEIGHT_G": 2000,
    # LAANC filing.
    "GRID_CELLS": ["37N122W-01"],
    "REQUESTED_ALT_FT": 350,
    "WINDOW_START": "2026-06-01T08:00:00Z",
    "WINDOW_END": "2026-06-01T12:00:00Z",
    # Drop.
    "HOVER_ALT_FT": 15,
    "PHOTO_REF": "photo-1",
}

# Derived reference values for the canonical Bay/N1/Ann/2000 g STANDARD scenario.
# distance 5.550 km, planned route 11.100 km, order_total 8.96,
# required_energy_pct 38.6 (wind 0), actual_energy_pct 23.6 at the same route.
REF_DISTANCE_KM = 5.550
REF_PLANNED_ROUTE_KM = 11.100
REF_DELIVERY_FEE = 8.30
REF_AIRSPACE_SURCHARGE = 0.66
REF_ORDER_TOTAL = 8.96
REF_REQUIRED_ENERGY_PCT = 38.6
REF_ACTUAL_ENERGY_PCT = 23.6
REF_FLIGHT_HOURS = 0.19
