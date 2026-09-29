"""Numeric constants and vocabularies the PRD fixes as part of the contract."""

# --------------------------------------------------------------- logical clock --
# At server startup the logical clock reads exactly this instant.
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00.000Z"

# The instant nearly every fixture chain runs at.
CLOCK_WORKING_DAY = "2026-08-05T00:00:00Z"

# ------------------------------------------------------------------- envelope --
API_REQUEST_ID_PREFIX = "req_"

# ----------------------------------------------------------------- pagination --
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ------------------------------------------------------------------ vocabularies --
EXPOSURE_CATEGORIES = ["B", "C", "D"]
SEISMIC_DESIGN_CATEGORIES = ["A", "B", "C", "D"]
PANEL_PROFILES = ["PBR", "STANDING_SEAM", "R_PANEL"]
PANEL_COLORS = ["POLAR_WHITE", "GALVALUME", "BRIGHT_RED", "EVERGREEN"]
BUILDER_TIERS = ["BRONZE", "SILVER", "GOLD"]
KIT_TYPES = ["WALK_DOOR", "OVERHEAD_DOOR", "WINDOW", "INSULATION", "VENTILATION"]
DESIGN_VARIANTS = ["ASD", "LRFD"]
COMPONENT_CLASSES = [
    "PRIMARY_FRAME_MEMBER",
    "SECONDARY_MEMBER",
    "PANEL_BUNDLE",
    "ANCHOR_PACKAGE",
    "CONNECTION_DETAIL",
]
MEMBER_TYPES = ["COLUMN", "RAFTER", "PURLIN", "GIRT", "PANEL", "ANCHOR_BOLT", "DETAIL"]
CONNECTION_TYPES = ["KNEE", "BASE", "RIDGE", "ENDWALL"]
LINE_TYPES = ["PLATE_CUT_WELD", "ROLL_FORM", "PANEL_ROLL"]
LOT_TYPES = ["PRIMARY_FRAME_FAB", "SECONDARY_ROLL_FORM", "PANEL_RUN"]
QUOTE_VARIANTS = ["PRELIMINARY", "FINAL"]
VALID_INSULATION_R_VALUES = [0, 13, 19, 25]

# The erection stage vocabulary is ordered: sequence numbers 1 through 6.
ERECTION_STAGE_SEQUENCE = {
    "ANCHORAGE": 1,
    "PRIMARY_FRAME": 2,
    "SECONDARY_FRAME": 3,
    "ROOF_PANEL": 4,
    "WALL_PANEL": 5,
    "TRIM_ACCESSORY": 6,
}
ERECTION_STAGES = list(ERECTION_STAGE_SEQUENCE)

# Erection stage to the fabrication step that produces it.
STAGE_TO_LOT_TYPE = {
    "PRIMARY_FRAME": "PRIMARY_FRAME_FAB",
    "SECONDARY_FRAME": "SECONDARY_ROLL_FORM",
    "ROOF_PANEL": "PANEL_RUN",
    "WALL_PANEL": "PANEL_RUN",
}

# Fabrication lot type to the line type able to run it.
LOT_TYPE_TO_LINE_TYPE = {
    "PRIMARY_FRAME_FAB": "PLATE_CUT_WELD",
    "SECONDARY_ROLL_FORM": "ROLL_FORM",
    "PANEL_RUN": "PANEL_ROLL",
}

# ------------------------------------------------------------- jurisdictions --
DEFAULT_MAX_AUTHORIZED_BUILDERS = 2
INITIAL_CRITERIA_REVISION = 1

# ------------------------------------------------------------------- builders --
TIER_DISCOUNT_RATES = {"BRONZE": 0.00, "SILVER": 0.03, "GOLD": 0.08}

