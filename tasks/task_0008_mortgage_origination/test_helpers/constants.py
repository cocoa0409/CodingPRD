"""Domain thresholds — numeric constants from PRD §3 calculations and validations.

All values are PRD-stated; the file is a single source of truth so tests do not
re-derive thresholds.
"""

# ---------------------------------------------------------------------
# Per-extension fee schedule for rate-lock extensions (PRD §3.6).
# ---------------------------------------------------------------------
EXT_FEE_TIER_BPS: dict = {7: 5, 15: 10, 30: 25}
EXT_DAYS_ALLOWED: list = [7, 15, 30]
MAX_EXTENSIONS: int = 2
LOCK_TOTAL_DURATION_DAYS_CAP: int = 90  # PRD §3.6 90-day total-duration cap

# ---------------------------------------------------------------------
# DTI thresholds (PRD §3.2).
# ---------------------------------------------------------------------
DTI_FRONT_END_MAX: float = 0.31
DTI_BACK_END_MAX: float = 0.43
DEFAULT_UNDERWRITING_RATE_BPS: int = 700

# ---------------------------------------------------------------------
# LTV thresholds (PRD §3.2 / §3.4).
# ---------------------------------------------------------------------
LTV_PREQUAL_MAX: float = 0.95

# ---------------------------------------------------------------------
# Pre-qualification ceilings (PRD §3.2).
# ---------------------------------------------------------------------
MIN_CREDIT_SCORE_FOR_PREQUAL: int = 580
CONFORMING_LOAN_CAP_CENTS: int = 4_000_000_00  # $4,000,000 = 400,000,000 cents

# ---------------------------------------------------------------------
# Rounding rules (PRD §2.9).
# ---------------------------------------------------------------------
RATIO_DECIMAL_PLACES: int = 4
APR_PERCENT_DECIMAL_PLACES: int = 3

# ---------------------------------------------------------------------
# TRID waiting periods (PRD §3.7).
# ---------------------------------------------------------------------
LE_WAITING_DAYS: int = 7
CD_WAITING_DAYS: int = 3
CD_REDISCLOSE_TOLERANCE_BPS: float = 12.5

# ---------------------------------------------------------------------
# Loan-term whitelist (PRD §3.1).
# ---------------------------------------------------------------------
LOAN_TERM_MONTHS_ALLOWED: list = [180, 360]
LOCK_TERM_DAYS_ALLOWED: list = [30, 45, 60]

# ---------------------------------------------------------------------
# Credit-score range (PRD §3.1).
# ---------------------------------------------------------------------
CREDIT_SCORE_MIN: int = 300
CREDIT_SCORE_MAX: int = 850
