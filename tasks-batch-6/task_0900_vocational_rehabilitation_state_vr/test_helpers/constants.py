"""Domain thresholds — numeric constants drawn from the PRD calculations (§2, §3)."""

# Consumer cost-share participation tiers (PRD §3.5).
TIER1_INCOME_CENTS = 200000    # income <= this: 0% participation
TIER2_INCOME_CENTS = 400000    # income <= this (and > TIER1): 10% participation
TIER1_RATE = 0.00
TIER2_RATE = 0.10
TIER3_RATE = 0.20              # income above TIER2_INCOME_CENTS: 20% participation

# Federal reimbursement match rate (PRD §3.7).
FEDERAL_MATCH_RATE = 0.787

# Stabilization window (PRD §3.8).
STABILIZATION_DAYS = 90

# Logical clock startup default (PRD §2.11).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Priority-category ranks (PRD §3.2).
RANK_MSD = 1
RANK_SD = 2
RANK_NSD = 3
