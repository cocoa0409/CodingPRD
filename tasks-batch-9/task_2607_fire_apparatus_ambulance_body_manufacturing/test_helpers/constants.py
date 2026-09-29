"""Numeric thresholds, boundaries and defaults stated by the PRD."""

# ─── Logical clock ────────────────────────────────────────────────────────

# Before the clock has ever been set it reads exactly this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ─── Pagination ───────────────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ─── Program field ranges ─────────────────────────────────────────────────

MIN_BASE_YEAR = 2020
MAX_BASE_YEAR = 2030
MIN_BASE_UNIT_PRICE_CENTS = 1_000_000
MIN_ESCALATION_INDEX_PCT = 0.0
MAX_ESCALATION_INDEX_PCT = 15.0
MIN_MAX_OPTION_UNITS = 0
MAX_MAX_OPTION_UNITS = 20
NAME_MAX_LENGTH = 120
AGENCY_NAME_MAX_LENGTH = 120

# The award year window: base_year through base_year + 5 inclusive.
ESCALATION_WINDOW_YEARS = 5

# ─── Fiscal ceilings ──────────────────────────────────────────────────────

# The soft ceiling is ninety percent of the hard contract ceiling; committed
# money landing exactly on it is not a breach because the comparison is strict.
SOFT_CEILING_FRACTION = 0.90

# ─── Award pricing ────────────────────────────────────────────────────────

OPTION_PREMIUM_PCT = 3.5
BOND_TIER_1_CEILING_CENTS = 50_000_000
BOND_TIER_2_CEILING_CENTS = 90_000_000
BOND_RATE_TIER_1_PCT = 1.25
BOND_RATE_TIER_2_PCT = 1.00
BOND_RATE_TIER_3_PCT = 0.75

# ─── Specification gates ──────────────────────────────────────────────────

MANDATORY_CLAUSE_WEIGHT = 3
OPTIONAL_CLAUSE_WEIGHT = 1
MAX_RESTRICTIVE_CLAUSE_RATIO_PCT = 40.00
MIN_COMPLIANCE_SCORE_STRICT = 75.00
CLAUSE_CODE_MAX_LENGTH = 24
REQUIREMENT_TEXT_MAX_LENGTH = 500
SPEC_TITLE_MAX_LENGTH = 160
VOID_DISPOSITION_NOTE = "voided by supersede"

# ─── Axle load model ──────────────────────────────────────────────────────

MIN_GVWR_KG = 4_000
MAX_GVWR_KG = 40_000
MIN_FRONT_AXLE_RATING_KG = 1_500
MAX_FRONT_AXLE_RATING_KG = 12_000
MIN_REAR_AXLE_RATING_KG = 2_000
MAX_REAR_AXLE_RATING_KG = 30_000
MIN_BASE_CURB_KG = 500
MIN_CREW_SEAT_COUNT = 0
MAX_CREW_SEAT_COUNT = 8

CREW_MASS_PER_SEAT_KG = 80
FRONT_AXLE_SEAT_COUNT = 2
FRONT_PAYLOAD_SHARE_CAP_KG = 450

# Payload capacity: the smaller of the fixed cap and the floored percentage
# of the chassis rating, by apparatus family.
PAYLOAD_CAP_KG = {
    "PUMPER": 3_400,
    "AERIAL": 1_800,
    "AMBULANCE": 900,
}
PAYLOAD_PCT_OF_GVWR = {
    "PUMPER": 28,
    "AERIAL": 12,
    "AMBULANCE": 20,
}

# ─── Supplier slot lines and reservations ─────────────────────────────────

MIN_TOTAL_SLOT_COUNT = 1
MAX_TOTAL_SLOT_COUNT = 50
DEFAULT_CHANGEOVER_BUFFER_DAYS = 7
MIN_CHANGEOVER_BUFFER_DAYS = 0
MAX_CHANGEOVER_BUFFER_DAYS = 30
SUPPLIER_NAME_MAX_LENGTH = 120

# ─── Plant bays and inspection trips ──────────────────────────────────────

BAY_NAME_MAX_LENGTH = 80
MIN_MAX_CONCURRENT_VISITORS = 1
MAX_MAX_CONCURRENT_VISITORS = 60
MIN_COMMITTEE_SIZE = 1
MAX_COMMITTEE_SIZE = 40

# ─── Change orders ────────────────────────────────────────────────────────

MIN_LINE_ITEMS = 1
MAX_LINE_ITEMS = 12
MIN_QUANTITY = 1
MIN_UNIT_COST_CENTS = 0
MIN_MARKUP_PCT = 0.0
MAX_MARKUP_PCT = 22.0
TAX_RATE_PCT = 6.5
MIN_WEIGHT_DELTA_KG = -2_000
MAX_WEIGHT_DELTA_KG = 2_000

# ─── Delivery and warranty ────────────────────────────────────────────────

MIN_TRAINING_HOURS = 0.0
MAX_TRAINING_HOURS = 200.0
MIN_WARRANTY_MONTHS = 12
MAX_WARRANTY_MONTHS = 120
WARRANTY_DEFERRAL_DAYS = 30
TRAINING_HOURS_ACTIVATION_THRESHOLD = 16.0

# ─── Test standards by apparatus family ───────────────────────────────────

VALID_TEST_STANDARDS = {
    "PUMPER": ["NFPA_1901"],
    "AERIAL": ["NFPA_1911"],
    "AMBULANCE": ["NFPA_1917", "AMD_STD_003"],
}
