"""Domain thresholds and numeric constants stated by the PRD."""

# --- Casing credit (PRD §3.4) -------------------------------------------
DEFAULT_CASING_CREDIT_CENTS = 12000
GRADE_FACTORS = {"A": 1.00, "B": 0.70, "C": 0.40, "REJECT": 0.00}
RETREAD_DECAY_PCT = 0.15
MIN_CREDIT_FACTOR = 0.25
PRODUCTION_VERIFIED_UPLIFT_PCT = 0.10

# --- Road service pricing (PRD §3.6) ------------------------------------
BASE_SERVICE_CALL_CENTS = 9500
LABOR_RATE_CENTS_PER_HOUR = 11000
MILEAGE_CENTS_PER_MILE = 285
EMERGENCY_MULTIPLIER = 1.75
AFTER_HOURS_MULTIPLIER = 1.35
MAX_EMERGENCY_SURCHARGE_CENTS = 40000
SLA_MISS_CREDIT_PCT = 0.20
NORMAL_PRIORITY_GRACE_MINUTES = 60
AFTER_HOURS_START_HOUR = 18
AFTER_HOURS_END_HOUR = 6

# --- Invoice rollup (PRD §3.8) ------------------------------------------
CREDIT_CAP_PCT = 0.25
MAX_BILLING_PERIOD_DAYS = 92

# --- Retread scheduling (PRD §3.5) --------------------------------------
MIN_JOB_MINUTES = 60
MAX_JOB_MINUTES = 480
DEFAULT_CURE_COOLDOWN_MINUTES = 30

# --- Warranty terms (PRD §3.5) ------------------------------------------
WARRANTY_BASE_MONTHS = {"A": 36, "B": 24, "C": 12}
WARRANTY_MONTHS_PER_RETREAD_DEDUCTION = 6
WARRANTY_FLOOR_MONTHS = 6

# --- Technician selector ranks (PRD §3.6) -------------------------------
CERTIFICATION_RANKS = {"TIA_CERTIFIED": 3, "LEVEL_2": 2, "LEVEL_1": 1}

# --- Logical clock (PRD §2.5) -------------------------------------------
DEFAULT_LOGICAL_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Pagination (PRD §2.3) ---------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --- Canonical DRIVE policy used across setups --------------------------
CANONICAL_DRIVE_POLICY = {
    "position": "DRIVE",
    "target_pressure_psi": 100,
    "pressure_tolerance_pct": 0.10,
    "min_tread_depth_32nds": 4,
    "pull_point_32nds": 6,
    "max_retread_count": 3,
    "approved_brands": ["Bridgestone"],
    "new_tire_tread_depth_32nds": 24,
    "casing_spec_code": "ANY",
}

# Placeholder identifiers used by the per-path not-found sweep. They are
# well-formed UUIDs that are never assigned to any created resource.
UNASSIGNED_UUIDS = [
    "00000000-0000-4000-8000-00000000000{}".format(suffix)
    for suffix in "123456789abcdef"
]
