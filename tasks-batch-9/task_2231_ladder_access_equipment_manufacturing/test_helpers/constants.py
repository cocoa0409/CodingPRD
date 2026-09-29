"""Domain thresholds and numeric constants declared by the PRD.

Every value here is quoted from PRD prose (§2.x, §3.x). Generic helpers such as
NON_EXISTENT_UUID come from the prd_bench_local_runner framework.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Duty-rating derivation (PRD §3.1)
# ---------------------------------------------------------------------------
RATED_LOAD_BY_DUTY_RATING = {
    "TYPE_III": 200,
    "TYPE_II": 225,
    "TYPE_I": 250,
    "TYPE_IA": 300,
    "TYPE_IAA": 375,
}

SAFETY_FACTOR_BASE = 4.00
SAFETY_FACTOR_PER_LENGTH_STEP = 0.15
SAFETY_FACTOR_CAP = 4.60
LENGTH_STEP_BASELINE_FT = 12.0
LENGTH_STEP_DIVISOR_FT = 4.0

PRODUCT_TYPE_SAFETY_BONUS = {
    "STEP_LADDER": 0.00,
    "EXTENSION_LADDER": 0.00,
    "PLATFORM_LADDER": 0.00,
    "ARTICULATED_LADDER": 0.10,
    "MOBILE_SCAFFOLD_TOWER": 0.25,
}

FIBERGLASS_SAFETY_BONUS = 0.05
PULL_FORCE_MULTIPLIER = 1.5
DEFLECTION_INCHES_PER_FOOT = 12
DEFLECTION_SPAN_DIVISOR = 180
MAX_WORKING_LENGTH_FT = 60.0
MODEL_CODE_MAX_LENGTH = 40

# ---------------------------------------------------------------------------
# Design revision review cycle (PRD §3.2)
# ---------------------------------------------------------------------------
MIN_STRUCTURAL_MARGIN_PCT_FOR_SUBMIT = 2.00
MIN_RAIL_SECTION_MODULUS_IN3_FOR_APPROVE = 0.180

# ---------------------------------------------------------------------------
# Test lab (PRD §3.4)
# ---------------------------------------------------------------------------
MAX_COOLDOWN_MINUTES = 480
PERMANENT_SET_CEILING_IN = 0.020

# ---------------------------------------------------------------------------
# Certification listing and periodic audits (PRD §3.5)
# ---------------------------------------------------------------------------
MAX_AUDIT_INTERVAL_DAYS = 730
LISTING_TERM_DAYS = 1825
AUDIT_BASE_SAMPLE_UNITS = 5
AUDIT_TIER_ADDER = {
    "TIER_0": 0,
    "TIER_1": 3,
    "TIER_2": 8,
    "TIER_3": 15,
}
AUDIT_TIER_1_UPPER_BOUND_PCT = 20.00
AUDIT_TIER_2_UPPER_BOUND_PCT = 40.00

# ---------------------------------------------------------------------------
# Production lots (PRD §3.6)
# ---------------------------------------------------------------------------
MIN_REQUIRED_JOINT_SAMPLES = 4
UNITS_PER_JOINT_SAMPLE = 250
MIN_CONFORMANCE_INDEX = 2.00

# ---------------------------------------------------------------------------
# Retail release (PRD §3.7)
# ---------------------------------------------------------------------------
MANDATED_DOCUMENT_KINDS = [
    "DUTY_RATING_LABEL",
    "WARNING_LABEL",
    "INSTRUCTION_LABEL",
    "RETAIL_CARTON",
    "ASSEMBLY_INSTRUCTION_SHEET",
    "CONSUMER_SAFETY_SHEET",
]
RESUME_SHIP_RISK_SCORE_CEILING = 25.00

# ---------------------------------------------------------------------------
# Field incidents (PRD §3.8)
# ---------------------------------------------------------------------------
INJURY_SEVERITY_WEIGHT = {
    "NONE": 1,
    "MINOR": 4,
    "HOSPITALIZATION": 12,
    "FATALITY": 30,
}
INCIDENT_TYPE_WEIGHT = {
    "RAIL_FRACTURE": 3.0,
    "RUNG_SEPARATION": 2.5,
    "HINGE_FAILURE": 2.0,
    "SLIP_FALL": 1.5,
    "LABEL_ILLEGIBLE": 1.0,
}
RISK_SCORE_CEILING = 100.00
VERIFIED_CAPA_CREDIT_FRACTION = 0.25
RISK_SCORE_INPUT_STATUSES = [
    "UNDER_INVESTIGATION",
    "ROOT_CAUSE_IDENTIFIED",
    "CAPA_OPENED",
    "CLOSED",
]

# ---------------------------------------------------------------------------
# Recall (PRD §3.9)
# ---------------------------------------------------------------------------
RECALL_OUTREACH_WINDOW_DAYS = 365
RECALL_EXPOSURE_REGISTRATION_STATUSES = ["REGISTERED", "NOTIFIED", "ACKNOWLEDGED"]

# ---------------------------------------------------------------------------
# Design-history retention (PRD §2.10)
# ---------------------------------------------------------------------------
RETENTION_YEARS = 7
RETENTION_ANCHOR_PRECEDENCE = [
    "LOT_RELEASE",
    "INCIDENT_CLOSURE",
    "RECALL",
    "DESIGN_FREEZE",
]

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Convenience defaults used by the test fixtures
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "BENCH_CAPACITY_LB": 5000.00,
    "BENCH_COOLDOWN_MINUTES": 60,
    "PLANNED_UNITS": 500,
    "PRODUCED_UNITS": 400,
    "AUDIT_INTERVAL_DAYS": 180,
    "STRUCTURAL_MARGIN_PCT": 7.25,
    "RAIL_SECTION_MODULUS_IN3": 0.310,
}

# All six load-test codes the PRD declares (PRD §3.4). Fixtures that must drive a
# campaign to PASSED record one passing row for each so that any required set the
# PRD prose implies is fully covered.
ALL_TEST_CODES = [
    "STATIC_VERTICAL",
    "RAIL_BENDING",
    "SLIP_RESISTANCE",
    "HINGE_CYCLE",
    "ELECTRICAL_LEAKAGE",
    "RIVET_SHEAR",
]
