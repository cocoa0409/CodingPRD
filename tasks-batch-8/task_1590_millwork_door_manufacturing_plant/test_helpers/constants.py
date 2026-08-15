"""Domain thresholds and constants from PRD §2.7, §2.8, §3.2–§3.7."""

# PRD §3.2 — budget-variant pricing constants
SPECIES_BASE_PRICE_CENTS = {
    "OAK": 42000,
    "MAPLE": 38000,
    "CHERRY": 51000,
    "WALNUT": 56000,
    "PAINT_GRADE": 29000,
}
BUDGET_WASTE_PCT = 1.12
BUDGET_FINISH_PCT = 1.08
BUDGET_HARDWARE_PER_OPENING = 5500
BUDGET_FREIGHT_FLAT = 25000

# PRD §3.3 — contract-variant pricing constants
SPECIES_WASTE = {
    "OAK": 0.14,
    "MAPLE": 0.10,
    "CHERRY": 0.18,
    "WALNUT": 0.20,
    "PAINT_GRADE": 0.08,
}
HARDWARE_TEMPLATE_CHARGE_PER_OPENING = 8500
HARDWARE_INSTALLER_CREDIT_PER_OPENING = -4000
FIRE_SURCHARGE_PER_LEAF = {
    "MIN_20": 6000,
    "MIN_45": 9500,
    "MIN_90": 14000,
}

# PRD §3.3 — freight fee schedule (keyed on merchandise_total_cents)
FREIGHT_FLAT = 25000
FREIGHT_TIER1_MAX = 500000
FREIGHT_TIER2_MAX = 2000000
FREIGHT_MID_PCT = 0.04
FREIGHT_HIGH_PCT = 0.03

# PRD §3.5 — sheen conformance
SHEEN_TOLERANCE_GU = 2.0
SHEEN_TARGET_GU = {
    "MATTE": 15,
    "SATIN": 35,
    "SEMI_GLOSS": 60,
    "HIGH_GLOSS": 85,
}

# PRD §3.4 — species families and changeover buffer
CHANGEOVER_HOURS = 2
SPECIES_FAMILY = {
    "PAINT_GRADE": "PAINT",
    "OAK": "STAIN",
    "MAPLE": "STAIN",
    "CHERRY": "STAIN",
    "WALNUT": "STAIN",
}

# PRD §3.5 — finish family mapping
FINISH_FAMILY = {
    "PAINT": "PAINT",
    "CLEAR_COAT": "CLEAR_STAIN",
    "STAIN": "CLEAR_STAIN",
}

# PRD §3.5 — minimum cure window in shop-hours
MIN_CURE_WINDOW_HOURS = 4

# PRD §2.9 — rating rank and label-series correspondence
FIRE_RATING_RANK = {"NONE": 0, "MIN_20": 1, "MIN_45": 2, "MIN_90": 3}
RATING_TO_LABEL_SERIES = {
    "MIN_20": "UL_20MIN",
    "MIN_45": "UL_45MIN",
    "MIN_90": "UL_90MIN",
}

TEST_DEFAULTS = {
    "SITE_ADDRESS": "1 Main St",
    "WIDTH_IN": 36,
    "HEIGHT_IN": 84,
    "REQUIRED_ON_SITE_DATE": "2026-10-01",
    "DEPARTURE_DATE": "2026-10-02",
    "SITE_ARRIVAL_DATE": "2026-10-04",
}
