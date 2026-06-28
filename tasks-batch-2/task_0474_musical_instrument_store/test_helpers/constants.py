"""Domain thresholds — numeric constants from the PRD's financial calculations."""

# Rent-to-own buyout (PRD §3.4 Buyout payoff)
EARLY_BUYOUT_FEE_CENTS = 5000

# Billing cycle / default (PRD §3.3)
LATE_FEE_CENTS = 1500
DEFAULT_THRESHOLD = 3

# Repair invoice (PRD §3.6 Repair invoice)
MIN_BENCH_CENTS = 4000
RUSH_PCT = 0.25

# Trade-in offer condition tiers (PRD §3.7)
TRADEIN_PCT = {
    "NEW": 0.60,
    "USED": 0.50,
    "VINTAGE": 0.70,
}

# Financing APR tiers (PRD §3.8 Financing terms)
APR_TIER_PRIME = 0.0599        # score >= 720
APR_TIER_NEAR_PRIME = 0.1299   # score 660..719
APR_TIER_SUBPRIME = 0.2299     # score < 660 (blocked by credit floor)
SCORE_PRIME_MIN = 720
SCORE_NEAR_PRIME_MIN = 660
MIN_FINANCE_SCORE = 660

# Lesson tuition (PRD §3.9 Lesson tuition)
VOLUME_THRESHOLD = 8
VOLUME_PCT = 0.15
BUNDLE_PCT = 0.20

# Defaults declared by the PRD for optional fractions
DEFAULT_EQUITY_RATE_PCT = 0.50
DEFAULT_EQUITY_CAP_PCT = 1.0
DEFAULT_RESTOCK_FEE_PCT = 0.10
DEFAULT_COMMISSION_PCT = 0.20
DEFAULT_DEPOSIT_PCT = 0.25

# Credit-score bounds (PRD §3.1)
MIN_CREDIT_SCORE = 300
MAX_CREDIT_SCORE = 850

# Pagination (PRD §2.3)
PAGINATION_LIMIT_MAX = 100
PAGINATION_LIMIT_MIN = 1
