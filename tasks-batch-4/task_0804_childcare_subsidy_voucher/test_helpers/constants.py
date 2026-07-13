"""Domain thresholds — numeric constants named in the PRD's calculations (§3)."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # re-exported for convenience

# Minimum summed weekly activity hours for activity eligibility (PRD §3.2).
MIN_WEEKLY_ACTIVITY_HOURS = 20

# Months added to effective_date for the redetermination deadline (PRD §3.2).
REDETERMINATION_MONTHS = 12

# Maximum paid-absence allowance per service month (PRD §3.6).
MAX_PAID_ABSENCE_DAYS = 5

# Sliding-fee copay bands: (max_ratio, pct). Ascending scan (PRD §3.2).
COPAY_BANDS = [
    (0.50, 2),
    (0.75, 5),
    (1.00, 8),
    (1.25, 10),
]

# Logical clock default at server startup (PRD §2.7).
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"
