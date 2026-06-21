"""Domain thresholds — numeric constants from PRD calculations and capacity rules."""

# Virtual-queue supply fraction carved out of total hourly_throughput (PRD §3.1).
VQ_SUPPLY_FRACTION = 0.40

# Lightning Lane pricing thresholds (PRD §3.6).
RIDE_PEAK_LOAD = 0.75
SINGLE_PASS_CAP_CENTS = 9900

# Posted wait estimate baseline (PRD §3.8).
STANDBY_BASELINE = 20

# Per-guest ceilings (PRD §3.3).
VQ_MAX_PER_GUEST = 2

# Park day-phase default threshold (PRD §2.8).
DEFAULT_PEAK_THRESHOLD_PCT = 0.85

THRESHOLDS = {
    "VQ_SUPPLY_FRACTION": VQ_SUPPLY_FRACTION,
    "RIDE_PEAK_LOAD": RIDE_PEAK_LOAD,
    "SINGLE_PASS_CAP_CENTS": SINGLE_PASS_CAP_CENTS,
    "STANDBY_BASELINE": STANDBY_BASELINE,
    "VQ_MAX_PER_GUEST": VQ_MAX_PER_GUEST,
    "DEFAULT_PEAK_THRESHOLD_PCT": DEFAULT_PEAK_THRESHOLD_PCT,
}

# Common fixture defaults.
OPERATING_DATE = "2026-06-15"
CLOCK_BASE = "2026-06-15T09:00:00.000Z"
WINDOW_START = "2026-06-15T10:00:00.000Z"
WINDOW_END = "2026-06-15T11:00:00.000Z"
