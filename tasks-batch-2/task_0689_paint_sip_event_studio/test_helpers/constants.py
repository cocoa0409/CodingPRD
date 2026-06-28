"""Domain thresholds — numeric constants from the Paint & Sip pricing, credit,
and seat-ledger rules. The generic NON_EXISTENT_UUID comes from the framework."""

# Group-discount tiers (reservation pricing).
TIER_LARGE_MIN_SEATS = 8     # >= 8 seats earns 15%
TIER_LARGE_PCT = 15
TIER_MID_MIN_SEATS = 4       # 4..7 seats earns 10%
TIER_MID_PCT = 10
TIER_SMALL_MAX_SEATS = 3     # <= 3 seats earns 0%

# Cancellation credit ladder (hours before start_utc).
FULL_CREDIT_MIN_HOURS = 48   # >= 48h earns 100%
HALF_CREDIT_MIN_HOURS = 24   # 24..47h earns 50%
HALF_CREDIT_PCT = 50
FULL_CREDIT_PCT = 100
STUDIO_OVERRIDE_PCT = 100    # studio-initiated event cancel forces 100%

# Artist travel buffer for double-booking (minutes on each side of the window).
ARTIST_TRAVEL_BUFFER_MINUTES = 30

# Pagination defaults.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Logical-clock startup default.
DEFAULT_CLOCK_UTC = "2026-04-01T00:00:00Z"

# A syntactically valid UUID that resolves to no entity (path-resource 404 tests).
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
