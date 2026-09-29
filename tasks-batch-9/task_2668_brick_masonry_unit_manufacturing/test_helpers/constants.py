"""
Domain constants for the brick and masonry unit manufacturing API.

Every value here is transcribed from the PRD narrative (sections 2 and 3) or the
endpoint / error tables (sections 4 and 5). Tests import these instead of
hard-coding literals so that a PRD reading is traceable to a single symbol.
"""

# --- Logical clock (PRD 2.4, 4) --------------------------------------------
# "The startup default is exactly 2026-08-01T00:00:00Z."
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_PATH = "/_clock/set_current_utc"

# --- Pagination (PRD 2.3) --------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Enumerated vocabularies (PRD 2.11) -----------------------------------
PLANT_STATUSES = ["ACTIVE", "IDLED"]
CLAY_PIT_STATUSES = ["OPEN", "SUSPENDED", "DEPLETED"]
MATERIAL_TYPES = ["CLAY", "SHALE"]
FORMULATION_STATUSES = ["DRAFT", "QUALIFIED", "RETIRED"]
KILN_STATUSES = ["AVAILABLE", "MAINTENANCE"]
KILN_CAR_STATUSES = ["IDLE", "SET", "IN_KILN", "OUT_OF_SERVICE"]
PRODUCTION_RUN_STATUSES = ["SETTING", "SET", "HELD", "LOADED", "FIRED", "SCRAPPED"]
KILN_RUN_STATUSES = ["SCHEDULED", "FIRING", "GRADED", "ABORTED"]
FIRED_LOT_STATUSES = ["AVAILABLE", "RESERVED", "CONSUMED", "QUARANTINED", "SCRAP"]
FIRING_GRADES = ["ON_COLOR", "OFF_COLOR_SALVAGE", "OVERFIRE_SCRAP", "UNDERFIRE_SCRAP"]
ORDER_FULFILLMENT_STATUSES = [
    "DRAFT", "ASSIGNED", "IN_BLENDING", "PACKAGED", "DELIVERED", "CANCELLED",
]
ORDER_FREIGHT_STATUSES = ["UNQUOTED", "ESTIMATED", "FINALIZED", "INVOICED", "WAIVED"]
BLEND_STATUSES = ["DRAFT", "COMPOSED", "CERTIFIED", "RELEASED", "VOID"]
BLEND_COMPONENT_STATUSES = ["ALLOCATED", "VOIDED", "CONSUMED"]
BLEND_COMPONENT_SOURCES = ["MANUAL", "AUTO_FILL"]
PANEL_STATUSES = [
    "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "EXPIRED", "WITHDRAWN",
]
COLOR_FAMILIES = ["RED", "BUFF", "GRAY", "BROWN"]
TEXTURES = ["WIRE_CUT", "SMOOTH", "SAND_FACED", "TUMBLED"]
DURABILITY_GRADES = ["SW", "MW", "NW"]
UNLOADING_EQUIPMENT = ["CUSTOMER_FORKLIFT", "TRUCK_MOUNTED_FORKLIFT", "CRANE"]
BANDING_TYPES = ["STEEL", "POLY"]

# --- Body blend chemistry (PRD 3.2) ---------------------------------------
ABSORPTION_BASE = 18.0
IRON_ABSORPTION_COEFF = 1.2
SHALE_ABSORPTION_COEFF = 0.08
LIME_ABSORPTION_COEFF = 1.5
ABSORPTION_MIN = 2.0
ABSORPTION_MAX = 22.0
SW_MAX_ABSORPTION = 8.00
MW_MAX_ABSORPTION = 14.00
COMPONENT_SHARE_TOTAL_REQUIRED = 100.00

# --- Green yield (PRD 3.3) ------------------------------------------------
GREEN_HANDLING_LOSS_BP = 350          # 3.50 percent, expressed in basis points
SETTING_LOSS_UNITS_PER_CAR = 12
GREEN_LOSS_HOLD_PCT = 6.00

# --- Firing colour development (PRD 3.4) ---------------------------------
CDI_TEMP_ORIGIN_C = 900
CDI_TEMP_COEFF = 0.62
CDI_SOAK_COEFF = 4.0
POSITION_TEMP_GRADIENT_C = 6.0
OVERFIRE_CDI_MARGIN = 6.00
UNDERFIRE_CDI_MARGIN = 6.00
ON_COLOR_CDI_BAND = 3.00
COLOR_INDEX_MIDPOINT = 50.0
COLOR_INDEX_CDI_SLOPE = 3.2
COLOR_INDEX_MIN = 0.0
COLOR_INDEX_MAX = 100.0

# --- Durability ranking (PRD 3.5, 3.7) -----------------------------------
DURABILITY_RANK = {"SW": 3, "MW": 2, "NW": 1}

# --- Blend colour profile (PRD 3.7) --------------------------------------
BLEND_SPAN_CEILING = 12.00

# --- Freight (PRD 3.5, 3.8) ----------------------------------------------
UNIT_WEIGHT_LB = 4.5
LB_PER_TON = 2000
PALLET_TARE_LB = 60
PALLET_UNITS = 500
BAND_WEIGHT_LB = {"STEEL": 3.0, "POLY": 1.2}
SURCHARGE_TIER_1_CEILING_CENTS = 50000
SURCHARGE_TIER_2_CEILING_CENTS = 150000
SURCHARGE_TIER_1_PCT = 6.5
SURCHARGE_TIER_2_PCT = 4.5
SURCHARGE_TIER_3_PCT = 3.0

# --- Lead time (PRD 3.5) -------------------------------------------------
BASE_LEAD_DAYS = 14
SPECIAL_ORDER_LEAD_DAYS = 28
PANEL_APPROVAL_LEAD_DAYS = 7

# --- Sample panels (PRD 3.6) -------------------------------------------
PANEL_APPROVAL_VALID_DAYS = 180
PANEL_MAX_REVISION_ROUNDS = 3
PANEL_EQUIVALENCE_MAX_HOPS = 16
