"""Domain thresholds and numeric constants named in the PRD (§2.7, §3)."""

# Ticket pricing (§3.5)
CONVENIENCE_FEE_CENTS = 150           # per-ticket fee on DAY orders only
GROUP_TIER1_PCT = 0.10                # quantity >= 1 x group_min_size
GROUP_TIER2_PCT = 0.15                # quantity >= 2 x group_min_size
GROUP_TIER3_PCT = 0.20                # quantity >= 4 x group_min_size
GROUP_TIER2_MULT = 2
GROUP_TIER3_MULT = 4

# Booth fees (§3.3, §3.9)
TIER_RATE_PRIME = 120                 # cents per sqft per week
TIER_RATE_STANDARD = 80
TIER_RATE_MEADOW = 50
RAIN_CREDIT_PCT = 0.25                # quarter of provisional fee per residency day
PRIME_SURCHARGE_PCT = 0.05
PRIME_SURCHARGE_THRESHOLD_CENTS = 20000

# Cast payroll (§3.2)
REHEARSAL_SHORTFALL_CENTS_PER_HOUR = 5000

# Rehearsal stage turnover buffer (§3.2)
TURNOVER_BUFFER_MINUTES = 15

# Jury weights (§3.3)
W_CRAFT = 0.5
W_AUTHENTICITY = 0.3
W_SAFETY = 0.2

# Logical clock startup default (§2.5)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Standard season window used across tests (14 days -> season_weeks 2)
DEFAULT_OPENING_DATE = "2026-06-06T00:00:00Z"
DEFAULT_CLOSING_DATE = "2026-06-20T00:00:00Z"

TEST_DEFAULTS = {
    "DAILY_CAPACITY": 500,
    "GROUP_MIN_SIZE": 10,
    "VOLUNTEER_MIN_HOURS": 0,
    "WEATHER_CALL_DEADLINE_HOUR": 6,
    "RAIN_CHECK_GRACE_DAYS": 14,
    "UNIT_PRICE_CENTS": 3000,
}
