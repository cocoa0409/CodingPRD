"""Domain thresholds — numeric constants from PRD calculations."""

# Rush surcharge percentage by tier (PRD §3.2 / §3.7).
RUSH_PCT = {"NONE": 0.00, "EXPRESS": 0.20, "SAME_DAY": 0.50}

# SLA horizon in hours by rush tier (PRD §3.2).
SLA_HOURS = {"NONE": 120, "EXPRESS": 48, "SAME_DAY": 8}

# condition_score ceilings (PRD §3.5).
FAIL_CEILING = 50          # score < 50 -> FAIL; exactly 50 is NOT fail.
CONDITIONAL_CEILING = 80   # 50 <= score < 80 -> CONDITIONAL; >= 80 -> PASS.
CRITICAL_PENALTY_PER_PHOTO = 15
CRITICAL_PENALTY_CAP = 40
ROAD_TEST_BONUS = 5

# odometer rollback tolerance (PRD §3.6).
ROLLBACK_TOLERANCE_MILES = 100  # a reading must be MORE than 100 below to flag.

# vin_risk_score weights (PRD §3.6).
BRANDING_RISK = {"NONE": 0, "REBUILT": 25, "FLOOD": 40, "SALVAGE": 55, "LEMON": 70}
BRANDING_RANK = {"NONE": 0, "REBUILT": 1, "FLOOD": 2, "SALVAGE": 3, "LEMON": 4}
OWNER_PTS_PER_TITLE = 6
OWNER_TITLE_CAP = 5
ROLLBACK_PTS = 30
RECALL_PTS_PER = 5
RECALL_CAP = 3

# dispute_refund cap (PRD §3.8).
MISSED_DEFECT_CAP_PCT = 0.50

# Inspector default daily cap (PRD §3.1).
DEFAULT_MAX_DAILY_JOBS = 3

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_LIMIT = 1

# Logical-clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-04-01T00:00:00Z"
