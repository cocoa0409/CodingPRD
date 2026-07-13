"""Domain thresholds — numeric constants from the PRD's fee, credit, fund,
and delinquency calculations (PRD §2.5, §3.2, §3.4, §3.5, §3.6, §3.8)."""

# ERU assessment (PRD §3.2): 3,000 sqft per Equivalent Residential Unit.
ERU_BASE_SQFT = 3000

# Tiered stormwater fee (PRD §3.5): cents per ERU by band.
RATE_T1 = 4000   # ERU (0.0, 1.0]
RATE_T2 = 3500   # ERU (1.0, 5.0]
RATE_T3 = 3000   # ERU (5.0, inf)
FIXED_CHARGE_CENTS = 500   # flat per-bill administrative charge

# BMP credit (PRD §3.4): provisional/inspected credit fraction.
MAX_CREDIT_PCT = 0.50
CREDIT_SCALE = 0.60
INSPECTION_INTERVAL_DAYS = 365

# Fund allocation (PRD §3.6): capital target share of an applied payment.
CAPITAL_TARGET_PCT = 0.30

# Delinquency (PRD §3.8): grace period and penalty.
GRACE_DAYS = 30
DELINQUENCY_PENALTY_PCT = 0.10

# Default logical clock before any request sets it (PRD §2.4).
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"
