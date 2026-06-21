"""Domain thresholds — numeric constants from the PRD calculation rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Tax / discount arithmetic (PRD §2.8, §3.6, §3.8).
BPS_DENOMINATOR = 10000  # one basis point = one ten-thousandth

# Invoice volume-discount tiers, keyed on taxable_subtotal_cents (PRD §3.6).
TIER1_THRESHOLD_CENTS = 500000    # >= $5,000 -> 5%
TIER2_THRESHOLD_CENTS = 1000000   # >= $10,000 -> 10%
TIER1_PCT = 0.05
TIER2_PCT = 0.10

# A well-formed UUID that is never minted by the server (for not-found probes).
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

# Standard period window used throughout the suite (a single calendar month).
PERIOD_START = "2026-01-01T00:00:00.000Z"
PERIOD_END = "2026-02-01T00:00:00.000Z"
