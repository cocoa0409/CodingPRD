"""Domain thresholds — numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Demurrage tiered pricing (PRD §3.6).
TIER1_DAYS = 3
TIER2_DAYS = 4
TIER1_RATE_CENTS = 5000
TIER2_RATE_CENTS = 8000
TIER3_RATE_CENTS = 12000

# Gate slot clash turnaround buffer in minutes (PRD §3.4).
GATE_BUFFER_MIN = 30

# Reefer excursion band in degrees Celsius (PRD §3.8); boundary is strict (>).
EXCURSION_BAND_C = 2.0

# No-show reschedule cap (PRD §3.4): an appointment whose no_show_count exceeds
# three may not be rescheduled.
MAX_NO_SHOWS = 3

# Default demurrage free-time period in days (PRD §3.1).
DEFAULT_FREE_TIME_DAYS = 5

# Logical clock epoch (PRD §2.4).
CLOCK_EPOCH = "2026-01-01T00:00:00.000Z"

# A bogus-but-well-formed UUID for FK-not-found tests.
BOGUS_UUID = "00000000-0000-4000-8000-000000000099"
