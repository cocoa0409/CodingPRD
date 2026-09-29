"""Domain thresholds and default fixture values drawn from the PRD's rules."""

# --- The logical show clock (PRD §2.6) ---------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# --- Licensing (PRD §3.1) ----------------------------------------------------
MAX_LICENSE_REVISIONS = 2

# --- Purse waterfall (PRD §3.2) ---------------------------------------------
BASIS_POINTS_TOTAL = 10000
PLACE_SHARE_BP = {1: 4000, 2: 2500, 3: 1600, 4: 1100, 5: 800}
MAX_PAYING_PLACES = 5

# --- Duration estimation (PRD §3.6) -----------------------------------------
BASE_ROUND_SECONDS = {"HUNTER": 90, "JUMPER": 75, "EQUITATION": 100, "DRESSAGE": 300}
HEIGHT_FACTOR_BASE_CM = 100
HEIGHT_FACTOR_DIVISOR = 200
JUMPOFF_RATE = 0.30
JUMPOFF_CAP = 8
COURSE_WALK_MIN_MINUTES = 10
COURSE_WALK_BLOCK_MINUTES = 5
COURSE_WALK_ENTRIES_PER_BLOCK = 10
WARMUP_LEAD_MINUTES = 30

# --- Ring / official geometry (PRD §3.3, §3.6) ------------------------------
DEFAULT_TURNOVER_BUFFER_MINUTES = 10
DEFAULT_FOOTING_CONDITION_SCORE = 100
DEFAULT_WARMUP_CAPACITY_HORSES = 12
MIN_FOOTING_SCORE = 60
OFFICIAL_TRAVEL_GAP_MINUTES = 20
MAX_OFFICIAL_DAILY_MINUTES = 480
COVERAGE_CHECKIN_LEAD_MINUTES = 60

MIN_OFFICIAL_LICENSE_LEVEL = {"LOCAL": 1, "REGIONAL": 2, "NATIONAL": 3, "PREMIER": 4}
REQUIRED_OFFICIALS = {
    "LOCAL": {"JUDGE": 1, "STEWARD": 1, "TECHNICAL_DELEGATE": 0},
    "REGIONAL": {"JUDGE": 2, "STEWARD": 1, "TECHNICAL_DELEGATE": 0},
    "NATIONAL": {"JUDGE": 2, "STEWARD": 1, "TECHNICAL_DELEGATE": 1},
    "PREMIER": {"JUDGE": 3, "STEWARD": 2, "TECHNICAL_DELEGATE": 1},
}

# --- Welfare (PRD §3.7, §3.9) ----------------------------------------------
WELFARE_STRIKE_LIMIT = 2

# --- Entry settlement (PRD §3.5) -------------------------------------------
OFFICE_FEE_WAIVER_CENTS = 100000
OFFICE_FEE_REDUCED_CENTS = 50000
OFFICE_FEE_REDUCED_AMOUNT_CENTS = 2500
OFFICE_FEE_FULL_AMOUNT_CENTS = 5000

# --- Registries (PRD §3.4) --------------------------------------------------
COGGINS_VALIDITY_DAYS = 365

# --- Standings (PRD §3.8) ---------------------------------------------------
MIN_ENTRIES_FOR_POINTS = 3
NATIONAL_PLACE_POINTS = {1: 10, 2: 6, 3: 4, 4: 3, 5: 2}
REGIONAL_PLACE_POINTS = {1: 8, 2: 5, 3: 3}
REGIONAL_PLACING_CAP = 3
REGIONAL_SHOW_CAP = 20
NATIONAL_MULTIPLIER_TIERS = [(25, 2.0), (10, 1.5), (3, 1.0)]

# --- Pagination (PRD §2.3) --------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# --- Shared fixture defaults ------------------------------------------------
TEST_DEFAULTS = {
    "SHOW_NAME": "Autumn Classic",
    "FEDERATION_SHOW_ID": "FED-2434",
    "VENUE": "Ridgeline Park",
    "COMPETITION_LEVEL": "LOCAL",
    "SHOW_START_UTC": "2026-09-10T13:00:00Z",
    "SHOW_END_UTC": "2026-09-13T22:00:00Z",
    "ENTRY_CLOSE_UTC": "2026-09-01T00:00:00Z",
    "PRIZE_POOL_CENTS": 750000,
    "STALL_CAPACITY": 40,
    "STALL_FEE_CENTS": 7500,
    "ENTRY_FEE_CENTS": 25000,
    "DIVISION_SHARE_BP": 3333,
    "CLASS_SHARE_BP": 1669,
    "JUMP_HEIGHT_CM": 120,
    "MAX_ENTRIES": 30,
    "COGGINS_DRAWN_ON": "2026-03-01T00:00:00Z",
    "MEMBERSHIP_EXPIRES_ON": "2027-06-30T00:00:00Z",
    "LICENSE_EXPIRES_ON": "2027-12-31T00:00:00Z",
    "SLOT_START_UTC": "2026-09-10T14:00:00Z",
    "COVERAGE_START_UTC": "2026-09-10T12:00:00Z",
    "COVERAGE_END_UTC": "2026-09-10T20:00:00Z",
    "COMPETITION_DAY_CLOCK": "2026-09-10T13:30:00Z",
}

# A well-formed UUID that matches no stored row.
MISSING_UUID = "00000000-0000-4000-8000-000000000001"
MISSING_UUID_ALT = "00000000-0000-4000-8000-000000000002"
