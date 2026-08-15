"""Domain thresholds — numeric constants named in the PRD.

PRD §2.8/§3.11 (rebate tiers), §3.5/§2.8 (cold-chain rates and kink),
§3.10 (payment closing tolerance), §3.13 (restocking fee), §3.14 (price cap),
§2.4 (logical clock startup default).
"""

# PRD §2.4: before any clock call the logical clock reads this instant.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# PRD §2.8 / §3.5: cold-chain surcharge tiers.
# cold_rate(h) = 5*h for h <= 72; 5*72 + 12*(h-72) for h > 72.
COLD_TIER1_MAX_HOURS = 72
COLD_TIER1_RATE_CENTS = 5
COLD_TIER2_RATE_CENTS = 12

# PRD §3.11: volume rebate tiers (pre-rebate subtotal, inclusive boundaries).
REBATE_TIER1_SUBTOTAL_CENTS = 500000   # >= 500,000 -> 4%
REBATE_TIER1_PCT = 4
REBATE_TIER2_SUBTOTAL_CENTS = 1000000  # >= 1,000,000 -> 7%
REBATE_TIER2_PCT = 7

# PRD §3.10: settlement closing tolerance (+/- 50 cents books a write-off).
FX_CLOSING_TOLERANCE_CENTS = 50

# PRD §3.13: restocking fee — max(500, 5% of gross rounded half-up).
RESTOCKING_PCT = 5
RESTOCKING_MIN_CENTS = 500

# PRD §3.14: substitution price cap — 115% of the original base price.
SUBSTITUTION_CAP_PCT_NUM = 115
SUBSTITUTION_CAP_PCT_DEN = 100

# Shared schedule used by most fixtures: a 100-hour planned port stay.
DEFAULT_ETA = "2026-08-10T08:00:00Z"
DEFAULT_ETD = "2026-08-14T12:00:00Z"
DEFAULT_VALID_UNTIL = "2026-08-12T00:00:00Z"
DEFAULT_WINDOW_START = "2026-08-10T10:00:00Z"
DEFAULT_WINDOW_END = "2026-08-10T14:00:00Z"
