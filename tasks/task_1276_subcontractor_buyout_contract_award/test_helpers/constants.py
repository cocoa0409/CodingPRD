"""Domain thresholds — numeric constants from the PRD's calculation rules."""

DEFAULT_PROJECT_CLOCK = "2026-05-01T00:00:00Z"

# Negotiation loop bound (PRD: at most two PENDING_AWARD -> DRAFT loops).
MAX_NEGOTIATION_ROUNDS = 2

# Retainage band (inclusive).
RETAINAGE_MIN = 0.05
RETAINAGE_MAX = 0.10

# Trade-risk scoring points (PRD section 3.7).
RISK_VALUE_LOW_PTS = 10          # contract_value_cents < 5_000_000
RISK_VALUE_MID_PTS = 20          # 5_000_000 <= value <= 10_000_000
RISK_VALUE_HIGH_PTS = 35         # value > 10_000_000
RISK_VALUE_TIER1_MAX_CENTS = 4_999_999
RISK_VALUE_TIER2_MAX_CENTS = 10_000_000
RISK_SIZE_RATIO_THRESHOLD = 0.25
RISK_SIZE_PTS = 25
RISK_HISTORY_CLEAN_PTS = 10
RISK_HISTORY_CLAIMS_PTS = 25
RISK_TIER1_MAX = 40              # <= 40 -> NOT_REQUIRED (PER_TRADE_RISK)
RISK_TIER2_MAX = 60              # 41..60 -> SURETY_BOND
RISK_TIER3_MAX = 85              # 61..85 -> SUBGUARD

# Bond premium rates (PRD section 3.7).
SURETY_RATE = 0.015
SUBGUARD_RATE = 0.010

# Replacement exposure (PRD section 3.9).
SUBGUARD_CLAIM_PCT = 0.20

# Default buyout target fraction used across scenarios.
TARGET_DEFAULT_PCT = 0.05

TEST_DEFAULTS = {
    "PROJECT_BUDGET_CENTS": 50_000_000,
    "PACKAGE_BUDGET_CENTS": 10_000_000,
    "BID_RECEIVED_AT": "2026-05-15T12:00:00Z",
    "BID_DUE_AT": "2026-05-20T16:00:00Z",
    "CERT_EXPIRES_ON": "2027-06-01",
}
