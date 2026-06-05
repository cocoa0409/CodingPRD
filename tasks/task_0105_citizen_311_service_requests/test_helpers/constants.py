"""Domain thresholds — numeric constants from the PRD calculations."""

# Cluster membership radius (PRD §2.9 / §3.7): inclusive boundary at 150 meters.
CLUSTER_RADIUS_METERS = 150

# Reopen window (PRD §3.5): a RESOLVED request may be reopened within 72 hours
# of resolved_at.
REOPEN_WINDOW_HOURS = 72

# Earth radius used by the haversine distance formula (PRD §2.9).
EARTH_RADIUS_METERS = 6_371_000

# A clock anchor reused by time-dependent fixtures.
DEFAULT_CLOCK_ISO = "2026-06-01T08:00:00Z"
