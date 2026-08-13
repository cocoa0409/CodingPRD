"""Domain thresholds and numeric constants from the PRD."""

# Logical clock boot default (PRD §2.4).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Impact rating tier bands and provisional variant constants (PRD §3.1 / §3.4).
TIER_LOW_MAX = 5.0
TIER_MEDIUM_MAX = 12.0
TIER_HIGH_MAX = 20.0
PROVISIONAL_ASSUMED_LIKELIHOOD = 3
SEVERITY_HINT_MAP = {"LOW": 1, "MEDIUM": 2, "HIGH": 4, "CRITICAL": 5}
SCOPE_MULTIPLIER_1_LINE = 1.0
SCOPE_MULTIPLIER_2_3_LINES = 1.2
SCOPE_MULTIPLIER_4_PLUS_LINES = 1.5

# Gap analysis requirement points per obligation criticality (PRD §3.5).
CRITICALITY_POINTS = {"LOW": 4, "MEDIUM": 8, "HIGH": 16, "CRITICAL": 32}

# Control effectiveness tiers by review staleness in days (PRD §3.3).
REVIEW_FULL_DAYS = 90
REVIEW_STALE_DAYS = 180
EFFECTIVENESS_FRESH = 1.0
EFFECTIVENESS_STALE = 0.8
EFFECTIVENESS_NEVER = 0.5

# Implementation deadline mandate days per criticality (PRD §3.6).
MANDATE_DAYS = {"LOW": 180, "MEDIUM": 90, "HIGH": 45, "CRITICAL": 15}

# Deadline posture band width in days (PRD §3.6).
AT_RISK_WINDOW_DAYS = 14

# Plan extension caps (PRD §3.6).
MAX_EXTENSIONS = 2
MAX_EXTENSION_DAYS = 90

# Policy publish minimum training runway in days (PRD §3.7).
MIN_TRAINING_WINDOW_DAYS = 7

# Training rollout thresholds (PRD §3.7).
COMPLETE_THRESHOLD = 95.0
EXCEPTION_THRESHOLD = 80.0

# Owner suspension threshold on open escalations (PRD §3.4 / §3.6).
SUSPENSION_THRESHOLD = 3

# Committee report compliance-index tier weights (PRD §3.9).
TIER_LOW_WEIGHT = 10
TIER_MID_WEIGHT = 20
TIER_HIGH_WEIGHT = 35

# Default fixture values.
DEFAULT_OWNER_NAME = "Rhea Patel"
DEFAULT_OWNER_DEPARTMENT = "OPS"
DEFAULT_OWNER_EMAIL = "rhea@x.com"
DEFAULT_DUE_DATE = "2026-08-10T00:00:00Z"
DEFAULT_PLAN_TARGET = "2026-08-16T00:00:00Z"
DEFAULT_POLICY_EFFECTIVE = "2026-08-20T00:00:00Z"
