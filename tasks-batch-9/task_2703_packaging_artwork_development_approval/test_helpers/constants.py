"""Domain thresholds and rate tables stated in the PRD's business narratives."""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Mandatory element verification
# ---------------------------------------------------------------------------
ELEMENT_ORDER = [
    "NET_CONTENTS",
    "INGREDIENT_STATEMENT",
    "ALLERGEN_STATEMENT",
    "DATE_CODE_ZONE",
    "BARCODE",
    "RECYCLING_MARK",
    "ADDRESS_BLOCK",
]

ELEMENT_SEVERITY = {
    "NET_CONTENTS": "CRITICAL",
    "INGREDIENT_STATEMENT": "CRITICAL",
    "ALLERGEN_STATEMENT": "CRITICAL",
    "DATE_CODE_ZONE": "MAJOR",
    "BARCODE": "MAJOR",
    "RECYCLING_MARK": "MINOR",
    "ADDRESS_BLOCK": "MINOR",
}

ELEMENT_SEVERITY_WEIGHT = {"CRITICAL": 25.0, "MAJOR": 10.0, "MINOR": 4.0}
WAIVED_WEIGHT_FACTOR = 0.5

SCHEME_FACTOR = {"FDA_FOOD": 1.00, "EU_FIC": 1.10, "HEALTH_CANADA": 1.05}
MARKET_PENALTY_POINTS = 2.5
LANGUAGE_PENALTY_POINTS = 1.5
COMPLIANCE_SCORE_FLOOR = 70.0

# ---------------------------------------------------------------------------
# Version revision cycle
# ---------------------------------------------------------------------------
REVISION_CYCLE_CAP = 3

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
STAGE_PLAN = [
    {"stage_no": 1, "mode": "PARALLEL", "disciplines": ["BRAND", "REGULATORY"]},
    {"stage_no": 2, "mode": "SEQUENTIAL", "disciplines": ["LEGAL"]},
    {"stage_no": 3, "mode": "SEQUENTIAL", "disciplines": ["QUALITY"]},
]
FINAL_STAGE_NO = 3
APPROVING_DECISIONS = ["APPROVED", "CONDITIONAL"]
DISCIPLINE_ROLE = {
    "BRAND": "BrandReviewer",
    "LEGAL": "LegalReviewer",
    "REGULATORY": "RegulatoryReviewer",
    "QUALITY": "QualityReviewer",
}

# ---------------------------------------------------------------------------
# Assets, proofs and press checks
# ---------------------------------------------------------------------------
STANDARD_UNIT_COST_CENTS = {"CARTON": 42, "LABEL": 9, "FILM": 15, "SHIPPER": 120}

DELTA_E_TOLERANCE = {
    "G7_MASTER": {
        "COATED_PAPER": 2.0,
        "UNCOATED_PAPER": 3.0,
        "FILM": 3.5,
        "METALLIZED": 4.0,
    },
    "ISO12647": {
        "COATED_PAPER": 2.5,
        "UNCOATED_PAPER": 3.5,
        "FILM": 4.0,
        "METALLIZED": 4.5,
    },
}
BRAND_CRITICAL_TIGHTENING = 0.5
PRESS_CHECK_BUFFER_MINUTES = 120

# ---------------------------------------------------------------------------
# Plate orders
# ---------------------------------------------------------------------------
PLATE_RATE_1_CENTS = 18000
PLATE_RATE_2_CENTS = 15500
PLATE_RATE_3_CENTS = 13000
PLATE_BAND_1_LIMIT = 4
PLATE_BAND_2_LIMIT = 8
PLATE_SETUP_FEE_SMALL_CENTS = 60000
PLATE_SETUP_FEE_LARGE_CENTS = 90000
EXPEDITE_PCT = 0.25

# ---------------------------------------------------------------------------
# Inventory runouts and changeover
# ---------------------------------------------------------------------------
WEEK_LENGTH_DAYS = 7
TRAILING_WINDOW_RECORDS = 3
MIN_TRAILING_AVG_QTY = 1
REWORK_UNIT_CENTS = 18
CHANGEOVER_TIER_1_CEILING_CENTS = 500000
CHANGEOVER_TIER_2_CEILING_CENTS = 2000000
CHANGEOVER_TIER_1_PCT = 0.05
CHANGEOVER_TIER_2_PCT = 0.08
CHANGEOVER_TIER_3_PCT = 0.12

# ---------------------------------------------------------------------------
# Error escapes and vendor standing
# ---------------------------------------------------------------------------
RECOVERY_LINE_ORDER = ["reprint", "scrap", "freight", "investigation"]
SCRAP_HANDLING_CENTS = 7
INVESTIGATION_FEE_EARLY_CENTS = 60000
INVESTIGATION_FEE_LATE_CENTS = 150000
LATE_DISCOVERY_STAGES = ["DISTRIBUTION", "MARKET"]
PENALTY_POINTS_PER_1000_UNITS = 2.0
ESCAPE_STAGE_PENALTY_POINTS = {
    "PRESS": 2.0,
    "PACKING": 4.0,
    "DISTRIBUTION": 8.0,
    "MARKET": 10.0,
}
PENALTY_CAP_POINTS = 40.0
PRINTER_PROBATION_SCORE = 70.0

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------
AUTO_CANCEL_REASON = "SUPERSEDED_BY_NEW_ARTWORK"
ELEMENT_ABSENT_DETAIL = "ELEMENT_ABSENT"
ELEMENT_OK_DETAIL = "OK"
