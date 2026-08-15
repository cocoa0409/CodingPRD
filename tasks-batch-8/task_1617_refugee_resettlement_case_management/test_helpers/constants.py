"""Domain thresholds and constants — numeric values from the PRD's
calculation and validation rules (PRD §3.2, §3.3, §3.5, §3.7)."""

# Furnishing set a setup must complete before it can be marked READY (PRD §3.2:
# "the six required furnishings"). The API accepts these six item names.
REQUIRED_FURNISHINGS = [
    "BED",
    "LINENS",
    "TABLE",
    "CHAIRS",
    "COOKWARE",
    "CLEANING_SUPPLIES",
]

# Benchmark due-rule offsets in days (PRD §3.3).
DUE_RULE_OFFSET_DAYS = {
    "DAYS_30": 30,
    "DAYS_90": 90,
}

# Posture look-ahead window in days (PRD §3.3: "a seven-day look-ahead window").
AT_RISK_WINDOW_DAYS = 7

# Self-sufficiency determination constants, integer cents (PRD §3.5).
FPG_MONTHLY_BASE_CENTS = 130000
FPG_MONTHLY_INCREMENT_CENTS = 45000
EARNED_DISREGARD_MONTHLY_CENTS = 20000

# Per-capita allocation constants (PRD §3.7).
PER_CAPITA_ANNUAL_CENTS = 1250000
SIZE_CAP = 8

# Orientation scheduling buffer in minutes (PRD §3.5: "a 30-minute buffer").
SESSION_BUFFER_MINUTES = 30

# The six-topic cultural orientation curriculum (PRD §3.5).
ALL_ORIENTATION_TOPICS = [
    "US_LAWS",
    "HEALTHCARE_ACCESS",
    "EDUCATION_SYSTEM",
    "EMPLOYMENT_RIGHTS",
    "HOUSING_SAFETY",
    "BUDGETING",
]

# Default logical clock reading before any set call (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Common fixture defaults.
DEFAULT_AGENCY_CODE = "AFF-01"
DEFAULT_ARRIVAL_DATE = "2026-08-10"
DEFAULT_OCCUPANCY_START = "2026-08-10"
DEFAULT_OCCUPANCY_END = "2027-02-10"

# The five benchmark service types seeded for every arrived case (PRD §3.3).
BASE_BENCHMARK_TYPES = [
    "HOME_VISIT",
    "HEALTH_SCREENING",
    "SSN_APPLICATION",
    "BENEFITS_ENROLLMENT",
    "CULTURAL_ORIENTATION",
]
