"""Domain thresholds — numeric constants from the PRD calculations (§3) and
global specifications (§2). Generic NON_EXISTENT_UUID comes from the framework.
"""

# Labor rate used by both the quote estimate (§3.3) and the install labor
# component of the job final total (§3.6).
LABOR_RATE_CENTS_PER_MIN = 250

# Default part markup fraction (§3.1) — a part priced at 135% of catalog.
DEFAULT_MARKUP_PCT = 0.35

# Default equipment unit concurrent capacity (§3.1).
DEFAULT_CONCURRENT_CAPACITY = 1

# Default tune-ups included on a warranty plan (§3.11).
DEFAULT_TUNE_UPS_INCLUDED = 2

# Quote expiry term (§3.4).
QUOTE_EXPIRY_DAYS = 14

# Scheduling travel buffer (§3.5).
TECH_TRAVEL_BUFFER_MINUTES = 30

# Emergency surcharge bands and clamp (§3.7).
AFTER_HOURS_RATE = 0.25
OVERNIGHT_RATE = 0.50
SURCHARGE_MIN_CENTS = 5000
SURCHARGE_MAX_CENTS = 40000

# Financing approval ceiling (§3.12) — fifteen thousand dollars.
FINANCING_CEILING_CENTS = 1_500_000

# Financing APR tiers by term_months (§3.12).
APR_TIER_0_6 = 0.00
APR_TIER_7_12 = 0.099
APR_TIER_13_24 = 0.149

# Callback rate rounding precision (§2.5, §3.10).
CALLBACK_RATE_DECIMALS = 4
