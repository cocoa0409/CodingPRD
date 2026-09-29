"""Domain thresholds and numeric constants of the Home-Cook Meal Marketplace API.

Every constant here is stated in PRD.md; the names mirror the PRD's own wording so
tests read as the contract reads. All money is integer cents (PRD 2.8).
"""

# --- Logical clock (PRD 2.5) ---
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- Pagination (PRD 2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Order charge breakdown (PRD 3.5 / 3.6) ---
DINER_SERVICE_FEE_PCT = 0.09
COLD_CHAIN_SURCHARGE_DOOR_CENTS = 75
COLD_CHAIN_SURCHARGE_HUB_CENTS = 40

# --- Commission tiers, read from ytd_gross_sales_cents (PRD 3.5 / 3.8) ---
COMMISSION_TIER_1_CEILING_CENTS = 1_000_000
COMMISSION_TIER_2_CEILING_CENTS = 5_000_000
COMMISSION_RATE_TIER_1 = 0.225
COMMISSION_RATE_TIER_2 = 0.185
COMMISSION_RATE_TIER_3 = 0.150

# --- Production window capacity (PRD 3.3) ---
SPOILAGE_RESERVE_PCT = 0.10

# --- Cottage-food cap classification (PRD 3.5) ---
CAP_WARNING_UTILIZATION = 0.90

# --- Routing and cold chain (PRD 3.6) ---
HOT_HANDOFF_MAX_MINUTES = 120
COLD_CHAIN_BUFFER_MINUTES = 45

# --- Safety score (PRD 3.7) ---
SEVERITY_POINTS = {
    "MINOR": 5,
    "MODERATE": 12,
    "SEVERE": 25,
    "CRITICAL": 50,
}
SAFETY_SCORE_START = 100
DECAY_STEP_1_WEEKS = 8
DECAY_STEP_2_WEEKS = 26
DECAY_WEIGHT_FULL = 1.00
DECAY_WEIGHT_HALF = 0.50
DECAY_WEIGHT_QUARTER = 0.25
OPEN_INCIDENT_WEIGHT = 0.5
SUSPEND_SCORE_CEILING = 60
WARN_SCORE_CEILING = 80

# --- Payout withholding and refund split (PRD 3.8) ---
WARNED_HOLD_PCT = 0.10
SHARED_FAULT_COOK_PCT = 0.50

# --- Menu item revision cycle (PRD 3.2) ---
MAX_REVISION_ROUNDS = 2

# --- Order placement bounds (PRD 3.5) ---
ORDER_QUANTITY_MIN = 1
ORDER_QUANTITY_MAX = 20

# --- Cook defaults (PRD 3.1) ---
DEFAULT_WEEKLY_CAPACITY_MEALS = 40

# --- Enumerations quoted by the PRD, kept as tuples for parametrised tests ---
ALLERGENS = (
    "MILK", "EGG", "FISH", "SHELLFISH", "TREE_NUT",
    "PEANUT", "WHEAT", "SOY", "SESAME",
)
KITCHEN_TYPES = ("HOME_COTTAGE", "HOME_INSPECTED", "COMMERCIAL_SHARED")
FOOD_CATEGORIES = ("TCS", "NON_TCS", "BAKED_NON_TCS")
HANDOFF_MODES = ("BATCH_COOK_AND_CHILL", "SAME_DAY_HOT")
SERVICE_MODES = ("DOOR_DELIVERY", "HUB_PICKUP")
INCIDENT_CATEGORIES = (
    "ALLERGEN_MISLABEL", "FOODBORNE_ILLNESS", "TEMP_ABUSE",
    "FOREIGN_OBJECT", "LABEL_MISSING",
)
INCIDENT_SEVERITIES = ("MINOR", "MODERATE", "SEVERE", "CRITICAL")
REFUND_REASONS = (
    "SAFETY", "QUALITY", "LATE", "COOK_CANCELLED",
    "PLATFORM_ERROR", "WINDOW_CANCELLED",
)
FAULT_PARTIES = ("COOK", "PLATFORM", "SHARED")
PAYOUT_BASES = ("ACCRUAL_WINDOW", "CASH_HANDOFF")

# Label keys used across the suite; the state policies created by the factories
# require exactly this set (PRD 3.1 label_required_fields).
STANDARD_LABEL_FIELDS = [
    "cook_name",
    "ingredients",
    "allergens",
    "net_weight",
    "cottage_food_disclaimer",
]
