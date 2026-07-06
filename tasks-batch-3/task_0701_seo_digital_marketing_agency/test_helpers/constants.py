"""Domain thresholds — numeric constants from PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Deliverable credit cost (PRD §3.6)
BASE_COST = {"CONTENT": 3, "BACKLINK": 2, "TECHNICAL": 4}
COMPLEXITY_MULT = {"STANDARD": 1.0, "COMPLEX": 1.5}

# PPC management fee marginal tiers (PRD §3.7)
AGENCY_PPC_PCT = 0.20
TIER1_CENTS = 500000      # $5,000
TIER2_CENTS = 2000000     # $20,000
TIER1_DISCOUNT = 0.03
TIER2_DISCOUNT = 0.06

# Retainer rollover (PRD §3.4)
DEFAULT_ROLLOVER_CAP_PCT = 0.25

# Early termination fee (PRD §3.5)
EARLY_TERM_RATE = 0.5

# Audit composite score weights (PRD §3.1)
W_TECH = 0.4
W_CONTENT = 0.35
W_BACKLINK = 0.25

# Account health score (PRD §3.3)
MOMENTUM_WEIGHT = 2.0
OVERDUE_PENALTY = 5
DISPUTE_PENALTY = 10
HEALTH_MOMENTUM_CLAMP = 30

# Rank momentum (PRD §3.3)
UNRANKED_SENTINEL = 101

# GBP optimization (PRD §3.9)
GBP_OPTIMIZE_THRESHOLD = 80

# Report period buffer (PRD §3.3)
REPORT_GAP_DAYS = 1

# Reseller PPC default management rate (PRD §3.1)
RESELLER_DEFAULT_PPC_PCT = 0.15

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
