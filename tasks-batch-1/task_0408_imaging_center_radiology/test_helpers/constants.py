"""Domain thresholds — numeric constants from PRD calculations (§3.3, §3.6, §3.7).

NON_EXISTENT_UUID comes from the framework barrel export.
"""

# Contrast screening renal gate (PRD §3.3): eGFR strictly below 30 blocks.
EGFR_MIN = 30

# RVU credit factors (PRD §3.6).
STAT_MULTIPLIER = 1.5
CONTRAST_ADDON = 0.75
AMEND_FACTOR = 0.5

# Turnaround targets in minutes by (priority, modality_type) (PRD §3.6).
STAT_TARGET_MIN = {"MRI": 60, "CT": 45, "XRAY": 30, "US": 45}
ROUTINE_TARGET_MIN = {"MRI": 1440, "CT": 720, "XRAY": 240, "US": 480}

# Center defaults (PRD §3.1).
DEFAULT_CRITICAL_ACK_SLA_MINUTES = 60
DEFAULT_REPEAT_RATE_THRESHOLD_PCT = 8.0

# A non-existent but well-formed UUID for reference-not-found tests.
RANDOM_UUID = "00000000-0000-4000-8000-000000000000"
