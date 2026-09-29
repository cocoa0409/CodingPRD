"""Numeric constants the PRD fixes for the licensure and comity calculations."""

# ---------------------------------------------------------------------------
# Experience credit evaluation
# ---------------------------------------------------------------------------
MULT_RESPONSIBLE_CHARGE = 1.00
MULT_PROGRESSIVE = 0.75
MULT_SUBORDINATE = 0.50
PRE_DEGREE_FACTOR = 0.50
MAX_SINGLE_RECORD_MONTHS = 48
MAX_TOTAL_CREDIT_MONTHS = 96
INDIRECT_REFERENCE_WEIGHT = 0.50
MIN_EXPERIENCE_MONTHS = 48

# ---------------------------------------------------------------------------
# Continuing professional competency: PDH valuation
# ---------------------------------------------------------------------------
CAP_COURSE = 30
CAP_SEMINAR = 30
CAP_TEACHING = 10
CAP_PUBLICATION = 10
CAP_PATENT = 10
CAP_SELF_STUDY_SELF_CERTIFIED = 8
CAP_SELF_STUDY_AUDIT_VERIFIED = 0
MAX_CARRYOVER_PDH = 15
ETHICS_REQUIRED_PDH = 2
DEFAULT_PDH_REQUIREMENT = 30

# ---------------------------------------------------------------------------
# Application fee assessment
# ---------------------------------------------------------------------------
BASE_FEE_STANDARD_CENTS = 25000
BASE_FEE_COMITY_CENTS = 37500
RECORDS_FEE_PER_RECORD_CENTS = 2500
NCEES_RECORD_FEE_CENTS = 7500
EXPEDITE_PCT = 0.18
COMITY_TIER_HIGH_CENTS = 50000
COMITY_TIER_HIGH_PCT = 0.15
COMITY_TIER_MID_CENTS = 30000
COMITY_TIER_MID_PCT = 0.10
COMITY_TIER_LOW_PCT = 0.05

# ---------------------------------------------------------------------------
# Civil penalty assessment
# ---------------------------------------------------------------------------
BASE_NEGLIGENCE_CENTS = 150000
BASE_UNLICENSED_PRACTICE_CENTS = 250000
BASE_PLAN_STAMPING_CENTS = 200000
BASE_CPC_FRAUD_CENTS = 100000
AGGRAVATING_STEP = 0.25
MITIGATING_STEP = 0.15
FACTOR_FLOOR = 0.50
FACTOR_CEILING = 2.00
PER_SHEET_STAMP_CENTS = 1725
INVESTIGATION_COST_CENTS = 48000
STATUTORY_CAP_CENTS = 1000000

# ---------------------------------------------------------------------------
# Licence period roll, renewal and reinstatement
# ---------------------------------------------------------------------------
BIENNIUM_MONTHS = 24
RENEWAL_WINDOW_DAYS = 90
REINSTATEMENT_GRACE_DAYS = 730
REINSTATEMENT_MAKEUP_PDH = 15
REINSTATEMENT_FEE_CENTS = 45000

# ---------------------------------------------------------------------------
# Test centre seats and exam windows
# ---------------------------------------------------------------------------
MAX_SEAT_LABELS = 20
TURNOVER_BUFFER_MINUTES = 45
EXAM_WINDOW_MINUTES = 480

# ---------------------------------------------------------------------------
# Exam authorization lifecycle
# ---------------------------------------------------------------------------
AUTHORIZATION_VALID_DAYS = 365
RETAKE_WAIT_DAYS = 90
MAX_EXAM_ATTEMPTS = 3
PASSING_SCORE = 70

# ---------------------------------------------------------------------------
# Deficiency cycles
# ---------------------------------------------------------------------------
DEFICIENCY_RESPONSE_DAYS = 30
MAX_DEFICIENCY_CYCLES = 3

# ---------------------------------------------------------------------------
# Comity
# ---------------------------------------------------------------------------
COMITY_MIN_YEARS = 4

# ---------------------------------------------------------------------------
# CPC audit sampling and firm registration
# ---------------------------------------------------------------------------
MIN_SAMPLE_COUNT = 1
FIRM_REGISTRATION_DAYS = 365

# ---------------------------------------------------------------------------
# Fixed clock origin of every freshly launched harness process
# ---------------------------------------------------------------------------
INITIAL_CLOCK = "2026-08-01T00:00:00Z"
