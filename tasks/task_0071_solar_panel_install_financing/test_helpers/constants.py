"""Domain thresholds — numeric constants from the PRD calculation sections."""

# System sizing (PRD 3.3)
SQFT_PER_KW = 70
USAGE_OFFSET = 1.0
SYSTEM_DERATE = 0.80

# Federal ITC (PRD 3.4)
ITC_RATE = 0.30
ITC_RATE_CAP = 0.40
STATE_ADDER = {"CA": 0.00, "NJ": 0.10, "MA": 0.10, "TX": 0.00, "AZ": 0.10}

# Warranty (PRD 2.4 / 3.10)
WARRANTY_COVERAGE_YEARS = 25

# Recognized state codes (PRD 3.1)
STATE_CODES = ["CA", "NJ", "MA", "TX", "AZ"]

# Pagination (PRD 2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
