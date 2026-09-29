"""Numeric tables, enums and canonical fixture literals from the PRD.

Every table below is transcribed from the PRD sections that declare it; nothing
here is inferred. Values are used by tests to express expectations in the same
units the PRD uses (cents, kilometres, kilograms, days, cycles).
"""

# --- Routing -----------------------------------------------------------------

API_PREFIX = "/challenge-course"
CLOCK_PATH = "/_clock/set_current_utc"

# --- Global defaults (PRD 2.3, 2.4) ------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# --- Roles (PRD 2.1) ---------------------------------------------------------

ROLE_PROGRAM_DIRECTOR = "ProgramDirector"
ROLE_SAFETY_OFFICER = "SafetyOfficer"
ROLE_FACILITATOR = "Facilitator"
ROLE_PROFESSIONAL_INSPECTOR = "ProfessionalInspector"
ROLE_GROUP_COORDINATOR = "GroupCoordinator"

ALL_ROLES = [
    ROLE_PROGRAM_DIRECTOR,
    ROLE_SAFETY_OFFICER,
    ROLE_FACILITATOR,
    ROLE_PROFESSIONAL_INSPECTOR,
    ROLE_GROUP_COORDINATOR,
]

# --- Element types and phases (PRD 3.1, 3.7) ---------------------------------

ELEMENT_TYPES = [
    "GROUND_INITIATIVE",
    "LOW_ELEMENT",
    "HIGH_ELEMENT",
    "CLIMBING_WALL",
    "ZIP_LINE",
]

PHASES = ["ICEBREAKER", "GROUND_INITIATIVE", "LOW_ELEMENT", "HIGH_ELEMENT", "DEBRIEF"]

# Program-block phase -> element types the block may be rigged to (PRD 3.7).
PHASE_ELEMENT_FAMILY = {
    "GROUND_INITIATIVE": ["GROUND_INITIATIVE"],
    "LOW_ELEMENT": ["LOW_ELEMENT"],
    "HIGH_ELEMENT": ["HIGH_ELEMENT", "CLIMBING_WALL", "ZIP_LINE"],
}

# --- Element asset life (PRD 3.1) --------------------------------------------

DESIGN_LIFE_YEARS = {
    "GROUND_INITIATIVE": 20,
    "LOW_ELEMENT": 15,
    "HIGH_ELEMENT": 12,
    "CLIMBING_WALL": 15,
    "ZIP_LINE": 10,
}

DESIGN_CYCLE_LIMIT = {
    "GROUND_INITIATIVE": 43800,
    "LOW_ELEMENT": 29200,
    "HIGH_ELEMENT": 21900,
    "CLIMBING_WALL": 25550,
    "ZIP_LINE": 18250,
}

# --- Belay equipment life (PRD 3.4) ------------------------------------------

MFG_SHELF_LIFE_YEARS = {"ROPE": 10, "HARNESS": 10, "CARABINER": 15, "LANYARD": 8}
SERVICE_LIFE_YEARS = {"ROPE": 5, "HARNESS": 7, "CARABINER": 10, "LANYARD": 5}

REQUIRED_BELAY_SETS_BY_TYPE = {
    "GROUND_INITIATIVE": 0,
    "LOW_ELEMENT": 0,
    "HIGH_ELEMENT": 2,
    "CLIMBING_WALL": 2,
    "ZIP_LINE": 3,
}

EQUIPMENT_KINDS = ["ROPE", "HARNESS", "CARABINER", "LANYARD"]

# --- Facilitator certification (PRD 3.2) -------------------------------------

CERT_LEVELS = ["LEVEL_1", "LEVEL_2", "LEVEL_3"]

SUPERVISION_CAPACITY_BY_LEVEL = {"LEVEL_1": 8, "LEVEL_2": 12, "LEVEL_3": 16}

RESCUE_DRILL_VALID_DAYS = 180
REFRESHER_HOURS_REQUIRED = 8
REFRESHER_WINDOW_DAYS = 730

REQUIRED_CERT_LEVEL_BY_ELEMENT_TYPE = {
    "GROUND_INITIATIVE": "LEVEL_1",
    "LOW_ELEMENT": "LEVEL_1",
    "HIGH_ELEMENT": "LEVEL_2",
    "CLIMBING_WALL": "LEVEL_2",
    "ZIP_LINE": "LEVEL_3",
}

# --- Supervision (PRD 3.7) ---------------------------------------------------

RATIO_BY_ELEMENT_TYPE = {
    "GROUND_INITIATIVE": 12,
    "LOW_ELEMENT": 10,
    "HIGH_ELEMENT": 6,
    "CLIMBING_WALL": 5,
    "ZIP_LINE": 4,
}

MIN_FACILITATORS_BY_PHASE = {
    "ICEBREAKER": 1,
    "GROUND_INITIATIVE": 1,
    "LOW_ELEMENT": 1,
    "HIGH_ELEMENT": 2,
    "DEBRIEF": 1,
}

HIGH_RISK_TYPE_FLOOR = 2
FACILITATOR_BUFFER_MINUTES = 20

# --- Pricing (PRD 3.5) -------------------------------------------------------

PHASE_RATE_CENTS = {
    "ICEBREAKER": 850,
    "GROUND_INITIATIVE": 1250,
    "LOW_ELEMENT": 2275,
    "HIGH_ELEMENT": 4650,
    "DEBRIEF": 625,
}

