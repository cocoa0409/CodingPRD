"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Incentive accrual (PRD §3.5)
LENGTH_BONUS_STEP_MIN = 5          # divide estimated_minutes by 5 minute steps
LENGTH_BONUS_POINTS_PER_STEP = 10  # 10 points per step
CENTS_PER_POINT = 2                # cash_cents = points_requested * 2

# Quality score weights and thresholds (PRD §3.6)
W_ATTENTION = 0.5
W_SPEED = 0.3
W_STRAIGHTLINE = 0.2
MIN_SPEED_FRACTION = 0.34
MAX_SPEED_FRACTION = 3.0
STRAIGHTLINE_PENALTY_PER_RUN = 4
QUALITY_PASS_THRESHOLD = 70        # PASS when score >= 70
QUALITY_FLAG_THRESHOLD = 50        # FLAGGED when 50 <= score < 70; FAIL below 50

# Quality multipliers at finalize (PRD §3.5)
MULT_TIER_HIGH = 1.25              # score >= 90
MULT_TIER_MID = 1.00              # score >= 70
MULT_TIER_LOW = 0.50              # score >= 50

# Panel health (PRD §3.6)
RECENT_WINDOW = 5
INACTIVITY_STEP_DAYS = 30
INACTIVITY_PENALTY_PER_STEP = 5
CHURN_THRESHOLD = 50               # ACTIVE<->AT_RISK boundary
CHURN_FLOOR = 30                   # AT_RISK->CHURNED requires below this

# Recruitment / payout limits (PRD §3.2, §3.7)
MAX_RESCREENS = 3                  # rescreen_count must be strictly below 3
MIN_PAYOUT_POINTS = 100            # request must redeem at least 100 points

# Logical clock (PRD §2.4)
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"
