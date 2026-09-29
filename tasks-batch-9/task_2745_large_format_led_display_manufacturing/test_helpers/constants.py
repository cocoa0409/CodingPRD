"""Business constants for the LED Display Manufacturing API test suite.

Every value here is transcribed from the product requirements document; no
constant is invented and none is derived by the tests themselves.
"""

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_PLANT_ADMIN = "PlantAdmin"
ROLE_DESIGN_ENGINEER = "DesignEngineer"
ROLE_STRUCTURAL_REVIEWER = "StructuralReviewer"
ROLE_PRODUCTION_OPERATOR = "ProductionOperator"
ROLE_QA_ENGINEER = "QAEngineer"
ROLE_FIELD_ENGINEER = "FieldEngineer"
ROLE_SERVICE_MANAGER = "ServiceManager"

ALL_ROLES = [
    ROLE_PLANT_ADMIN,
    ROLE_DESIGN_ENGINEER,
    ROLE_STRUCTURAL_REVIEWER,
    ROLE_PRODUCTION_OPERATOR,
    ROLE_QA_ENGINEER,
    ROLE_FIELD_ENGINEER,
    ROLE_SERVICE_MANAGER,
]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

ENVIRONMENTAL_RATINGS = ["IP65_FRONT_IP54_REAR", "IP65_FULL", "IP43_INDOOR"]
INSTALL_ENVIRONMENTS = ["STADIUM", "ROADSIDE", "RETAIL"]
REDUNDANCY_MODES = ["NONE", "HOT_BACKUP", "DUAL_LINK", "RING"]
COLOR_DEPTH_BITS = [8, 10, 12]
MOUNTING_TYPES = ["WALL", "FREESTANDING", "ROOF", "GANTRY"]
SERVICE_ACCESS_SIDES = ["FRONT", "REAR"]
CERTIFICATION_LEVELS = ["L1", "L2", "L3"]
CONTRACT_TIERS = ["BRONZE", "SILVER", "GOLD"]
CASE_TYPES = ["MODULE_FAULT", "BRIGHTNESS_DEGRADATION"]
CASE_SEVERITIES = ["CRITICAL", "MAJOR", "MINOR"]
ASSESSMENT_BASES = ["PRO_RATA_REMAINING_TERM", "SHORTFALL_SEVERITY"]
COLOR_BINS = ["A1", "A2", "B1", "B2"]

# engineering_state: DRAFT -> UNDER_REVIEW -> {REJECTED, APPROVED}; APPROVED terminal
ENGINEERING_DRAFT = "DRAFT"
ENGINEERING_UNDER_REVIEW = "UNDER_REVIEW"
ENGINEERING_REJECTED = "REJECTED"
ENGINEERING_APPROVED = "APPROVED"

# production_state
PRODUCTION_NOT_STARTED = "NOT_STARTED"
PRODUCTION_IN_ASSEMBLY = "IN_ASSEMBLY"
PRODUCTION_QA_COMPLETE = "QA_COMPLETE"
PRODUCTION_INSTALLED = "INSTALLED"
PRODUCTION_COMMISSIONED = "COMMISSIONED"
PRODUCTION_BLOCKED = "BLOCKED"

# service_posture
POSTURE_NORMAL = "NORMAL"
POSTURE_AT_RISK = "AT_RISK"

# revision_state
REVISION_SUBMITTED = "SUBMITTED"
REVISION_APPROVED = "APPROVED"
REVISION_REJECTED = "REJECTED"

# module_state
MODULE_MANUFACTURED = "MANUFACTURED"
MODULE_PIXEL_TESTED = "PIXEL_TESTED"
MODULE_REWORK = "REWORK"
MODULE_SCRAPPED = "SCRAPPED"
MODULE_CALIBRATED = "CALIBRATED"
MODULE_INSTALLED = "INSTALLED"
MODULE_RETURNED = "RETURNED"

# cabinet_state
CABINET_PLANNED = "PLANNED"
CABINET_IN_ASSEMBLY = "IN_ASSEMBLY"
CABINET_POPULATED = "POPULATED"
CABINET_BURN_IN = "BURN_IN"
CABINET_BURN_IN_PASSED = "BURN_IN_PASSED"
CABINET_QUARANTINED = "QUARANTINED"
CABINET_QA_PASSED = "QA_PASSED"
CABINET_MOUNTED = "MOUNTED"

# run_state
RUN_SCHEDULED = "SCHEDULED"
RUN_PASSED = "PASSED"
RUN_FAILED = "FAILED"
RUN_ABORTED = "ABORTED"

# visit_state
VISIT_SCHEDULED = "SCHEDULED"
VISIT_ON_SITE = "ON_SITE"
VISIT_CALIBRATED = "CALIBRATED"
VISIT_SIGNED_OFF = "SIGNED_OFF"
VISIT_ABORTED = "ABORTED"

# contract_state
CONTRACT_PENDING = "PENDING"
CONTRACT_ACTIVE = "ACTIVE"
CONTRACT_SUSPENDED = "SUSPENDED"

