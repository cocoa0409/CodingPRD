"""Domain thresholds — numeric constants taken from the PRD's pricing,
financing, scheduling, warranty, and referral rules.
"""

# Volume-discount tier boundaries and multipliers (PRD Section 3.4).
TIER1_MAX_FEET = 200          # feet < 200 -> tier 1; feet >= 200 crosses to tier 2
TIER2_MAX_FEET = 400          # feet >= 400 crosses to tier 3
TIER1_MULT = 1.00
TIER2_MULT = 0.95
TIER3_MULT = 0.90
DOWNSPOUT_UNIT_CENTS = 12000  # $120 per drainage add-on unit

# Discount cap tiers keyed on subtotal_cents (PRD Section 3.4).
CAP_TIER1_MAX_CENTS = 500000
CAP_TIER2_MAX_CENTS = 1000000
CAP_TIER1 = 0.10
CAP_TIER2 = 0.15
CAP_TIER3 = 0.20

# Financing bounds (PRD Section 3.6).
MIN_FINANCE_AMOUNT_CENTS = 100000
FINANCE_MAX_CENTS = 5000000

# Install-day span (PRD Section 3.7).
FEET_PER_CREW_DAY = 150

# Deposit (PRD Section 3.7).
DEPOSIT_PCT = 0.10

# Referral payout (PRD Section 3.9).
REFERRAL_PCT = 0.03
REFERRAL_MAX_CENTS = 50000

# Warranty remediation (PRD Section 3.8).
REMEDIATION_BASE_CLOG_CENTS = 15000
REMEDIATION_BASE_OVERFLOW_CENTS = 30000
REMEDIATION_BASE_DETACHMENT_CENTS = 60000
REMEDIATION_CENTS_PER_FOOT = 200

# No-show auto-LOST threshold (PRD Section 3.3).
NO_SHOW_LIMIT = 2

# Quote validity window (PRD Section 3.5).
QUOTE_VALIDITY_DAYS = 30

# Logical clock default before any clock has been set (PRD Section 2.9).
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
