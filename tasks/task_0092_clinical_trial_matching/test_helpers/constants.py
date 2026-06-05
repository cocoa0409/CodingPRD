"""Domain thresholds — numeric constants from the PRD calculations (§3.3, §3.6, §3.7)."""

# ─── Match-score weights (PRD §3.3) ─────────────────────
INCLUSION_WEIGHT = 0.6
EXCLUSION_WEIGHT = 0.4
MATCH_SCORE_DECIMALS = 4

# ─── Visit compensation (PRD §3.6) ──────────────────────
BASE_VISIT_CENTS = 7500
ON_TIME_MINUTES = 15          # deviation <= 15 → full bonus
LATE_GRACE_MINUTES = 60       # 15 < deviation <= 60 → reduced bonus
ON_TIME_BONUS_CENTS = 2500
LATE_BONUS_CENTS = 1000
MILEAGE_RATE_CENTS = 1200     # per visit beyond the first

# ─── Compensation sweep withholding (PRD §3.7) ──────────
WITHHOLDING_THRESHOLD_CENTS = 30000   # gross >= threshold → high rate
LOW_WITHHOLDING_RATE = 0.0
HIGH_WITHHOLDING_RATE = 0.10

# ─── Capacity / enrollment (PRD §3.1, §3.4) ─────────────
TARGET_ENROLLMENT_MIN = 1

# ─── Pagination (PRD §2.3) ──────────────────────────────
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
