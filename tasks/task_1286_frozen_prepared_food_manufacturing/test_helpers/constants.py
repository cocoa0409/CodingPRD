"""Domain thresholds — numeric constants from PRD calculations (§2.7, §3)."""

THRESHOLDS = {
    # recipe scale-up clamp (PRD §3.1)
    "SCALE_MIN": 0.25,
    "SCALE_MAX": 8.0,
    # freezer dwell (PRD §3.4)
    "MIN_DWELL_HOURS": 4,
    "HIGH_TEMP_FACTOR": 1.25,
    "CORE_TARGET_C": -18,
    "VERIFY_GRACE_HOURS": 2,
    # film reservation (PRD §3.5)
    "WASTE_PCT": 0.06,
    "RETAIL_METERS_PER_UNIT": 0.42,
    "FOODSERVICE_METERS_PER_UNIT": 0.35,
    # pack-out (PRD §3.5)
    "RETAIL_CASE_UNITS": 12,
    "FOODSERVICE_CASE_UNITS": 6,
    # complaint contagion (PRD §3.8)
    "LOT_QUARANTINE_THRESHOLD": 3,
    "RECIPE_RATE_THRESHOLD": 0.005,
    "WINDOW_DAYS": 90,
    # deep-storage rule (PRD §3.7)
    "DEEP_SHELF_LIFE_DAYS": 545,
    # changeover (PRD §2.10)
    "DEFAULT_CHANGEOVER_MINUTES": 45,
    "ALLERGEN_CHANGEOVER_MINUTES": 120,
}

TEST_DEFAULTS = {
    "BASE_BATCH_YIELD_UNITS": 1000,
    "PORTION_WEIGHT_G": 340,
    "SHELF_LIFE_DAYS": 365,
    "UNITS_PLANNED": 6000,
    "CELL_CAPACITY_KG": 2000,
    "CELL_MIN_LOAD_KG": 200,
    "CELL_PULL_DOWN_KG_PER_HOUR": 400,
    "CELL_SANITATION_MINUTES": 30,
    "LINE_RATE_UNITS_PER_MINUTE": 100,
    "FILM_ROLLS": 10,
    "FILM_METERS_PER_ROLL": 1000,
}

CLOCK_START = "2026-08-01T00:00:00Z"
