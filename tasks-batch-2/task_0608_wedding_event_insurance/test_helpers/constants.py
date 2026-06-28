"""Domain thresholds — numeric constants from the PRD calculation contracts (§3)."""

# Rider rating (PRD §3.3)
RIDER_RATE = 0.015          # 1.5% of scheduled value
RIDER_MIN_PREMIUM = 2500    # cents floor
RIDER_MAX_PREMIUM = 50000   # cents ceiling

# Cancellation refund (PRD §3.6)
EARNED_MIN_RATIO = 0.25     # carrier retains at least 25% after free-look
DEFAULT_FREE_LOOK_DAYS = 15

# Claim resubmit cap (PRD §3.7)
MAX_REVISIONS = 3

# Logical-clock default at server startup (PRD §2.4)
DEFAULT_CLOCK_UTC = "2026-01-01T00:00:00Z"

# Canonical reference fixture values reused across tests.
CANC_BASE_PREMIUM_CENTS = 20000
CANC_PER_GUEST_CENTS = 300
CANC_LIMIT_CENTS = 5000000
CANC_DEPOSIT_SUBLIMIT_PCT = 0.5

LIAB_BASE_PREMIUM_CENTS = 15000
LIAB_PER_GUEST_CENTS = 200
LIAB_LIMIT_CENTS = 2000000
LIAB_DEPOSIT_SUBLIMIT_PCT = 1.0

LIQ_BASE_PREMIUM_CENTS = 18000
LIQ_PER_GUEST_CENTS = 250
LIQ_LIMIT_CENTS = 1000000

DEFAULT_ATTENDANCE = 150
# rated premiums at attendance 150
CANC_RATED_AT_150 = 65000   # 20000 + 300*150
LIAB_RATED_AT_150 = 45000   # 15000 + 200*150

# A random, non-existent but well-formed UUID for not-found probes.
RANDOM_UUID = "00000000-0000-4000-8000-000000000000"
