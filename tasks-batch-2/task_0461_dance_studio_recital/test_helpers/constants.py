"""Domain thresholds — numeric constants from PRD calculations."""

# Tuition discount percentages (PRD §3.3 tuition discount engine)
MULTI_CLASS_2ND_PCT = 0.10
MULTI_CLASS_3RD_PLUS_PCT = 0.20
FAMILY_2_PCT = 0.05
FAMILY_3_PLUS_PCT = 0.08

# Logical clock default at server startup (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
