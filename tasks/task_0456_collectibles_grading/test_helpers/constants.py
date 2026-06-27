"""Domain thresholds — numeric constants drawn from PRD calculations."""

# Grades live on a half-point lattice, rounded down (floor). (PRD §2.7, §3.4)
HALF_STEP = 0.5

# Final overall grade caps at the lowest subgrade plus 1.5. (PRD §3.4)
LOWEST_CAP_DELTA = 1.5

# Each completed regrade cycle adds 1500 cents to the item's final fee. (PRD §3.8)
REGRADE_SURCHARGE_CENTS = 1500

# Sentinel grade_value for the AUTHENTIC-only population bucket. (PRD §3.10)
AUTHENTIC_ONLY_GRADE_SENTINEL = -1

# Pagination bounds. (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# A syntactically valid UUID that is never minted by the server — used for
# not-found probes.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
