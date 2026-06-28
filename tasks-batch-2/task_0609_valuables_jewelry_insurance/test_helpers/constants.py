"""Domain thresholds — numeric constants from the PRD pricing/settlement rules."""

# Deductible resolution (PRD §3.3)
DEDUCTIBLE_CENTS = {
    "ZERO": 0,
    "LOW": 25000,
    "STANDARD": 50000,
    "HIGH": 100000,
}

# Per-item premium factors (PRD §3.4)
CATEGORY_RISK_MULT = {
    "RING": 1.00,
    "NECKLACE": 1.05,
    "WATCH": 1.20,
    "LOOSE_STONE": 1.40,
    "OTHER": 1.10,
}
ALL_RISK_MULT = 1.30
NAMED_PERIL_MULT = 1.00
TIER1_CENTS = 500000      # $5,000 — at or below: tier multiplier 1.00
TIER2_CENTS = 2000000     # $20,000 — at or below: tier multiplier 1.10
CAT_SURCHARGE_CENTS = 1500  # flat $15 per catastrophe-loaded zone item
DEDUCTIBLE_CREDIT = {
    "ZERO": 1.10,
    "LOW": 1.00,
    "STANDARD": 0.92,
    "HIGH": 0.85,
}
ITEM_MIN_PREMIUM_CENTS = 2500   # $25 floor per item

# Settlement / replacement-cost (PRD §3.12)
REPLACEMENT_CAP_FACTOR = 1.0
REPLACEMENT_DEPRECIATION_PCT = 0.05  # 5% depreciation per completed revaluation epoch

# Revaluation (PRD §3.5)
MAX_EPOCHS = 10

# Global thresholds (PRD §3.3, §3.6, §3.7, §3.11)
APPRAISAL_REQUIRED_THRESHOLD_CENTS = 1000000  # items strictly above $10,000 need appraisal
MAX_INFO_REQUESTS = 2
GRACE_DAYS = 30
REINSTATE_DAYS = 30
POLICY_YEAR_DAYS = 365

# Default clock instant used by most fixtures.
DEFAULT_CLOCK_ISO = "2026-02-01T00:00:00Z"

# A premium amount comfortably above any single-item annual premium in these tests,
# used whenever a fixture just needs the policy to reach PAID/ACTIVE.
GENEROUS_PAYMENT_CENTS = 5000000
