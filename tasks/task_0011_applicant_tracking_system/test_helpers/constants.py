"""Domain thresholds — numeric constants from PRD calculations (§3.6, §3.7, §3.1, §3.5)."""

# Referral bonus level base (cents), keyed by JobRequisition.target_level (PRD §3.6).
LEVEL_BASE_CENTS = {
    "JUNIOR": 100_000,   # $1,000
    "MID":    200_000,   # $2,000
    "SENIOR": 400_000,   # $4,000
    "STAFF":  600_000,   # $6,000
}

# Salary band multipliers for referral bonus (PRD §3.6).
# Thresholds in offer.base_salary_cents.
BAND_THRESHOLD_LOW = 10_000_000   # 1.0 below this
BAND_THRESHOLD_MID = 15_000_000   # 1.25 at/above LOW, below MID
BAND_THRESHOLD_HIGH = 20_000_000  # 1.5 at/above MID, below HIGH; 1.75 at/above HIGH

# Diversity uplift multiplier (PRD §3.6).
DIVERSITY_UPLIFT = 1.20

# Underrepresented ethnicity bucket (PRD §3.1, §3.6, §3.7).
UNDERREPRESENTED_ETHNICITIES = {"BLACK", "HISPANIC", "NATIVE", "PACIFIC", "TWO_OR_MORE"}

# Referral bonus payable decay (PRD §3.7).
DECAY_30 = 1.00
DECAY_60 = 0.75
DECAY_90 = 0.50
DECAY_CUTOFF_DAYS = 90

# Interview recommendation thresholds (PRD §3.5).
THRESH_STRONG_HIRE = 4.50
THRESH_HIRE = 3.50
THRESH_NO_HIRE = 2.50

# Offer expiry window (PRD §3.6).
OFFER_EXPIRY_DAYS = 14

# Interview panel constraints (PRD §3.5).
PANEL_MIN = 1
PANEL_MAX = 5
PANELIST_BUFFER_MINUTES = 15
INTERVIEW_MIN_DURATION = 15

# Diversity rounding (PRD §2.6, §3.1).
DIVERSITY_PCT_DECIMALS = 4
INTERVIEW_SCORE_DECIMALS = 2
