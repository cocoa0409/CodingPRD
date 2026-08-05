"""Domain thresholds — numeric constants from the PRD's billing and scheduling rules."""

# Federal-poverty-level math for the self-pay sliding scale (PRD §3.8).
FPL_BASE_CENTS = 1_560_000
FPL_PER_PERSON_CENTS = 550_000

# Therapy base rates by modality (PRD §3.8).
INDIVIDUAL_RATE_CENTS = 12503
GROUP_RATE_CENTS = 6503

# Sliding-scale minimum fee floor (PRD §3.8).
MIN_FEE_CENTS = 2000

# Room turnaround buffer in minutes (PRD §3.5).
TURNAROUND_BUFFER_MINUTES = 15

# Server logical clock startup default (PRD §2.5).
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
