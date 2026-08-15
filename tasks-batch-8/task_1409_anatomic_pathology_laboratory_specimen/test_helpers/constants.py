"""Domain thresholds and numeric constants stated in the PRD."""

# Turnaround allowance in hours per complexity class (PRD case intake section).
TAT_HOURS = {
    "SIMPLE": 48,
    "MODERATE": 72,
    "COMPLEX": 120,
    "HIGH_COMPLEXITY": 168,
}

# Workload weights per complexity class, plus the per-accepted-consult weight.
COMPLEXITY_WEIGHT = {
    "SIMPLE": 1,
    "MODERATE": 2,
    "COMPLEX": 3,
    "HIGH_COMPLEXITY": 5,
}
CONSULT_WEIGHT = 2

# Complexity score ingredients.
SPECIMEN_BASE_WEIGHT = {
    "BIOPSY": 1,
    "EXCISION": 2,
    "RESECTION": 3,
    "CYTOLOGY": 0,
}
BLOCK_WEIGHT = 1.0
SLIDE_WEIGHT = 0.5
STAIN_WEIGHT = 2.0
TIER_MODERATE_MIN = 4.0
TIER_COMPLEX_MIN = 10.0
TIER_HIGH_COMPLEXITY_MIN = 20.0

# Tissue accounting.
MIN_RECUTABLE_PCT = 5.0
BLOCK_START_TISSUE_PCT = 100.0

# Cold-ischemia gates in minutes for cold-sensitive stains.
COLD_ISCHEMIA_LIMIT_MINUTES = {
    "HER2_IHC": 60,
    "PD_L1": 90,
}

# Reflex engine.
MAX_REFLEX_CHAIN_DEPTH = 3

# Discrepancy rates.
SEVERITY_WEIGHT = {
    "LEVEL_1": 1,
    "LEVEL_2": 3,
    "LEVEL_3": 5,
}
DISCREPANCY_WINDOW_DAYS = 365

# Coverage windows.
UNAVAILABILITY_BUFFER_MINUTES = 60

# Logical clock startup value.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Shared timestamp defaults for payloads (all in the logical-clock era).
DEFAULT_DOB = "1980-01-01"
DEFAULT_COLLECTION = "2026-08-03T09:00:00Z"
DEFAULT_RECEIVED = "2026-08-03T10:00:00Z"
DEFAULT_CONSULT_DUE = "2026-08-10T00:00:00Z"
DEFAULT_LOAN_OUT = "2026-08-10T00:00:00Z"
DEFAULT_LOAN_DUE_BACK = "2026-08-20T00:00:00Z"
