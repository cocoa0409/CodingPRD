"""Domain thresholds and constants stated in the PRD's business rules."""

# ---------------------------------------------------------------------------
# Weekly entitlement (PRD §3.3)
# ---------------------------------------------------------------------------

DIAGNOSIS_FACTOR = {
    "MEDICAL_ACUTE": 1.00,
    "MEDICAL_CHRONIC": 1.00,
    "PSYCHIATRIC": 0.80,
    "PREGNANCY_POSTPARTUM": 0.90,
    "INJURY_REHAB": 1.00,
}

MID_DURATION_DAYS = 30
MID_DURATION_BONUS_MINUTES = 30
LONG_DURATION_DAYS = 60
LONG_DURATION_BONUS_MINUTES = 60
SPED_FLOOR_FACTOR = 0.60
MIN_EXPECTED_ABSENCE_DAYS_FOR_ACCEPTANCE = 10

# ---------------------------------------------------------------------------
# Per-session instructional credit (PRD §3.6)
# ---------------------------------------------------------------------------

VIRTUAL_CREDIT_FACTOR = 0.90
CREDIT_ROUNDING_STEP = 5

# ---------------------------------------------------------------------------
# Weekly minute allocation (PRD §3.4)
# ---------------------------------------------------------------------------

SUPPORT_SHARE = 0.30
ALLOCATION_ROUNDING_STEP = 5

# ---------------------------------------------------------------------------
# Home-visit risk score and clearance bands (PRD §3.5)
# ---------------------------------------------------------------------------

HAZARD_WEIGHT = {
    "AGGRESSIVE_ANIMAL": 25,
    "NO_SECONDARY_EXIT": 15,
    "WEAPON_PRESENT_UNSECURED": 40,
    "SMOKE_OR_AIR_QUALITY": 10,
    "ACTIVE_INFECTION_RISK": 30,
    "UNLIT_ACCESS": 5,
    "NO_ADULT_PRESENT": 20,
}

SELF_REPORT_DISCOUNT = 0.75
ESCORT_MITIGATION_POINTS = 10
RISK_SCORE_MAX = 100

CLEARANCE_BLOCKED_THRESHOLD = 60
CLEARANCE_VIRTUAL_ONLY_THRESHOLD = 35
CLEARANCE_WITH_ESCORT_THRESHOLD = 15

SAFETY_REVIEW_VALIDITY_DAYS = 60

# ---------------------------------------------------------------------------
# Funding reconciliation bands (PRD §3.7)
# ---------------------------------------------------------------------------

FULL_CREDIT_RATIO = 0.90
PARTIAL_CREDIT_RATIO = 0.75
FORFEIT_RATIO = 0.50

RECAPTURE_RATE_FULL = 0.00
RECAPTURE_RATE_TEN_PERCENT = 0.10
RECAPTURE_RATE_TWENTY_FIVE_PERCENT = 0.25

SERVICE_GAP_BREACH_MULTIPLE = 1

# ---------------------------------------------------------------------------
# Extensions (PRD §3.8) and transition plans (PRD §3.9)
# ---------------------------------------------------------------------------

MAX_EXTENSIONS_PER_CASE = 2
MAX_RESUBMITS_PER_EXTENSION = 2
MIN_REQUIRED_ACK_COUNT = 1
COMPENSATORY_WEEK_DAYS = 7

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"

# Baseline instants used across the suite's setups.
CLOCK_CONFIG_INSTANT = "2026-09-01T00:00:00Z"
CLOCK_ACTIVATION_INSTANT = "2026-09-07T08:00:00Z"

# ---------------------------------------------------------------------------
# Test data defaults
# ---------------------------------------------------------------------------

MISSING_UUID = "00000000-0000-0000-0000-0000000000ff"

TEST_DEFAULTS = {
    "PHYSICIAN_NPI": "1234567890",
    "CERTIFIED_START_DATE": "2026-09-07",
    "CERTIFIED_END_DATE": "2026-10-07",
    "SIGNATURE_DATE": "2026-08-28",
    "REFERRAL_DATE": "2026-09-01",
    "EXPECTED_ABSENCE_DAYS": 40,
}

# The MIDDLE / IN_HOME rule used as the spine of most setups.
MIDDLE_IN_HOME_RULE = {
    "grade_band": "MIDDLE",
    "delivery_mode": "IN_HOME",
    "base_weekly_minutes": 360,
    "cap_weekly_minutes": 480,
    "min_session_minutes": 30,
    "max_session_minutes": 120,
    "max_daily_minutes": 240,
    "min_gap_minutes": 15,
    "travel_buffer_minutes": 30,
}

# The MIDDLE / VIRTUAL_SYNC rule used by the virtual-mode setups.
MIDDLE_VIRTUAL_RULE = {
    "grade_band": "MIDDLE",
    "delivery_mode": "VIRTUAL_SYNC",
    "base_weekly_minutes": 240,
    "cap_weekly_minutes": 400,
    "min_session_minutes": 20,
    "max_session_minutes": 90,
    "max_daily_minutes": 180,
    "min_gap_minutes": 10,
    "travel_buffer_minutes": 0,
}