# case_state
CASE_OPEN = "OPEN"
CASE_RESPONDED = "RESPONDED"
CASE_APPROVED = "APPROVED"
CASE_DENIED = "DENIED"
CASE_FULFILLED = "FULFILLED"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_EPOCH = "2026-08-01T00:00:00.000Z"

# The canonical timeline used by the composite fixtures.
SOAK_WINDOW_START = "2026-08-02T00:00:00.000Z"
SOAK_WINDOW_END = "2026-08-03T00:00:00.000Z"
SOAK_WINDOW_END_48H = "2026-08-04T00:00:00.000Z"
VISIT_WINDOW_START = "2026-08-05T08:00:00.000Z"
VISIT_WINDOW_END = "2026-08-05T16:00:00.000Z"
VISIT_INSTANT = "2026-08-05T09:00:00.000Z"
WARRANTY_CASE_INSTANT = "2027-02-05T09:00:00.000Z"

# ---------------------------------------------------------------------------
# Rework allowance (module manufacturing)
# ---------------------------------------------------------------------------

MAX_REWORK_CYCLES = 2

# ---------------------------------------------------------------------------
# Module colour calibration
# ---------------------------------------------------------------------------

CHROMA_BIN_LETTER_THRESHOLD = 0.003
CHROMA_CALIBRATE_THRESHOLD = 0.008
CHROMA_REWORK_THRESHOLD = 0.020
BIN_DIGIT_BRIGHTNESS_FRACTION = 0.96
COLOR_BIN_RANKS = {"A1": 0, "A2": 1, "B1": 2, "B2": 3}
COLOR_BIN_RANK_TOLERANCE = 1

# ---------------------------------------------------------------------------
# Cabinet uniformity scoring
# ---------------------------------------------------------------------------

MIN_MODULES_FOR_UNIFORMITY_SCORE = 2
UNIFORMITY_BASE_SCORE = 100
UNIFORMITY_BRIGHTNESS_WEIGHT = 1.5
UNIFORMITY_CHROMA_WEIGHT = 2000
UNIFORMITY_SCORE_FLOOR = 0.00

# ---------------------------------------------------------------------------
# Burn-in acceptance floors
# ---------------------------------------------------------------------------

BURN_IN_MIN_BRIGHTNESS_NITS = 4800
BURN_IN_MIN_UNIFORMITY_PCT = 92.00
PROJECT_BLOCKED_ABORT_REASON = "PROJECT_BLOCKED"

# ---------------------------------------------------------------------------
# On-site commissioning floors
# ---------------------------------------------------------------------------

ON_SITE_BRIGHTNESS_FRACTION = 0.95
ON_SITE_MIN_UNIFORMITY_PCT = 90.00

# ---------------------------------------------------------------------------
# Structural engineering floors
# ---------------------------------------------------------------------------

WIND_LOAD_FLOOR_KPH = {"STADIUM": 160, "ROADSIDE": 200, "RETAIL": 100}

# ---------------------------------------------------------------------------
# Project pricing and bandwidth
# ---------------------------------------------------------------------------

ENVIRONMENT_SURCHARGE_PCT = {"STADIUM": 0.12, "ROADSIDE": 0.18, "RETAIL": 0.05}
REDUNDANCY_SURCHARGE_PCT = {"NONE": 0.00, "HOT_BACKUP": 0.06, "DUAL_LINK": 0.09, "RING": 0.14}
REDUNDANCY_DERATE_FACTOR = {"NONE": 1.0, "HOT_BACKUP": 0.5, "DUAL_LINK": 0.5, "RING": 0.75}
PLAYER_THROUGHPUT_MBPS = 2500
MAX_DATA_LOAD_PCT = 100.00
COLOR_CHANNELS = 3

# ---------------------------------------------------------------------------
# Service contracts
# ---------------------------------------------------------------------------

TIER_RESPONSE_HOURS = {"BRONZE": 48, "SILVER": 24, "GOLD": 8}
TIER_SPARE_MIN_BP = {"BRONZE": 100, "SILVER": 200, "GOLD": 300}
TIER_RATE_CENTS_PER_SQM = {"BRONZE": 120000, "SILVER": 190000, "GOLD": 268000}
SPARE_CARRY_CENTS_PER_MODULE = 4500
VOLUME_DISCOUNT_BREAKS_CENTS = [2000000, 5000000, 10000000]
VOLUME_DISCOUNT_PCTS = [0.00, 0.04, 0.07, 0.10]
BASIS_POINT_DIVISOR = 10000
MAX_SLA_BREACHES = 2

# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------

SEVERITY_MULTIPLIER = {"CRITICAL": 0.5, "MAJOR": 1.0, "MINOR": 2.0}
WARRANTY_TERM_MONTHS = 60
WARRANTY_GUARANTEED_DEGRADATION_PCT = 50
WARRANTY_MONTH_DAYS = 30
SECONDS_PER_DAY = 86400
SHORTFALL_SEVERITY_MULTIPLIER = 2.5
SHORTFALL_SEVERITY_CAP = 0.6

# ---------------------------------------------------------------------------
# Rounding tolerances used by the assertions
# ---------------------------------------------------------------------------

TOLERANCE_2DP = 0.01
TOLERANCE_4DP = 0.0001
TOLERANCE_6DP = 0.000001
