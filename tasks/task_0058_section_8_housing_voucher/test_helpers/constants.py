"""Domain thresholds — numeric constants stated in the PRD (Section 3)."""

# Income deductions (PRD §3.2)
DEPENDENT_DEDUCTION_CENTS = 48000          # 480 dollars per dependent
ELDERLY_DEDUCTION_CENTS = 40000            # 400 dollars when elderly/disabled

# Eligibility ceiling base (PRD §3.2)
REGION_VLI_BASE_CENTS = 4000000            # 40,000 dollars

# Tenant share (PRD §3.5)
MINIMUM_RENT_CENTS = 5000                  # 50 dollars statutory minimum rent

# Occupancy standard (PRD §3.3)
MAX_BEDROOM = 6

# Inspection cure window (PRD §3.4)
CURE_WINDOW_DAYS = 14

# Voucher search term (PRD §3.3)
DEFAULT_TERM_DAYS = 60

# Special mobility (PRD §3.8)
DEFAULT_TERM_EXTENSION_DAYS = 30

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
