"""All 64 declared constants, enums and constant mappings (PRD sections 2.x / 3.x).

Nothing in this module is data: it is the SYSTEM's fixed configuration.
"""

# --- Route metering ---------------------------------------------------------
ROUTE_MAX_UNITS_PER_DAY = 44
ROUTE_MAX_MINUTES_PER_DAY = 480
MAX_STOPS_PER_ROUTE = 8
ROUTE_DAY_START_MINUTE = 480  # declared but deliberately unenforced (PRD 3.4)

# --- Per-limb shoeing load --------------------------------------------------
SERVICE_UNITS_TRIM = 1
SERVICE_UNITS_RESET = 2
SERVICE_UNITS_NEW_SHOES = 3
SERVICE_UNITS_CORRECTIVE = 5
SERVICE_UNITS_GLUE_ON = 4

SERVICE_MINUTES_TRIM = 8
SERVICE_MINUTES_RESET = 14
SERVICE_MINUTES_NEW_SHOES = 20
SERVICE_MINUTES_CORRECTIVE = 32
SERVICE_MINUTES_GLUE_ON = 26

HORSE_HANDLING_MINUTES = 6
SEDATION_EXTRA_MINUTES = 15
SEDATION_HANDLING_MULTIPLIER_BP = 15000

STOP_TRAVEL_MINUTES_ZONE_A = 15
STOP_TRAVEL_MINUTES_ZONE_B = 30
STOP_TRAVEL_MINUTES_ZONE_C = 50

# --- Cycles -----------------------------------------------------------------
MIN_ROUTINE_CYCLE_WEEKS = 6
MAX_ROUTINE_CYCLE_WEEKS = 8
MIN_PRESCRIBED_CYCLE_WEEKS = 2
MAX_PRESCRIBED_CYCLE_WEEKS = 8
DAYS_PER_WEEK = 7
SNAP_FORWARD_LOOKAHEAD_DAYS = 3

# --- Lameness / prescriptions ----------------------------------------------
LAMENESS_MIN_SEVERITY = 1
LAMENESS_MAX_SEVERITY = 5
LAMENESS_HOLD_SEVERITY_THRESHOLD = 3
PRESCRIPTION_MAX_DURATION_DAYS = 180

# --- Reminders --------------------------------------------------------------
REMINDER_OFFSET_DAYS_PRIMARY = 7
REMINDER_OFFSET_DAYS_SECONDARY = 2
REMINDER_SUPPRESSION_WINDOW_DAYS = 3

# --- Cancellation / no-show -------------------------------------------------
ADVANCE_CANCEL_MIN_LEAD_DAYS = 3
LATE_CANCEL_FEE_CENTS = 3500
ONSITE_CANCEL_FEE_CENTS = 5500
NO_SHOW_FEE_CENTS = 6500
NO_SHOW_ROLLING_WINDOW_DAYS = 180
NO_SHOW_PREPAY_THRESHOLD = 3
NO_SHOW_SUSPEND_THRESHOLD = 5
PREPAY_DEPOSIT_MIN_CENTS = 10000

# --- Money ------------------------------------------------------------------
SEDATION_LABOR_SURCHARGE_BP = 1250
MULTI_HORSE_DISCOUNT_MIN_HORSES = 3
MULTI_HORSE_DISCOUNT_BP = 500
LOYALTY_THRESHOLD_VISITS = 12
LOYALTY_STANDARD_BP = 300
LOYALTY_PREMIER_THRESHOLD_VISITS = 30
LOYALTY_PREMIER_BP = 600
PRODUCT_TAX_RATE_BP = 725
LABOR_TAX_RATE_BP = 0
TRIP_FEE_TAX_RATE_BP = 0
FEE_TAX_RATE_BP = 0
BASIS_POINT_DENOMINATOR = 10000

# --- Warranty / stock -------------------------------------------------------
WARRANTY_WINDOW_DAYS = 21
SHOES_PER_PAIR = 2
REORDER_POINT_PAIRS = 2
MAX_TRANSFER_PAIRS = 40
MAX_CONSECUTIVE_RESETS = 1
LIMB_COUNT_PER_HORSE = 4
MINUTES_PER_DAY = 1440

