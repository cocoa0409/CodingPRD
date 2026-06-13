"""Domain thresholds — numeric constants from the PRD's pay and penalty rules.

Rank multipliers and postseason uplift (§3.5/§3.9); reliability deduction
threshold/percent (§3.9); decline and no-show penalty breakpoints (§3.8).
Generic NON_EXISTENT_UUID comes from the framework.
"""

# Rank pay multipliers (§3.5 / §3.9)
RANK_MULTIPLIER = {
    "ROOKIE": 1.0,
    "CERTIFIED": 1.25,
    "SENIOR": 1.5,
    "MASTER": 2.0,
}

# Postseason pay uplift (§3.5 / §3.9)
POSTSEASON_UPLIFT = 1.20

# Reliability deduction at settlement (§3.9)
RELIABILITY_DEDUCTION_THRESHOLD = 10
RELIABILITY_DEDUCTION_PCT = 0.10

# Decline penalty breakpoints (§3.8)
LATE_HOURS = 24
SHORT_HOURS = 72
LATE_DECLINE_POINTS = 8
SHORT_DECLINE_POINTS = 4
STANDARD_DECLINE_POINTS = 1
ESCALATION_STEP_POINTS = 2
MAX_ESCALATION_STEPS = 3
POSTSEASON_PENALTY_MULT = 2.0

# No-show penalty breakpoints (§3.8)
NOSHOW_BASE_POINTS = 15
NS_ESCALATION_POINTS = 5
NS_MAX_STEPS = 3
NS_POSTSEASON_MULT = 2.0

# Reliability gauge bounds (§3.7)
RELIABILITY_FLOOR = 0
RELIABILITY_CEIL = 100

# League postseason eligibility defaults (§3.1)
DEFAULT_POSTSEASON_MIN_GAMES = 8
DEFAULT_POSTSEASON_MIN_RATING = 3.5
DEFAULT_POSTSEASON_MAX_NOSHOWS = 0

# Official defaults (§3.1)
DEFAULT_MAX_TRAVEL_MILES = 50

# Game defaults (§3.3)
DEFAULT_DURATION_MINUTES = 120

# Geometry/clock conventions shared by the design recipes:
# official home == game venue (40.0, -75.0) => great-circle distance 0.
HOME_LAT = 40.0
HOME_LON = -75.0
VENUE_LAT = 40.0
VENUE_LON = -75.0

# A wide AVAILABLE window covering every game interval used in the recipes.
WIDE_WINDOW_START = "2026-01-01T00:00:00Z"
WIDE_WINDOW_END = "2027-01-01T00:00:00Z"
