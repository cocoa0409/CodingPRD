"""Domain constants for the RV share marketplace API.

Every value here is published by the PRD; nothing is invented. Tests import
these names instead of repeating magic numbers so that a single PRD sentence
maps to a single symbol.
"""

# --- API surface -----------------------------------------------------------
API_PREFIX = "/rv-marketplace"

# --- Logical clock (PRD 2.5) ----------------------------------------------
# "The server's startup default logical clock is exactly 2026-08-01T00:00:00Z"
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Pagination (PRD 2.3) -------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# --- Seasonal pricing (PRD 3.1) ------------------------------------------
SEASON_DEFAULT_MULTIPLIER_BP = 10000
SEASON_DEFAULT_CODE = "OFF"

# --- Protection premium (PRD 3.5) ----------------------------------------
TOWING_SURCHARGE_BP = 2500
PREMIUM_CEILING_CAP_BP = 1500

# --- Loyalty banding (PRD 3.5) -------------------------------------------
LOYALTY_TIER_2_MIN_CENTS = 150000
LOYALTY_TIER_2_DISCOUNT_BP = 700
LOYALTY_TIER_1_MIN_CENTS = 100000
LOYALTY_TIER_1_DISCOUNT_BP = 400

# --- Platform service fee (PRD 3.5) --------------------------------------
SERVICE_FEE_BP = 1200

# --- Trip clock anchors (PRD 3.5) ----------------------------------------
SCHEDULED_PICKUP_TIME_UTC = "15:00:00"
SCHEDULED_RETURN_TIME_UTC = "11:00:00"

# --- Late return (PRD 3.7) -----------------------------------------------
LATE_GRACE_MINUTES = 60
LATE_HOUR_FEE_CENTS = 7500
LATE_FEE_CAP_BP = 20000

# --- Penalty thresholds (PRD 3.3, 3.4) -----------------------------------
OWNER_SUSPENSION_POINT_THRESHOLD = 12
RENTER_BLOCK_POINT_THRESHOLD = 8

# --- Driving record window (PRD 3.4) -------------------------------------
RECORD_LOOKBACK_MONTHS = 36
MAX_RECORD_POINTS = 6

# --- Photo completeness (PRD 3.2, 3.7) -----------------------------------
MIN_INSPECTION_PHOTO_ZONES = 5
MIN_TRIP_PHOTO_ZONES = 4

# --- Damage claim review (PRD 3.8) ---------------------------------------
MAX_INFO_ROUNDS = 2
VERDICT_FACTOR_BP = {
    "NEW_DAMAGE": 10000,
    "NO_VISIBLE_CHANGE": 5000,
    "PRE_EXISTING": 0,
}

# --- Towing tiers (PRD 3.5) ----------------------------------------------
TOWING_ADVANCED_GVWR_THRESHOLD_LBS = 10000

# --- Availability geometry (PRD 3.5, 3.6) --------------------------------
TURNAROUND_BUFFER_NIGHTS = 1

# --- Pricing guidance (PRD 3.11) -----------------------------------------
GUIDANCE_WINDOW_DAYS = 90
GUIDANCE_LOOKAHEAD_DAYS = 30
UTILIZATION_BANDS_BP = (
    (7000, 1500),
    (4000, 500),
    (2000, 0),
)
UTILIZATION_FLOOR_ADJUSTMENT_BP = -1000

# --- Zone vocabulary (PRD 3.2, 3.7) --------------------------------------
INSPECTION_ZONES = (
    "EXTERIOR_FRONT",
    "EXTERIOR_REAR",
    "INTERIOR",
    "ROOF",
    "UNDERCARRIAGE",
)

ALL_VEHICLE_CLASSES = (
    "CLASS_A",
    "CLASS_C",
    "CAMPER_VAN",
    "TRAVEL_TRAILER",
    "FIFTH_WHEEL",
)

# Vehicle classes for which requires_towing is derived true (PRD 3.2).
TOWED_VEHICLE_CLASSES = ("TRAVEL_TRAILER", "FIFTH_WHEEL")
