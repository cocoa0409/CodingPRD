"""Every named constant of SCAFFOLD §1.3 / PRD §3."""

from decimal import Decimal

# --- storm_targeting_score ---------------------------------------------------
SEVERITY_WEIGHT_GROUND_TRUTHED = Decimal("2.2")
SEVERITY_WEIGHT_MODELED = Decimal("1.6")
SEVERITY_DIVISOR = Decimal("2")
HAIL_MM_CAP = 60
POPULATION_CAP = 250000
POPULATION_DIVISOR = Decimal("5000")
SWATH_BONUS_KM2_THRESHOLD = 400
SWATH_BONUS_POINTS = Decimal("8")
COMPETITOR_PENALTY_PER_SHOP = Decimal("1.5")
COMPETITOR_CAP = 12
TARGETING_SCORE_FLOOR = 60

# --- vehicle_repair_estimate -------------------------------------------------
DENT_TIER_LIGHT_MAX = 15
DENT_TIER_MEDIUM_MAX = 50
TIER_MULT_LIGHT = Decimal("1.00")
TIER_MULT_MEDIUM = Decimal("0.85")
TIER_MULT_HEAVY = Decimal("0.70")
ALUMINUM_MULTIPLIER = Decimal("1.30")

# --- repairability_triage ----------------------------------------------------
TOTAL_LOSS_THRESHOLD_PCT = Decimal("0.75")

# --- vehicle_net_billable ----------------------------------------------------
DISCOUNT_TIER_1_FLOOR_CENTS = 250000
DISCOUNT_TIER_2_FLOOR_CENTS = 500000
DISCOUNT_PCT_TIER_0 = Decimal("0.00")
DISCOUNT_PCT_TIER_1 = Decimal("0.02")
DISCOUNT_PCT_TIER_2 = Decimal("0.04")

# --- supplement_gate ---------------------------------------------------------
SUPPLEMENT_AUTO_APPROVE_FLOOR_CENTS = 15000
SUPPLEMENT_CUMULATIVE_CAP_PCT = Decimal("0.40")
SUPPLEMENT_MAX_ROUNDS = 3

# --- crew_pay_split ----------------------------------------------------------
LABOR_POOL_PCT = Decimal("0.55")
POOL_SPLIT_PCT = Decimal("0.50")
TIER_WEIGHT = {
    "APPRENTICE": Decimal("0.80"),
    "JOURNEYMAN": Decimal("1.00"),
    "MASTER": Decimal("1.25"),
}

# --- facility_posture --------------------------------------------------------
REQUIRED_PERMIT_TYPES = ("TEMP_BUSINESS_LICENSE", "ZONING_USE")

# --- rental_exposure ---------------------------------------------------------
RENTAL_MINIMUM_DAYS = 1

# --- facility_throughput_projection -----------------------------------------
VEHICLES_PER_TECH_PER_DAY = Decimal("1.5")

# --- misc --------------------------------------------------------------------
MAX_REWORK_COUNT = 2
REST_BUFFER_DAYS = 1
WARRANTY_DAYS = 90

# --- enums -------------------------------------------------------------------
SWATH_CONFIDENCE = ("MODELED", "GROUND_TRUTHED")
PAY_MODELS = ("FLAT", "POOLED")
PERMIT_TYPES = ("TEMP_BUSINESS_LICENSE", "ZONING_USE", "FIRE_OCCUPANCY", "SIGNAGE")
PERMIT_STATUSES = ("PENDING", "APPROVED", "DENIED", "EXPIRED")
SKILL_TIERS = ("APPRENTICE", "JOURNEYMAN", "MASTER")
PANEL_CODES = (
    "HOOD", "ROOF", "DECK_LID", "LEFT_FENDER", "RIGHT_FENDER",
    "LEFT_FRONT_DOOR", "RIGHT_FRONT_DOOR", "LEFT_REAR_DOOR", "RIGHT_REAR_DOOR",
    "LEFT_QUARTER", "RIGHT_QUARTER",
)
DENT_SIZE_CLASSES = ("DIME", "NICKEL", "QUARTER", "HALF_DOLLAR")
SUPPLEMENT_REASON_CODES = (
    "HIDDEN_DAMAGE", "ADDITIONAL_PANEL", "R_AND_I_ADDITION", "PARTS_PRICE_CHANGE",
)

OPEN_REPAIR_STATUSES = (
    "INTAKE", "ESTIMATED", "TRIAGED", "IN_REPAIR", "QC_PENDING", "QC_FAILED",
    "READY", "TOTAL_LOSS_PENDING",
)
TERMINAL_REPAIR_STATUSES = ("RELEASED", "TOWED_OUT")
