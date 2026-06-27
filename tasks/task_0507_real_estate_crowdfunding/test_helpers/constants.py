"""Domain thresholds — numeric constants from the PRD's calculations and time rules."""

# NAV bootstrap par value before any shares exist (PRD §3.1).
PAR_NAV_CENTS = 1000

# ACH fee calculation (PRD §3.4).
ACH_RATE = 0.008
ACH_MIN_FEE_CENTS = 100
LARGE_INVESTOR_THRESHOLD_CENTS = 2_500_000   # preliminary-total waiver threshold

# Non-accredited annual suitability cap (PRD §3.4): 10% of max(income, net_worth).
NON_ACCREDITED_RATE = 0.10

# Early-withdrawal penalty schedule (PRD §3.7), inclusive lower bounds on age in quarters.
TIER1_RATE_BPS = 300    # age < 4 quarters
TIER2_RATE_BPS = 200    # 4 <= age < 8
TIER3_RATE_BPS = 100    # 8 <= age < 12
TIER4_RATE_BPS = 0      # age >= 12
TIER1_MAX_Q = 4
TIER2_MAX_Q = 8
TIER3_MAX_Q = 12

# Quarterly redemption cap (PRD §3.7): 5% of fund.total_capital_cents at sweep start.
QUARTERLY_REDEMPTION_CAP_RATE = 0.05

# Logical-clock default boot instant (PRD §2.9).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Income / net-worth values large enough to lift accredited investors clear of any cap.
BIG_INCOME_CENTS = 50_000_000
BIG_NET_WORTH_CENTS = 50_000_000
