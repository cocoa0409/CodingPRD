"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock (PRD section 2.5): reads exactly 2026-08-01T00:00:00Z before
# any test-driving call.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Prequalification score (PRD section 3.4).
W_FINANCIAL = 0.40
W_SAFETY = 0.35
W_BONDING = 0.25
REVENUE_REFERENCE_CENTS = 5_000_000_000
BONDING_REFERENCE_CENTS = 2_000_000_000
EMR_FLOOR = 0.70
EMR_CEILING = 1.20
EMR_HARD_FAIL = 1.25
PREQUAL_PASS_THRESHOLD = 70
PREQUAL_VALIDITY_DAYS = 365

# Bid bond (PRD section 3.6): default fraction of base bid.
DEFAULT_BOND_PCT = 0.05
MAX_BOND_PCT = 0.20

# Last-minute revision window (PRD section 3.6): gap <= 60 minutes inclusive.
LAST_MINUTE_WINDOW_MINUTES = 60

TEST_DEFAULTS = {
    "BID_DUE_AT": "2026-08-10T14:00:00Z",
    "AFTER_DUE": "2026-08-10T15:00:00Z",
    "BASE_BID_CENTS": 1_000_000,
    "DECLARED_REVENUE_CENTS": 3_000_000_000,
    "DECLARED_EMR": 0.80,
    "DECLARED_BONDING_CENTS": 1_500_000_000,
    "VERIFIED_REVENUE_CENTS": 4_000_000_000,
    "VERIFIED_EMR": 0.80,
    "VERIFIED_BONDING_CENTS": 2_000_000_000,
}
