"""Domain thresholds and numeric constants stated by the PRD."""

# The logical clock reads exactly this instant before any request moves it.
INITIAL_CLOCK_UTC = "2026-08-01T00:00:00Z"
INITIAL_CLOCK_TIMESTAMP = "2026-08-01T00:00:00.000Z"

ROLES = (
    "ProjectManager",
    "SurveyTechnician",
    "BuildingRepresentative",
    "AHJInspector",
    "ServiceManager",
    "SystemOperator",
)

# Condition grade point scale.
CONDITION_POINTS = {
    "EXCELLENT": 100,
    "GOOD": 80,
    "FAIR": 55,
    "POOR": 25,
    "FAILED": 0,
    "NOT_OBSERVED": 0,
}

# Condition dimension weights.
CONDITION_WEIGHTS = {
    "controller": 0.45,
    "machine": 0.30,
    "door": 0.25,
}

SCORE_BASES = ("OBSERVED_ONLY", "IMPUTED_FAILED")

# Recommended scope tier thresholds, evaluated top down on the final score.
TIER_THRESHOLDS = (
    (80.00, "CONTROLLER_ONLY"),
    (60.00, "CONTROLLER_DOOR"),
    (35.00, "CONTROLLER_MACHINE"),
)
FULL_REPLACEMENT_TIER = "FULL_REPLACEMENT"

SCOPE_TIER_RANKS = {
    "CONTROLLER_ONLY": 1,
    "CONTROLLER_DOOR": 2,
    "CONTROLLER_MACHINE": 3,
    "FULL_REPLACEMENT": 4,
}

# Lead-time escalation buckets keyed on max lead_time_days across the option's orders.
ESCALATION_BUCKETS = (
    (60, 0.0000),
    (120, 0.0300),
    (180, 0.0650),
)
ESCALATION_TOP_PCT = 0.1100

# Volume discount buckets keyed on the post-escalation subtotal in cents.
VOLUME_DISCOUNT_BUCKETS = (
    (15_000_000, 0.0000),
    (30_000_000, 0.0200),
    (60_000_000, 0.0450),
)
VOLUME_DISCOUNT_TOP_PCT = 0.0700

# Monthly maintenance multipliers by the car's approved scope tier.
TIER_MULTIPLIERS = {
    "CONTROLLER_ONLY": 1.00,
    "CONTROLLER_DOOR": 1.15,
    "CONTROLLER_MACHINE": 1.30,
    "FULL_REPLACEMENT": 1.45,
}

# Group-size factors by number of covered cars in the same group.
GROUP_SIZE_FACTORS = {
    1: 1.00,
    "2_TO_3": 0.93,
    "4_PLUS": 0.88,
}

CREDIT_BASES = ("THIRTY_360", "ACTUAL_CALENDAR")

# Countable ceilings.
MAX_REVISION_COUNT = 3
MAX_RESCHEDULE_COUNT = 2

# Declared jurisdiction defaults.
JURISDICTION_DEFAULTS = {
    "inspection_lead_days": 10,
    "witness_test_required": False,
    "reinspection_extension_hours": 24,
    "permit_surcharge_pct": 0.0000,
}

# Declared project defaults.
PROJECT_DEFAULTS = {
    "outage_buffer_hours": 4,
    "tenant_notice_lead_hours": 72,
}

# Staging pressure line: staging_committed_sqft * 100 > staging_area_sqft * 85.
STAGING_PRESSURE_NUMERATOR = 100
STAGING_PRESSURE_THRESHOLD = 85

WORK_STATUSES = (
    "SURVEY_PENDING",
    "SURVEYED",
    "SCOPED",
    "PROCURING",
    "OUTAGE_ACTIVE",
    "TESTING",
    "ACCEPTED",
    "IN_WARRANTY",
    "UNDER_CONTRACT",
)

COMPLIANCE_STATUSES = (
    "NOT_EVALUATED",
    "TRIGGERS_OPEN",
    "TRIGGERS_CLEARED",
    "CODE_ACCEPTED",
)

DOWNTIME_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")

TEST_DEFAULTS = {
    "JURISDICTION_NAME": "City of Brentwood",
    "PROJECT_NAME": "Brentwood Tower",
    "CONTRACT_VALUE_CENTS": 60_000_000,
    "STAGING_AREA_SQFT": 1200,
    "MAX_CONCURRENT_OUTAGES": 2,
    "MONTHLY_BASE_CENTS": 45_000,
}
