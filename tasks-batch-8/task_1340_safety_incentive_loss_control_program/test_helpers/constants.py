"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup value (PRD: the clock reads exactly this before any call).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Program defaults (PRD: tunable at creation).
DEFAULT_NEAR_MISS_FLOOR_RATIO = 0.20
DEFAULT_QUORUM_MIN = 5

# Hazard risk banding and response SLA days (PRD hazard assessment).
RISK_BAND_LOW_MAX = 4
RISK_BAND_MEDIUM_MAX = 9
RISK_BAND_HIGH_MAX = 15
SLA_DAYS = {"CRITICAL": 7, "HIGH": 14, "MEDIUM": 30, "LOW": 60}

# Incentive point ledger (PRD incentive scoring).
POINTS_BASE = {
    "OBSERVATION_VALIDATED": 10,
    "NEAR_MISS_VALIDATED": 20,
    "CONTROL_VERIFIED": 15,
    "ACTION_VERIFIED": 10,
    "MEETING_ATTENDED": 5,
    "CLAIMS_FREE_BONUS": 50,
}
HAZARD_CLASS_MULTIPLIER = {"LOW": 1.0, "MODERATE": 1.2, "HIGH": 1.5}
TIMELINESS_MULTIPLIER_ON_TIME = 1.25

# Award tiers (inclusive point ranges) and per-point values in cents.
TIER_BOUNDS = {"BRONZE": (1, 49), "SILVER": (50, 99), "GOLD": (100, 199),
               "PLATINUM": (200, None)}
TIER_VALUE_CENTS = {"BRONZE": 150, "SILVER": 200, "GOLD": 250, "PLATINUM": 300}

# Contractor prequalification score (PRD contractor section).
PREQUAL_EMR_BENCHMARK = 1.25
PREQUAL_TRIR_BENCHMARK = 8.0
PREQUAL_WEIGHTS = {"emr": 0.40, "trir": 0.30, "audit": 0.20, "insurance": 0.10}
PREQUAL_BAND_APPROVE_MIN = 80.00
PREQUAL_BAND_CONDITIONAL_MIN = 65.00
PREQUAL_INSURANCE_FULL_DAYS = 90
PREQUAL_INSURANCE_PARTIAL_DAYS = 30
PREQUAL_VALIDITY_DAYS = 365

# EMR forecast (PRD experience-modification section).
EMR_SPLIT_POINT_CENTS = 1_500_000
EMR_ERA_MEDICAL_ONLY_FACTOR = 0.3
EMR_EXCESS_RATIO = 0.55
EMR_BALLAST_RATE = 0.10
EMR_W_FLOOR = 0.05
EMR_W_CAP = 0.75
EMR_W_OFFSET_DOLLARS = 20_000
EMR_W_SPAN_DOLLARS = 180_000
EMR_MIN_ELAPSED_DAYS = 30

# Posture rule (PRD sweep section).
POSTURE_RESTRICTED_OVERDUE_CONTROLS = 3

# Leading-indicator normalization basis.
HOURS_NORMALIZATION = 200_000

# Auto-assignment lead time for job-hazard required training (days).
AUTO_ASSIGNMENT_DUE_DAYS = 30

# Shared payroll / ELR rate cards used by most fixtures ($100k per class).
DEFAULT_PAYROLL_BY_CLASS = [
    {"hazard_class": "LOW", "payroll_cents": 10_000_000},
    {"hazard_class": "MODERATE", "payroll_cents": 10_000_000},
    {"hazard_class": "HIGH", "payroll_cents": 10_000_000},
]
DEFAULT_ELR_BY_CLASS = [
    {"hazard_class": "LOW", "elr": 1.0},
    {"hazard_class": "MODERATE", "elr": 1.0},
    {"hazard_class": "HIGH", "elr": 1.0},
]

TEST_DEFAULTS = {
    "PROGRAM_YEAR": 2026,
    "INCENTIVE_BUDGET_CENTS": 500_000,
    "OBSERVATION_TARGET_RATE": 5.0,
    "EXPOSURE_HOURS": 100_000,
}
