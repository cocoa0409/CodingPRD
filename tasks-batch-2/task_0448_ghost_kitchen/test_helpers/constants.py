"""Domain thresholds — numeric constants from the PRD's calculations and defaults."""

# Basis-point divisor for commission (PRD §2.9): bps / 10000 is the plain fraction.
BPS_DENOMINATOR = 10000

# Equipment booking buffer default (PRD §2.8): turnaround_buffer_minutes defaults to 0.
DEFAULT_TURNAROUND_BUFFER_MINUTES = 0

# Server logical-clock startup default (PRD §2.7).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# A canonical clock instant used by routing fixtures (well past lots' received_at).
# floor(epoch_seconds / 60) of 2026-01-05T00:00:00Z == 29459520 (PRD §2.7 current clock minute).
ROUTING_CLOCK_UTC = "2026-01-05T00:00:00Z"
ROUTING_CLOCK_EPOCH_MINUTE = 29459520

# Brand commission_rate_bps valid range (PRD §3.2 / §3.10): 0..5000 inclusive.
COMMISSION_RATE_BPS_MIN = 0
COMMISSION_RATE_BPS_MAX = 5000

# A syntactically valid UUID that resolves to no resource.
NONEXISTENT_UUID = "00000000-0000-0000-0000-000000000000"
