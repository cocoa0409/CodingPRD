"""Domain thresholds and defaults — numeric constants from the PRD (§2.4, §2.10, §3)."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# PlantUnit config defaults (PRD §3.1).
UNIT_DEFAULTS = {
    "temp_moc_max_days": 180,
    "max_extensions": 2,
    "extension_max_days": 90,
    "total_temp_cap_days": 360,
    "training_coverage_threshold_pct": 100.00,
}

# Screening risk class multipliers (PRD §3.2).
CLASS_MULT = {
    "PERMANENT": 1.0,
    "TEMPORARY": 1.2,
    "REPLACEMENT_IN_KIND": 0.5,
}

# Risk-rank band edges (PRD §3.2): inclusive-low.
RANK_MEDIUM_MIN = 5.0
RANK_HIGH_MIN = 12.0
RANK_CRITICAL_MIN = 20.0

# Definitive risk constants (PRD §3.3).
DEFINITIVE_BASE_CAP = 25
DETECTION_STEP = 0.25
POSTURE_FACTOR_THRESHOLD = 70
POSTURE_FACTOR = 1.25

# Action-item SLA days per priority (PRD §3.9).
SLA_DAYS = {"P1": 30, "P2": 90, "P3": 180}

# Unit process safety index weights and bands (PRD §2.10).
INDEX_WEIGHTS = {
    "overdue_item": 15,
    "study_overdue": 25,
    "study_forced": 20,
    "open_high_incident": 10,
    "open_major_nc": 5,
}
INDEX_CAP = 100
RESTRICTED_MIN = 40
FROZEN_MIN = 70

# PHA scheduling constants (PRD §3.7).
DAYS_PER_MONTH = 30
DUE_SOON_LEAD_DAYS = 60
ACCEL_PER_INCIDENT = 0.1
ACCEL_FLOOR = 0.25

# Audit window separation rule (PRD §3.8).
AUDIT_SEPARATION_DAYS = 14
