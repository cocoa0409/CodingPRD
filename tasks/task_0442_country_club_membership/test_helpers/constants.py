"""Domain constants and defaults for the Country Club Membership API.

Values are drawn from PRD-declared defaults (§3.1) and the numeric scenarios
that the design-index test recipes pin.
"""

# Club policy defaults (PRD §3.1).
DEFAULT_RESIGNATION_REFUND_PCT = 80
DEFAULT_GUEST_VISITS_CAP_PER_PERIOD = 4
DEFAULT_FB_MINIMUM_CARRYOVER_ALLOWED = False

# Logical clock default before it is ever set (PRD §2.6, §3.8).
DEFAULT_LOGICAL_CLOCK = "2026-01-01T00:00:00Z"

# Resource default booking knobs (PRD §3.1).
DEFAULT_TURNAROUND_MINUTES = 0
DEFAULT_SEAT_CAPACITY = 1

# Reservation default (PRD §3.4).
DEFAULT_PARTY_SIZE = 1
