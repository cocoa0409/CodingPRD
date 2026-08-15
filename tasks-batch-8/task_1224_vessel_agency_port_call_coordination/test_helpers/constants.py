"""Domain thresholds — numeric constants from PRD calculation rules."""

# Logical clock startup default (PRD: "startup default, before anyone sets it,
# is exactly 2026-05-01T00:00:00Z")
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

# Agency fee / funding (PRD §3.8)
AGENCY_FEE_PCT = 0.025
ADVANCE_PCT = 0.80

# Purchase order variance tolerance (PRD §3.4: "at most 10.0 percent")
VARIANCE_TOLERANCE_PCT = 10.0
VARIANCE_SENTINEL = 999.99

# Late cancellation (PRD §3.5: quarter of estimated_cents inside two hours)
LATE_CANCEL_PCT = 0.25
LATE_CANCEL_CUTOFF_MINUTES = 120

# Resource-unit turnaround buffer (PRD §2.9: forty-five minutes on both ends)
RESOURCE_UNIT_BUFFER_MINUTES = 45

# Port dues day rules (PRD §3.8)
MIN_DAYS = 1
NIGHT_WINDOW_START_HOUR = 18
NIGHT_WINDOW_END_HOUR = 6

# Service-order start lead (PRD §3.5: sixty minutes before window_start)
SERVICE_START_LEAD_MINUTES = 60

TEST_DEFAULTS = {
    "CLOCK_BASE": "2026-05-01T00:00:00Z",
}
