"""Domain thresholds — numeric constants from the PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Enforcement certification: certifiable arrears (principal + interest) must be
# at least 50000 cents; the boundary is inclusive (PRD §3.8).
ENFORCEMENT_CERT_THRESHOLD_CENTS = 50000

# Interest accrual (PRD §3.6).
DAYS_PER_YEAR = 365
BPS_DENOMINATOR = 10000
DEFAULT_INTEREST_RATE_BPS = 1000  # 10.00%/yr default

# CCPA withholding cap percentage tiers (PRD §3.4).
CAP_SECOND_FAMILY_UNDER_12 = 0.50
CAP_SECOND_FAMILY_12_PLUS = 0.55
CAP_NO_SECOND_FAMILY_UNDER_12 = 0.60
CAP_NO_SECOND_FAMILY_12_PLUS = 0.65
WEEKS_THRESHOLD = 12

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
