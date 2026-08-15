"""Domain thresholds — numeric constants named in the PRD."""

# Logical clock startup default (PRD logical clock section).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Per-shift comp ceiling in cents (PRD parking-session comp rule).
    "COMP_CAP_PER_SHIFT_CENTS": 5000,
    # Reconciliation variance routing thresholds; both inclusive.
    "SHORTAGE_REVIEW_CENTS": 2000,
    "OVERAGE_REVIEW_CENTS": 5000,
    # Auto-incident severity split on absolute variance.
    "VARIANCE_HIGH_CENTS": 10000,
    # Housekeeping window hygiene buffer on the same facility+level.
    "WINDOW_BUFFER_MINUTES": 30,
    # EV utilization review: session-basis floor and rolling window.
    "MIN_UTIL_PCT": 5.0,
    "UTIL_WINDOW_DAYS": 28,
    # Sliding-notice cancellation threshold in hours.
    "SLIDING_THRESHOLD_HOURS": 48,
    # Heartbeat staleness limit used by the close-of-business sweep.
    "HEARTBEAT_STALE_HOURS": 24,
    # Structural condition classification anchors.
    "CRITICAL_LOAD_RATING": 2,
    "CRITICAL_INDEX": 40,
    "FAIR_INDEX": 70,
    # Media limit per agreement.
    "CREDENTIAL_LIMIT_PER_AGREEMENT": 2,
}

# Reference tariff used across fee-engine tests (PRD transient fee rules):
# 15-minute grace, 500 first hour, 300 per additional hour, 2400 daily cap,
# 1500 event flat, 2400 per-day lost ticket.
REFERENCE_TARIFF = {
    "grace_minutes": 15,
    "first_hour_cents": 500,
    "additional_hour_cents": 300,
    "daily_max_cents": 2400,
    "event_flat_cents": 1500,
    "lost_ticket_daily_cents": 2400,
}

TEST_DEFAULTS = {
    "FACILITY_TOTAL_SPACES": 200,
    "FACILITY_MONTHLY_CAPACITY": 50,
    "FACILITY_EVENT_POOL_SPACES": 40,
    "OPENING_FLOAT_CENTS": 10000,
    "MONTHLY_RATE_CENTS": 10000,
    "CREDENTIAL_DEPOSIT_CENTS": 5000,
    "CHARGER_MAX_KW": 7,
}