# ------------------------------------------------- configuration lock arithmetic --
EXPOSURE_COEFFICIENTS = {"B": 0.70, "C": 0.85, "D": 1.03}
VELOCITY_PRESSURE_CONSTANT = 0.00256
WALL_PRESSURE_COEFFICIENT = 0.90
ROOF_PRESSURE_COEFFICIENT_LOW_SLOPE = 1.10
ROOF_PRESSURE_COEFFICIENT_STEEP_SLOPE = 0.95
LOW_SLOPE_PITCH_THRESHOLD = 2
HEIGHT_FACTOR_BASE_HEIGHT_FT = 20
HEIGHT_FACTOR_PER_FT = 0.01
HEIGHT_FACTOR_CAP = 1.25
PANEL_DEAD_LOADS_PSF = {"PBR": 1.20, "STANDING_SEAM": 1.60, "R_PANEL": 1.10}
FRAME_DEAD_LOAD_ALLOWANCE_PSF = 1.50
INSULATION_DEAD_LOAD_PER_R = 0.02
SNOW_ROOF_FACTOR = 0.70
SPAN_FACTOR_BASE_SPAN_FT = 80
SPAN_FACTOR_PER_FT = 0.004
FRAME_WEIGHT_BASE_PSF = 4.6

# --------------------------------------------------------------- price pipeline --
STEEL_RATE_CENTS_PER_LB = 92
PANEL_RATES_CENTS_PER_SQFT = {"PBR": 210, "STANDING_SEAM": 340, "R_PANEL": 185}
FREIGHT_ZONE_RATES_CENTS_PER_TON_MILE = {1: 18, 2: 22, 3: 27, 4: 33, 5: 41}
POUNDS_PER_TON = 2000
VOLUME_DISCOUNT_TIERS = [
    (100_000_000, 0.06),
    (50_000_000, 0.04),
    (25_000_000, 0.02),
]
TOTAL_DISCOUNT_RATE_CAP = 0.12
ADJUSTMENT_FLOOR_FRACTION_OF_SUBTOTAL = 0.20

# ------------------------------------------------------------------- quoting --
QUOTE_VALIDITY_DAYS = 30
DEFAULT_SITE_DELIVERY_CAPACITY = 2

# ------------------------------------------------------------------ designs --
MAX_DESIGN_REVISIONS = 3
ASD_COMBINATION_NAMES = [
    "ASD_D_PLUS_S",
    "ASD_D_PLUS_0_6W",
    "ASD_D_PLUS_0_75S_PLUS_0_45W",
]
LRFD_COMBINATION_NAMES = [
    "LRFD_1_4D",
    "LRFD_1_2D_PLUS_1_6S",
    "LRFD_1_2D_PLUS_1_0W_PLUS_0_5S",
]

# ------------------------------------------------------------ production lines --
DEFAULT_CHANGEOVER_BUFFER_MINUTES = 120

# ------------------------------------------------------------------- statuses --
BUILDER_STATUSES = ["PENDING_AUTHORIZATION", "AUTHORIZED", "SUSPENDED"]
CONFIGURATION_STATUSES = ["DRAFT", "LOCKED", "CRITERIA_STALE"]
QUOTE_STATUSES = ["DRAFT", "ISSUED", "ACCEPTED"]
DESIGN_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "APPROVED",
    "REVISION_REQUIRED",
    "SUPERSEDED",
    "VOIDED",
]
PACKAGE_STATUSES = ["PENDING", "SEALED", "VOIDED"]
ENGINEERING_STATUSES = ["ENG_PENDING", "ENG_APPROVED", "ENG_SEALED", "ENG_REWORK"]
PRODUCTION_STATUSES = [
    "PROD_NOT_RELEASED",
    "PROD_RELEASED",
    "PROD_IN_FABRICATION",
    "PROD_COMPLETE",
    "PROD_HOLD",
]
LOT_STATUSES = ["SCHEDULED", "COMPLETE", "CANCELLED"]
LOAD_STATUSES = ["PLANNED", "DISPATCHED", "CANCELLED"]
