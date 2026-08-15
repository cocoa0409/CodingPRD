"""Domain thresholds — numeric constants from the PRD's calculation rules (§3.4-§3.10)."""

# Logical clock startup default (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Fatigue governance (PRD §3.7)
MAX_DUTY_MINUTES_7D = 4320
DUTY_WINDOW_DAYS = 7

# Rest rule (PRD §3.4)
LONG_DUTY_THRESHOLD_MINUTES = 480
LONG_REST_MINUTES = 960
SHORT_REST_MINUTES = 600

# Boat turnaround buffer (PRD §2.10)
BOAT_TURNAROUND_BUFFER_MINUTES = 45

# Apprentice readiness (PRD §3.10)
STANDARD_TRIPS_REQUIRED = 50
ACCEL_TRIPS_REQUIRED = 40
ACCEL_EVAL_AVG_REQUIRED = 85

# Revenue distribution levy (PRD §3.8)
LEVY_TIER_THRESHOLD_CENTS = 10_000_000
LEVY_LOW_PCT = 0.08
LEVY_HIGH_PCT = 0.10

# Standard tariff fixture used across tests (three tiers; effective before the
# default clock so it resolves ACTIVE):
#   (0, 5000] @ 20c/gt ; (5000, 20000] @ 15c/gt ; (20000, inf) @ 10c/gt
MAIN_TARIFF_TIERS = [
    {"min_gt_exclusive": 0, "max_gt_inclusive": 5000, "rate_cents_per_gt": 20},
    {"min_gt_exclusive": 5000, "max_gt_inclusive": 20000, "rate_cents_per_gt": 15},
    {"min_gt_exclusive": 20000, "max_gt_inclusive": None, "rate_cents_per_gt": 10},
]
MAIN_TARIFF_EFFECTIVE_FROM = "2026-01-01T00:00:00Z"
DRAFT_SURCHARGE_THRESHOLD_DM = 100
DRAFT_SURCHARGE_PCT = 0.15
DETENTION_FREE_MINUTES = 30
DETENTION_RATE_CENTS_PER_MINUTE = 200
DELAY_RATE_CENTS_PER_MINUTE = 150

# Common instants (all strictly after the default clock unless noted)
ENDORSEMENT_EXPIRY_FUTURE = "2027-01-01T00:00:00Z"
ETA_DEFAULT = "2026-08-10T00:00:00Z"
