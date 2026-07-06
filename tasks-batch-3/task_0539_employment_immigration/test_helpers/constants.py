"""Domain thresholds and numeric constants declared in the PRD.

All monetary amounts are integer cents (PRD §2.5). Time windows are day-granular
on the logical clock (PRD §2.4).
"""

# --- H-1B filing-fee tiers (PRD §3.6) ---
BASE_FILING_FEE_CENTS = 46000
FRAUD_FEE_CENTS = 50000
ACWIA_SMALL_CENTS = 75000      # employee_count <= 25
ACWIA_LARGE_CENTS = 150000     # employee_count > 25
ACWIA_SIZE_THRESHOLD = 25
PL_SIZE_THRESHOLD = 50         # PL 114-113 fee only when employee_count > 50
PL_114_113_FEE_CENTS = 400000

# --- PERM recruitment / quiet-period / validity windows (PRD §3.3) ---
RECRUITMENT_MIN_DAYS = 30
QUIET_PERIOD_DAYS = 30
PERM_VALIDITY_DAYS = 180

# --- RFE response window (PRD §3.6) ---
RFE_RESPONSE_DAYS = 87

# --- Public-access-file completeness scoring (PRD §3.4) ---
PAF_DOC_WEIGHT = 25            # each of the four PAF documents is worth 25 points
PAF_COMPLETE_SCORE = 100

# --- Aggregate wage obligation proration (PRD §3.4 / §2.5) ---
FULL_TIME_HOURS = 40

# --- Logical clock (PRD §2.4) ---
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# --- Pagination (PRD §2.3) ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
