"""Domain thresholds — numeric constants from the PRD calculations (§2, §3)."""

# Answer window (§3.2): created_at + 14 days.
ANSWER_WINDOW_DAYS = 14

# Rental-assistance award (§3.3).
INCOME_CAP_BASE_CENTS = 300000
INCOME_CAP_PER_MEMBER_CENTS = 100000
ASSISTANCE_PROGRAM_BUDGET_CENTS = 5000000

# Installment schedule (§3.5).
INSTALLMENT_INTERVAL_DAYS = 30

# Money judgment (§3.7).
JUDGMENT_FILING_FEE_CENTS = 4500

# Lockout officer buffer (§3.8).
LOCKOUT_BUFFER_HOURS = 48

# Sealing eligibility (§3.9).
SEALING_WAIT_DAYS = 90

# Logical clock startup default (§2.5).
CLOCK_START = "2026-05-01T00:00:00Z"

# Pagination defaults (§2.3).
PAGINATION = {"limit": 10, "min": 1, "max": 100, "offset": 0}
