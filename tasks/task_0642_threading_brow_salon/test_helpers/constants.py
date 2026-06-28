"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# No-show strike escalation thresholds (PRD §3.7).
SUSPEND_THRESHOLD = 2   # at least 2 strikes -> SUSPENDED
BAN_THRESHOLD = 4       # at least 4 strikes -> BANNED

# Queue recall bound (PRD §3.3).
MAX_RECALLS = 2

# Loyalty point cash value at settle (PRD §3.7).
POINT_VALUE_CENTS = 5

# Default loyalty earn rate when omitted on salon create (PRD §3.1).
DEFAULT_LOYALTY_EARN_RATE_BPS = 500

# Default chair sanitation dwell minutes (PRD §3.1).
DEFAULT_SANITATION_MINUTES = 5

# Membership tier -> (discount_bps, total_credits) (PRD §3.6).
TIER_DISCOUNT_BPS = {"BRONZE": 500, "SILVER": 1000, "GOLD": 1500}
TIER_TOTAL_CREDITS = {"BRONZE": 4, "SILVER": 8, "GOLD": 12}

# Server startup default logical clock (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# Common test clock used by fixtures that need licenses/certs valid.
TEST_CLOCK = "2026-02-01T09:00:00Z"
FAR_FUTURE_EXPIRY = "2027-01-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
