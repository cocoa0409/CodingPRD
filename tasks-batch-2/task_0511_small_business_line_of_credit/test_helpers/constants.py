"""Domain thresholds — numeric constants from the PRD calculations (§3.2-§3.8)."""

# Risk-score weighted blend (PRD §3.2).
W_BALANCE = 0.50
W_REVENUE = 0.35
W_NSF = 0.40
NSF_PENALTY_STEP = 0.15

# Tier selection by score band + advance multiples + fee factors (PRD §3.2, §3.3).
TIER_A_FLOOR = 80
TIER_B_FLOOR = 65
APPROVAL_SCORE_FLOOR = 50

ADVANCE_MULTIPLE = {"TIER_A": 1.50, "TIER_B": 1.00, "TIER_C": 0.60}
FEE_BPS = {"TIER_A": 800, "TIER_B": 1200, "TIER_C": 1800}

# Underwriting NSF gate (PRD §3.2).
NSF_UNDERWRITE_MAX = 3

# Time-to-live windows (PRD §3.2, §3.7).
APPLICATION_TTL_DAYS = 14
RENEWAL_TTL_DAYS = 30

# Basis-point denominator (PRD §3.4, §3.7).
BPS_DENOMINATOR = 10000

# Remittance target percentages by cadence (PRD §3.5).
DAILY_REMIT_PCT = 0.02
WEEKLY_REMIT_PCT = 0.10

# NSF retry / delinquency / default constants (PRD §3.5, §3.6).
NSF_MAX_RETRIES = 5
NSF_RETRY_GAP_DAYS = 2
NSF_DELINQUENCY_THRESHOLD = 3
NSF_DEFAULT_THRESHOLD = 5

# APR annualization (PRD §3.7).
DAYS_PER_YEAR = 365

# Default logical clock at server startup (PRD §2.4).
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
