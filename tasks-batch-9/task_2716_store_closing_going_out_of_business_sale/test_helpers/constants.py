"""Domain thresholds and shared test payload defaults from the PRD prose."""

# Per-category projected sell-through rates used by the projected recovery
# estimate.
CATEGORY_SELL_THROUGH_RATE = {
    "APPAREL": 0.85,
    "FOOTWEAR": 0.80,
    "HOME": 0.70,
    "ELECTRONICS": 0.95,
    "JEWELRY": 0.60,
    "SEASONAL": 0.90,
}

# Settlement liquidator fee tier table, keyed on the original-merchandise
# recovery ratio.
FEE_TIER_LOW_RATE = 0.0200
FEE_TIER_MID_RATE = 0.0350
FEE_TIER_HIGH_RATE = 0.0500
FEE_TIER_MID_FLOOR = 0.60
FEE_TIER_HIGH_FLOOR = 0.80

# Markdown checkpoint escalation.
ESCALATION_BAND = 0.05
ESCALATION_STEP_PCT = 0.05
MAX_ESCALATION_PCT = 0.20
MAX_DISCOUNT_PCT = 0.9000

# Retention bonus settlement.
MIN_ATTENDANCE_RATE = 0.90

# Lease surrender.
HOLDOVER_MULTIPLIER = 1.5

# Compliance posture thresholds.
RESTRICTED_STRIKES_AT = 1
FROZEN_STRIKES_AT = 3

# Augmentation delivery slot capacity.
MAX_CONSIGNMENTS_PER_DELIVERY_DAY = 2

# Lease negotiation bound.
MAX_NEGOTIATION_ROUNDS = 3

# Pagination.
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# The logical clock's default reading before any client sets it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# The clock instant every fixture pins so date arithmetic is deterministic.
BASE_CLOCK_UTC = "2026-09-15T00:00:00Z"
BASE_DATE = "2026-09-15"

TEST_DEFAULTS = {
    "RETAILER_NAME": "Halloran Stores",
    "LIQUIDATOR_NAME": "Meridian Liquidation",
    "SALE_START_DATE": "2026-09-15",
    "TARGET_END_DATE": "2026-11-30",
    "JURISDICTION_CODE": "NY",
    "JURISDICTION_NAME": "New York",
    "STORE_CODE": "ST-001",
    "ADDRESS_LINE": "100 Main Street",
    "LICENSE_NUMBER": "NY-GOB-1001",
    "LICENSE_PERIOD_START": "2026-09-15",
    "LICENSE_PERIOD_END": "2026-10-14",
    "SUPPLIER_NAME": "Northgate Supply",
    "LANDLORD_NAME": "Cornice Realty",
}
