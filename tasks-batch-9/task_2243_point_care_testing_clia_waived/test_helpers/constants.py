"""Domain thresholds, defaults and pinned literals from the PRD."""

# The logical clock reads exactly this at server startup (PRD 2.4).
CLOCK_STARTUP = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DATE = "2026-08-01"

THRESHOLDS = {
    # Posture derivation (PRD 2.10)
    "POSTURE_SUSPEND_WEIGHT": 16.0,
    "POSTURE_RESTRICT_WEIGHT": 6.0,
    "POSTURE_RESTRICT_HELD_RESULTS": 3,
    # Deficiency severity bases (PRD 3.8)
    "WEIGHT_CONDITION_LEVEL": 8.00,
    "WEIGHT_STANDARD_LEVEL": 3.00,
    "WEIGHT_ADVISORY": 1.00,
    "REPEAT_MULTIPLIER": 2.0,
    # Readiness penalties (PRD 3.9)
    "DEFICIENCY_PENALTY_FACTOR": 2.5,
    "DEFICIENCY_PENALTY_CAP": 50.0,
    "COMPETENCY_PENALTY_FACTOR": 0.25,
    "COMPETENCY_PENALTY_CAP": 25.0,
    "QC_PENALTY_FACTOR": 0.40,
    "QC_PENALTY_CAP": 20.0,
    "PT_UNIT_MODERATE": 6,
    "PT_UNIT_WAIVED": 3,
    "PT_PENALTY_CAP": 18.0,
    "PERFECT_SCORE": 100.00,
    # Proficiency testing (PRD 3.7)
    "PT_PASS_THRESHOLD": 80.00,
    "PT_FAIL_WINDOW": 3,
    "PT_SEVERE_FAIL_COUNT": 2,
    # Competency (PRD 3.3)
    "MIN_METHODS_DEMONSTRATED": 6,
    "CONSECUTIVE_REJECTIONS_TO_REVOKE": 2,
    # Competency grace pass (PRD 3.9)
    "GRACE_BASE_PHYSICIAN": 30,
    "GRACE_BASE_OTHER": 14,
    "GRACE_PENALTY_OPEN": 0,
    "GRACE_PENALTY_RESTRICTED": 7,
    "GRACE_PENALTY_SUSPENDED": 14,
    # Compliance rate window (PRD 3.4)
    "QC_WINDOW_DAYS": 30,
    # Pagination (PRD 2.3)
    "PAGE_LIMIT_DEFAULT": 10,
    "PAGE_LIMIT_MIN": 1,
    "PAGE_LIMIT_MAX": 100,
}

TEST_DEFAULTS = {
    "DEVICE_MODEL": "GlucoMeter-X",
    "SECOND_DEVICE_MODEL": "StripReader-Z",
    "MODERATE_DEVICE_MODEL": "ChemAnalyzer-M",
    "ANALYTE": "GLUCOSE",
    "SECOND_ANALYTE": "URINALYSIS",
    "MODERATE_ANALYTE": "CHEMISTRY_PANEL",
    "QC_FREQUENCY_DAYS": 30,
    "CONTROL_MIN_L1": 80.0,
    "CONTROL_MAX_L1": 120.0,
    "CONTROL_MIN_L2": 250.0,
    "CONTROL_MAX_L2": 350.0,
    "STORAGE_MIN_C": 2.0,
    "STORAGE_MAX_C": 8.0,
    "TRAINING_MODULE_CODE": "POCT-101",
}
