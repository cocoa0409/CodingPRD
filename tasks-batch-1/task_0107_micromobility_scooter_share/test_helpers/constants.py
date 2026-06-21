"""Domain thresholds — numeric constants drawn from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Minimum battery state-of-charge to start a trip / return a vehicle to service (PRD §3.3, §3.1).
MIN_START_BATTERY_PCT = 20

# Forward-looking provisional fare assumes a projected 15-minute ride (PRD §3.3).
PROJECTED_TRIP_MINUTES = 15

# Cancel grace window in seconds (PRD §3.5).
GRACE_SECONDS = 120

# Auto-swap task window length when a trip ends with a depleted battery (PRD §3.5).
AUTO_SWAP_WINDOW_SECONDS = 3600

# Technician assignment buffer applied to each side of a task window (PRD §3.7).
TASK_BUFFER_SECONDS = 600

# Low-income approval income ceiling per household member, in cents (PRD §3.2).
INCOME_CEILING_PER_PERSON_CENTS = 3_000_000

# Base parking fine and the low-income reduction (PRD §3.5).
BASE_PARKING_FINE_CENTS = 2500
LOW_INCOME_FINE_DISCOUNT_PCT = 0.40
LOW_INCOME_FINE_CENTS = 1500  # round_half_up(2500 * (1 - 0.40))

SECONDS_PER_MINUTE = 60

# A syntactically valid UUID guaranteed not to resolve to any resource.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
