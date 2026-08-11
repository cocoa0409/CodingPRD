"""Domain thresholds and defaults (PRD §2.4, §2.6, §3)."""

# Logical clock default (PRD §2.4): before any clock-set call the clock reads this.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Record-position settlement lag, days (PRD §3.4 SETTLED_BASIS cutoff).
SETTLEMENT_LAG_DAYS = 2

# Odd-lot threshold for merger proration (PRD §3.6): fewer than 100 shares.
ODD_LOT_THRESHOLD = 100

# Claim amount cap, cents (PRD §3.8).
CLAIM_AMOUNT_CAP_CENTS = 250000

# Claim filing window, days after payable_date inclusive (PRD §3.8).
CLAIM_WINDOW_DAYS = 30

# Quantity decimal places (PRD §2.6).
QUANTITY_DECIMALS = 4

TEST_DEFAULTS = {
    "RECORD_DATE": "2026-05-15",
    "PAYABLE_DATE": "2026-05-29",
    "ACQ_DATE": "2026-04-01",
    "CAPTURE_CLOCK": "2026-05-15T00:00:00Z",
    "CLAIM_CLOCK": "2026-06-01T00:00:00Z",
    "ELECTION_DEADLINE": "2026-05-20T16:00:00Z",
}
