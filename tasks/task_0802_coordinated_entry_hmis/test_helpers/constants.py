"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Vulnerability score bounds (PRD §3.1: verified score clamped to 0..17).
SCORE_MIN = 0
SCORE_MAX = 17

# Acuity tier thresholds (PRD §3.1: score >= 8 -> HIGH, >= 4 -> MODERATE, else LOW).
ACUITY_HIGH_MIN = 8
ACUITY_MODERATE_MIN = 4

# Prioritization rank_score weights (PRD §3.6).
TIER_WEIGHTS = {"HIGH": 1000, "MODERATE": 500, "LOW": 100, None: 0}
CHRONIC_BONUS = 300
TIME_12_MONTHS_POINTS = 200   # months_homeless >= 12
TIME_6_MONTHS_POINTS = 100    # months_homeless >= 6
TIME_MULT = 10                # else months_homeless * 10
HOUSEHOLD_CAP = 5
HOUSEHOLD_MULT = 20

# Lazy-expiry windows (PRD §3.1 / §3.6).
ASSESSMENT_EXPIRY_DAYS = 90
REFERRAL_EXPIRY_DAYS = 14

# APR rounding precision (PRD §2.8).
RATE_DECIMAL_PLACES = 1
LOS_DECIMAL_PLACES = 2

# Logical-clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

TEST_DEFAULTS = {
    "PROJECT_TYPE": "ES",
    "CONSENT_SCOPE": "SHARE_ALL",
    "EFFECTIVE_DATE": "2026-03-01",
    "EXPIRY_DATE": "2027-03-01",
    "PSH_PROJECT": "Maple PSH",
}
