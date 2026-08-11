"""Domain thresholds — numeric constants from PRD calculation rules."""

OVERFILL_PCT = {"CARTRIDGE": 0.02, "PAIL": 0.01, "DRUM": 0.005}

HAZMAT = {
    "SOLVENT_THRESHOLD_PCT": 24.0,
    "PG_II_FLASH_BELOW_C": 23.0,
    "CLASS3_FLASH_BELOW_C": 60.5,
    "LQ_MAX_UNIT_ML": 5000,
}

SETTLEMENT = {
    "TIER1_GROSS_CENTS": 500000,
    "TIER1_PCT": 5,
    "TIER2_GROSS_CENTS": 1000000,
    "TIER2_PCT": 10,
}

FULL_SPECIMEN_COUNT = 5
QUICK_SPECIMEN_COUNT = 1
SPECIMEN_TOLERANCE_MPA = 2.0
EXPOSURE_HOLD_THRESHOLD_MINUTES = 30
MAX_RETEST_COUNT = 2

# Clock defaults used across scenarios (the logical clock starts at
# 2026-05-01T00:00:00Z on service startup).
CLOCK_START = "2026-05-01T00:00:00Z"
WORK_MORNING = "2026-05-01T08:00:00Z"

# Shared QA identities (opaque-role user ids used for segregation-of-duties
# separation between recording technician and releasing manager).
QA_TECH_USER_ID = "tech-1"
QA_MANAGER_USER_ID = "qm-1"