TIER_DISCOUNT_PCT = {"STANDARD": 0.00, "PARTNER": 0.075, "ANCHOR": 0.125}

CLIENT_TIERS = ["STANDARD", "PARTNER", "ANCHOR"]
ORG_TYPES = ["SCHOOL", "CAMP", "NONPROFIT", "CORPORATE"]

# High-element surcharge bands resolved once from the pre-surcharge subtotal.
SURCHARGE_BAND_LOW_CEILING_CENTS = 30000
SURCHARGE_BAND_MID_CEILING_CENTS = 36000
SURCHARGE_PCT_LOW = 0.06
SURCHARGE_PCT_MID = 0.05
SURCHARGE_PCT_HIGH = 0.03

DEPOSIT_PCT = 0.25

# --- Cancellation (PRD 3.9) --------------------------------------------------

CANCEL_FREE_NOTICE_DAYS = 30
CANCEL_QUARTER_NOTICE_DAYS = 14
CANCEL_HALF_NOTICE_DAYS = 7
WEATHER_ADMIN_FEE_CENTS = 2500
LATE_CANCELLATION_NOTICE_DAYS = 14

# --- Roster (PRD 3.6) --------------------------------------------------------

CHAPERONE_RATIO_MINORS = 10
ADULT_AGE_YEARS = 18
BLOCKING_HEALTH_FLAGS = ["CARDIAC", "SEIZURE", "PREGNANCY", "RECENT_SURGERY"]

# --- Weather and readiness (PRD 2.5, 3.9) ------------------------------------

LIGHTNING_STOP_KM = 8.0
LIGHTNING_WATCH_KM = 16.0
LIGHTNING_HOLD_MINUTES = 30
WIND_STOP_KPH = 48.0
WIND_WATCH_KPH = 32.0
TEMP_STOP_C = -12.0

RESCUE_READY_MINIMUM = 2
EMS_MAX_MINUTES = 30

MIN_LEAD_DAYS = 3

# --- Canonical fixture literals ---------------------------------------------
# Shared literals used by the composite setup builders in fixtures.py.

CLOCK_TEST_UTC = "2026-08-10T08:00:00Z"
CLOCK_TEST_DATE = "2026-08-10"

COURSE_NAME_PRIMARY = "Pine Ridge Challenge Course"
COURSE_NOTE_PRIMARY = "Gravel access road; ALS 18 minutes"
COURSE_NAME_SECONDARY = "Cedar Hollow Challenge Course"
COURSE_NOTE_SECONDARY = "Paved lane; ALS 18 minutes"
COURSE_EMS_MINUTES = 18

SAFETY_OFFICER_NAME = "Dana Reyes"
FACILITATOR_NAME = "Kim Alvarez"
INSPECTOR_NAME = "Morgan Yeo"
CERT_EXPIRES_ON = "2027-06-30"
TRAINING_COMPLETED_ON = "2026-07-15"

ELEMENT_INSTALLED_ON = "2024-08-10"
ELEMENT_INSPECTION_DUE_ON = "2027-06-30"
ELEMENT_NAME_GROUND = "Nitro Crossing"
ELEMENT_NAME_LOW = "Whale Watch"
ELEMENT_NAME_LOW_ALT = "Wild Woosey"
ELEMENT_NAME_HIGH = "Pamper Pole"
ELEMENT_NAME_ZIP = "Screaming Eagle"

LOW_WEIGHT_MIN_KG = 20.0
LOW_WEIGHT_MAX_KG = 136.0
HIGH_WEIGHT_MIN_KG = 27.0
HIGH_WEIGHT_MAX_KG = 113.0

CLIENT_NAME = "Ridgeview Middle School"
CLIENT_ORG_TYPE = "SCHOOL"
CLIENT_TIER = "PARTNER"
CLIENT_PAYMENT_CENTS = 20000
CLIENT_PAYMENT_REFERENCE = "CHK-8801"

PROGRAM_DATE = "2026-09-15"

ADULT_NAME = "Alex Stone"
ADULT_BIRTH_DATE = "1990-04-12"
ADULT_WEIGHT_KG = 78.0
MINOR_NAME = "Ada Lin"
MINOR_BIRTH_DATE = "2013-05-10"
MINOR_WEIGHT_KG = 45.0
CHAPERONE_NAME = "Robin Vale"
CHAPERONE_BIRTH_DATE = "1988-11-30"
CHAPERONE_WEIGHT_KG = 71.0
HEAVY_NAME = "Bo Grant"
HEAVY_BIRTH_DATE = "1985-03-03"

# The canonical five-block program used by most pricing and start scenarios.
CANONICAL_BLOCKS = [
    ("ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z"),
    ("GROUND_INITIATIVE", "2026-09-15T09:45:00Z", "2026-09-15T10:30:00Z"),
    ("LOW_ELEMENT", "2026-09-15T10:30:00Z", "2026-09-15T11:30:00Z"),
    ("HIGH_ELEMENT", "2026-09-15T13:00:00Z", "2026-09-15T15:00:00Z"),
    ("DEBRIEF", "2026-09-15T15:15:00Z", "2026-09-15T16:00:00Z"),
]
