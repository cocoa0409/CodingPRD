"""Domain thresholds — numeric constants from the PRD calculations and workflows."""

# Coding compliance risk scoring (PRD §3.5)
W_UNSPECIFIED = 40            # unspecified principal diagnosis weight
W_PER_SECONDARY = 10         # points per secondary code beyond the first three
SECONDARY_FREE_COUNT = 3     # number of secondary codes that add nothing
W_MISMATCH = 35              # charge-to-code mismatch weight
AUDIT_THRESHOLD = 50         # score >= 50 routes to AUDIT_HOLD (inclusive)

# Bad-debt aging (PRD §3.11)
BAD_DEBT_AGING_DAYS = 120    # minimum days since issued_at to send to collections

# Payer filing-rule defaults (PRD §3.1)
DEFAULT_TIMELY_FILING_DAYS = 90
DEFAULT_APPEAL_WINDOW_DAYS = 30

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
