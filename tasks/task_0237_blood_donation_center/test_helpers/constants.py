"""Domain thresholds — numeric constants from the PRD calculations (§3.5, §3.7, §3.4).

Generic NON_EXISTENT_UUID comes from the framework, re-exported via __init__.
"""

# Inter-donation interval days by donation type (PRD §3.5).
INTERVAL_DAYS = {
    "WHOLE": 56,
    "PLASMA": 28,
    "PLATELET": 7,
}

# Shelf-life days by component (PRD §3.7).
SHELF_DAYS = {
    "RBC": 42,
    "PLASMA": 365,
    "WHOLE_BLOOD": 35,
    "PLATELET": 5,
}

# Health screening constants (PRD §3.4).
SCREENING = {
    "UNISEX_HGB_FLOOR": 12.5,
    "MIN_WEIGHT_KG": 50,
    "BP_SYS_MIN": 90,
    "BP_SYS_MAX": 180,
    "PULSE_MIN": 50,
    "PULSE_MAX": 100,
    "HEMOGLOBIN_DEFERRAL_DAYS": 90,
    "TRAVEL_DEFERRAL_DAYS": 21,
    "MED_DEFERRAL_DAYS": 14,
}

# Plasma volume caps (PRD §3.5).
PLASMA = {
    "PER_CAP_LOW": 690,       # weight band [50, 68)
    "PER_CAP_MID": 825,       # weight band [68, 79)
    "PER_CAP_HIGH": 880,      # weight band [79, +inf)
    "WEIGHT_BAND_LOW_MAX": 68,
    "WEIGHT_BAND_MID_MAX": 79,
    "ANNUAL_PLASMA_LITERS_CAP": 2.00,
    "ROLLING_WINDOW_DAYS": 365,
}

SECONDS_PER_DAY = 86400

# Pagination defaults (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# The deterministic center clock starts here (PRD §2.4 / §3.1).
EPOCH = "1970-01-01T00:00:00.000Z"
