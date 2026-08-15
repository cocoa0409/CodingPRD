"""Domain constants shared by fixtures and tests.

The pricing calculations in the PRD declare no named numeric constants; the
values below are the shared catalog/clock fixtures used across test setups.
"""

# Logical clock startup default (PRD section 2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"
DEFAULT_AWARD_MONTH = "2026-08"

# Catalog fixture: THHN copper wire sold by the foot.
THHN_SKU = "THHN-12CU"
THHN_MANUFACTURER = "Southwire"
THHN_PRICE_CENTS = 45.25
THHN_REEL_LENGTH_FT = 500
THHN_MIN_CUT_FT = 50
THHN_CUT_CHARGE_CENTS = 1500

# Catalog fixture: SquareD breaker sold each.
BRK_SKU = "BRK-20A"
BRK_MANUFACTURER = "SquareD"
BRK_PRICE_CENTS = 5000

# Alternate catalog item used by substitution scenarios.
BRK_ALT_SKU = "BRK-20B"
BRK_ALT_MANUFACTURER = "Eaton"
BRK_ALT_PRICE_CENTS = 2400

# Common scheduling geometry.
TRUCK_T1 = "T1"
TRUCK_T2 = "T2"
TRUCK_T9 = "T9"

# Quote validity used by scenarios that must not expire.
FAR_FUTURE_VALID_UNTIL = "2027-01-01"
