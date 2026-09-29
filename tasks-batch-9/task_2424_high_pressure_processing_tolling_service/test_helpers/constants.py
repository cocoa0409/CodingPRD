"""Domain thresholds and literals taken from the PRD's global rules and calculations.

Nothing here is invented: every value is a number, string or enumeration the PRD
names explicitly, gathered in one place so the test suite never repeats a magic
literal.
"""

# --- Logical clock ---------------------------------------------------------- #
# The clock reads exactly this instant before any client sets it.
INITIAL_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Pagination ------------------------------------------------------------- #
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# --- Identity --------------------------------------------------------------- #
USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

# --- Enumerations ----------------------------------------------------------- #
CROSS_CONTAMINATION_GROUPS = [
    "RTE_PRODUCE",
    "RAW_PROTEIN",
    "DAIRY",
    "JUICE",
    "PET_FOOD",
]

PACKAGE_FORMATS = ["POUCH", "TRAY_SEALED", "RIGID_BOTTLE", "GLASS"]

# Only these three may be supplied to the vessel status patch; IN_USE is the
# system's to set.
PATCHABLE_VESSEL_STATUSES = ["AVAILABLE", "MAINTENANCE", "DOWN"]

ROOT_CAUSE_PREFIXES = ["EQUIP", "PKG", "OPS"]

# The three CCP flags are collected in this fixed order and never re-sorted.
DEVIATION_FLAG_ORDER = ["UNDER_PRESSURE", "SHORT_HOLD", "TEMP_EXCURSION"]

CHARGEBACK_BASES = ["PACKAGE_LEAKER", "REPROCESS", "TAKE_OR_PAY_SHORTFALL"]

# --- Package suitability score (§3.2) --------------------------------------- #
PRESSURE_MARGIN_DIVISOR_MPA = 50.0
FILM_MARGIN_DIVISOR_MICRON = 80.0
SUITABILITY_WEIGHTS = {
    "PRESSURE_MARGIN": 0.50,
    "FILM_MARGIN": 0.30,
    "FORMAT_FACTOR": 0.20,
}
FORMAT_FACTORS = {
    "POUCH": 1.0,
    "TRAY_SEALED": 0.85,
    "RIGID_BOTTLE": 0.60,
    "GLASS": 0.0,
}

# --- Qualification gates (§3.2) --------------------------------------------- #
MIN_ACCEPTABLE_VALIDATION_RUNS = 2
MIN_SUITABILITY_SCORE = 70.00
QUALIFICATION_VALIDITY_DAYS = 365
MAX_COMPLETED_REVISION_ROUNDS = 3
MAX_QUALIFICATION_PRESSURE_MPA = 600

# --- Cycle time and tolling fee (§3.5, §3.8) -------------------------------- #
HANDLING_SECONDS = 180
CENTS_PER_BILLABLE_MINUTE = 1250
SECONDS_PER_MINUTE = 60

UTILIZATION_SURCHARGE_TIERS = {
    "LOW_UTIL_BELOW_PCT": 60.00,
    "LOW_UTIL_RATE": 0.20,
    "MID_UTIL_BELOW_PCT": 85.00,
    "MID_UTIL_RATE": 0.08,
    "NO_SURCHARGE_AT_OR_ABOVE_PCT": 85.00,
    "NO_SURCHARGE_RATE": 0.00,
}

LOYALTY_CREDIT_TIERS = {
    "TOP_TIER_MIN_GROSS_CENTS": 12000,
    "TOP_TIER_RATE": 0.05,
    "MID_TIER_MIN_GROSS_CENTS": 8000,
    "MID_TIER_RATE": 0.03,
    "NO_CREDIT_RATE": 0.00,
}

# --- Contract settlement (§3.3) --------------------------------------------- #
MIN_TAKE_FRACTION = 0.80

# --- CCP verdict and deviation severity (§3.6) ------------------------------ #
CRITICAL_SHORTFALL_PCT = 5.00
CCP_HOLD_REASON = "CCP deviation"

# --- Package leakers and chargebacks (§3.8) --------------------------------- #
LEAKER_CHARGEBACK_PPM = 3000
LEAKER_WATCH_PPM = 1500
TRAILING_REPEAT_OFFENDER_PPM = 2000
HANDLING_CENTS_PER_LEAKER = 125
REWORK_RATE = 0.50
REPROCESS_RATE = 0.50
PPM_SCALE = 1000000

# --- End-of-day sweep (§3.9) ------------------------------------------------ #
TRAILING_WINDOW_DAYS = 90

# --- Convenient payload defaults for tests ---------------------------------- #
TEST_DEFAULTS = {
    "CUSTOMER_NAME": "Verde Foods",
    "CUSTOMER_CODE": "VERDE",
    "BILLING_EMAIL": "ap@verde.example",
    "FAMILY_CODE": "RTE_GUAC",
    "GROUP": "RTE_PRODUCE",
    "CLEANOUT_MINUTES": 45,
    "MAX_RECEIPT_TEMP_C": 4.0,
    "MAX_OUTBOUND_TEMP_C": 4.0,
    "VESSEL_CODE": "HPP-1",
    "ROOM_CODE": "CR-1",
    "SKU_CODE": "GUAC-500",
    "VERSION_LABEL": "REV-A",
    "PRESSURE_MPA": 600.0,
    "HOLD_TIME_SECONDS": 180,
    "MAX_WATER_TEMP_C": 8.0,
    "TARGET_LOG_REDUCTION": 5.0,
    "SEASON_CODE": "FY26",
    "WINDOW_START": "2026-08-01T00:00:00Z",
    "WINDOW_END": "2026-12-31T23:59:59Z",
    "PEAK_WINDOW_START": "2026-10-01T00:00:00Z",
    "PEAK_WINDOW_END": "2026-11-30T23:59:59Z",
    "PEAK_MULTIPLIER": 1.25,
    "SLOT_TAKE_OR_PAY_CENTS": 60000,
    "SHIP_BY": "2026-08-20T00:00:00Z",
    "CLOCK_AUG03": "2026-08-03T08:00:00Z",
    "CYCLE_START": "2026-08-05T09:00:00Z",
    "ROOT_CAUSE_EQUIP": "EQUIP_PUMP_FAULT",
    "ROOT_CAUSE_PKG": "PKG_SEAL_SUPPLIER",
    "ROOT_CAUSE_OPS": "OPS_LOADING_ERROR",
}
