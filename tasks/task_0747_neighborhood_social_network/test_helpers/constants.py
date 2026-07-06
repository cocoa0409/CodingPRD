"""Domain thresholds — numeric constants from the PRD calculations and gates."""

# Trust score constants (PRD §3.7)
MOD_UPHOLD_PENALTY = 25
REJECTION_PENALTY = 10
SUSPENSION_FLOOR = 60

# Post flagging threshold (PRD §3.2)
FLAG_HIDE_THRESHOLD = 3

# Neighborhood safety posture thresholds (PRD §3.4)
EMERGENCY_INCIDENT_COUNT = 3
ELEVATED_INCIDENT_COUNT = 1
ELEVATED_AGE_SECONDS = 3600

# Post feed score weights (PRD §3.2)
RECENCY_WEIGHT = 0.5
CATEGORY_WEIGHT = 0.4
RECENCY_HALF_LIFE_HOURS = 72

# Marketplace reservation window (PRD §3.3): 48 hours.
RESERVATION_HOURS = 48

# Local ad minimums (PRD §3.8)
MIN_AD_BUDGET_CENTS = 1000
MIN_AD_BID_CENTS = 1

# Event group concurrency ceiling (PRD §3.6)
GROUP_EVENT_CONCURRENCY_CAP = 3

# Marketplace price bounds (PRD §3.3)
MAX_LISTING_PRICE_CENTS = 100_000_000

# Verification expiry: submitted_at + 14 days (PRD §3.1).
VERIFICATION_EXPIRY_DAYS = 14

# Test-driving default clock start (PRD §2.10).
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

# Default clock used across most fixtures.
TEST_BASE_CLOCK = "2026-06-01T00:00:00Z"

# Default neighborhood geofence used by fixtures.
DEFAULT_NEIGHBORHOOD_CENTER_LAT = 37.75
DEFAULT_NEIGHBORHOOD_CENTER_LNG = -122.42
DEFAULT_NEIGHBORHOOD_RADIUS_M = 2000

# Opaque operator identifiers for AgencyOfficer / PlatformAdmin — never
# compared to any entity id at the server (identity: opaque). Kept as
# named constants so tests can inject a specific officer identity where
# officer-authored ownership is checked (retract on a CivicNotice, resolve
# on an Incident).
PLATFORM_ADMIN_USER_ID = "platform-admin-1"
AGENCY_OFFICER_USER_ID = "OFF1"
AGENCY_OFFICER_2_USER_ID = "OFF2"
