"""Domain thresholds — numeric constants from the PRD's pricing, adherence,
transport, and no-show rules. Generic NON_EXISTENT_UUID comes from the framework.
"""

# Session charge (PRD §3.6)
MODALITY_BASE_CENTS = {
    "HEMODIALYSIS": 28500,
    "HEMODIAFILTRATION": 34000,
    "PERITONEAL": 22000,
}
EPO_BLOCK_CENTS = 1200            # per whole 1000-unit block
IRON_DOSE_CENTS = 4500            # flat add-on when iron_ordered
CONTRACTED_PCT = 0.82            # in-network discount multiplier
STANDARD_PCT = 1.00

# Transport fare (PRD §3.8)
BASE_FLAG_CENTS = 800
SHARED_MULT = 0.75
WHEELCHAIR_CENTS = 1500
CROSS_COUNTY_CENTS = 500
MILEAGE_TIER1_PER_MI = 250        # first 5 miles
MILEAGE_TIER2_PER_MI = 200        # next 10 miles (5..15)
MILEAGE_TIER3_PER_MI = 150        # beyond 15

# No-show / adherence (PRD §3.7)
AT_RISK_THRESHOLD = 3
SUSPEND_THRESHOLD = 5
WINDOW_DAYS = 30
MISSED_FEE_CENTS = 7500

# Adherence score (PRD §3.7)
ROLLING_WINDOW = 8

# Clinic defaults (PRD §3.1)
DEFAULT_DIALYZER_REUSE_LIMIT = 12

# Convenience grouping
THRESHOLDS = {
    "AT_RISK_THRESHOLD": AT_RISK_THRESHOLD,
    "SUSPEND_THRESHOLD": SUSPEND_THRESHOLD,
    "WINDOW_DAYS": WINDOW_DAYS,
    "MISSED_FEE_CENTS": MISSED_FEE_CENTS,
    "ROLLING_WINDOW": ROLLING_WINDOW,
    "DEFAULT_DIALYZER_REUSE_LIMIT": DEFAULT_DIALYZER_REUSE_LIMIT,
}
