"""Domain thresholds and shared constants from the PRD calculations (§3.7, §3.10)
and the logical-clock default (§2.6)."""

# Logical clock startup default (PRD §2.6).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Deviation score (PRD §3.7).
WEIGHT_CRITICAL = 3
WEIGHT_MAJOR = 2
WEIGHT_MINOR = 1
DEVIATION_ACCEPT_BLOCK = 150  # exactly 150 blocks ACCEPT

# Contract tier price (PRD §3.7).
TIER1_BASE = 4.50
TIER2_BASE = 4.20
TIER3_BASE = 3.95
TIER1_CAP_KG = 10000
TIER2_CAP_KG = 50000
INDEX_NAME_SPOT = "INGREDIENT-SPOT"

# Annual rebate (PRD §3.7).
REBATE_HIGH_RATE = 0.02
REBATE_LOW_RATE = 0.015
REBATE_HIGH_RATE_THRESHOLD = 250000

# Supplier composite risk (PRD §3.10).
RISK_W_COA = 0.35
RISK_W_AUDIT = 0.30
RISK_W_OVERDUE = 0.20
RISK_W_DECLARATION = 0.15
RISK_OVERDUE_UNIT = 25
RISK_SUSPEND_THRESHOLD = 70

# Audit cadence (PRD §3.10).
CADENCE_MONTHS = {"TIER_A": 12, "TIER_B": 6, "TIER_C": 3}
ESCALATION_DAYS = 7
AUDIT_WINDOW_DAYS = 14

# Substitution auto-approval fiscal gate (PRD §3.8).
AUTO_APPROVE_MAX_ABS_DELTA = 0.5000

# Qualification gate (PRD §3.3).
QUALIFICATION_SCORE_MIN = 70

# Dual sourcing (PRD §3.10).
MIN_DUAL_SOURCES = 2

# Shared timestamp defaults used by fixtures.
SPEC_EFFECTIVE_DATE = "2026-07-01T00:00:00Z"
SPEC_EFFECTIVE_DATE_V2 = "2026-07-15T00:00:00Z"
DECLARATION_VALID_FROM = "2026-01-01T00:00:00Z"
DECLARATION_VALID_UNTIL = "2027-01-01T00:00:00Z"
CONTRACT_WINDOW_START = "2026-01-01T00:00:00Z"
CONTRACT_WINDOW_END = "2027-01-01T00:00:00Z"
COA_RECEIVED_AT = "2026-08-01T00:00:00Z"

# Operator ids used as segregation-of-duties anchors (opaque, PRD §2.1).
AUTHOR_1 = "author-1"
AUTHOR_2 = "author-2"
QM_1 = "qm-1"
QM_2 = "qm-2"
SQE_1 = "sqe-1"
SQE_2 = "sqe-2"
PM_1 = "pm-1"
PM_2 = "pm-2"
RA_1 = "ra-1"
ADMIN_1 = "admin-1"
