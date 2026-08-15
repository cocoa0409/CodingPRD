"""Domain thresholds and pinned instants — numeric constants from the PRD."""

# PRD §2.4: logical clock startup default (never wall-clock).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# PRD §3.2: per-disease quantitative immunity thresholds (raw comparison,
# inclusive boundary).
TITER_THRESHOLDS = {
    "HEP_B": 10.0,
    "MEASLES": 1.0,
    "MUMPS": 1.0,
    "RUBELLA": 10.0,
    "VARICELLA": 1.0,
}
REQUIRED_TITER_DISEASES = ["HEP_B", "VARICELLA"]

# PRD §3.5: prophylaxis window / course length.
PEP_WINDOW_HOURS = 72
PEP_COURSE_DAYS = 28

# PRD §3.5: serology schedule offsets (days).
SEROLOGY_OFFSET_DAYS = {"BASELINE": 0, "WEEK_6": 42, "WEEK_12": 84, "MONTH_6": 183}
WINDOW_OPEN_LEAD_DAYS = 7
WINDOW_CLOSE_LAG_DAYS = 28

# PRD §3.7: disease-specific tracing constants.
DISEASE_INCUBATION_OFFSET_DAYS = {
    "COVID": 2, "INFLUENZA": 1, "PERTUSSIS": 7, "NOROVIRUS": 1, "MEASLES": 4,
}
DISEASE_MONITORING_WINDOW_DAYS = {
    "COVID": 14, "INFLUENZA": 7, "PERTUSSIS": 21, "NOROVIRUS": 3, "MEASLES": 21,
}

# PRD §3.9: coverage percentages use two decimal places, round-half-up.
COVERAGE_DP = 2

# PRD §3.8: workers' compensation claim number shape.
WC_CLAIM_PREFIX = "WC-"
WC_CLAIM_DIGITS = 6

# Serology waive justification minimum length (PRD §3.5).
WAIVE_REASON_MIN_LENGTH = 10
