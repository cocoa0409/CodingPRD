"""Domain thresholds — numeric constants from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Over-run allowance applied at run completion (PRD 3.5): a run may produce at
# most planned_units * (1 + 10/100).
OVERRUN_ALLOWANCE_PCT = 10

# QA release gate (PRD 3.6): reject rate must not exceed this maximum.
MAX_REJECT_RATE = 0.05

# Lot-code sequence is zero-padded to three digits (PRD 3.4).
SEQ_PAD = 3

# Defaults from the PRD for optional create fields.
DEFAULT_CHANGEOVER_MINUTES = 30
DEFAULT_REST_BUFFER_MINUTES = 15

# The server logical clock's startup default (PRD 2.11).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# A non-existent but well-formed UUID for not-found tests.
RANDOM_UUID = "00000000-0000-4000-8000-000000000000"
