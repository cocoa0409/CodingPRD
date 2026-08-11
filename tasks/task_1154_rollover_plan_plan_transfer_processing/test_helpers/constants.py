"""Domain thresholds and shared constants from the PRD."""

# Eligibility age threshold: 714 complete calendar months == 59.5 years (PRD §3.3).
AGE_THRESHOLD_MONTHS = 714

# Mandatory federal withholding rate for indirect rollovers (PRD §3.6).
WITHHOLDING_RATE = 0.20

# 60-day rollover window in calendar days (PRD §3.7).
ROLLOVER_WINDOW_DAYS = 60

# Statutory spousal-consent threshold default, in cents (PRD §3.1).
SPOUSAL_CONSENT_THRESHOLD_CENTS = 500000

# Server startup logical clock reading (PRD §2.4).
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

# Canonical four-source account used across the suite:
#   PRE_TAX 8,000,000/0/100; EMPLOYER_PRETAX 2,000,000/0/60;
#   ROTH 1,000,000/800,000/100; AFTER_TAX 600,000/500,000/100
#   -> total 11,600,000; vested 10,800,000; basis 1,300,000
CANONICAL_BALANCES = [
    {"source_type": "PRE_TAX", "balance_cents": 8000000, "basis_cents": 0, "vested_pct": 100},
    {"source_type": "EMPLOYER_PRETAX", "balance_cents": 2000000, "basis_cents": 0, "vested_pct": 60},
    {"source_type": "ROTH", "balance_cents": 1000000, "basis_cents": 800000, "vested_pct": 100},
    {"source_type": "AFTER_TAX", "balance_cents": 600000, "basis_cents": 500000, "vested_pct": 100},
]
CANONICAL_TOTAL_CENTS = 11600000
CANONICAL_VESTED_CENTS = 10800000
CANONICAL_BASIS_CENTS = 1300000

# Common dates.
DATE_CLOCK_MAY = "2026-05-01T00:00:00Z"
DATE_CLOCK_JUNE = "2026-06-01T00:00:00Z"

# Standard participant fixture values (SEPARATED -> SEPARATION qualifying event).
P1_DOB = "1960-06-15"
P1_SEPARATION_DATE = "2026-04-15"

# Processor identities used to satisfy segregation of duties:
# the approver (proc-1) and the money mover (proc-2) are always distinct.
PROCESSOR_APPROVER_ID = "proc-1"
PROCESSOR_MOVER_ID = "proc-2"