# --- Pagination / clock -----------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# --- Enumerations -----------------------------------------------------------
LIMBS = ("LF", "RF", "LH", "RH")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
ZONES = ("A", "B", "C")
SERVICE_TYPES = ("TRIM", "RESET", "NEW_SHOES", "CORRECTIVE", "GLUE_ON")
MATERIALS = ("STEEL", "ALUMINUM", "COMPOSITE")
CERT_LEVELS = ("APPRENTICE", "JOURNEYMAN", "CERTIFIED_THERAPEUTIC")
DEACTIVATE_REASONS = ("VOLUNTARY", "CERT_EXPIRED")
DELIVERY_OUTCOMES = ("DELIVERED", "FAILED")
REORDER_DIRECTIONS = ("EARLIER", "LATER")
WARRANTY_REASONS = ("SPRUNG_SHOE", "LOST_SHOE", "QUICK")
VISIT_KINDS = ("ROUTINE", "WARRANTY_REVISIT")

ROLES = (
    "PlatformAdmin",
    "Dispatcher",
    "Farrier",
    "ClientUser",
    "Veterinarian",
    "BillingClerk",
)

# --- Constant mappings ------------------------------------------------------
SERVICE_TYPE_TO_UNITS = {
    "TRIM": SERVICE_UNITS_TRIM,
    "RESET": SERVICE_UNITS_RESET,
    "NEW_SHOES": SERVICE_UNITS_NEW_SHOES,
    "CORRECTIVE": SERVICE_UNITS_CORRECTIVE,
    "GLUE_ON": SERVICE_UNITS_GLUE_ON,
}

SERVICE_TYPE_TO_MINUTES = {
    "TRIM": SERVICE_MINUTES_TRIM,
    "RESET": SERVICE_MINUTES_RESET,
    "NEW_SHOES": SERVICE_MINUTES_NEW_SHOES,
    "CORRECTIVE": SERVICE_MINUTES_CORRECTIVE,
    "GLUE_ON": SERVICE_MINUTES_GLUE_ON,
}

SERVICE_TYPE_TO_PRICE_FIELD = {
    "TRIM": "price_trim_cents",
    "RESET": "price_reset_cents",
    "NEW_SHOES": "price_new_shoes_cents",
    "CORRECTIVE": "price_corrective_cents",
    "GLUE_ON": "price_glue_on_cents",
}

ZONE_TO_TRAVEL_MINUTES = {
    "A": STOP_TRAVEL_MINUTES_ZONE_A,
    "B": STOP_TRAVEL_MINUTES_ZONE_B,
    "C": STOP_TRAVEL_MINUTES_ZONE_C,
}

ZONE_TO_TRIP_FEE_FIELD = {
    "A": "trip_fee_zone_a_cents",
    "B": "trip_fee_zone_b_cents",
    "C": "trip_fee_zone_c_cents",
}

SERVICE_TYPE_REQUIRES_SKU = {
    "TRIM": False,
    "RESET": False,
    "NEW_SHOES": True,
    "CORRECTIVE": True,
    "GLUE_ON": True,
}

# with_pad may be true only for NEW_SHOES and CORRECTIVE (PRD 3.5).
SERVICE_TYPE_ALLOWS_PAD = {
    "TRIM": False,
    "RESET": False,
    "NEW_SHOES": True,
    "CORRECTIVE": True,
    "GLUE_ON": False,
}

CERT_LEVEL_TO_ALLOWED_SERVICE_TYPES = {
    "APPRENTICE": {"TRIM"},
    "JOURNEYMAN": {"TRIM", "RESET", "NEW_SHOES", "GLUE_ON"},
    "CERTIFIED_THERAPEUTIC": {"TRIM", "RESET", "NEW_SHOES", "GLUE_ON", "CORRECTIVE"},
}

SHOD_STATES = ("SHOD", "SHOD_WITH_PAD", "GLUED")

TERMINAL_APPOINTMENT_STATUSES = (
    "COMPLETED",
    "CANCELLED_ADVANCE",
    "CANCELLED_LATE",
    "CANCELLED_ONSITE",
    "NO_SHOW",
)

# Appointment statuses that contribute to a route's committed meters.
ROUTE_COMMITTING_STATUSES = ("SCHEDULED", "CONFIRMED", "IN_PROGRESS", "COMPLETED")

# Appointment statuses that bear a trip-fee share at a completed stop.
TRIP_FEE_BILLABLE_STATUSES = ("COMPLETED", "NO_SHOW", "CANCELLED_ONSITE")
