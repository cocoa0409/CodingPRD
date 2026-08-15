"""Domain thresholds — numeric constants from PRD calculations (§3.3, §3.7, §3.8, §3.9)."""

# Logical clock (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Acuity index (PRD §3.3)
ACUITY_WEIGHTS = {
    "housing": 0.30,
    "employment": 0.25,
    "education": 0.15,
    "language": 0.20,
    "health": 0.10,
}
VERIFIED_MULTIPLIER = 1.25
HOUSEHOLD_BONUS_MIN = 5
HOUSEHOLD_BONUS_POINTS = 10
RECENT_ARRIVAL_DAYS = 90
RECENT_ARRIVAL_POINTS = 5

# Benefits tiering (PRD §3.7) — federal poverty guideline, annual cents by household size
FPL_ANNUAL_CENTS = {
    1: 1506000,
    2: 2044000,
    3: 2582000,
    4: 3120000,
    5: 3658000,
    6: 4196000,
    7: 4734000,
    8: 5272000,
}
TIER_A_PCT = 138
TIER_B_PCT = 200
TIER_C_PCT = 300
DOC_GATED_PROGRAMS = {"CASH_ASSIST"}

# Enrollment fee subsidy (PRD §3.8)
BASE_SUBSIDY_PCT = {"TIER_A": 0.90, "TIER_B": 0.60, "TIER_C": 0.30, "TIER_D": 0.00}
BURDEN_RATE = 0.05
MONTHS_PER_YEAR = 12

# Funder cost allocation (PRD §3.9)
REFERRAL_COMPLETION_CENTS = 7500
ENROLLMENT_COMPLETION_CENTS = 12000
WORKSHOP_ATTENDANCE_CENTS = 2500

# Workshop room turnover buffer (PRD §3.8)
ROOM_BUFFER_MIN = 15

# Referral defaults (PRD §3.5)
DEFAULT_TTL_DAYS = 14

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
