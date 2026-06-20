"""Domain thresholds — numeric constants from the PRD's calculations and workflows."""

# Reconciliation tolerance (PRD 3.9): abs(variance) strictly greater than 500c -> DISPUTED.
VARIANCE_TOLERANCE_CENTS = 500

# No-show suspension threshold (PRD 3.5): count reaching three or more auto-suspends.
NOSHOW_SUSPEND_THRESHOLD = 3

# Pagination defaults (PRD 2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Modality / level-of-service ordering ranks (PRD 2.7), least to most capable.
MODALITY_RANK = {"AMBULATORY": 0, "WHEELCHAIR": 1, "STRETCHER": 2}
LOS_RANK = {"ROUTINE": 0, "URGENT": 1, "BARIATRIC": 2}

# Reusable test defaults for rate rows used by the fixtures.
TEST_DEFAULTS = {
    "AMBULATORY_RATE": {
        "modality": "AMBULATORY",
        "base_fare_cents": 1500,
        "loaded_rate_cents_per_mile": 120,
        "dwell_free_minutes": 15,
        "dwell_cents_per_minute": 40,
    },
    "WHEELCHAIR_RATE": {
        "modality": "WHEELCHAIR",
        "base_fare_cents": 2000,
        "loaded_rate_cents_per_mile": 150,
        "dwell_free_minutes": 10,
        "dwell_cents_per_minute": 50,
    },
    "STRETCHER_RATE": {
        "modality": "STRETCHER",
        "base_fare_cents": 4000,
        "loaded_rate_cents_per_mile": 250,
        "dwell_free_minutes": 10,
        "dwell_cents_per_minute": 60,
    },
}
