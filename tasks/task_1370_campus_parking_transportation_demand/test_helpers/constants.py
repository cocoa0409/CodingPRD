"""Domain thresholds and shared fixture constants (PRD §2.5, §3).

Shared fixture term: TERM_START..TERM_END spans 112 days (exactly 16 weeks);
midterm date is 2026-09-28. The logical clock startup default is
2026-08-01T00:00:00Z (before the term starts), so a purchase without an
explicit valid_from covers the full term.
"""

# Logical clock (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Shared allocation term window used across the suite
TERM_START = "2026-08-03"
TERM_END = "2026-11-22"

# Patron standing (PRD §3.1)
BLOCK_THRESHOLD_CENTS = 10000

# Permit fee / refund (PRD §3.3, §3.5)
SURCHARGE_PCT = 0.05
ADMIN_FEE_CENTS = 500

# Waitlist offers (PRD §3.4)
OFFER_TTL_HOURS = 72
MAX_REQUEUES = 2
ROLE_WEIGHT = {"FACULTY": 100, "STAFF": 80, "STUDENT": 60}
WAIT_DAY_CAP = 30
WAIT_DAY_POINTS = 2
RESIDENCY_BONUS = 10
DECLINE_PENALTY = 15

# Citation fines (PRD §3.6.1)
VIOLATION_BASE_CENTS = {
    "NO_VALID_PERMIT": 7500,
    "EXPIRED_PERMIT": 5000,
    "WRONG_ZONE": 4000,
    "CLOSED_LOT": 6000,
}
REPEAT_WINDOW_DAYS = 365
REPEAT_THRESHOLD = 2
ESCALATION_MULTIPLIER = 1.5
EVENT_DAY_SURCHARGE_CENTS = 1500

# Incentive program (PRD §3.9)
POINTS_PER_DAY = 10
MAX_ACCRUAL_DAYS_PER_POSTING = 31
REDEMPTION_BLOCK_POINTS = 500
REDEMPTION_BLOCK_CREDIT_CENTS = 2500

# Shuttle fleet window buffer (PRD §3.8)
FLEET_BUFFER_MINUTES = 30

# Canonical full-term fee at the default clock for base_fee_cents=80000:
# 16 weeks * 5000 weekly rate -> 80000 base, 4000 surcharge, 84000 total/paid.
FULL_TERM_BASE_CENTS = 80000
FULL_TERM_SURCHARGE_CENTS = 4000
FULL_TERM_TOTAL_CENTS = 84000
