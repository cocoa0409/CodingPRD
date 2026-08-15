"""Domain thresholds and constants from the PRD's calculation rules (§3)."""

# Logical clock startup default (PRD §2.6).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Facility defaults (PRD §3.1).
DEFAULT_SIR_HIGH_THRESHOLD = 1.25
DEFAULT_HH_MIN_OPPORTUNITIES = 30

# Standard facility baselines used by most scenarios (PRD §3.1).
DEFAULT_CLABSI_BASELINE_PER_1000 = 2.0
DEFAULT_CAUTI_BASELINE_PER_1000 = 1.5
DEFAULT_SSI_BASELINE_PER_PROCEDURE = 0.25

# SIR computation (PRD §3.7).
SIR_NOT_CALCULATED_FLOOR = 1.0

# SSI procedure risk weights (PRD §3.7).
SSI_WEIGHT_LOW = 1.0
SSI_WEIGHT_MEDIUM = 1.5
SSI_WEIGHT_HIGH = 2.0

# Outbreak cluster detection (PRD §3.8).
CLUSTER_THRESHOLD = 3
DETECTION_WINDOW_DAYS = 14

# Isolation audit compliance (PRD §3.9).
COMPLIANCE_THRESHOLD_PCT = 90.0
AUTO_CAP_DUE_DATE_OFFSET_DAYS = 14

# Hand hygiene opportunity weights (PRD §3.10).
HH_WEIGHTS = {
    "BEFORE_PATIENT_CONTACT": 1.0,
    "AFTER_PATIENT_CONTACT": 1.0,
    "ASEPTIC_TASK": 2.0,
    "BODY_FLUID_RISK": 1.5,
    "AFTER_SURROUNDINGS": 1.0,
}

# Employee exposure follow-up schedule (PRD §3.11).
BASELINE_SLA_HOURS = 72
WEEK6_DUE_DAYS = 42
WEEK12_DUE_DAYS = 84
WEEK24_DUE_DAYS = 168
FOLLOWUP_WINDOW_EARLY_DAYS = 7
FOLLOWUP_WINDOW_LATE_DAYS = 28
LOST_AFTER_OVERDUE_DAYS = 28

# Repeat-infection-timeframe length (PRD §3.4): DOE through DOE + 13 days.
RIT_DAYS_AFTER_DOE = 13

# Infection window period offsets (PRD §3.4).
IWP_DAYS_BEFORE_SPECIMEN = 3
IWP_DAYS_AFTER_SPECIMEN = 3

# Default calendar month used by the majority of scenarios.
DEFAULT_MONTH = "2026-08"
