"""Domain constants for the Promotion Coupon Engine.

Numeric anchors used by tests: the standard active window, the default in-window
clock, and the SINGLE_USE coupon cap (the only literal constant the PRD pins for
usage counting — a SINGLE_USE coupon's cap is one).
"""

# Time anchors (ISO 8601 UTC). The default clock falls strictly inside the window.
ACTIVE_FROM = "2026-06-01T00:00:00Z"
ACTIVE_UNTIL = "2026-07-01T00:00:00Z"
DEFAULT_CLOCK = "2026-06-15T00:00:00Z"

# A SINGLE_USE coupon admits at most one confirmed redemption ever.
SINGLE_USE_CAP = 1

# Every second matching unit is free for BOGO.
BOGO_PAIR_SIZE = 2
