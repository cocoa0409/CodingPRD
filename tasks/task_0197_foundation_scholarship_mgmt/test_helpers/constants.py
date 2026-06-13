"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Rubric weighted-value weights (PRD §3.4): academic 1/2, need 3/10, essay 2/10.
W_ACADEMIC = 0.5
W_NEED = 0.3
W_ESSAY = 0.2

# Scoring quorum: finalize-scoring requires at least two SUBMITTED scores (PRD §3.5).
SCORING_QUORUM = 2

# Award score floor: rubric_total must be at least 60 (PRD §3.6).
AWARD_SCORE_FLOOR = 60

# Provisional-award score-tier multipliers (PRD §3.6).
TIER_HIGH = 90      # rubric_total >= 90 -> MULT_HIGH
TIER_MID = 75       # 75 <= rubric_total < 90 -> MULT_MID
MULT_HIGH = 1.00
MULT_MID = 0.80
MULT_LOW = 0.60     # 60 <= rubric_total < 75

# Final-award verified-GPA factors (PRD §3.7).
GPA_HIGH = 3.50     # verified_gpa >= 3.50 -> FACTOR_HIGH
GPA_MID = 3.00      # 3.00 <= verified_gpa < 3.50 -> FACTOR_MID
FACTOR_HIGH = 1.00
FACTOR_MID = 0.90
FACTOR_LOW = 0.80   # verified_gpa < 3.00

# Revision ceiling: resumption allowed only while revision_round <= 2 (PRD §3.5).
MAX_REVISION_ROUNDS = 2

# Concurrent committee-assignment cap of three (PRD §3.4).
MAX_CONCURRENT_ASSIGNMENTS = 3

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# GPA value range (PRD §2.8).
GPA_MIN = 0.00
GPA_MAX = 4.00

# Rubric raw-score range (PRD §3.4).
RAW_SCORE_MIN = 0
RAW_SCORE_MAX = 100
