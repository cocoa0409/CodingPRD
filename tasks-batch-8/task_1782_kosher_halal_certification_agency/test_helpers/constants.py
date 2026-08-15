"""Domain thresholds — numeric constants from PRD fee/score/window rules."""

# Logical clock
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Annual certification fee (PRD section 3.8)
TIER1_CENTS = 120000          # first facility
TIER2_CENTS = 90000           # facilities 2..5
TIER3_CENTS = 70000           # facilities beyond 5
COPACKER_SURCHARGE_CENTS = 25000
DUAL_SCHEME_MULTIPLIER = 1.8
MEDIUM_RISK_SURCHARGE_PCT = 5
HIGH_RISK_SURCHARGE_PCT = 15

# Nonconformance score weights and tier bounds (PRD section 3.6)
W_MINOR = 1
W_MAJOR = 3
W_CRITICAL = 8
TIER_MEDIUM_MIN = 3
TIER_HIGH_MIN = 8

# Product-addition proration (PRD section 3.8)
DAYS_IN_CYCLE = 365
DISCOUNT_TIER1_CENTS = 100000   # 5% at/above
DISCOUNT_TIER2_CENTS = 200000   # 10% at/above
DISCOUNT_TIER1_PCT = 5
DISCOUNT_TIER2_PCT = 10

# Certificate terms (PRD section 3.7)
ANNUAL_TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 60

# Kosherization validity (PRD section 3.2)
KOSHERIZATION_VALIDITY_HOURS = 72

# Invoices (PRD section 3.8)
INVOICE_DUE_DAYS = 30
GRACE_DAYS = 14
REINSTATEMENT_FEE_CENTS = 50000

# Scheduling buffers (PRD sections 3.5, 3.9)
TRAVEL_BUFFER_HOURS = 2
SUPERVISION_BUFFER_HOURS = 24
NO_ACCESS_DEADLINE_DAYS = 7
