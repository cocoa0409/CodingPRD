"""Domain thresholds — numeric constants from PRD §2/§3 rules."""

# Segregation-of-duties threshold: self-approval barred at or above this amount (PRD §3.5)
SOD_THRESHOLD_CENTS = 100000

# Fixed invoice-payment overrun allowance: consumption may not be pushed past
# allocation by more than ten percent (PRD §2.7 / §3.5)
OVERRUN_ALLOWANCE_PCT = 0.10

# Budget posture ratio at which a budget is EXCEEDED (PRD §2.7)
EXCEEDED_RATIO = 1.0

# Department default governance thresholds (PRD §3.1)
DEFAULT_BUDGET_WARNING_PCT = 0.8
DEFAULT_BUDGET_CRITICAL_PCT = 0.95
DEFAULT_DEFLECTION_TARGET_PCT = 0.30

# A hard-closed period may be reopened at most this many times (PRD §3.7)
REOPEN_MAX = 2

# Pagination defaults and bounds (PRD §2.3)
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# Logical clock reading at server start (PRD §2.6)
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "FIRM_BLENDED_RATE_CENTS": 25000,
    "COUNSEL_LOADED_RATE_CENTS": 15000,
    "COUNSEL_CAPACITY_HOURS": 2000,
    "BUDGET_ALLOCATED_CENTS": 10000000,
    "MATTER_BUDGET_CENTS": 100000000,
}
