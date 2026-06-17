"""Domain thresholds — numeric constants from PRD calculations (§3.7, §3.8, §3.4)."""

# Commission rate tiers (PRD §3.8)
LONG_TERM_MONTHS = 120        # term >= 120 months qualifies for the discount tier
LONG_TERM_DISCOUNT = 0.01     # one-percentage-point large-deal discount
MIN_COMMISSION_PCT = 0.03     # effective commission rate floored at 3%

# Brokerage default commission (PRD §3.1)
DEFAULT_COMMISSION_PCT = 0.06

# Listing defaults (PRD §3.2)
DEFAULT_ANNUAL_ESCALATION_PCT = 0.03
DEFAULT_CO_BROKE_OFFERED_PCT = 0.5

# Space asking-package defaults (PRD §3.1)
DEFAULT_FREE_RENT_MONTHS = 0
DEFAULT_TI_ALLOWANCE_PSF = 0

# Tour overlap geometry (PRD §3.4)
TURNOVER_BUFFER_MINUTES = 30  # space-side buffered overlap on both ends

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
