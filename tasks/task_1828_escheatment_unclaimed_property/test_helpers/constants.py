"""Domain thresholds — numeric constants named in PRD §2.5, §2.6, §3."""

# Logical clock default (PRD §2.5): the server starts at this instant.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# DormancyRule documented defaults (PRD §3.2).
DEFAULT_DD_THRESHOLD_CENTS = 5000
DEFAULT_DD_WINDOW_MIN_DAYS = 60
DEFAULT_DD_WINDOW_MAX_DAYS = 180
DEFAULT_ANNUAL_INTEREST_RATE_BP = 1200
DEFAULT_DAILY_PENALTY_CENTS = 10000
DEFAULT_GROSS_DAILY_PENALTY_CENTS = 25000
DEFAULT_GROSS_NEGLIGENCE_DAY_THRESHOLD = 30
DEFAULT_PENALTY_CAP_PCT = 25
DEFAULT_REPORT_CUTOFF_MONTH_DAY = "06-30"
DEFAULT_REPORT_DUE_MONTH_DAY = "11-01"

# Letter response deadline (PRD §3.3): sent_date + 30 days.
LETTER_RESPONSE_DAYS = 30

# Liquidation execution grace (PRD §3.5): due_date + 60 days, inclusive.
LIQUIDATION_GRACE_DAYS = 60

# Interest accrual divisor (PRD §2.6): 10,000 bp x 365 days.
BP_DENOMINATOR = 3_650_000

# Claim processing fee (PRD §3.7): 150 bp (1.5%), tiered on gross > 100000c.
CLAIM_FEE_BP = 150
CLAIM_FEE_FREE_CAP_CENTS = 100000

# Document retention years by artifact type (PRD §3.9).
RETENTION_YEARS = {
    "LETTER_COPY": 5,
    "CLAIM_EVIDENCE": 7,
    "REPORT_FILE": 10,
    "REMITTANCE_RECEIPT": 10,
}
