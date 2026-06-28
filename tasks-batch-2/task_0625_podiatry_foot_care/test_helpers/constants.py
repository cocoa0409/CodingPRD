"""Domain thresholds — numeric constants from the PRD's calculations and defaults."""

# Practice-level policy defaults (PRD §3.1).
DEFAULT_ROUTINE_CARE_MIN_INTERVAL_DAYS = 61
DEFAULT_FEE_SPLIT_MEDICARE_PCT = 0.80
DEFAULT_CLEANUP_BUFFER_MINUTES = 15

# Recall cadence by diabetic-foot risk category (PRD §3.10).
RECALL_INTERVAL_BY_CATEGORY = {0: 365, 1: 180, 2: 90, 3: 30}

# Logical clock startup default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# Routine procedure kinds subject to the Medicare frequency rule (PRD §3.4).
ROUTINE_KINDS = ["ROUTINE_NAIL_DEBRIDEMENT", "ROUTINE_CALLUS_PARING"]
NON_ROUTINE_KINDS = ["WOUND_DEBRIDEMENT", "NAIL_AVULSION"]

# A syntactically valid UUID that names no existing row.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
