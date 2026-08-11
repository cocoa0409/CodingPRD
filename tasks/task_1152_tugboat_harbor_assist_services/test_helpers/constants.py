"""Domain thresholds — numeric constants from PRD calculation rules."""

# Required-bollard-pull calculation (PRD §3.2).
MANEUVER_FACTOR = {
    "DOCKING": 1.5,
    "UNDOCKING": 1.2,
    "SHIFTING": 1.0,
    "ESCORT": 0.8,
    "TOWAGE": 2.0,
}
LOA_SURCHARGE_THRESHOLD_M = 200
LOA_MULTIPLIER = 1.25
MIN_BOLLARD_PULL_TONS = 20.0

# Liability settlement constants (PRD §3.9).
MIN_CAP_CENTS = 10000000
TUG_VALUE_CAP_FRACTION = 0.5
VOYAGE_INVOICE_MULTIPLE = 20
DEDUCTIBLE_PCT = 0.10

# Crew rest calculation (PRD §3.5).
REST_WINDOW_HOURS = 24
REQUIRED_REST_MINUTES = 600

# Pilot turnaround buffer (PRD §3.4).
PILOT_TURNAROUND_MINUTES = 60

# Logical clock default before any set call (PRD §2.4).
LOGICAL_CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Common reference timestamps used across the fixtures.
CLOCK_JUNE_01_MIDNIGHT = "2026-06-01T00:00:00Z"
