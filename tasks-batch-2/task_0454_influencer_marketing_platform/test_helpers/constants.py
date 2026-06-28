"""Domain thresholds — numeric constants from PRD calculations."""

# Fraud scoring (PRD §3.2)
FRAUD = {
    "FAKE_WEIGHT": 0.7,
    "ANOMALY_WEIGHT": 0.3,
    "EXPECTED_ENGAGEMENT_CEILING": 0.05,
    "FRAUD_BLOCK_THRESHOLD": 60,
}

# Negotiation / revision caps (PRD §3.4, §3.6)
MAX_NEGOTIATION_ROUNDS = 4
MAX_REVISION_ROUNDS = 2

# Campaign window buffer (PRD §3.3)
CAMPAIGN_BUFFER_DAYS = 7

# Payout breakdown tiers (PRD §3.9)
PAYOUT = {
    "TIER1_CAP_CENTS": 100000,   # first $1,000
    "TIER2_CAP_CENTS": 500000,   # next up to $5,000
    "TIER1_RATE": 0.20,
    "TIER2_RATE": 0.15,
    "TIER3_RATE": 0.10,
    "BACKUP_WITHHOLDING_RATE": 0.24,
}

# 1099 reporting floor (PRD §3.9 / §3.11)
TAX_1099_THRESHOLD_CENTS = 60000   # $600.00

# Clock default (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"
