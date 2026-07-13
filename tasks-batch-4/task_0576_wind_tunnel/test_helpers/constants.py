"""Domain thresholds and pricing constants drawn from the PRD narratives."""

# Scheduling / lifecycle thresholds
MIN_SESSION_MINUTES = 15          # PRD §3.4: duration must be at least fifteen minutes
WAIVER_VALID_DAYS = 90            # PRD §2.7: expires_at is ninety days after signed_at
SENIOR_UPGRADE_THRESHOLD = 2      # PRD §3.1: two completed sessions upgrade JUNIOR -> SENIOR

# Booking price (PRD §3.3)
WALK_IN_SURCHARGE_MULT = 1.20     # walk-in adds a twenty-percent surcharge
PARTY_MULT = {"1-2": 1.00, "3-4": 0.95, "5+": 0.90}
LEAD_DISCOUNT = {"lt3": 0.00, "3-6": 0.05, "ge7": 0.10}
MEMBER_DISCOUNT = {"NONE": 0.00, "STANDARD": 0.10, "PRO": 0.15}

# Add-on pricing (PRD §3.8)
VIDEO_PRICE_CENTS = 3335
COACHING_RATE_PER_MIN_CENTS = 1245

# Logical clock (PRD §2.7)
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# Convenient reusable timestamps for session windows (all >= 15 min duration)
SESSION_START = "2026-05-10T10:00:00Z"
SESSION_END = "2026-05-10T10:30:00Z"
