"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

# Size standard caps (PRD §3.4); all inclusive.
TNW_CAP = 2_000_000_000          # $20,000,000 tangible net worth ceiling (cents)
NET_INCOME_CAP = 650_000_000     # $6,500,000 average net income ceiling (cents)
EMPLOYEE_CAP = 500               # 500-employee headcount ceiling

# Collateral coverage (PRD §3.2 / §3.4).
ASSET_DISCOUNT = {
    "REAL_ESTATE": 0.80,
    "EQUIPMENT": 0.50,
    "INVENTORY": 0.30,
    "RECEIVABLES": 0.50,
}
SHORT_TERM_COVERAGE = 0.50       # 50% net coverage for maturity <= 120 months
LONG_TERM_MATURITY_THRESHOLD = 120

# Guaranty fee tiered schedule (PRD §3.6).
TIER1_CENTS = 15_000_000         # $150,000
TIER2_CENTS = 70_000_000         # $700,000
RATE1 = 0.02                     # 2.00% band 1
RATE2 = 0.03                     # 3.00% band 2
RATE3 = 0.035                    # 3.50% band 3

# Secondary-market premium split (PRD §3.8).
LENDER_RETAINED_BPS = 100        # lender keeps premium up to 1.00% of par
SBA_SPLIT = 0.50                 # SBA takes 50% above the retained floor

# Ongoing servicing fee (PRD §3.9).
ANNUAL_ONGOING_RATE = 0.0055     # 0.55% per annum

# Servicing axis thresholds (PRD §3.9 / §3.10).
DELINQUENT_DAYS_THRESHOLD = 60   # days_past_due >= 60 -> DELINQUENT
DEFAULT_DAYS_THRESHOLD = 90      # most-recent accepted report >= 90 to declare default

# Common test defaults reused across fixtures.
TEST_DEFAULTS = {
    "requested_amount_cents": 50_000_000,
    "guaranty_pct": 0.75,
    "maturity_months": 240,
    "tangible_net_worth_cents": 1_000_000_000,
    "avg_net_income_cents": 300_000_000,
    "affiliate_employee_count": 50,
    "naics_code": "236220",
}
