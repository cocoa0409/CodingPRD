"""Domain thresholds — numeric constants from the PRD's calculations (§3)."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Qualification predicate (§3.3): age is at least 18; current year from server clock.
MIN_AGE = 18

# Failure-to-appear disqualification (§3.1, §3.6): default threshold when omitted.
DEFAULT_FTA_DISQUALIFY_THRESHOLD = 3

# Deferral cap (§3.5): a summons may be deferred at most twice (deferral_count < 2).
MAX_DEFERRALS = 2

# A syntactically valid UUID that resolves to nothing — used by not-found probes
# where the corner design pins a specific literal.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"

# Pay configuration used across the pay/mileage fixtures (the term defaults the
# difficulty/corner recipes build on).
TEST_DEFAULTS = {
    "DAILY_PAY_CENTS": 4000,
    "HALF_DAY_PAY_CENTS": 2000,
    "FULL_DAY_HOURS": 6.0,
    "MILEAGE_RATE_CENTS": 25,
    "PAY_DAY_CAP": 3,
}
