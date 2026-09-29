"""Numeric constants and canonical instants the PRD pins by name.

Every value here is copied from the PRD's calculation and default sections so a
test never re-derives a rate or a limit inline.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.4)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Fabrication cost model (PRD section 3.7)
# ---------------------------------------------------------------------------
SHOP_RATE_CENTS_PER_HOUR = {
    "STANDARD": 9500,
    "PRECISION": 14500,
    "CONSERVATION_GRADE": 18500,
}
MATERIAL_RATE_CENTS_PER_M2 = {
    "CASE_INTERIOR": 42500,
    "CASE_EXTERIOR": 31000,
    "MOUNT": 58000,
    "GRAPHIC": 12500,
    "INTERACTIVE_HOUSING": 47500,
}
FINISH_PCT = {"MILL": 0.0, "SATIN": 0.075, "MUSEUM_GLOSS": 0.135}
SCHEMATIC_LABOR_CONTINGENCY = 1.15
SCHEMATIC_WASTE_FACTOR = 1.20
ACTUAL_LABOR_MULTIPLIER = 1.00

# ---------------------------------------------------------------------------
# Interactive durability index (PRD section 3.8)
# ---------------------------------------------------------------------------
OPERATING_DAYS_PER_YEAR = 320
KIND_FRAGILITY = {
    "TOUCHSCREEN": 18,
    "MECHANICAL": 26,
    "PROJECTION": 14,
    "AUDIO": 8,
    "AR_HEADSET": 34,
}
W_WEAR = 0.55
W_KIND = 0.9
W_PARTS = 1.0
WEAR_PENALTY_CAP = 60.0
PARTS_TARGET_YEARS = 10
PROTOTYPE_CREDIT = 8
TIER_THRESHOLDS = {"LOW": 80, "MEDIUM": 60, "HIGH": 40}

# ---------------------------------------------------------------------------
# Case environmental envelope (PRD section 3.4)
# ---------------------------------------------------------------------------
SECURITY_RANK = {"BASIC": 1, "ENHANCED": 2, "HIGH_VALUE": 3}
SILICA_KG_PER_M3_EXCHANGE = 3.5
MAX_UV_MICROWATT_PER_LUMEN = 75.0

# ---------------------------------------------------------------------------
# Design package flow and accessibility (PRD section 3.2)
# ---------------------------------------------------------------------------
SQM_PER_VISITOR = 0.65
MIN_EGRESS_WIDTH_CM = 112
MIN_TURN_RADIUS_CM = 76
MIN_FLOW_SCORE = 60.0

# ---------------------------------------------------------------------------
# Material off-gassing verdict (PRD section 3.6)
# ---------------------------------------------------------------------------
VOC_LIMIT_MG_PER_M2_DAY = {
    "CASE_INTERIOR": 0.05,
    "MOUNT": 0.05,
    "CASE_EXTERIOR": 0.50,
    "GRAPHIC": 0.80,
    "INTERACTIVE_HOUSING": 0.60,
}
FORMALDEHYDE_LIMIT_PPM = {
    "CASE_INTERIOR": 0.02,
    "MOUNT": 0.02,
    "CASE_EXTERIOR": 0.10,
    "GRAPHIC": 0.10,
    "INTERACTIVE_HOUSING": 0.10,
}
MIN_CURE_DAYS = {
    "CASE_INTERIOR": 21,
    "MOUNT": 21,
    "CASE_EXTERIOR": 7,
    "GRAPHIC": 3,
    "INTERACTIVE_HOUSING": 5,
}

# ---------------------------------------------------------------------------
# Install window geometry (PRD section 3.9)
# ---------------------------------------------------------------------------
PRE_ACCESS_BUFFER_MIN = {
    "QUIET": 0,
    "NOISY": 15,
    "DUST_GENERATING": 30,
    "CRANE_ACCESS": 45,
}
SETTLING_BUFFER_MIN = {
    "QUIET": 0,
    "NOISY": 30,
    "DUST_GENERATING": 120,
    "CRANE_ACCESS": 60,
}
DEFAULT_DUST_SETTLING_BUFFER_MINUTES = 120
DEFAULT_MAX_CONCURRENT_CLOSURES = 2

# ---------------------------------------------------------------------------
# Closeout settlement waterfall (PRD section 3.9)
# ---------------------------------------------------------------------------
PARTS_PREMIUM_PCT_BY_MIN_YEARS = [(15, 0.005), (10, 0.012), (5, 0.028), (0, 0.045)]
RETAINAGE_TIERS_CENTS = [(20000000, 0.05), (5000000, 0.075), (0, 0.10)]
WARRANTY_RESERVE_PCT = 0.02
MIN_WARRANTY_MONTHS_BY_TIER = {"LOW": 12, "MEDIUM": 24, "HIGH": 36, "CRITICAL": 60}

# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Literal strings the PRD pins for cascaded reasons (PRD sections 3.3 and 3.6)
# ---------------------------------------------------------------------------
MATERIAL_SPEC_REJECTED = "MATERIAL_SPEC_REJECTED"
DESIGN_REVISION_REOPENED = "DESIGN_REVISION_REOPENED"
