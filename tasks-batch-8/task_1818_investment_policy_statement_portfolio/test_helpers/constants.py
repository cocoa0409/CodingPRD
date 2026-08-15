"""Domain thresholds and defaults — numeric constants from the PRD (§2.5, §2.6, §3)."""

# Logical clock startup default (PRD §2.5).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# Rounding / rate constants (PRD §2.6).
CAPITAL_GAINS_RATE_BPS = 2000
BPS_PER_PERCENT = 100

# Governance / lifecycle constants (PRD §3.5, §3.8).
PROPOSAL_TTL_DAYS = 7
AMENDMENT_QUORUM = 3
RISK_DELTA_MAX = 10

# Fixed asset-class processing order (PRD §3.5).
CLASS_ORDER = [
    "US_EQUITY",
    "INTL_EQUITY",
    "FIXED_INCOME",
    "CASH_EQUIVALENT",
    "ALTERNATIVES",
]

# Reusable fixture inputs.
TEST_DEFAULTS = {
    "CLIENT_RISK": 50,
    "REVIEW_CADENCE_MONTHS": 12,
    "OBJECTIVE_TEXT": "Growth",
    "OCCURRED_AT": CLOCK_DEFAULT_ISO,
}

# A non-existent id used for 404 / reference probes (value irrelevant; any
# well-formed UUID that was never created).
BOGUS_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
