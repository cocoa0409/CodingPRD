"""Domain thresholds — numeric constants from PRD calculations and globals."""

# Restocking fee applies only to OVERAGE returns (PRD §3.7).
RESTOCK_FEE_RATE = 0.15

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}

# Server clock starts at the Unix epoch (PRD §2.9).
EPOCH_UTC = "1970-01-01T00:00:00.000Z"

# Day-of-week convention: 0=Monday .. 6=Sunday (PRD §3.1).
# 2026-06-17 is a Wednesday (dow 2); 2026-06-16 is a Tuesday; 2026-06-24 is the next Wednesday.
WEDNESDAY = 2
