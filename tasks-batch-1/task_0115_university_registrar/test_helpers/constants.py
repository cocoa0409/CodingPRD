"""Domain thresholds — numeric constants from the University Registrar PRD.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Grade-point mapping on the 4.0 scale (PRD §3.8).
GRADE_POINTS = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}

# Academic-standing thresholds (PRD §3.8).
STANDING_GOOD_MIN = 2.00
STANDING_WARNING_MIN = 1.00

# Degree-audit passing-grade floor (PRD §3.9): D or better, grade points >= 1.0.
PASSING_GRADE_POINTS = 1.0

# Default prerequisite minimum grade points when omitted (PRD §3.1).
DEFAULT_MIN_GRADE_POINTS = 1.0

# Default refund fractions when a term omits them (PRD §3.1).
DEFAULT_REFUND_FULL_PCT = 1.0
DEFAULT_REFUND_PARTIAL_PCT = 0.5

# Canonical fixture defaults shared across the suite. These mirror the
# canonical conventions the design indices were authored against:
#   per-credit cost 50000 cents -> a 3cr course charges 150000 cents.
PER_CREDIT_COST_CENTS = 50000

# Canonical term deadlines (ISO 8601 UTC).
REGISTRATION_OPENS_AT = "2026-01-01T00:00:00Z"
ADD_DEADLINE = "2026-02-01T00:00:00Z"
DROP_DEADLINE = "2026-02-15T00:00:00Z"
WITHDRAW_DEADLINE = "2026-03-15T00:00:00Z"

# Canonical clocks.
CLOCK_REGISTRATION = "2026-01-10T00:00:00Z"   # >= window_opens_at, <= add_deadline
WINDOW_OPENS_AT = "2026-01-05T00:00:00Z"
CLOCK_AFTER_DROP_DEADLINE = "2026-02-20T00:00:00Z"   # in partial/withdraw window
CLOCK_AT_DROP_DEADLINE = "2026-02-15T00:00:00Z"      # inclusive full-refund boundary

# Pagination bounds (PRD §2.3).
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
