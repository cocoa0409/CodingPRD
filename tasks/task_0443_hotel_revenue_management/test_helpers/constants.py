"""Domain thresholds — numeric constants from PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Pickup forecast (PRD §3.3)
PACE_FACTOR = 1.5
TRAILING_DAILY_PICKUP = 2

# Rate yield last-room-value premium (PRD §3.4)
LRV_SCARCITY_ROOMS = 5
LRV_PREMIUM_PCT = 0.20

# Channel sync parity band (PRD §3.6)
PARITY_TOLERANCE = 0.02

# Oversell bound (PRD §2.7)
OVERBOOKING_LIMIT_MAX = 0.30

# Logical-clock startup default (PRD §2.4)
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# A non-existent but well-formed UUID used in not-found / FK tests.
PLACEHOLDER_PROPERTY_ID = "44444444-4444-4444-4444-444444444444"
PLACEHOLDER_DECISION_ID = "22222222-2222-2222-2222-222222222222"
PLACEHOLDER_GENERIC_ID = "00000000-0000-0000-0000-000000000000"
