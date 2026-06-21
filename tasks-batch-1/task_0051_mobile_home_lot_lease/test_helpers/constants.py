"""Domain thresholds — numeric constants from the PRD's business rules.

Generic NON_EXISTENT_UUID comes from the framework; a literal UUID is also kept
here for setup_api_calls that use a fixed not-found UUID.
"""

# Annual rent-increase caps by state (fraction of prior rent). TX is uncapped.
CAP_PCT = {
    "CA": 0.05,   # California: at most 5%
    "OR": 0.07,   # Oregon: at most 7%
    "FL": 0.10,   # Florida: at most 10%
    "TX": None,   # Texas: no statutory cap
}

# Cure-period length in days by state.
CURE_DAYS = {
    "CA": 60,
    "OR": 30,
    "FL": 30,
    "TX": 14,
}

# NONPAYMENT eviction arrears threshold: $500.00.
ARREARS_THRESHOLD_CENTS = 50000

# Minimum spacing between EFFECTIVE rent schedules on a lot.
RENT_INCREASE_MIN_MONTHS = 12

# Pagination.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# A syntactically valid UUID guaranteed not to exist after a server restart.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
