"""Domain thresholds — numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework. These mirror the literal
constants stated in PRD §2.7, §3.2, §3.4, §3.5, §3.6, and §3.8.
"""

# Surety premium marginal banding (PRD §3.2)
TIER1_CAP_CENTS = 1_000_000
TIER2_CAP_CENTS = 5_000_000
TIER1_FLOOR_BPS = 1000
TIER2_FLOOR_BPS = 800
TIER3_FLOOR_BPS = 600
MIN_PREMIUM_CENTS = 10_000

# Risk-tier collateral coverage for SURETY bonds (PRD §3.2)
COVERAGE_PCT = {"LOW": 0.10, "MEDIUM": 0.25, "HIGH": 0.50}

# Collateral refund processing fee (PRD §3.4)
PROCESSING_FEE_CENTS = 2_500

# Judgment recovery credit (PRD §3.6)
RECOVERY_CREDIT_CENTS = 50_000

# Forfeiture grace window (PRD §3.6)
GRACE_PERIOD_DAYS = 30

# Compliance score weighting (PRD §3.8)
MISSED_WEIGHT = 1
FAIL_BASE_WEIGHT = 2
GPS_FAIL_BONUS = 3

# Docket overlap buffer (PRD §3.5)
DOCKET_BUFFER_MINUTES = 30

# Device occupancy capacity (PRD §3.8)
DEVICE_CAPACITY = 1

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
