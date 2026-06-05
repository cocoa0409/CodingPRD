"""Domain thresholds — numeric constants from the PRD's pricing, screening,
refund, and payout rules. Generic NON_EXISTENT_UUID comes from the framework.
"""

# Basis-points denominator: 10000 bps == a factor of 1.0 (PRD §2.5).
BPS_DENOMINATOR = 10000

# Guest risk scoring weights and pass threshold (PRD §3.5).
CANCEL_WEIGHT = 15
CHARGEBACK_WEIGHT = 60
UNVERIFIED_WEIGHT = 40
RISK_SCORE_CAP = 100
RISK_THRESHOLD = 50  # PASS only when risk_score is strictly less than 50.

# Cancellation refund tier lead-hour breakpoints (PRD §3.9), all inclusive >=.
FLEXIBLE_FULL_HOURS = 24
MODERATE_FULL_HOURS = 120
MODERATE_HALF_HOURS = 24
STRICT_HALF_HOURS = 168

# Listing default policy values (PRD §3.1).
DEFAULT_PET_FEE_CENTS = 0
DEFAULT_TAX_RATE_BPS = 0
DEFAULT_MIN_NIGHTS = 1
DEFAULT_GAP_NIGHTS = 0
DEFAULT_CANCELLATION_TIER = "MODERATE"
DEFAULT_SECURITY_DEPOSIT_CENTS = 0
DEFAULT_PLATFORM_COMMISSION_BPS = 1500
DEFAULT_PAYOUT_DELAY_DAYS = 1
DEFAULT_PAYOUT_METHOD = "BANK_TRANSFER"
DEFAULT_WEEKEND_MULTIPLIER_BPS = 10000

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
