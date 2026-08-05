"""Domain thresholds — numeric constants from PRD calculations."""

# Commission calculation (PRD §2.5, §3.5)
MILLS_TO_CENTS_DIVISOR = 10
MIN_COMMISSION_CENTS = 5000        # $50 floor per statement
MAX_COMMISSION_CENTS = 5000000     # $50,000 ceiling per statement

# Broker margin floor (PRD §3.2, §3.3)
MIN_BROKER_ADDER_MILLS = 2

# Demand-response settlement penalty (PRD §3.6)
DR_PENALTY_PER_KW_CENTS = 2000     # $20/kW shortfall penalty

# Temporal windows (PRD §3.4, §3.6)
RENEWAL_WINDOW_DAYS = 60
RATE_ALERT_DROP_PCT = 0.10
DR_BUFFER_DAYS = 14

# Logical clock (PRD §2.8)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "ESTIMATED_ANNUAL_USAGE_KWH": 60000,
    "RATE_MILLS_PER_KWH": 60,
    "BROKER_ADDER_MILLS": 5,
    "TERM_MONTHS": 12,
    "APPROVAL_LIMIT_CENTS": 100000000,
    "LOA_EXPIRES_AT": "2028-01-01T00:00:00Z",
    "RFP_DUE_AT": "2026-06-01T00:00:00Z",
    "START_DATE": "2026-07-01T00:00:00Z",
}
